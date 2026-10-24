"""Emails sent from a lead, opportunity, contact or account page, with attachments.

The email goes out over SMTP (see app/mailer.py) and is saved with its attachments,
so it shows on the record's activity even if sending failed (status "Failed").
A failed email can be sent again with POST /api/emails/{id}/resend (same message and attachments).

From: every email goes out from the CRM mailbox (MAIL_FROM), shown as "<your name> via SalesTrack".
Replies go to the Reply-To address: your own email unless you type another one.
open_in=gmail|outlook: nothing is sent from here; the email is only saved on the record, and the
app opens it in your own Gmail / Outlook to send (attachments have to be added there).
"""
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mailer, schemas
from app.database import get_db
from app.models import Account, Contact, Email, EmailAttachment, Lead, Opportunity, User
from app.security import acting_user, require, require_view
from app.services import get_or_404

router = APIRouter(prefix="/api/emails", tags=["Emails"])

MAX_FILES = 10
MAX_FILE_BYTES = 10 * 1024 * 1024    # 10 MB per file
MAX_TOTAL_BYTES = 25 * 1024 * 1024   # 25 MB per email, like most mail servers
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def address_list(value: str | None, label: str, required: bool = False) -> list[str]:
    items = [a.strip() for a in re.split(r"[,;]", value or "") if a.strip()]
    if required and not items:
        raise HTTPException(status_code=422, detail=f"{label} is required")
    bad = [a for a in items if not EMAIL_RE.match(a)]
    if bad:
        raise HTTPException(status_code=422, detail=f"Invalid email address in {label}: {', '.join(bad)}")
    return items


def email_visible(db: Session, email: Email) -> bool:
    """You can see an email you sent, or one on a record you can see."""
    me = acting_user()
    if me.sees_team or email.sent_by_id == me.id:
        return True
    for model, record_id in ((Lead, email.lead_id), (Opportunity, email.opportunity_id),
                             (Contact, email.contact_id), (Account, email.account_id)):
        record = db.get(model, record_id) if record_id is not None else None
        if record is not None and record.owner_id == me.id:
            return True
    return False


def email_out(e: Email) -> schemas.EmailOut:
    return schemas.EmailOut.model_validate(e).model_copy(
        update={"sent_by_name": e.sent_by.full_name if e.sent_by else None}
    )


@router.post("", response_model=schemas.EmailOut, status_code=status.HTTP_201_CREATED)
async def send_email(
    to: str = Form(..., description="One or more addresses, separated by commas"),
    subject: str = Form(..., min_length=1, max_length=255),
    body: str = Form(..., min_length=1),
    sent_by_id: int | None = Form(None, description="Ignored: the logged-in user sends it"),
    cc: str | None = Form(None),
    reply_to: str | None = Form(None, description="Where replies go; default: your own email"),
    open_in: str | None = Form(None, description="outlook: only save it; you send it from your own Outlook"),
    lead_id: int | None = Form(None),
    opportunity_id: int | None = Form(None),
    contact_id: int | None = Form(None),
    account_id: int | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    """Send an email from the CRM and save it on the record (lead, opportunity, contact or account)."""
    to_list = address_list(to, "To", required=True)
    cc_list = address_list(cc, "Cc")
    if not any(x is not None for x in (lead_id, opportunity_id, contact_id, account_id)):
        raise HTTPException(status_code=400, detail="Link the email to a lead, opportunity, contact or account")
    require("send_emails")
    sender = db.get(User, acting_user().id)
    reply = (address_list(reply_to, "Reply-To") or [sender.email])[0]
    if open_in not in (None, "", "outlook"):
        raise HTTPException(status_code=422, detail="open_in must be outlook")
    for model, record_id, label in ((Lead, lead_id, "Lead"), (Opportunity, opportunity_id, "Opportunity"),
                                    (Contact, contact_id, "Contact"), (Account, account_id, "Account")):
        if record_id is not None:
            require_view(get_or_404(db, model, record_id, label).owner_id, label.lower())

    files = [f for f in files if f.filename]
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=422, detail=f"You can attach up to {MAX_FILES} files")
    attachments: list[tuple[str, str, bytes]] = []
    total = 0
    for f in files:
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename} is larger than 10 MB")
        total += len(data)
        attachments.append((f.filename, f.content_type or "application/octet-stream", data))
    if total > MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail="Attachments are larger than 25 MB in total")

    if open_in:
        error, state = None, "Outlook"
    else:
        error = mailer.send(
            to_list, subject.strip(), body, cc=cc_list, sender_name=f"{sender.full_name} via SalesTrack",
            reply_to=reply, attachments=attachments,
        )
        state = "Failed" if error else "Sent"
    email = Email(
        subject=subject.strip(), body=body, to_address=", ".join(to_list), cc_address=", ".join(cc_list) or None,
        status=state, error=error, sent_by_id=sender.id,
        lead_id=lead_id, opportunity_id=opportunity_id, contact_id=contact_id, account_id=account_id,
        attachments=[EmailAttachment(filename=n, content_type=t, size_bytes=len(d), data=d) for n, t, d in attachments],
    )
    db.add(email)
    db.commit()
    db.refresh(email)
    return email_out(email)


