"""Lead APIs: the first half of the lifecycle.

New -> Nurturing -> Demo -> Converted (becomes an Opportunity), or Lost at any open stage.
At each stage the system closes the old follow-up ("Auto-closed") and creates the next one.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app import schemas
from app.constants import LEAD_FLOW, LEAD_OPEN_STAGES, LEAD_SOURCES, LEAD_STAGES, STAGE_PROBABILITY
from app.database import get_db
from app.security import acting_user, acting_user_id, check_owner_change, forbid_admin_create, owner_for_new, require_edit, require_view, visible
from app.models import Account, Contact, Email, Lead, Opportunity, User
from app.serializers import account_out, contact_out, history_out, lead_detail, lead_out, opportunity_out, task_out
from app.services import (
    confirm_skipped,
    customer_email,
    assignment_notice,
    auto_close_open_tasks,
    create_auto_task,
    get_or_404,
    now,
    record_stage_change,
    notify,
    reassign_system_tasks,
    record_link,
    resolve_user_id,
    schedule_close_date_task,
    schedule_demo_tasks,
    stage_notice,
    task_line,
)

router = APIRouter(prefix="/api/leads", tags=["Leads"])


def ensure_open(lead: Lead):
    if lead.stage not in LEAD_OPEN_STAGES:
        raise HTTPException(status_code=400, detail=f"Lead {lead.id} is {lead.stage} (closed); it can't change any more")


# ---------- list, create, view, edit ----------

@router.get("", response_model=list[schemas.LeadOut])
def list_leads(
    stage: str | None = Query(None, description="New, Nurturing, Demo, Converted or Lost"),
    source: str | None = Query(None),
    owner_id: int | None = Query(None),
    search: str | None = Query(None, description="Name, company or email"),
    db: Session = Depends(get_db),
):
    if stage and stage not in LEAD_STAGES:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'. Use: {', '.join(LEAD_STAGES)}")
    if source and source not in LEAD_SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Use: {', '.join(LEAD_SOURCES)}")
    query = visible(select(Lead), Lead)
    if stage:
        query = query.where(Lead.stage == stage)
    if source:
        query = query.where(Lead.source == source)
    if owner_id is not None:
        query = query.where(Lead.owner_id == owner_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(Lead.name.ilike(like), Lead.company.ilike(like), Lead.email.ilike(like)))
    return [lead_out(lead) for lead in db.scalars(query.order_by(Lead.id.desc())).all()]


# ---------- duplicate email check ----------

def find_duplicates(db: Session, email: str | None, exclude_lead_id: int | None = None) -> list[dict]:
    """Leads and contacts that already have this email (any owner, any stage)."""
    email = (email or "").strip().lower()
    if not email:
        return []
    me = acting_user()
    found = []
    query = select(Lead).where(func.lower(Lead.email) == email)
    if exclude_lead_id is not None:
        query = query.where(Lead.id != exclude_lead_id)
    for lead in db.scalars(query.order_by(Lead.id.desc())).all():
        found.append({"type": "Lead", "id": lead.id, "name": lead.name, "company": lead.company, "stage": lead.stage,
                      "open": lead.stage in LEAD_OPEN_STAGES, "owner_name": lead.owner.full_name if lead.owner else None,
                      "can_open": lead.owner_id == me.id or me.sees_team})
    for contact in db.scalars(select(Contact).where(func.lower(Contact.email) == email)).all():
        found.append({"type": "Contact", "id": contact.id, "name": contact.full_name,
                      "company": contact.account.name if contact.account else None, "stage": None, "open": False,
                      "owner_name": contact.owner.full_name if contact.owner else None,
                      "can_open": contact.owner_id == me.id or me.sees_team})
    return found


@router.get("/duplicates")
def check_duplicates(email: str = Query(..., min_length=3), exclude_lead_id: int | None = Query(None),
                     db: Session = Depends(get_db)):
    """Before saving a lead: is this email already in the CRM? (open lead = can't create another one)"""
    matches = find_duplicates(db, email, exclude_lead_id)
    return {"email": email.strip().lower(), "matches": matches, "has_open_lead": any(m["open"] for m in matches)}


def check_email_free(db: Session, email: str | None, *, confirmed: bool, exclude_lead_id: int | None = None) -> list[dict]:
    matches = find_duplicates(db, email, exclude_lead_id)
    open_lead = next((m for m in matches if m["open"]), None)
    if open_lead:
        raise HTTPException(status_code=409, detail=(
            f'An open lead with this email already exists: {open_lead["name"]} ({open_lead["company"]}), '
            f'owner {open_lead["owner_name"]}. Use that lead instead.'))
    if matches and not confirmed:
        first = matches[0]
        raise HTTPException(status_code=409, detail=(
            f'This email already exists: {first["type"].lower()} {first["name"]} ({first["company"]}). '
            "Confirm to create a new lead for the returning customer, or use a different email."))
    return matches


@router.post("", response_model=schemas.LeadDetail, status_code=status.HTTP_201_CREATED)
def create_lead(data: schemas.LeadCreate, db: Session = Depends(get_db)):
    """Create a lead at stage New. The system adds a 'Make first contact' task for the owner."""
    forbid_admin_create("leads")
    owner_id = resolve_user_id(db, owner_for_new(data.owner_id))
    actor_id = acting_user_id()
    previous = check_email_free(db, data.email, confirmed=data.confirm_duplicate)
    lead = Lead(**data.model_dump(exclude={"owner_id", "created_by_id", "welcome_email", "confirm_duplicate"}),
                owner_id=owner_id, stage="New")
    db.add(lead)
    db.flush()
    db.refresh(lead)  # loads "name", which the database builds from first + last name
    record_stage_change(db, lead_id=lead.id, from_stage=None, to_stage="New", changed_by_id=actor_id,
                        note=(f"Returning customer (already in the CRM as {previous[0]['type'].lower()} "
                              f"{previous[0]['name']}, {previous[0]['stage'] or 'contact'})") if previous else None)
    task = create_auto_task(db, stage="New", owner_id=owner_id, record_name=lead.name, lead_id=lead.id)
    # one notification for the new lead; it says so when someone else created it for the owner
    assigned = actor_id != owner_id
    stage_notice(
        db, kind="Lead", stage="New", record_name=lead.name, owner_id=owner_id,
        actor_id=actor_id, lead_id=lead.id, task=task,
        title="Lead assigned to you" if assigned else None,
        details=[f"Company: {lead.company}", f"Source: {lead.source}"],
    )
    if data.welcome_email:
        customer_email(db, "welcome", to=lead.email, first_name=lead.first_name or lead.name, owner_id=owner_id)
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)



