"""Email campaigns: one email to many leads, sent a few at a time so the Outlook mailbox stays inside its limits.

Outlook / Exchange Online limits for one mailbox (Microsoft, 2026):
  - 30 messages a minute
  - 10,000 recipients a day
  - 2,000 EXTERNAL recipients a day (External Recipient Rate Limit, enforced from 1 Oct 2026); over it, Outlook
    holds back external email until the 24-hour window resets
  - Microsoft Graph answers 429 (Too Many Requests) with a Retry-After when a mailbox is called too often
So by default the CRM sends at most 20 a minute and 1,800 in any 24 hours (all campaigns together, because they
share the MAIL_FROM mailbox), and waits when Outlook asks it to. Change with CAMPAIGN_PER_MINUTE / CAMPAIGN_PER_DAY.

Who gets the email (checked when the campaign is made AND again right before each email):
  - the lead has an email address, it isn't marked invalid, and the lead hasn't unsubscribed.
Invalid addresses are found three ways: the address isn't a valid email, its domain has no mail server (DNS), or the
mail server rejects the recipient (e.g. 550 5.1.1 user unknown). The lead is then marked invalid, listed under
Leads > "Invalid emails", and left out of every later campaign. A salesperson can also mark an email invalid (e.g. after
a bounce in Outlook) or valid again after fixing it.

Recipients are leads (Leads > select > Actions > Email Campaign) and/or email addresses typed in on New Campaign
(people who aren't in the CRM). An unsubscribed or invalid address is left out whichever way it is added
(email_addresses table + the lead's own flags, kept in step).

The first campaign email to an address ends with Unsubscribe and Subscribe links; later ones (the person is
subscribed) only with Unsubscribe. SMTP mail also carries the List-Unsubscribe headers that Outlook and Gmail show as
an "Unsubscribe" button.
Temporary problems (Outlook busy, network) are retried 3 times (after 5 minutes, 30 minutes and 2 hours).
If the mail settings are wrong (login refused), sending campaigns pause and their owners are told.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import smtplib
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mailer
from app.models import Campaign, CampaignRecipient, EmailAddress, Lead, User
from app.services import log_activity, notify, now

log = logging.getLogger("crm.campaigns")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
RETRY_AFTER = (timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2))  # then it counts as Failed
MERGE_FIELDS = ("first_name", "last_name", "full_name", "company", "sender_name")


def per_minute() -> int:
    return max(1, min(30, int(os.getenv("CAMPAIGN_PER_MINUTE", "20"))))


def per_day() -> int:
    return max(1, min(10_000, int(os.getenv("CAMPAIGN_PER_DAY", "1800"))))


def check_domains() -> bool:
    return os.getenv("CAMPAIGN_CHECK_DOMAINS", "true").lower() == "true"


def limits() -> dict:
    return {"per_minute": per_minute(), "per_day": per_day(), "retries": len(RETRY_AFTER),
            "outlook": {"per_minute": 30, "recipients_per_day": 10_000, "external_per_day": 2_000}}


# ---------- who can get campaign email ----------

def email_status(lead: Lead) -> str:
    if not lead.email:
        return "No email"
    if lead.unsubscribed_at:
        return "Unsubscribed"
    if lead.email_invalid_at:
        return "Invalid"
    return "OK"


def exclusion(lead: Lead) -> str | None:
    """Why this lead must not get a campaign email (None = it can)."""
    status = email_status(lead)
    if status == "No email":
        return "No email address"
    if status == "Unsubscribed":
        return "Unsubscribed"
    if status == "Invalid":
        return f"Invalid email: {lead.email_invalid_reason or 'marked invalid'}"
    if not EMAIL_RE.match(lead.email):
        return "Invalid email: not a valid address"
    return None


def mark_invalid(db: Session, lead: Lead, reason: str, actor_id: int | None = None) -> None:
    if lead.email_invalid_at:
        return
    lead.email_invalid_at = now()
    lead.email_invalid_reason = reason[:300]
    log_activity(db, actor_id, "Lead email marked invalid", lead.name, reason[:300])


# ---------- any address (typed in, or a lead's) ----------

def address(db: Session, email: str, create: bool = False) -> EmailAddress | None:
    key = (email or "").strip().lower()
    row = db.get(EmailAddress, key) if key else None
    if row is None and create and key:
        row = EmailAddress(email=key)
        db.add(row)
    return row


def leads_with(db: Session, email: str) -> list[Lead]:
    return db.scalars(select(Lead).where(func.lower(Lead.email) == (email or "").strip().lower())).all()


def address_exclusion(db: Session, email: str | None) -> str | None:
    """Why this address must not get a campaign email, whoever it belongs to (None = it can): unsubscribed or invalid
    as a typed-in address, or on any lead with this email."""
    if not email:
        return "No email address"
    if not EMAIL_RE.match(email.strip()):
        return "Invalid email: not a valid address"
    row = address(db, email)
    if row and row.unsubscribed_at:
        return "Unsubscribed"
    if row and row.invalid_at:
        return f"Invalid email: {row.invalid_reason or 'marked invalid'}"
    for lead in leads_with(db, email):
        reason = exclusion(lead)
        if reason:
            return reason
    return None


def mark_address_invalid(db: Session, email: str, reason: str) -> None:
    """A typed-in address that doesn't work (and any lead with it)."""
    row = address(db, email, create=True)
    if not row.invalid_at:
        row.invalid_at, row.invalid_reason = now(), reason[:300]
    for lead in leads_with(db, email):
        mark_invalid(db, lead, reason)


