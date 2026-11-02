"""Email campaigns (one email to many leads) and the lead's email status.

Who can do what:
  - Send email campaigns permission (Managers and Salespersons by default): make a campaign for the leads they can see.
    A Salesperson's campaign only reaches their own leads (unless they have team access).
  - The person who made a campaign, a Manager or the Admin can pause, resume or cancel it.
Unsubscribed leads and invalid emails are always left out (see app/campaigns.py for the sending rules and limits).
The unsubscribe page (/api/public/unsubscribe) needs no login: it's opened from the link in the email.
"""
import re
from datetime import datetime, timedelta
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import campaigns as engine
from app.constants import LEAD_OPEN_STAGES, LEAD_STAGES
from app.database import get_db
from app.models import Campaign, CampaignRecipient, Lead
from app.security import acting_user, require, require_edit, visible
from app.services import log_activity, notify, now

router = APIRouter(prefix="/api/campaigns", tags=["Email campaigns"])
leads_router = APIRouter(prefix="/api/leads", tags=["Email campaigns"])
public = APIRouter(prefix="/api/public", tags=["Email campaigns"])

MAX_RECIPIENTS = 20_000


class Audience(BaseModel):
    """Either the leads ticked in the Leads list (lead_ids), or every lead matching the filter."""
    lead_ids: list[int] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
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
    if data.lead_ids:
        query = query.where(Lead.id.in_(data.lead_ids))
    else:
        query = query.where(Lead.stage.in_(data.stages or LEAD_OPEN_STAGES))
        if data.owner_id:
            query = query.where(Lead.owner_id == data.owner_id)
    if not me.sees_team:
        query = query.where(Lead.owner_id == me.id)  # a salesperson's campaign reaches only their own leads
    return query


def audience_size(db: Session, data: Audience) -> int:
    return db.scalar(select(func.count()).select_from(audience_query(data).subquery())) or 0


def audience(db: Session, data: Audience) -> list[Lead]:
    if audience_size(db, data) > MAX_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"A campaign can go to up to {MAX_RECIPIENTS:,} leads. "
                                                    "Choose fewer stages or one owner.")
    return db.scalars(audience_query(data).order_by(Lead.id)).all()


def split(leads: list[Lead]) -> tuple[list[Lead], list[tuple[Lead, str]]]:
    ok, left_out, seen = [], [], set()
    for lead in leads:
        reason = engine.exclusion(lead)
        if reason is None and lead.email.lower() in seen:
            reason = "Same email as another lead in this campaign"
        if reason:
            left_out.append((lead, reason))
        else:
            ok.append(lead)
            seen.add(lead.email.lower())
    return ok, left_out


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
    return {"limits": engine.limits(), "mail": mailer.mode(), "merge_fields": list(engine.MERGE_FIELDS),
            "unsubscribe_base": engine.unsubscribe_link(0).split("?")[0]}


@router.post("/preview")
def preview(data: Audience, db: Session = Depends(get_db)):
    """Who would get the email and who is left out (and why), before making the campaign."""
    require("send_campaigns")
    size = audience_size(db, data)
    if size > MAX_RECIPIENTS:  # say so instead of failing, so the screen can ask for a smaller list
        return {"eligible": 0, "left_out": 0, "reasons": reason_counts([]), "sample": [], "left_out_sample": [],
                "too_many": size, "max": MAX_RECIPIENTS, "eta": eta(0, now())}
    ok, left_out = split(audience(db, data))
    return {"eligible": len(ok), "left_out": len(left_out), "reasons": reason_counts(left_out),
            "sample": [{"id": l.id, "name": l.name, "email": l.email, "company": l.company} for l in ok[:5]],
            "left_out_sample": [{"id": l.id, "name": l.name, "email": l.email, "reason": r} for l, r in left_out[:50]],
            "eta": eta(len(ok), now())}


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
    ok, left_out = split(audience(db, data))
    if not ok:
        raise HTTPException(status_code=400, detail="None of these leads can get the email "
                                                    "(no email, unsubscribed or invalid email)")
    campaign = Campaign(name=data.name, subject=data.subject, body=data.body, created_by_id=me.id, send_at=send_at,
                        status="Scheduled")
    db.add(campaign)
    db.flush()
    db.add_all([CampaignRecipient(campaign_id=campaign.id, lead_id=l.id, email=l.email, name=l.name[:101])
                for l in ok])
    db.add_all([CampaignRecipient(campaign_id=campaign.id, lead_id=l.id, email=l.email, name=l.name[:101],
                                  status="Skipped", error=reason[:300]) for l, reason in left_out])
    when = "now" if send_at <= now() else f"at {send_at:%d %b %Y %I:%M %p}"
    log_activity(db, me.id, "Campaign created", campaign.name,
                 f"{len(ok):,} leads, sending {when} • {len(left_out):,} left out (unsubscribed, invalid or no email)")
    db.commit()
    return campaign_out(campaign, counts_of(db, [campaign.id])[campaign.id]) | {"eta": eta(len(ok), send_at)}


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
        log_activity(db, me.id, "Lead email marked valid", lead.name, data.reason)
    else:
        if not (data.reason or "").strip():
            raise HTTPException(status_code=400, detail="Say when the lead asked to get emails again")
        lead.unsubscribed_at = None
        log_activity(db, me.id, "Lead subscribed again", lead.name, data.reason.strip())
    db.commit()
    return {"id": lead.id, "email_status": engine.email_status(lead), "email_invalid_at": lead.email_invalid_at,
            "email_invalid_reason": lead.email_invalid_reason, "unsubscribed_at": lead.unsubscribed_at}