@router.get("/{lead_id}", response_model=schemas.LeadDetail)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """The lead record page: details, tasks, notes and stage history."""
    lead = get_or_404(db, Lead, lead_id, "Lead")
    require_view(lead.owner_id, "lead")
    return lead_detail(lead)


@router.put("/{lead_id}", response_model=schemas.LeadOut)
def update_lead(lead_id: int, data: schemas.LeadUpdate, db: Session = Depends(get_db)):
    lead = get_or_404(db, Lead, lead_id, "Lead")
    require_edit(lead.owner_id, "lead")
    changes = data.model_dump(exclude_unset=True)
    changes.pop("changed_by_id", None)
    actor = acting_user_id()
    check_owner_change(lead.owner_id, changes.get("owner_id"))
    old_owner = lead.owner_id
    old_demo = lead.demo_date
    if changes.get("email") and (changes["email"] or "").strip().lower() != (lead.email or "").strip().lower():
        if any(m["open"] for m in find_duplicates(db, changes["email"], exclude_lead_id=lead.id)):
            raise HTTPException(status_code=409, detail="An open lead with this email already exists. Use that lead instead.")
    for field in ("last_name", "company", "source"):  # required, like Salesforce
        if field in changes and not changes[field]:
            raise HTTPException(status_code=400, detail=f"{field} can't be empty")
    if "owner_id" in changes:
        changes["owner_id"] = resolve_user_id(db, changes["owner_id"])
    for field, value in changes.items():
        setattr(lead, field, value)
    if lead.owner_id != old_owner:
        db.flush()
        db.refresh(lead)
        reassign_system_tasks(db, lead.owner_id, lead_id=lead.id)  # follow-ups and reminders go to the new owner
        assignment_notice(db, owner_id=lead.owner_id, actor_id=actor, kind="Lead", name=lead.name, link=f"/leads/{lead.id}")
    if lead.stage == "Demo" and lead.demo_date != old_demo:
        # demo rescheduled: move the demo reminders and tell the owner
        prep = schedule_demo_tasks(db, lead)
        if lead.demo_date is not None:
            was = f" (was {old_demo:%d %b %Y %I:%M %p})" if old_demo else ""
            notify(db, lead.owner_id, "Lead demo rescheduled",
                   "\n".join([f'Demo with "{lead.name}" is now on {lead.demo_date:%d %b %Y at %I:%M %p}{was}.',
                               *task_line("Prep reminder", prep)]),
                   link=record_link(lead_id=lead.id))
    db.commit()
    db.refresh(lead)
    return lead_out(lead)