def already_emailed(db: Session, email: str, row_id: int | None = None) -> bool:
    """This address got a campaign email before (so it's subscribed: the Subscribe link isn't needed again)."""
    query = select(CampaignRecipient.id).where(CampaignRecipient.status == "Sent",
                                               func.lower(CampaignRecipient.email) == (email or "").strip().lower())
    if row_id is not None:
        query = query.where(CampaignRecipient.id != row_id)
    return db.scalar(query.limit(1)) is not None


# ---------- unsubscribe links ----------

def _key() -> bytes:
    return os.getenv("SECRET_KEY", "salestrack-dev-secret-change-me").encode()


def _sign(text: str) -> str:
    sig = hmac.new(_key(), f"unsubscribe:{text}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig[:18]).decode().rstrip("=")


def unsubscribe_token(lead_id: int) -> str:
    """A lead's link: '<lead id>.<signature>'."""
    return f"{lead_id}.{_sign(str(lead_id))}"


def recipient_token(recipient_id: int) -> str:
    """A typed-in address's link (not a lead): 'r<campaign recipient id>.<signature>'."""
    return f"r{recipient_id}.{_sign(f'r{recipient_id}')}"


def lead_from_token(token: str) -> int | None:
    lead_id, _, _ = (token or "").partition(".")
    if not lead_id.isdigit():
        return None
    return int(lead_id) if hmac.compare_digest(unsubscribe_token(int(lead_id)), token) else None


def recipient_from_token(token: str) -> int | None:
    head, _, _ = (token or "").partition(".")
    if not (head.startswith("r") and head[1:].isdigit()):
        return None
    return int(head[1:]) if hmac.compare_digest(recipient_token(int(head[1:])), token) else None


def _public_base() -> str:
    return os.getenv("PUBLIC_URL", "").rstrip("/") or mailer.settings()["app_url"]


def unsubscribe_link(lead_id: int, action: str = "unsubscribe", *, token: str | None = None) -> str:
    """The page that unsubscribes (action=unsubscribe) or subscribes (action=subscribe); it asks before changing
    anything. PUBLIC_URL (else APP_URL) must be an address the people you email can open."""
    extra = "" if action == "unsubscribe" else f"&action={action}"
    return f"{_public_base()}/api/public/unsubscribe?t={token or unsubscribe_token(lead_id)}{extra}"


def row_token(row: CampaignRecipient) -> str:
    return unsubscribe_token(row.lead_id) if row.lead_id and not row.manual else recipient_token(row.id)


# ---------- the email ----------

def company_from_email(email: str | None) -> str:
    """'asha@acme-retail.com' -> 'Acme Retail' (empty for personal mailboxes like gmail.com)."""
    from app.services import is_personal_email
    domain = (email or "").rsplit("@", 1)[-1].lower() if "@" in (email or "") else ""
    if not domain or is_personal_email(email):
        return ""
    name = domain.split(".")[0]
    return " ".join(part.capitalize() for part in re.split(r"[-_]", name) if part)


def name_from_email(email: str | None) -> str:
    """'asha.rao@acme.com' -> 'Asha Rao' (a typed-in address with no name)."""
    local = (email or "").split("@", 1)[0]
    parts = [p for p in re.split(r"[._-]+", local) if p.isalpha()]
    return " ".join(p.capitalize() for p in parts[:2])


@dataclass
class Person:
    """Who an email goes to, for the {fields}: a lead, or a typed-in address with an optional name and company."""
    email: str | None
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None
    company: str | None = None

    @classmethod
    def of_lead(cls, lead: Lead) -> "Person":
        return cls(lead.email, lead.first_name, lead.last_name, lead.name, lead.company)

    @classmethod
    def typed(cls, email: str, name: str | None = None, company: str | None = None) -> "Person":
        name = (name or "").strip() or name_from_email(email)
        first, _, last = name.partition(" ")
        return cls(email, first or None, last or None, name or None, (company or "").strip() or None)


def fill(text: str, lead, sender: User) -> str:
    """The {fields} in the subject and message, filled for this person. Missing ones fill themselves: the company from
    the email's domain, the first name as 'there'."""
    values = {
        "first_name": lead.first_name or lead.last_name or "there",
        "last_name": lead.last_name or "",
        "full_name": lead.name or lead.last_name or "",
        "company": lead.company or company_from_email(lead.email) or "your team",
        "sender_name": sender.full_name,
    }
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), text)