# ---------- the unsubscribe page (opened from the email; no login) ----------

def page(title: str, text: str, token: str, show: str | None) -> HTMLResponse:
    button = ""
    if show:
        label = "Unsubscribe" if show == "unsubscribe" else "Subscribe again"
        button = (f'<form method="post"><input type="hidden" name="t" value="{escape(token)}">'
                  f'<input type="hidden" name="action" value="{show}"><button>{label}</button></form>')
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title, quote=False)}</title>
<style>body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f3f6fb;margin:0;color:#181818}}
main{{max-width:440px;margin:12vh auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 12px #0001}}
h1{{font-size:20px;margin:0 0 10px}}p{{color:#444;line-height:1.5}}button{{margin-top:12px;padding:10px 18px;border:0;
border-radius:6px;background:#0176d3;color:#fff;font-size:15px;cursor:pointer}}</style></head>
<body><main><h1>{escape(title, quote=False)}</h1><p>{escape(text, quote=False)}</p>{button}</main></body></html>"""
    return HTMLResponse(html)


def _lead(db: Session, token: str) -> Lead | None:
    lead_id = engine.lead_from_token(token)
    return db.get(Lead, lead_id) if lead_id else None


@public.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe_page(t: str = Query(""), action: str = Query("unsubscribe"), db: Session = Depends(get_db)):
    """Asks before changing anything: mail scanners open links, and must not unsubscribe people by themselves.
    action=subscribe (the "Subscribe again" link) offers to subscribe."""
    lead = _lead(db, t)
    company = engine.mailer.company_name()
    if lead is None:
        return page("Link not valid", "This unsubscribe link isn't valid. Please use the link from the latest email.",
                    t, None)
    if action == "subscribe":
        if lead.unsubscribed_at:
            return page("Subscribe again", f"Get campaign emails from {company} at {lead.email} again?", t, "subscribe")
        return page("You're subscribed", f"{lead.email} gets emails from {company}. Want to stop them?", t,
                    "unsubscribe")
    if lead.unsubscribed_at:
        return page("You're unsubscribed", f"{lead.email} won't get campaign emails from {company}. "
                                           "Changed your mind?", t, "subscribe")
    return page("Unsubscribe", f"Stop campaign emails from {company} to {lead.email}?", t, "unsubscribe")


@public.post("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(t: str = Query(""), form_t: str = Form("", alias="t"), action: str = Form("unsubscribe"),
                db: Session = Depends(get_db)):
    """The button on the page, and Outlook / Gmail one-click unsubscribe (RFC 8058, POST with the token in the URL)."""
    token = form_t or t
    lead = _lead(db, token)
    company = engine.mailer.company_name()
    if lead is None:
        return page("Link not valid", "This unsubscribe link isn't valid. Please use the link from the latest email.",
                    token, None)
    if action == "subscribe":
        if lead.unsubscribed_at:
            lead.unsubscribed_at = None
            log_activity(db, None, "Lead subscribed again", lead.name, "From the link in a campaign email")
            notify(db, lead.owner_id, "Lead subscribed again", f"{lead.name} ({lead.email}) subscribed to emails again.",
                   link=f"/leads/{lead.id}")
            db.commit()
        return page("You're subscribed", f"{lead.email} will get emails from {company} again.", token, "unsubscribe")
    if not lead.unsubscribed_at:
        lead.unsubscribed_at = now()
        log_activity(db, None, "Lead unsubscribed", lead.name, "From the link in a campaign email")
        notify(db, lead.owner_id, "Lead unsubscribed", f"{lead.name} ({lead.email}) unsubscribed from campaign emails.",
               link=f"/leads/{lead.id}")
        # anything still queued for this lead is left out
        db.query(CampaignRecipient).filter(CampaignRecipient.lead_id == lead.id,
                                           CampaignRecipient.status == "Queued").update(
            {"status": "Skipped", "error": "Unsubscribed"}, synchronize_session=False)
        db.commit()
    return page("You're unsubscribed", f"{lead.email} won't get campaign emails from {company} any more.",
                token, "subscribe")