# ---------- stage change, Lost ----------

@router.put("/{lead_id}/stage", response_model=schemas.LeadDetail)
def change_stage(lead_id: int, data: schemas.LeadStageChange, db: Session = Depends(get_db)):
    """Move to New, Nurturing or Demo (also to correct a wrong stage).
    Old follow-ups are auto-closed and the follow-up for the new stage is created."""
    lead = get_or_404(db, Lead, lead_id, "Lead")
    ensure_open(lead)
    if lead.stage == data.stage:
        raise HTTPException(status_code=400, detail=f"Lead {lead_id} is already at {data.stage}")
    require_edit(lead.owner_id, "lead")
    by = acting_user_id()

    if LEAD_FLOW.index(data.stage) > LEAD_FLOW.index(lead.stage):  # forward: no skipping (going back is allowed)
        lead.stage = confirm_skipped(db, flow=LEAD_FLOW, current=lead.stage, target_index=LEAD_FLOW.index(data.stage),
                                     completed=data.completed_stages, note=data.completed_note, by=by,
                                     lead_id=lead.id, what=data.stage)
    old = lead.stage
    lead.stage = data.stage
    if data.stage == "Demo" and data.demo_date:
        lead.demo_date = data.demo_date
    record_stage_change(db, lead_id=lead.id, from_stage=old, to_stage=data.stage, changed_by_id=by, note=data.note)
    auto_close_open_tasks(db, lead_id=lead.id)
    task = create_auto_task(
        db,
        stage=data.stage,
        owner_id=lead.owner_id,
        record_name=lead.name,
        lead_id=lead.id,
        due_date=data.demo_date if data.stage == "Demo" else None,
    )
    details = []
    if data.stage == "Demo":
        prep = schedule_demo_tasks(db, lead)  # "Conduct demo" reminder + day-before prep task
        if lead.demo_date:
            details.append(f"Demo date: {lead.demo_date:%d %b %Y %I:%M %p}")
        details += task_line("Prep reminder", prep)
    if data.note:
        details.append(f"Note: {data.note}")
    stage_notice(db, kind="Lead", stage=data.stage, record_name=lead.name, owner_id=lead.owner_id,
                 actor_id=by, lead_id=lead.id, task=task, details=details)
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


@router.post("/{lead_id}/lost", response_model=schemas.LeadDetail)
def mark_lost(lead_id: int, data: schemas.MarkLost, db: Session = Depends(get_db)):
    """Close the lead as Lost from any open stage. A lost reason is required."""
    lead = get_or_404(db, Lead, lead_id, "Lead")
    ensure_open(lead)
    require_edit(lead.owner_id, "lead")
    by = acting_user_id()
    old = lead.stage
    lead.stage = "Lost"
    lead.lost_reason = data.lost_reason
    lead.lost_notes = data.lost_notes
    lead.closed_at = now()
    record_stage_change(db, lead_id=lead.id, from_stage=old, to_stage="Lost", changed_by_id=by, note=data.lost_notes)
    auto_close_open_tasks(db, lead_id=lead.id)
    details = [f"Lost at stage: {old}", f"Reason: {data.lost_reason}"]
    if data.lost_notes:
        details.append(f"Notes: {data.lost_notes}")
    stage_notice(db, kind="Lead", stage="Lost", record_name=lead.name, owner_id=lead.owner_id,
                 actor_id=by, lead_id=lead.id, details=details)
    if data.notify_customer:
        customer_email(db, "lost", to=lead.email, first_name=lead.first_name or lead.name, owner_id=lead.owner_id,
                       after_proposal=False)  # a lead never got a proposal
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


