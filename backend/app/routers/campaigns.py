"""Email campaigns (one email to many leads) and the lead's email status.

Who can do what:
  - Send email campaigns permission (Managers and Salespersons by default): make a campaign for the leads they can see.
    A Salesperson's campaign only reaches their own leads (unless they have team access).
  - The person who made a campaign, a Manager or the Admin can pause, resume or cancel it.
Recipients: leads (Leads > select > Actions > Email Campaign) and/or email addresses typed in on New Campaign, for
people who aren't in the CRM (a typed address that belongs to a lead the user can see is treated as that lead).
Unsubscribed and invalid addresses are always left out (see app/campaigns.py for the sending rules and limits).
The unsubscribe page (/api/public/unsubscribe) needs no login: it's opened from the link in the email.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import ai_email, campaigns as engine
from app.constants import LEAD_OPEN_STAGES, LEAD_STAGES
from app.database import get_db
from app.models import Campaign, CampaignRecipient, EmailAddress, Lead
from app.security import acting_user, require, require_edit, visible
from app.services import log_activity, notify, now

router = APIRouter(prefix="/api/campaigns", tags=["Email campaigns"])
leads_router = APIRouter(prefix="/api/leads", tags=["Email campaigns"])
public = APIRouter(prefix="/api/public", tags=["Email campaigns"])

MAX_RECIPIENTS = 20_000


class TypedEmail(BaseModel):
    """An address typed in on New Campaign (name and company are optional: they fill {first_name} and {company})."""
    email: str = Field(max_length=255)
    name: str | None = Field(None, max_length=101)
    company: str | None = Field(None, max_length=200)


class Audience(BaseModel):
    """Who gets it: the leads ticked in the Leads list (lead_ids) and/or typed-in addresses (emails).
    With neither, every lead in `stages` (the stage picker, switched off in the app for now: see NewCampaign)."""
    lead_ids: list[int] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    emails: list[TypedEmail] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    stages: list[str] = Field(default_factory=list)   # empty = all open stages
    owner_id: int | None = None                       # only this owner's leads (Managers)

    @field_validator("stages")
    @classmethod
    def _stages(cls, value):
        unknown = [s for s in value if s not in LEAD_STAGES]
        if unknown:
            raise ValueError(f"Unknown stage: {', '.join(unknown)}")
        return value


class CampaignIn(Audience):
    name: str = Field(min_length=2, max_length=150)
    subject: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=10, max_length=20_000)
    send_at: datetime | None = None  # empty = now

    @field_validator("name", "subject", "body")
    @classmethod
    def _strip(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("is required")
        return value


class EmailStatusIn(BaseModel):
    status: Literal["invalid", "valid", "subscribed"]
    reason: str | None = Field(default=None, max_length=300)


def audience_query(data: Audience):
    me = acting_user()
    query = visible(select(Lead), Lead)
    if data.lead_ids or data.emails:
        query = query.where(Lead.id.in_(data.lead_ids))  # typed-in addresses are added by targets()
    else:
        query = query.where(Lead.stage.in_(data.stages or LEAD_OPEN_STAGES))
        if data.owner_id:
            query = query.where(Lead.owner_id == data.owner_id)
    if not me.sees_team:
        query = query.where(Lead.owner_id == me.id)  # a salesperson's campaign reaches only their own leads
    return query


def audience_size(db: Session, data: Audience) -> int:
    return (db.scalar(select(func.count()).select_from(audience_query(data).subquery())) or 0) + len(data.emails)


@dataclass
class Target:
    """One person a campaign goes to: a lead, or a typed-in address (lead is None)."""
    lead: Lead | None
    person: engine.Person

    @property
    def email(self) -> str | None:
        return self.person.email

    @property
    def name(self) -> str:
        return (self.person.name or self.person.email or "")[:101]


def targets(db: Session, data: Audience) -> list[Target]:
    if audience_size(db, data) > MAX_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"A campaign can go to up to {MAX_RECIPIENTS:,} people. "
                                                    "Choose fewer leads or emails.")
    out = [Target(lead, engine.Person.of_lead(lead)) for lead in db.scalars(audience_query(data).order_by(Lead.id))]
    typed = [e for e in data.emails if e.email.strip()]
    if typed:
        # a typed address that belongs to a lead this user can see is that lead (its name, company and owner)
        wanted = {e.email.strip().lower() for e in typed}
        mine = {}
        for lead in db.scalars(visible(select(Lead), Lead).where(func.lower(Lead.email).in_(wanted)).order_by(Lead.id)):
            mine.setdefault(lead.email.lower(), lead)
        for e in typed:
            lead = mine.get(e.email.strip().lower())
            out.append(Target(lead, engine.Person.of_lead(lead)) if lead
                       else Target(None, engine.Person.typed(e.email.strip(), e.name, e.company)))
    return out


def split(db: Session, people: list[Target]) -> tuple[list[Target], list[tuple[Target, str]]]:
    ok, left_out, seen = [], [], set()
    for t in people:
        reason = (engine.exclusion(t.lead) if t.lead else None) or engine.address_exclusion(db, t.email)
        if reason is None and t.email.lower() in seen:
            reason = "Same email twice in this campaign"
        if reason:
            left_out.append((t, reason))
        else:
            ok.append(t)
            seen.add(t.email.lower())
    return ok, left_out


def sample_of(t: Target, reason: str | None = None) -> dict:
    p = t.person
    out = {"id": t.lead.id if t.lead else None, "name": t.name, "email": t.email, "company": p.company,
           "first_name": p.first_name, "last_name": p.last_name}
    return out | ({"reason": reason} if reason else {})


def reason_counts(left_out) -> dict:
    counts = {"unsubscribed": 0, "invalid": 0, "no_email": 0, "other": 0}
    for _, reason in left_out:
        key = ("unsubscribed" if reason == "Unsubscribed" else "invalid" if reason.startswith("Invalid")
               else "no_email" if reason == "No email address" else "other")
        counts[key] += 1
    return counts


def eta(count: int, start: datetime) -> dict:
    """Roughly when the last email goes (all campaigns share the limits, so this is the earliest)."""
    days, rest = divmod(count, engine.per_day())
    minutes = rest / engine.per_minute()
    return {"minutes": round(count / engine.per_minute()), "days": days,
            "finish_by": (start + timedelta(days=days, minutes=minutes)).isoformat(timespec="minutes")}


def as_local(value: datetime | None) -> datetime:
    if value is None:
        return now()
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value


def can_manage(campaign: Campaign) -> None:
    me = acting_user()
    if campaign.created_by_id != me.id and me.role not in ("Manager", "Admin"):
        raise HTTPException(status_code=403, detail="Only the person who made this campaign, a Manager or the Admin "
                                                    "can change it")


def get_campaign(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    me = acting_user()
    if campaign is None or (campaign.created_by_id != me.id and not me.sees_team and not me.is_admin):
        raise HTTPException(status_code=404, detail="This campaign doesn't exist or you don't have access to it")
    return campaign


def counts_of(db: Session, ids: list[int]) -> dict[int, dict]:
    out = {i: {"total": 0, "Queued": 0, "Sent": 0, "Failed": 0, "Invalid": 0, "Skipped": 0, "Cancelled": 0} for i in ids}
    if ids:
        for campaign_id, status, n in db.execute(
                select(CampaignRecipient.campaign_id, CampaignRecipient.status, func.count())
                .where(CampaignRecipient.campaign_id.in_(ids))
                .group_by(CampaignRecipient.campaign_id, CampaignRecipient.status)).all():
            out[campaign_id][status] = n
            out[campaign_id]["total"] += n
    return out


def campaign_out(c: Campaign, counts: dict) -> dict:
    return {"id": c.id, "name": c.name, "subject": c.subject, "body": c.body, "status": c.status,
            "status_note": c.status_note, "send_at": c.send_at, "created_at": c.created_at,
            "started_at": c.started_at, "finished_at": c.finished_at,
            "created_by_id": c.created_by_id, "created_by": c.created_by.full_name if c.created_by else None,
            "counts": counts}


# ---------- campaigns ----------

@router.get("/settings")
def campaign_settings():
    """The sending limits and where the email goes (no secrets), for the New Campaign screen."""
    from app import mailer
    base = engine.unsubscribe_link(0).split("?")[0]
    # links in the email must open from the recipient's computer: localhost or a private address won't
    reachable = not re.search(r"//(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|\[::1\])", base)
    return {"limits": engine.limits(), "mail": mailer.mode(), "merge_fields": list(engine.MERGE_FIELDS),
            "unsubscribe_base": base, "links_reachable": reachable}


@router.post("/preview")
def preview(data: Audience, db: Session = Depends(get_db)):
    """Who would get the email and who is left out (and why), before making the campaign."""
    require("send_campaigns")
    size = audience_size(db, data)
    if size > MAX_RECIPIENTS:  # say so instead of failing, so the screen can ask for a smaller list
        return {"eligible": 0, "left_out": 0, "reasons": reason_counts([]), "sample": [], "left_out_sample": [],
                "too_many": size, "max": MAX_RECIPIENTS, "eta": eta(0, now())}
    ok, left_out = split(db, targets(db, data))
    return {"eligible": len(ok), "left_out": len(left_out), "reasons": reason_counts(left_out),
            "sample": [sample_of(t) for t in ok[:5]],
            "left_out_sample": [sample_of(t, r) for t, r in left_out[:50]],
            "eta": eta(len(ok), now())}


@router.post("/draft")
async def draft_campaign(data: ai_email.CampaignDraftRequest):
    """Draft with AI in New Campaign: writes (or refines) the subject and message with the placeholders {first_name},
    {company} and {sender_name}, filled in for each recipient when it's sent. Nothing is sent or saved."""
    require("send_campaigns")
    draft = await ai_email.generate_campaign_draft(data)
    return draft.model_dump()