def footer(lead_id: int | None = None, *, token: str | None = None, first: bool = True) -> str:
    """The first campaign email to an address ends with both links (Unsubscribe and Subscribe); later ones, when the
    person is already subscribed, only with Unsubscribe."""
    lines = [f"\n\n--\nYou are receiving this email from {mailer.company_name()}.",
             f"Unsubscribe: {unsubscribe_link(lead_id, token=token)}"]
    if first:
        lines.append(f"Subscribe: {unsubscribe_link(lead_id, 'subscribe', token=token)}")
    return "\n".join(lines)


@dataclass
class Result:
    outcome: str            # sent | retry | invalid | failed | setup (mail settings wrong: pause everything)
    detail: str = ""
    wait: int = 0           # seconds Outlook asked us to wait (Retry-After)


INVALID_SMTP = (550, 551, 553, 501)  # mailbox unknown / not allowed / bad address


def classify_smtp(exc: Exception) -> Result:
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        code, message = next(iter(exc.recipients.values()), (550, b""))
        text = message.decode(errors="replace") if isinstance(message, bytes) else str(message)
        if code in INVALID_SMTP or "5.1." in text:
            return Result("invalid", f"{code} {text}"[:300])
        return Result("retry" if 400 <= code < 500 else "failed", f"{code} {text}"[:300])
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return Result("setup", "The mail server refused the login (check SMTP_USER / SMTP_PASSWORD)")
    if isinstance(exc, smtplib.SMTPResponseException):
        text = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        return Result("retry" if 400 <= exc.smtp_code < 500 else "failed", f"{exc.smtp_code} {text}"[:300])
    return Result("retry", (str(exc) or exc.__class__.__name__)[:300])  # network problems: try again later


def send_one(to: str, subject: str, body: str, *, sender_name: str, reply_to: str, unsubscribe: str) -> Result:
    """Sends one campaign email and says what happened (used for every recipient; tests replace it)."""
    if mailer.provider() == "graph":
        return _send_graph(to, subject, body, sender_name=sender_name, reply_to=reply_to)
    cfg = mailer.settings()
    if not cfg["host"]:
        return Result("setup", "Email isn't set up (SMTP_HOST is empty)")
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = formataddr((sender_name, cfg["sender"]))
    msg["To"] = to
    msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    # one-click unsubscribe button in Outlook and Gmail (RFC 8058)
    msg["List-Unsubscribe"] = f"<{unsubscribe}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(body, cte="quoted-printable")  # keeps body lines short whatever the message
    # then no header folding: List-Unsubscribe must stay one plain <URL> for Outlook / Gmail to show the button.
    # (Set after the body: Python 3.12 can't encode a body with max_line_length=None.)
    msg.policy = policy.SMTP.clone(max_line_length=None)
    try:
        connect = smtplib.SMTP_SSL if cfg["port"] == 465 else smtplib.SMTP
        with connect(cfg["host"], cfg["port"], timeout=20) as smtp:
            if cfg["tls"] and cfg["port"] != 465:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return Result("sent")
    except (OSError, smtplib.SMTPException) as exc:
        return classify_smtp(exc)


