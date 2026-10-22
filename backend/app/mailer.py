"""Sending email over SMTP.

Settings (environment variables):
  SMTP_HOST       mail server. In Docker this is the Mailpit test inbox (http://localhost:8026).
                  If empty, emails are not sent (used by the automatic tests).
  SMTP_PORT       default 1025 (Mailpit). Use 587 for most real mail servers.
  SMTP_USER / SMTP_PASSWORD / SMTP_TLS=true   for a real mail server
  MAIL_FROM       sender address, default crm@salestrack.local (Gmail: must be the SMTP_USER address)
  MAIL_ASYNC      true (default) sends notification emails in the background after the save
  APP_URL         link used in notification emails, default http://localhost:5173

Emails queued during a request are sent only after the database commit succeeds,
so a failed save never sends an email.
"""
import logging
import os
import smtplib
import threading
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


def mode() -> dict:
    """Where emails go, without secrets. Used by GET /api/health/email."""
    cfg = settings()
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


def send(to: list[str], subject: str, body: str, *, cc: list[str] | None = None, sender_name: str = "SalesTrack CRM",
         reply_to: str | None = None, attachments: list[tuple[str, str, bytes]] = ()) -> str | None:
    """Sends one email. Returns None when sent, or the error text."""
    cfg = settings()
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
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as smtp:
            if cfg["tls"]:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return None
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("Email not sent (%s): %s", subject, exc)
        return str(exc) or exc.__class__.__name__


# ---------- outbox: send after commit ----------

def queue(db: Session, to: str, subject: str, body: str) -> None:
    db.info.setdefault("outbox", []).append((to, subject, body))


def _deliver(messages: list[tuple[str, str, str]]) -> None:
    for to, subject, body in messages:
        send([to], subject, body)


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