@router.post("", status_code=201)
def create_campaign(data: CampaignIn, db: Session = Depends(get_db)):
    me = require("send_campaigns")
    send_at = as_local(data.send_at)
    if send_at < now() - timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="Choose a time in the future, or send now")
    unknown = [f for f in re.findall(r"\{(\w+)\}", data.subject + data.body) if f not in engine.MERGE_FIELDS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown merge field {{{unknown[0]}}}. Use: "
                                                    + ", ".join("{" + f + "}" for f in engine.MERGE_FIELDS))
    if not (data.lead_ids or data.emails or data.stages):
        raise HTTPException(status_code=400, detail="Add the email addresses to send to")
    ok, left_out = split(db, targets(db, data))
    if not ok:
        raise HTTPException(status_code=400, detail="None of these people can get the email "
                                                    "(no email, unsubscribed or invalid email)")
    campaign = Campaign(name=data.name, subject=data.subject, body=data.body, created_by_id=me.id, send_at=send_at,
                        status="Scheduled")
    db.add(campaign)
    db.flush()
    def row(t: Target, **extra) -> CampaignRecipient:
        return CampaignRecipient(campaign_id=campaign.id, lead_id=t.lead.id if t.lead else None, email=t.email,
                                 name=t.name, company=(t.person.company or None) if not t.lead else None,
                                 manual=t.lead is None, **extra)
    db.add_all([row(t) for t in ok])
    db.add_all([row(t, status="Skipped", error=reason[:300]) for t, reason in left_out])
    when = "now" if send_at <= now() else f"at {send_at:%d %b %Y %I:%M %p}"
    log_activity(db, me.id, "Campaign created", campaign.name,
                 f"{len(ok):,} people, sending {when} • {len(left_out):,} left out (unsubscribed, invalid or no email)")
    db.commit()
    return campaign_out(campaign, counts_of(db, [campaign.id])[campaign.id]) | {"eta": eta(len(ok), send_at)}


