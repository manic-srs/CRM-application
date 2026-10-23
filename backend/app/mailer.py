"""Sending email over SMTP.

Settings (environment variables):
  SMTP_HOST       mail server. In Docker this is the Mailpit test inbox (http://localhost:8026).
                  If empty, emails are not sent (used by the automatic tests).
  SMTP_PORT       default 1025 (Mailpit). Use 587 for most real mail servers.
  SMTP_USER / SMTP_PASSWORD / SMTP_TLS=true   for a real mail server
  MAIL_FROM       sender address, default crm@salestrack.local (Gmail: must be the SMTP_USER address).
                  Every email goes out from this address, shown as "<user name> via SalesTrack";
                  replies go to the salesperson (Reply-To).
  MAIL_PROVIDER   smtp (default) or graph = Microsoft 365 / Outlook with OAuth (no SMTP password):
  MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET
                  an Azure app registration with the Mail.Send application permission (admin consent);
                  emails are sent from the MAIL_FROM mailbox through Microsoft Graph.
  MAIL_ASYNC      true (default) sends notification emails in the background after the save
  APP_URL         link used in notification emails, default http://localhost:5173

Emails queued during a request are sent only after the database commit succeeds,
so a failed save never sends an email.
"""
import base64
import json
import logging
import os
import smtplib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("crm.mail")


def settings() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "1025")),
        "user": os.getenv("SMTP_USER", ""),
        "password": password(),
        "tls": os.getenv("SMTP_TLS", "false").lower() == "true",
        "sender": os.getenv("MAIL_FROM", "crm@salestrack.local"),
        "app_url": os.getenv("APP_URL", "http://localhost:5173").rstrip("/"),
    }


def password() -> str:
    """Gmail shows App Passwords as "abcd efgh ijkl mnop"; the spaces are not part of the password."""
    value = os.getenv("SMTP_PASSWORD", "")
    return value.replace(" ", "") if "gmail" in os.getenv("SMTP_HOST", "").lower() else value


def provider() -> str:
    return os.getenv("MAIL_PROVIDER", "smtp").strip().lower()


def mode() -> dict:
    """Where emails go, without secrets. Used by GET /api/health/email."""
    cfg = settings()
    if provider() == "graph":
        ready = all(os.getenv(k) for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET"))
        return {"mode": "real email" if ready else "off", "provider": "Microsoft 365 (Graph, OAuth)",
                "sender": cfg["sender"],
                "detail": "Emails are sent from the Outlook mailbox" if ready
                else "MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET are needed"}
    if not cfg["host"]:
        return {"mode": "off", "detail": "SMTP_HOST is empty: emails are not sent"}
    test_inbox = cfg["host"] in ("mailpit", "localhost", "127.0.0.1") and cfg["port"] == 1025
    return {
        "mode": "test inbox" if test_inbox else "real email",
        "host": cfg["host"],
        "port": cfg["port"],
        "tls": cfg["tls"],
        "login": bool(cfg["user"]),
        "sender": cfg["sender"],
        "detail": "Emails land in Mailpit at http://localhost:8026" if test_inbox else "Emails are delivered to real inboxes",
    }


def app_link(path: str | None) -> str:
    return f"{settings()['app_url']}/#{path or '/'}"


# Name shown on system emails (notifications, reminders, welcome emails). Nobody reads replies to these.
SYSTEM_NAME = "SalesTrack (no-reply)"


def company_name() -> str:
    """Shown to customers in the lead welcome email (COMPANY_NAME in .env)."""
    return os.getenv("COMPANY_NAME", "").strip() or "SalesTrack"


def send(to: list[str], subject: str, body: str, *, cc: list[str] | None = None, sender_name: str = SYSTEM_NAME,
         reply_to: str | None = None, attachments: list[tuple[str, str, bytes]] = ()) -> str | None:
    """Sends one email. Returns None when sent, or the error text."""
    cfg = settings()
    if provider() == "graph":
        return send_graph(to, subject, body, cc=cc or [], sender_name=sender_name, reply_to=reply_to,
                          attachments=attachments)
    if not cfg["host"]:
        log.info("SMTP_HOST not set; email not sent: %s", subject)
        return None
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, cfg["sender"]))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)
    for filename, content_type, data in attachments:
        main, _, sub = (content_type or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=filename)
    try:
        # port 465 uses SSL from the start; other ports (587) switch to TLS with STARTTLS
        connect = smtplib.SMTP_SSL if cfg["port"] == 465 else smtplib.SMTP
        with connect(cfg["host"], cfg["port"], timeout=15) as smtp:
            if cfg["tls"] and cfg["port"] != 465:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return None
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("Email not sent (%s): %s", subject, exc)
        return str(exc) or exc.__class__.__name__