# ---------- Convert ----------

@router.post("/{lead_id}/convert", response_model=schemas.ConvertResult)
def convert_lead(lead_id: int, data: schemas.ConvertLead | None = None, db: Session = Depends(get_db)):
    """Convert an open lead, like Salesforce: creates (or reuses) the Account, creates the Contact
    and the Opportunity. Lead tasks are auto-closed and a 'Send proposal' task is created on the deal."""
    forbid_admin_create("opportunities")
    data = data or schemas.ConvertLead()
    lead = get_or_404(db, Lead, lead_id, "Lead")
    ensure_open(lead)
    require_edit(lead.owner_id, "lead")
    # Convert comes after Demo: New -> Nurturing -> Demo must be done (or confirmed as done)
    lead.stage = confirm_skipped(db, flow=LEAD_FLOW, current=lead.stage, target_index=len(LEAD_FLOW),
                                 completed=data.completed_stages, note=data.completed_note, by=acting_user_id(),
                                 lead_id=lead.id, what="converting")
    require_edit(lead.owner_id, "lead")
    by = acting_user_id()

    if data.account_id is not None:
        account = get_or_404(db, Account, data.account_id, "Account")
    else:
        account = Account(
            name=lead.company or lead.name, industry=lead.industry, phone=lead.phone, owner_id=lead.owner_id
        )
        db.add(account)
        db.flush()

    contact = Contact(
        salutation=lead.salutation,
        first_name=lead.first_name,
        last_name=lead.last_name,
        job_title=lead.title,
        email=lead.email,
        phone=lead.phone,
        account_id=account.id,
        owner_id=lead.owner_id,
    )
    db.add(contact)
    db.flush()

    opportunity = Opportunity(
        name=(data.opportunity_name or "").strip() or f"{account.name} - Opportunity",
        stage="Opportunity",
        probability=STAGE_PROBABILITY["Opportunity"],
        expected_value=data.expected_value,
        expected_close_date=data.expected_close_date or (date.today() + timedelta(days=30)),
        account_id=account.id,
        primary_contact_id=contact.id,
        lead_id=lead.id,
        owner_id=lead.owner_id,
    )
    db.add(opportunity)
    db.flush()

    # emails sent to the lead stay visible on the new opportunity, contact and account (like Salesforce)
    db.execute(
        update(Email).where(Email.lead_id == lead.id)
        .values(opportunity_id=opportunity.id, contact_id=contact.id, account_id=account.id)
    )
    closed = auto_close_open_tasks(db, lead_id=lead.id)
    old = lead.stage
    lead.stage = "Converted"
    lead.converted_at = now()
    record_stage_change(db, lead_id=lead.id, from_stage=old, to_stage="Converted", changed_by_id=by)
    record_stage_change(db, opportunity_id=opportunity.id, from_stage=None, to_stage="Opportunity", changed_by_id=by)
    task = create_auto_task(
        db, stage="Opportunity", owner_id=lead.owner_id, record_name=opportunity.name, opportunity_id=opportunity.id
    )
    details = [f"Converted from lead: {lead.name}", f"Account: {account.name}"]
    if opportunity.expected_value is not None:
        details.append(f"Amount: ${opportunity.expected_value:,.2f}")
    details.append(f"Close date: {opportunity.expected_close_date:%d %b %Y}")
    details += task_line("Close date reminder", schedule_close_date_task(db, opportunity))
    stage_notice(db, kind="Opportunity", stage="Opportunity", record_name=opportunity.name, owner_id=lead.owner_id,
                 actor_id=by, opportunity_id=opportunity.id, task=task, details=details)
    db.commit()
    for record in (lead, account, contact, opportunity, task):
        db.refresh(record)
    return {
        "lead": lead_out(lead),
        "account": account_out(account),
        "contact": contact_out(contact),
        "opportunity": opportunity_out(opportunity),
        "tasks_auto_closed": closed,
        "new_task": task_out(task) if task else None,
    }


@router.get("/{lead_id}/history", response_model=list[schemas.StageHistoryOut])
def lead_history(lead_id: int, db: Session = Depends(get_db)):
    lead = get_or_404(db, Lead, lead_id, "Lead")
    require_view(lead.owner_id, "lead")
    return [history_out(h) for h in sorted(lead.history, key=lambda h: h.id)]