def my_campaign_ids():
    me = acting_user()
    mine = select(Campaign.id)
    return mine if (me.sees_team or me.is_admin) else mine.where(Campaign.created_by_id == me.id)


def unsubscribed_emails():
    """Every address that has unsubscribed (typed in, or on a lead), lower case."""
    return (select(func.lower(EmailAddress.email)).where(EmailAddress.unsubscribed_at.is_not(None))
            .union(select(func.lower(Lead.email)).where(Lead.unsubscribed_at.is_not(None), Lead.email.is_not(None))))


def unsubscribed_rows():
    """The latest email each unsubscribed person got from these campaigns (one row per address)."""
    latest = (select(func.max(CampaignRecipient.id))
              .where(CampaignRecipient.campaign_id.in_(my_campaign_ids()), CampaignRecipient.status == "Sent",
                     func.lower(CampaignRecipient.email).in_(unsubscribed_emails()))
              .group_by(func.lower(CampaignRecipient.email)))
    return CampaignRecipient.id.in_(latest)


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """The email dashboard: totals across the campaigns this user can see (sent, not sent, not working, left out)
    and the leads they can see (working emails, invalid emails, unsubscribed)."""
    me = acting_user()
    mine = my_campaign_ids()
    by_status = dict(db.execute(select(CampaignRecipient.status, func.count())
                                .where(CampaignRecipient.campaign_id.in_(mine))
                                .group_by(CampaignRecipient.status)).all())
    leads = visible(select(Lead), Lead).subquery()
    count = lambda *where: db.scalar(select(func.count()).select_from(leads).where(*where)) or 0  # noqa: E731
    invalid = count(leads.c.email_invalid_at.is_not(None))
    unsubscribed = count(leads.c.unsubscribed_at.is_not(None))
    return {
        "campaigns": db.scalar(select(func.count()).select_from(mine.subquery())) or 0,
        "emails": {"sent": by_status.get("Sent", 0), "failed": by_status.get("Failed", 0),
                   "invalid": by_status.get("Invalid", 0), "queued": by_status.get("Queued", 0),
                   "left_out": by_status.get("Skipped", 0),
                   # people who unsubscribed after getting one of these campaigns, and how many people got one
                   "unsubscribed": db.scalar(select(func.count()).select_from(CampaignRecipient)
                                             .where(unsubscribed_rows())) or 0,
                   "people": db.scalar(select(func.count(func.distinct(func.lower(CampaignRecipient.email))))
                                       .where(CampaignRecipient.campaign_id.in_(mine),
                                              CampaignRecipient.status == "Sent")) or 0},
        "leads": {
            "working": count(leads.c.email.is_not(None), leads.c.email_invalid_at.is_(None),
                             leads.c.unsubscribed_at.is_(None)),
            "invalid": invalid, "unsubscribed": unsubscribed,
            "no_email": count(leads.c.email.is_(None)),
        },
        "sent_last_24h": engine.sent_last_24h(db), "limits": engine.limits(),
    }