# ---------- Microsoft 365 / Outlook through Microsoft Graph (OAuth, client credentials) ----------

_graph_token: dict = {"value": "", "expires": 0.0}
GRAPH_MAX_ATTACHMENTS = 3 * 1024 * 1024  # sendMail accepts up to about 3 MB of attachments in one request


def _post_json(url: str, data: bytes, headers: dict) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode() or "{}"
        return json.loads(text)


def graph_token() -> str:
    if _graph_token["value"] and _graph_token["expires"] > time.time() + 60:
        return _graph_token["value"]
    tenant = os.getenv("MS_TENANT_ID", "")
    form = urllib.parse.urlencode({
        "client_id": os.getenv("MS_CLIENT_ID", ""),
        "client_secret": os.getenv("MS_CLIENT_SECRET", ""),
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    result = _post_json(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", form,
                        {"Content-Type": "application/x-www-form-urlencoded"})
    _graph_token.update(value=result["access_token"], expires=time.time() + int(result.get("expires_in", 3600)))
    return _graph_token["value"]


def send_graph(to: list[str], subject: str, body: str, *, cc: list[str], sender_name: str,
               reply_to: str | None, attachments) -> str | None:
    sender = settings()["sender"]
    if not all(os.getenv(k) for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET")):
        return "Outlook (Graph) is not set up: MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET are needed"
    if sum(len(d) for _, _, d in attachments) > GRAPH_MAX_ATTACHMENTS:
        return "Attachments over 3 MB in total can't be sent through Outlook yet"
    people = lambda addresses: [{"emailAddress": {"address": a}} for a in addresses]  # noqa: E731
    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "from": {"emailAddress": {"address": sender, "name": sender_name}},
        "toRecipients": people(to),
        "ccRecipients": people(cc),
        "replyTo": people([reply_to] if reply_to else []),
        "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": n, "contentType": t,
                         "contentBytes": base64.b64encode(d).decode()} for n, t, d in attachments],
    }
    try:
        _post_json(f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
                   json.dumps({"message": message, "saveToSentItems": True}).encode(),
                   {"Authorization": f"Bearer {graph_token()}", "Content-Type": "application/json"})
        return None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        log.warning("Email not sent through Graph (%s): %s %s", subject, exc.code, detail)
        return f"Outlook refused the email ({exc.code}): {detail}"
    except (OSError, KeyError, ValueError) as exc:
        log.warning("Email not sent through Graph (%s): %s", subject, exc)
        return str(exc) or exc.__class__.__name__


# ---------- outbox: send after commit ----------

def queue(db: Session, to: str, subject: str, body: str, *, sender_name: str = SYSTEM_NAME) -> None:
    db.info.setdefault("outbox", []).append((to, subject, body, sender_name))


def _deliver(messages: list[tuple[str, str, str, str]]) -> None:
    for to, subject, body, sender_name in messages:
        send([to], subject, body, sender_name=sender_name)


@event.listens_for(Session, "after_commit")
def _send_outbox(session: Session) -> None:
    messages = session.info.pop("outbox", [])
    if not messages:
        return
    # Real mail servers can take a few seconds per email; send in the background so a click
    # (e.g. Mark Stage as Complete) returns at once. MAIL_ASYNC=false sends before returning (tests).
    if os.getenv("MAIL_ASYNC", "true").lower() == "true":
        threading.Thread(target=_deliver, args=(messages,), daemon=True, name="crm-mail").start()
    else:
        _deliver(messages)


@event.listens_for(Session, "after_rollback")
def _clear_outbox(session: Session) -> None:
    session.info.pop("outbox", None)