@router.post("/{email_id}/resend", response_model=schemas.EmailOut)
def resend_email(email_id: int, db: Session = Depends(get_db)):
    """Send a failed email again (same recipients, text and attachments). The saved email gets the new status."""
    email = get_or_404(db, Email, email_id, "Email")
    if email.status != "Failed":
        raise HTTPException(status_code=409, detail="This email was already sent")
    me = acting_user()
    if not me.can("edit_team_records") and email.sent_by_id != me.id:
        raise HTTPException(status_code=403, detail="Only the person who wrote it (or a Manager) can resend this email")
    sender = email.sent_by
    error = mailer.send(
        address_list(email.to_address, "To", required=True), email.subject, email.body,
        cc=address_list(email.cc_address, "Cc"), sender_name=f"{sender.full_name} via SalesTrack",
        reply_to=sender.email, attachments=[(a.filename, a.content_type, a.data) for a in email.attachments],
    )
    email.status, email.error = ("Failed", error) if error else ("Sent", None)
    if not error:
        email.sent_at = func.now()
    db.commit()
    db.refresh(email)
    return email_out(email)


@router.get("/settings")
def email_settings():
    """What the Send Email form shows as From (the CRM mailbox) and how email is sent."""
    me = acting_user()
    info = mailer.mode()
    sender = mailer.settings()["sender"]
    return {"from_address": sender, "from_display": f"{me.full_name} via SalesTrack <{sender}>",
            "reply_to": me.email, "mode": info.get("mode"), "detail": info.get("detail")}


@router.get("", response_model=list[schemas.EmailOut])
def list_emails(
    lead_id: int | None = Query(None),
    opportunity_id: int | None = Query(None),
    contact_id: int | None = Query(None),
    account_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Emails for a record, newest first."""
    query = select(Email)
    for column, value, model, label in ((Email.lead_id, lead_id, Lead, "Lead"),
                                        (Email.opportunity_id, opportunity_id, Opportunity, "Opportunity"),
                                        (Email.contact_id, contact_id, Contact, "Contact"),
                                        (Email.account_id, account_id, Account, "Account")):
        if value is not None:
            require_view(get_or_404(db, model, value, label).owner_id, label.lower())
            query = query.where(column == value)
    if not any(v is not None for v in (lead_id, opportunity_id, contact_id, account_id)) and not acting_user().sees_team:
        query = query.where(Email.sent_by_id == acting_user().id)
    return [email_out(e) for e in db.scalars(query.order_by(Email.id.desc())).all()]


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)):
    item = get_or_404(db, EmailAttachment, attachment_id, "Attachment")
    if not email_visible(db, item.email):
        raise HTTPException(status_code=404, detail=f"Attachment {attachment_id} not found")
    return Response(
        content=item.data,
        media_type=item.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(item.filename)}"},
    )