RECIPIENT_STATUSES = ("Sent", "Failed", "Invalid", "Queued", "Skipped", "Cancelled", "Unsubscribed")


@router.get("/recipients")
def all_recipients(status: Literal[RECIPIENT_STATUSES] = Query(...), offset: int = Query(0, ge=0),
                   limit: int = Query(100, ge=1, le=500), q: str | None = Query(None, max_length=100),
                   db: Session = Depends(get_db)):
    """The email dashboard's tabs: every email with this status, across the campaigns this user can see.
    q searches the recipient's name or email and the campaign name."""
    query = select(CampaignRecipient, Campaign.name).join(Campaign).where(
        unsubscribed_rows() if status == "Unsubscribed" else CampaignRecipient.status == status,
        Campaign.id.in_(my_campaign_ids()))
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(CampaignRecipient.name.ilike(like), CampaignRecipient.email.ilike(like),
                                Campaign.name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(CampaignRecipient.sent_at.desc().nulls_last(), CampaignRecipient.id.desc())
                      .offset(offset).limit(limit)).all()
    return {"total": total, "items": [
        {"id": r.id, "lead_id": r.lead_id, "name": r.name, "email": r.email, "status": r.status,
         "campaign_id": r.campaign_id, "campaign": name, "sent_at": r.sent_at, "attempts": r.attempts,
         "next_attempt_at": r.next_attempt_at, "error": r.error} for r, name in rows]}