def _send_graph(to: str, subject: str, body: str, *, sender_name: str, reply_to: str) -> Result:
    if not all(os.getenv(k) for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET")):
        return Result("setup", "Outlook isn't set up: MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET are needed")
    sender = mailer.settings()["sender"]
    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "from": {"emailAddress": {"address": sender, "name": sender_name}},
        "toRecipients": [{"emailAddress": {"address": to}}],
        "replyTo": [{"emailAddress": {"address": reply_to}}],
    }
    try:
        request = urllib.request.Request(
            f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
            data=json.dumps({"message": message, "saveToSentItems": True}).encode(), method="POST",
            headers={"Authorization": f"Bearer {mailer.graph_token()}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20):
            return Result("sent")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:250]
        if exc.code in (429, 503, 504, 500):
            wait = int(exc.headers.get("Retry-After") or 60) if exc.headers else 60
            return Result("retry", f"Outlook is busy ({exc.code})", wait=wait)
        if exc.code in (401, 403):
            return Result("setup", f"Outlook refused the app ({exc.code}): check Mail.Send permission")
        if "ErrorInvalidRecipients" in detail or "InvalidRecipient" in detail:
            return Result("invalid", "Outlook says the address is not valid")
        return Result("failed", f"Outlook refused the email ({exc.code}): {detail}"[:300])
    except (OSError, KeyError, ValueError) as exc:
        return Result("retry", (str(exc) or exc.__class__.__name__)[:300])


# ---------- domain check (has the domain got a mail server?) ----------

_domains: dict[str, tuple[bool, float]] = {}


def domain_accepts_mail(domain: str) -> bool:
    """True unless DNS clearly says the domain doesn't exist. Uses dnspython (MX) when installed, else an address lookup.
    Network problems count as OK (the send itself is the final check)."""
    domain = domain.lower()
    cached = _domains.get(domain)
    if cached and cached[1] > time.time():
        return cached[0]
    ok = True
    try:
        import dns.resolver  # optional (dnspython)
        try:
            dns.resolver.resolve(domain, "MX", lifetime=5)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            try:
                dns.resolver.resolve(domain, "A", lifetime=5)
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                ok = False
        except Exception:  # timeouts, no DNS: don't judge
            ok = True
    except ImportError:
        try:
            socket.getaddrinfo(domain, None)
        except socket.gaierror as exc:
            ok = exc.errno != getattr(socket, "EAI_NONAME", None)  # "name not known": the domain doesn't exist
        except OSError:
            ok = True
    _domains[domain] = (ok, time.time() + 6 * 3600)
    return ok


# ---------- the sender (runs every minute in the background) ----------

_lock = threading.Lock()


def sent_last_24h(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(CampaignRecipient)
                     .where(CampaignRecipient.sent_at >= now() - timedelta(hours=24))) or 0


def _finish(db: Session, campaign: Campaign) -> None:
    left = db.scalar(select(func.count()).select_from(CampaignRecipient).where(
        CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "Queued")) or 0
    if left or campaign.status != "Sending":
        return
    counts = dict(db.execute(select(CampaignRecipient.status, func.count()).where(
        CampaignRecipient.campaign_id == campaign.id).group_by(CampaignRecipient.status)).all())
    campaign.status, campaign.finished_at = "Completed", now()
    summary = (f"{counts.get('Sent', 0):,} sent • {counts.get('Invalid', 0):,} invalid emails • "
               f"{counts.get('Failed', 0):,} failed • {counts.get('Skipped', 0):,} left out")
    notify(db, campaign.created_by_id, "Campaign sent", f'"{campaign.name}": {summary}', link=f"/campaigns/{campaign.id}")
    log_activity(db, campaign.created_by_id, "Campaign completed", campaign.name, summary)


def _pause_all(db: Session, reason: str) -> None:
    for campaign in db.scalars(select(Campaign).where(Campaign.status == "Sending")).all():
        campaign.status, campaign.status_note = "Paused", reason[:300]
        notify(db, campaign.created_by_id, "Campaign paused", f'"{campaign.name}" is paused: {reason}',
               link=f"/campaigns/{campaign.id}")


def run(db: Session, budget: int | None = None, pause_seconds: float | None = None) -> dict:
    """One round: start campaigns that are due, then send up to a minute's worth of emails (fewer when the
    24-hour limit is near). Returns what happened. Safe to call often; one round runs at a time."""
    if not _lock.acquire(blocking=False):
        return {"busy": True}
    try:
        return _run(db, budget, pause_seconds)
    finally:
        _lock.release()


def _run(db: Session, budget: int | None, pause_seconds: float | None) -> dict:
    current = now()
    for campaign in db.scalars(select(Campaign).where(Campaign.status == "Scheduled", Campaign.send_at <= current)).all():
        campaign.status, campaign.started_at = "Sending", current
    db.commit()
    room = per_day() - sent_last_24h(db)
    budget = min(per_minute() if budget is None else budget, max(0, room))
    done = {"sent": 0, "invalid": 0, "retry": 0, "failed": 0, "skipped": 0}
    if budget <= 0:
        if room <= 0:
            log.info("Campaigns: the 24-hour limit (%s) is reached; sending continues later", per_day())
        return done | {"waiting": "daily limit"}
    gap = 60 / per_minute() if pause_seconds is None else pause_seconds
    rows = db.scalars(
        select(CampaignRecipient).join(Campaign)
        .where(Campaign.status == "Sending", CampaignRecipient.status == "Queued",
               (CampaignRecipient.next_attempt_at.is_(None)) | (CampaignRecipient.next_attempt_at <= current))
        .order_by(Campaign.send_at, Campaign.id, CampaignRecipient.id).limit(budget)
    ).all()
    touched = set()
    for i, row in enumerate(rows):
        campaign = row.campaign
        db.refresh(campaign)
        if campaign.status != "Sending":
            continue
        touched.add(campaign.id)
        lead = db.get(Lead, row.lead_id) if row.lead_id and not row.manual else None
        if row.manual:  # typed in: not a lead (or not one this user could see)
            reason = address_exclusion(db, row.email)
            person = Person.typed(row.email, row.name, row.company)
        else:
            reason = "The lead was deleted" if lead is None else (exclusion(lead) or address_exclusion(db, lead.email))
            person = Person.of_lead(lead) if lead else None
            if reason is None and lead.email.lower() != (row.email or "").lower():
                row.email = lead.email  # the email was corrected after the campaign was made
        if reason is None and check_domains() and not domain_accepts_mail(row.email.rsplit("@", 1)[1]):
            why = "The email domain doesn't exist or has no mail server"
            mark_invalid(db, lead, why) if lead else mark_address_invalid(db, row.email, why)
            reason = "Invalid email: the domain has no mail server"
        if reason:
            row.status, row.error = ("Invalid" if reason.startswith("Invalid") else "Skipped"), reason[:300]
            done["invalid" if row.status == "Invalid" else "skipped"] += 1
            db.commit()
            continue
        sender = campaign.created_by
        token = row_token(row)
        first = not already_emailed(db, row.email, row.id)
        result = send_one(row.email, fill(campaign.subject, person, sender),
                          fill(campaign.body, person, sender) + footer(row.lead_id, token=token, first=first),
                          sender_name=sender.full_name, reply_to=sender.email,
                          unsubscribe=unsubscribe_link(row.lead_id, token=token))
        row.attempts += 1
        if result.outcome == "sent":
            row.status, row.sent_at, row.error = "Sent", now(), None
            done["sent"] += 1
        elif result.outcome == "invalid":
            row.status, row.error = "Invalid", result.detail
            why = f"Rejected by the mail server: {result.detail}"
            mark_invalid(db, lead, why) if lead else mark_address_invalid(db, row.email, why)
            done["invalid"] += 1
        elif result.outcome == "setup":
            row.attempts -= 1  # not this recipient's fault
            _pause_all(db, result.detail)
            db.commit()
            log.warning("Campaigns paused: %s", result.detail)
            return done | {"paused": result.detail}
        elif result.outcome == "retry" and row.attempts <= len(RETRY_AFTER):
            wait = max(RETRY_AFTER[row.attempts - 1], timedelta(seconds=result.wait))
            row.next_attempt_at, row.error = now() + wait, f"Will try again: {result.detail}"[:300]
            done["retry"] += 1
        else:
            row.status, row.error = "Failed", result.detail or "Not sent"
            done["failed"] += 1
        db.commit()
        if result.outcome == "retry" and result.wait:
            break  # Outlook asked us to slow down: stop this round
        if gap and i < len(rows) - 1:
            time.sleep(gap)
    for campaign_id in touched | set(db.scalars(select(Campaign.id).where(Campaign.status == "Sending")).all()):
        _finish(db, db.get(Campaign, campaign_id))
    db.commit()
    if any(done.values()):
        log.info("Campaign round: %s", done)
    return done


async def loop(session_factory) -> None:
    """Runs a round every minute while the API is up (CAMPAIGN_INTERVAL_SECONDS)."""
    import asyncio
    interval = int(os.getenv("CAMPAIGN_INTERVAL_SECONDS", "60"))
    while True:
        try:
            def work():
                with session_factory() as db:
                    return run(db)
            await asyncio.to_thread(work)
        except Exception:  # keep the loop alive; the next round tries again
            log.exception("Campaign round failed")
        await asyncio.sleep(interval)