@router.get("")
def list_campaigns(db: Session = Depends(get_db)):
    me = acting_user()
    query = select(Campaign).options(selectinload(Campaign.created_by)).order_by(Campaign.id.desc()).limit(200)
    if not (me.sees_team or me.is_admin):
        query = query.where(Campaign.created_by_id == me.id)
    rows = db.scalars(query).all()
    counts = counts_of(db, [c.id for c in rows])
    return {"items": [campaign_out(c, counts[c.id]) for c in rows], "limits": engine.limits(),
            "sent_last_24h": engine.sent_last_24h(db)}


@router.get("/{campaign_id}")
def get_one(campaign_id: int, status: str | None = Query(None), offset: int = Query(0, ge=0),
            limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    campaign = get_campaign(db, campaign_id)
    query = select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id)
    if status:
        query = query.where(CampaignRecipient.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(CampaignRecipient.id).offset(offset).limit(limit)).all()
    counts = counts_of(db, [campaign.id])[campaign.id]
    return campaign_out(campaign, counts) | {
        "eta": eta(counts["Queued"], max(now(), campaign.send_at)),
        "recipients": {"total": total, "items": [
            {"id": r.id, "lead_id": r.lead_id, "name": r.name, "email": r.email, "status": r.status,
             "attempts": r.attempts, "sent_at": r.sent_at, "next_attempt_at": r.next_attempt_at, "error": r.error}
            for r in rows]}}


@router.post("/{campaign_id}/{action}")
def change(campaign_id: int, action: Literal["pause", "resume", "cancel"], db: Session = Depends(get_db)):
    campaign = get_campaign(db, campaign_id)
    can_manage(campaign)
    me = acting_user()
    allowed = {"pause": ("Scheduled", "Sending"), "resume": ("Paused",), "cancel": ("Scheduled", "Sending", "Paused")}
    if campaign.status not in allowed[action]:
        raise HTTPException(status_code=409, detail=f"A {campaign.status.lower()} campaign can't be {action}d")
    if action == "pause":
        campaign.status, campaign.status_note = "Paused", f"Paused by {me.full_name}"
    elif action == "resume":
        campaign.status = "Sending" if campaign.send_at <= now() else "Scheduled"
        campaign.status_note = None
    else:
        campaign.status, campaign.finished_at = "Cancelled", now()
        campaign.status_note = f"Cancelled by {me.full_name}"
        db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id,
                                           CampaignRecipient.status == "Queued").update(
            {"status": "Cancelled"}, synchronize_session=False)
    log_activity(db, me.id, f"Campaign {action}d", campaign.name)
    db.commit()
    return campaign_out(campaign, counts_of(db, [campaign.id])[campaign.id])


# ---------- a lead's email status (Invalid / valid again / subscribed again) ----------

@leads_router.post("/{lead_id}/email-status")
def set_email_status(lead_id: int, data: EmailStatusIn, db: Session = Depends(get_db)):
    """Mark the lead's email invalid (e.g. it bounced in Outlook), valid again (after fixing it), or subscribed again
    (only when the lead asked for it: they can also do it themselves from the link in any campaign email)."""
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="This lead doesn't exist or you don't have access to it")
    me = require_edit(lead.owner_id, "lead")
    if data.status == "invalid":
        if not lead.email:
            raise HTTPException(status_code=400, detail="This lead has no email")
        engine.mark_invalid(db, lead, (data.reason or "Marked invalid").strip() or "Marked invalid", me.id)
    elif data.status == "valid":
        lead.email_invalid_at = lead.email_invalid_reason = None
        if (row := engine.address(db, lead.email or "")) is not None:
            row.invalid_at = row.invalid_reason = None  # the address works for typed-in campaigns too
        log_activity(db, me.id, "Lead email marked valid", lead.name, data.reason)
    else:
        if not (data.reason or "").strip():
            raise HTTPException(status_code=400, detail="Say when the lead asked to get emails again")
        lead.unsubscribed_at = None
        if lead.email:  # the lead asked for emails: subscribed
            row = engine.address(db, lead.email, create=True)
            row.unsubscribed_at, row.subscribed_at = None, now()
        log_activity(db, me.id, "Lead subscribed again", lead.name, data.reason.strip())
    db.commit()
    return {"id": lead.id, "email_status": engine.email_status(lead), "email_invalid_at": lead.email_invalid_at,
            "email_invalid_reason": lead.email_invalid_reason, "unsubscribed_at": lead.unsubscribed_at}


# ---------- the unsubscribe page (opened from the email; no login) ----------

def page(title: str, text: str, token: str, show: str | None, ask: bool = False, done: bool = False) -> HTMLResponse:
    """ask=True: the "Are you sure?" step, with the action button and Cancel (which changes nothing).
    done=True: the thank-you after Unsubscribe / Subscribe, with a check mark; the opposite action is a small link."""
    button = ""
    if show and done:
        label = "Subscribe again" if show == "subscribe" else "Unsubscribe"
        button = (f'<form method="post" class="undo"><span>Changed your mind?</span>'
                  f'<input type="hidden" name="t" value="{escape(token)}">'
                  f'<input type="hidden" name="action" value="{show}"><button class="link">{label}</button></form>')
    elif show:
        label = "Unsubscribe" if show == "unsubscribe" else "Subscribe again"
        cancel = (f'<a class="cancel" href="?t={escape(token)}&amp;action=cancel">Cancel</a>' if ask else "")
        button = (f'<form method="post"><input type="hidden" name="t" value="{escape(token)}">'
                  f'<input type="hidden" name="action" value="{show}"><button>{label}</button>{cancel}</form>')
    check = ('<div class="done" aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
             'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
             '<path d="m5 12 5 5 9-10"/></svg></div>') if done else ""
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title, quote=False)}</title>
<style>body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f3f6fb;margin:0;color:#181818}}
main{{max-width:440px;margin:12vh auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 12px #0001}}
h1{{font-size:20px;margin:0 0 10px}}p{{color:#444;line-height:1.5}}button{{margin-top:12px;padding:10px 18px;border:0;
border-radius:6px;background:#0176d3;color:#fff;font-size:15px;cursor:pointer}}
.cancel{{display:inline-block;margin:12px 0 0 10px;padding:9px 18px;border:1px solid #c9c9c9;border-radius:6px;
color:#181818;text-decoration:none;font-size:15px}}
.done{{display:grid;place-items:center;width:48px;height:48px;margin-bottom:14px;border-radius:50%;background:#e6f4ea;color:#2e844a}}
.undo{{margin-top:18px;padding-top:14px;border-top:1px solid #eee;color:#666;font-size:14px}}
.undo button.link{{margin:0 0 0 6px;padding:0;background:none;color:#0176d3;font-size:14px;text-decoration:underline}}</style></head>
<body><main>{check}<h1>{escape(title, quote=False)}</h1><p>{escape(text, quote=False)}</p>{button}</main></body></html>"""
    return HTMLResponse(html)


@dataclass
class Subscriber:
    """Who an unsubscribe link belongs to: a lead ('<lead id>.<sig>') or a typed-in address ('r<recipient id>.<sig>').
    Either way the change applies to the address: its email_addresses row and every lead with that email."""
    email: str
    lead: Lead | None

    def subscribed(self, db: Session) -> bool:
        return engine.is_subscribed(db, self.email)

    def unsubscribed(self, db: Session) -> bool:
        row = engine.address(db, self.email)
        return bool((row and row.unsubscribed_at) or any(l.unsubscribed_at for l in engine.leads_with(db, self.email)))


def _subscriber(db: Session, token: str) -> Subscriber | None:
    lead_id = engine.lead_from_token(token)
    if lead_id:
        lead = db.get(Lead, lead_id)
        return Subscriber(lead.email, lead) if lead and lead.email else None
    recipient_id = engine.recipient_from_token(token)
    row = db.get(CampaignRecipient, recipient_id) if recipient_id else None
    return Subscriber(row.email, None) if row and row.email else None


def _set_subscribed(db: Session, who: Subscriber, subscribed: bool) -> None:
    """Unsubscribe (or subscribe again) the address everywhere: typed-in, and each lead with it (its owner is told)."""
    row = engine.address(db, who.email, create=True)
    row.unsubscribed_at = None if subscribed else now()
    row.subscribed_at = now() if subscribed else None
    for lead in engine.leads_with(db, who.email):
        if subscribed:
            title = "Lead subscribed again" if lead.unsubscribed_at else "Lead subscribed"
            text = "subscribed to emails again." if lead.unsubscribed_at else "subscribed to campaign emails."
        elif not lead.unsubscribed_at:
            title, text = "Lead unsubscribed", "unsubscribed from campaign emails."
        else:
            continue
        lead.unsubscribed_at = None if subscribed else now()
        log_activity(db, None, title, lead.name, "From the link in a campaign email")
        notify(db, lead.owner_id, title, f"{lead.name} ({lead.email}) {text}", link=f"/leads/{lead.id}")
    if not subscribed:  # anything still queued for this address is left out
        db.query(CampaignRecipient).filter(func.lower(CampaignRecipient.email) == who.email.lower(),
                                           CampaignRecipient.status == "Queued").update(
            {"status": "Skipped", "error": "Unsubscribed"}, synchronize_session=False)
    db.commit()


NOT_VALID = "This unsubscribe link isn't valid. Please use the link from the latest email."


@public.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe_page(t: str = Query(""), action: str = Query("unsubscribe"), db: Session = Depends(get_db)):
    """Asks before changing anything: mail scanners open links, and must not unsubscribe people by themselves.
    action=subscribe (the "Subscribe" link) offers to subscribe."""
    who = _subscriber(db, t)
    company = engine.mailer.company_name()
    if who is None:
        return page("Link not valid", NOT_VALID, t, None)
    off = who.unsubscribed(db)
    if action == "cancel":
        state = "unsubscribed from" if off else "subscribed to"
        return page("Nothing changed", f"{who.email} is still {state} emails from {company}. You can close this page.",
                    t, None)
    if action == "subscribe":
        if off:
            return page("Subscribe again", f"Get campaign emails from {company} at {who.email} again?", t, "subscribe",
                        ask=True)
        if who.subscribed(db):
            return page("You're subscribed", f"{who.email} gets emails from {company}. Want to stop them?", t,
                        "unsubscribe")
        return page("Subscribe", f"Subscribe {who.email} to emails from {company}?", t, "subscribe", ask=True)
    if off:
        return page("You're unsubscribed", f"{who.email} won't get campaign emails from {company}. "
                                           "Changed your mind?", t, "subscribe")
    return page("Are you sure you want to unsubscribe?",
                f"{who.email} will stop getting campaign emails from {company}. You can subscribe again at any time.",
                t, "unsubscribe", ask=True)


@public.post("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(t: str = Query(""), form_t: str = Form("", alias="t"), action: str = Form("unsubscribe"),
                db: Session = Depends(get_db)):
    """The button on the page, and Outlook / Gmail one-click unsubscribe (RFC 8058, POST with the token in the URL)."""
    token = form_t or t
    who = _subscriber(db, token)
    company = engine.mailer.company_name()
    if who is None:
        return page("Link not valid", NOT_VALID, token, None)
    if action == "subscribe":
        if not who.subscribed(db):
            _set_subscribed(db, who, True)
        return page("Thank you. You're subscribed again.",
                    f"{who.email} will get emails from {company} again. You can close this page.", token, "unsubscribe",
                    done=True)
    if not who.unsubscribed(db):
        _set_subscribed(db, who, False)
    return page("Thank you. You've been unsubscribed.",
                f"{who.email} won't receive further campaign emails from {company}. You can close this page.",
                token, "subscribe", done=True)
