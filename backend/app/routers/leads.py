"""Lead APIs: the first half of the lifecycle.

New -> Nurturing -> Revisit (optional, "not now": come back on a date) -> Demo -> Converted (becomes an Opportunity).
Closed without converting from any open stage: Unqualified (not eligible, with a reason; can be reopened) or Lost.
At each stage the system closes the old follow-up ("Auto-closed") and creates the next one.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app import schemas
from app.constants import (AUTO_TASKS, LEAD_FLOW, LEAD_OPEN_STAGES, LEAD_OPTIONAL_STAGES, LEAD_SOURCES, LEAD_STAGES,
                           LEAD_START, STAGE_PROBABILITY)
from app.database import get_db
from app.security import (acting_user, acting_user_id, forbid_admin_create, owner_for_new, require_edit,
                          require_transfer, require_view, visible)
from app.models import (Account, Contact, Email, EmailAttachment, Lead, LeadTransfer, Note, Notification, Opportunity,
                        StageHistory, Task, User)
from app.serializers import account_out, contact_out, history_out, lead_detail, lead_out, opportunity_out, task_out
from app.services import (
    add_stage_task,
    assignment_notice,
    auto_close_open_tasks,
    confirm_skipped,
    create_auto_task,
    email_website_problem,
    get_for_update,
    get_or_404,
    log_activity,
    notify,
    now,
    open_system_task,
    reassign_system_tasks,
    record_link,
    record_stage_change,
    resolve_user_id,
    schedule_close_date_task,
    schedule_demo_tasks,
    stage_notice,
    stage_task_owner,
    task_line,
)

router = APIRouter(prefix="/api/leads", tags=["Leads"])


def ensure_open(lead: Lead):
    if lead.stage not in LEAD_OPEN_STAGES:
        raise HTTPException(status_code=400, detail=f"Lead {lead.id} is {lead.stage} (closed); it can't change any more")


# ---------- list, create, view, edit ----------

@router.get("", response_model=list[schemas.LeadOut])
def list_leads(
    stage: str | None = Query(None, description=", ".join(LEAD_STAGES)),
    source: str | None = Query(None),
    owner_id: int | None = Query(None),
    search: str | None = Query(None, description="Name, company or email"),
    include_untouched: bool = Query(False, description="Also uploaded leads nobody has worked on yet"),
    db: Session = Depends(get_db),
):
    """Leads the user can see. Uploaded leads nobody has worked on yet are left out (they can be 100,000s);
    the Leads page lists every lead page by page at /api/leads/page."""
    if stage and stage not in LEAD_STAGES:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'. Use: {', '.join(LEAD_STAGES)}")
    if source and source not in LEAD_SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Use: {', '.join(LEAD_SOURCES)}")
    query = visible(select(Lead), Lead).options(selectinload(Lead.owner), selectinload(Lead.opportunity))
    if not include_untouched:
        query = query.where(Lead.untouched.is_(False))
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
    """Before saving a lead: is this email already in the CRM? Every email belongs to one lead or contact only."""
    matches = find_duplicates(db, email, exclude_lead_id)
    return {"email": email.strip().lower(), "matches": matches, "has_open_lead": any(m["open"] for m in matches)}


def check_email_free(db: Session, email: str | None, *, exclude_lead_id: int | None = None) -> None:
    """Email is unique: no other lead (any stage) or contact may have it. Records the user can't open are named
    only by their owner."""
    matches = find_duplicates(db, email, exclude_lead_id)
    if matches:
        first = matches[0]
        what = (f'{first["type"].lower()} {first["name"]} ({first["company"]}, {first["stage"] or "contact"})'
                if first["can_open"] else f'a {first["type"].lower()}')
        raise HTTPException(status_code=409, detail=(
            f'This email is already in the CRM: {what}, owner {first["owner_name"]}. '
            "Each email can belong to one lead only: use that record, or ask its owner or a Manager."))


def check_lead_email(db: Session, email: str | None, website: str | None, *, exclude_lead_id: int | None = None) -> None:
    """A lead's email is unique in the CRM and uses the company's domain (as its Company Website)."""
    problem = email_website_problem(email, website)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    check_email_free(db, email, exclude_lead_id=exclude_lead_id)


@router.post("", response_model=schemas.LeadDetail, status_code=status.HTTP_201_CREATED)
def create_lead(data: schemas.LeadCreate, db: Session = Depends(get_db)):
    """Create a lead at stage New. The system adds a 'Make first contact' task for the owner.
    Admins can create leads too, and choose who owns them."""
    # anyone can assign a new lead to an active teammate (Manager or Salesperson); the owner is told
    owner_id = acting_user_id() if data.owner_id is None else resolve_user_id(db, data.owner_id)
    if owner_id != acting_user_id():
        owner = db.get(User, owner_id)
        if not owner.is_active or owner.role == "Admin":
            raise HTTPException(status_code=400, detail="Leads can only be assigned to active Managers and Salespeople")
    actor_id = acting_user_id()
    check_lead_email(db, data.email, data.company_website)
    lead = Lead(**data.model_dump(exclude={"owner_id", "created_by_id"}),
                owner_id=owner_id, stage=LEAD_START)
    db.add(lead)
    db.flush()
    db.refresh(lead)  # loads "name", which the database builds from first + last name
    record_stage_change(db, lead_id=lead.id, from_stage=None, to_stage=LEAD_START, changed_by_id=actor_id)
    task = create_auto_task(db, stage=LEAD_START, owner_id=owner_id, record_name=lead.name, lead_id=lead.id)
    # one notification for the new lead; it says so when someone else created it for the owner
    assigned = actor_id != owner_id
    stage_notice(
        db, kind="Lead", stage=LEAD_START, record_name=lead.name, owner_id=owner_id,
        actor_id=actor_id, lead_id=lead.id, task=task,
        title="Lead assigned to you" if assigned else "Lead created",
        details=[f"Company: {lead.company}", f"Source: {lead.source}"],
    )
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
    lead.untouched = False  # someone is working on it now
    changes = data.model_dump(exclude_unset=True)
    changes.pop("changed_by_id", None)
    actor = acting_user_id()
    new_owner = changes.pop("owner_id", None)  # a new owner is a transfer (same rules and history as Transfer)
    old_demo = lead.demo_date
    if "email" in changes or "company_website" in changes:  # the email stays unique and on the company's domain
        email = changes.get("email", lead.email)
        website = changes.get("company_website", lead.company_website)
        problem = email_website_problem(email, website)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        if email and email.strip().lower() != (lead.email or "").strip().lower():
            check_email_free(db, email, exclude_lead_id=lead.id)
    for field in ("last_name", "company", "source"):  # required, like Salesforce
        if field in changes and not changes[field]:
            raise HTTPException(status_code=400, detail=f"{field} can't be empty")
    for field, value in changes.items():
        setattr(lead, field, value)
    if new_owner is not None and new_owner != lead.owner_id:
        require_transfer(lead.owner_id)
        transfer_lead(db, lead, new_owner, None, actor)
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


# ---------- transfer ----------

def transfer_lead(db: Session, lead: Lead, to_user_id: int, note: str | None, actor_id: int,
                  quiet: bool = False) -> LeadTransfer:
    """Gives the lead to another user and saves who, when, from and to. Only the owner changes.
    quiet=True (bulk transfer): no notifications here; the caller sends one summary instead."""
    target = db.get(User, resolve_user_id(db, to_user_id))
    if not target.is_active:
        raise HTTPException(status_code=400, detail=f"{target.full_name} is deactivated. Choose an active user.")
    if target.id == lead.owner_id:
        raise HTTPException(status_code=400, detail=f"This lead already belongs to {target.full_name}")
    previous = lead.owner
    record = LeadTransfer(lead_id=lead.id, from_user_id=lead.owner_id, to_user_id=target.id,
                          transferred_by_id=actor_id, note=(note or "").strip() or None)
    db.add(record)
    lead.owner_id = target.id
    db.flush()
    db.refresh(lead)
    reassign_system_tasks(db, target.id, lead_id=lead.id)  # follow-ups and reminders go to the new owner
    if quiet:
        log_activity(db, actor_id, "Lead reassigned", lead.name,
                     f"New owner: {target.full_name} (bulk transfer)" + (f" • Note: {record.note}" if record.note else ""))
        return record
    assignment_notice(db, owner_id=target.id, actor_id=actor_id, kind="Lead", name=lead.name, link=f"/leads/{lead.id}")
    if previous and previous.id != actor_id:  # e.g. the Admin moved it: tell the previous owner too
        notify(db, previous.id, "Lead transferred", f'Lead "{lead.name}" was transferred to {target.full_name}.',
               link=f"/leads/{lead.id}", category="assignment")
    # every active Manager and Admin hears about it too (bell + email), except whoever was already told above
    actor = db.get(User, actor_id)
    told = {actor_id, target.id, previous.id if previous else None}
    message = (f'Lead "{lead.name}" ({lead.company or "no company"}) was transferred from '
               f'{previous.full_name if previous else "no owner"} to {target.full_name}'
               f'{f" by {actor.full_name}" if actor else ""}.' + (f"\nNote: {record.note}" if record.note else ""))
    for user in db.scalars(select(User).where(User.role.in_(("Manager", "Admin")), User.is_active.is_(True))).all():
        if user.id not in told:
            notify(db, user.id, "Lead transferred", message, link=f"/leads/{lead.id}", category="assignment")
    return record


# ---------- bulk: several selected leads at once ----------

def _bulk_leads(db: Session, ids: list[int]) -> list[tuple[int, Lead | None]]:
    seen, out = set(), []
    for lead_id in ids:
        if lead_id not in seen:
            seen.add(lead_id)
            out.append((lead_id, db.get(Lead, lead_id)))
    return out


def _skip(lead_id: int, lead: Lead | None, exc: HTTPException) -> dict:
    """A lead that was left out, and why. Leads the user can't see are not named (and look like they don't exist)."""
    hidden = lead is None or exc.status_code == 404
    return {"id": lead_id, "name": f"Lead {lead_id}" if hidden else lead.name,
            "reason": "Not found, or you don't have access to it" if hidden else str(exc.detail)}


def _summary_notice(db: Session, title: str, lines: list[str], told: set[int], skip: set[int]) -> None:
    for user_id in told - skip:
        notify(db, user_id, title, "\n".join(lines)[:500], link="/leads", category="assignment")


@router.post("/bulk-transfer")
def bulk_transfer(data: schemas.BulkTransfer, db: Session = Depends(get_db)):
    """Transfer several leads to one user. Each lead follows the same rules as Transfer (Admin and Managers:
    any lead they can see; others: their own leads). Leads that can't be moved are skipped with the reason.
    One summary notification goes to the new owner, the previous owners, and the Managers and Admins."""
    me = acting_user()
    target = db.get(User, data.to_user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=400, detail="Choose an active user to transfer the leads to")
    moved, skipped, previous_owners = [], [], {}
    for lead_id, lead in _bulk_leads(db, data.lead_ids):
        try:
            if lead is None:
                raise HTTPException(status_code=404, detail="Not found")
            require_view(lead.owner_id, "lead")
            ensure_open(lead)
            require_transfer(lead.owner_id)
            previous_owners.setdefault(lead.owner_id, []).append(lead.name)
            transfer_lead(db, lead, target.id, data.note, me.id, quiet=True)
            moved.append({"id": lead.id, "name": lead.name})
        except HTTPException as exc:
            skipped.append(_skip(lead_id, lead, exc))
    if moved:
        names = ", ".join(m["name"] for m in moved[:10]) + (f" and {len(moved) - 10} more" if len(moved) > 10 else "")
        note = [f"Note: {data.note.strip()}"] if data.note and data.note.strip() else []
        _summary_notice(db, "Leads assigned to you",
                        [f"{me.full_name} transferred {len(moved)} lead{'s' if len(moved) != 1 else ''} to you: {names}.", *note],
                        {target.id}, {me.id})
        for owner_id, lead_names in previous_owners.items():
            _summary_notice(db, "Leads transferred",
                            [f"{len(lead_names)} of your leads were transferred to {target.full_name} by {me.full_name}: "
                             f"{', '.join(lead_names[:10])}.", *note], {owner_id}, {me.id, target.id})
        managers = set(db.scalars(select(User.id).where(User.role.in_(("Manager", "Admin")), User.is_active.is_(True))).all())
        _summary_notice(db, "Leads transferred",
                        [f"{me.full_name} transferred {len(moved)} lead{'s' if len(moved) != 1 else ''} to {target.full_name}: {names}.",
                         *note], managers, {me.id, target.id, *previous_owners})
    db.commit()
    return {"transferred": len(moved), "to": target.full_name, "moved": moved, "skipped": skipped}


@router.post("/bulk-delete")
def bulk_delete(data: schemas.BulkLeads, db: Session = Depends(get_db)):
    """Delete several leads. Each lead follows the same rules as Delete (its owner, a Manager or the Admin;
    converted leads can't be deleted). Leads that can't be deleted are skipped with the reason.
    One summary notification goes to the Managers and Admins and to owners whose leads someone else deleted."""
    me = acting_user()
    deleted, skipped, by_owner = [], [], {}
    for lead_id, lead in _bulk_leads(db, data.lead_ids):
        try:
            if lead is None:
                raise HTTPException(status_code=404, detail="Not found")
            require_edit(lead.owner_id, "lead")
            name, _, owner_id = delete_one(db, lead, me.id)
            deleted.append({"id": lead_id, "name": name})
            by_owner.setdefault(owner_id, []).append(name)
        except HTTPException as exc:
            skipped.append(_skip(lead_id, lead, exc))
    if deleted:
        names = ", ".join(d["name"] for d in deleted[:10]) + (f" and {len(deleted) - 10} more" if len(deleted) > 10 else "")
        managers = set(db.scalars(select(User.id).where(User.role.in_(("Manager", "Admin")), User.is_active.is_(True))).all())
        _summary_notice(db, "Leads deleted", [f"{me.full_name} deleted {len(deleted)} lead{'s' if len(deleted) != 1 else ''}: {names}."],
                        managers, {me.id})
        for owner_id, lead_names in by_owner.items():
            _summary_notice(db, "Leads deleted", [f"{me.full_name} deleted {len(lead_names)} of your leads: {', '.join(lead_names[:10])}."],
                            {owner_id}, {me.id, *managers})
    db.commit()
    return {"deleted": len(deleted), "removed": deleted, "skipped": skipped}


@router.post("/{lead_id}/transfer", response_model=schemas.LeadDetail)
def transfer(lead_id: int, data: schemas.LeadTransfer, db: Session = Depends(get_db)):
    """Give an open lead to another user. The Admin can transfer any lead; a user with the Transfer leads
    permission can transfer their own. No approval needed. The date and time are saved in the transfer history."""
    lead = get_or_404(db, Lead, lead_id, "Lead")
    require_view(lead.owner_id, "lead")
    ensure_open(lead)
    me = require_transfer(lead.owner_id)
    transfer_lead(db, lead, data.to_user_id, data.note, me.id)
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


# ---------- demo cancellation ----------

@router.post("/{lead_id}/cancel-demo", response_model=schemas.LeadDetail)
def cancel_demo(lead_id: int, data: schemas.CancelDemo, db: Session = Depends(get_db)):
    """Cancel a booked demo, with two choices:
    - reschedule_to: the demo moves to the new date, the lead stays at Demo and the demo reminders move with it
    - no new date: the lead goes back to Revisit and the demo reminders are removed. That is a stage change, so a
      reason (saved in the stage history) and the user's new task (instead of the system's follow-up call) are
      required."""
    lead = get_for_update(db, Lead, lead_id, "Lead")
    require_edit(lead.owner_id, "lead")
    if lead.stage != "Demo":
        raise HTTPException(status_code=400, detail="Only a lead at the Demo stage has a demo to cancel")
    reason = (data.reason or "").strip()
    if data.reschedule_to is None and not reason:
        raise HTTPException(status_code=422, detail=schemas.STAGE_NOTE_REQUIRED)
    if data.reschedule_to is None and data.task is None:
        raise HTTPException(status_code=422, detail=schemas.STAGE_TASK_REQUIRED)
    task_owner = stage_task_owner(db, data.task, lead.owner_id) if data.reschedule_to is None else None
    by = acting_user_id()
    was = lead.demo_date
    if data.reschedule_to is not None:
        new_date = data.reschedule_to.replace(tzinfo=None, microsecond=0)
        if new_date <= now():
            raise HTTPException(status_code=400, detail="Choose a new demo date and time in the future")
        if was is not None and new_date == was:
            raise HTTPException(status_code=400, detail="The demo is already booked for that date and time")
        lead.demo_date = new_date
        note = f"Demo rescheduled to {new_date:%d %b %Y %I:%M %p}" + (f": {reason}" if reason else "")
        record_stage_change(db, lead_id=lead.id, from_stage="Demo", to_stage="Demo", changed_by_id=by, note=note)
        if open_system_task(db, AUTO_TASKS["Demo"][0], lead_id=lead.id) is None:  # e.g. the demo task was ticked off
            create_auto_task(db, stage="Demo", owner_id=lead.owner_id, record_name=lead.name, lead_id=lead.id,
                             due_date=new_date)
        prep = schedule_demo_tasks(db, lead)  # moves "Conduct demo" and "Prepare for demo"
        lines = [f'Demo with "{lead.name}" is now on {new_date:%d %b %Y at %I:%M %p}'
                 + (f" (was {was:%d %b %Y %I:%M %p})." if was else "."), *task_line("Prep reminder", prep)]
        if reason:
            lines.append(f"Reason: {reason}")
        notify(db, lead.owner_id, "Lead demo rescheduled", "\n".join(lines), link=record_link(lead_id=lead.id))
        db.commit()
        db.refresh(lead)
        return lead_detail(lead)
    lead.stage, lead.demo_date = "Revisit", None
    lead.revisit_date, lead.revisit_reason = data.task.due_date.replace(tzinfo=None), "Demo cancelled"
    note = "Demo cancelled" + (f": {reason}" if reason else "")
    record_stage_change(db, lead_id=lead.id, from_stage="Demo", to_stage="Revisit", changed_by_id=by, note=note)
    auto_close_open_tasks(db, lead_id=lead.id)  # closes "Conduct demo" and "Prepare for demo"
    task = add_stage_task(db, data.task, owner_id=task_owner, record_owner_id=lead.owner_id, actor_id=by,
                          lead_id=lead.id)
    details = [f"Cancelled demo: {was:%d %b %Y %I:%M %p}" if was else "No demo date was set"]
    if reason:
        details.append(f"Reason: {reason}")
    stage_notice(db, kind="Lead", stage="Revisit", record_name=lead.name, owner_id=lead.owner_id, actor_id=by,
                 lead_id=lead.id, task=task, details=details, title="Lead demo cancelled")
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


# ---------- stage change, Lost ----------

@router.put("/{lead_id}/stage", response_model=schemas.LeadDetail)
def change_stage(lead_id: int, data: schemas.LeadStageChange, db: Session = Depends(get_db)):
    """Move to any open stage (New, Nurturing, Revisit, Demo), also to correct a wrong stage. Revisit needs the date to
    come back (the new task is due then) and the reason. A note (saved in the history) and the user's
    new task are required. Old follow-ups are auto-closed; the new task takes the place of the system follow-up for
    the new stage. The demo reminders ("Conduct demo" at the demo and the day-before prep task) are still created
    and kept in step with the demo date when one is given."""
    lead = get_for_update(db, Lead, lead_id, "Lead")
    ensure_open(lead)
    if lead.stage == data.stage:
        raise HTTPException(status_code=400, detail=f"Lead {lead_id} is already at {data.stage}")
    require_edit(lead.owner_id, "lead")
    task_owner = stage_task_owner(db, data.task, lead.owner_id)
    lead.untouched = False  # someone is working on it now
    by = acting_user_id()

    if data.stage == "Revisit":  # "not now": when to come back and why; the new task is due on that day
        if data.revisit_date is None or data.revisit_reason is None:
            raise HTTPException(status_code=422, detail="Choose when to revisit the lead and why")
        revisit_on = data.revisit_date.replace(tzinfo=None, microsecond=0)
        if revisit_on.date() <= now().date():
            raise HTTPException(status_code=400, detail="Choose a revisit date after today")
        data.task.due_date = revisit_on
        data.task.reminder_at = data.task.reminder_at or revisit_on
    if LEAD_FLOW.index(data.stage) > LEAD_FLOW.index(lead.stage):  # forward: no skipping (going back is allowed)
        lead.stage = confirm_skipped(db, flow=LEAD_FLOW, current=lead.stage, target_index=LEAD_FLOW.index(data.stage),
                                     completed=data.completed_stages, note=data.completed_note, by=by,
                                     lead_id=lead.id, what=data.stage, optional=LEAD_OPTIONAL_STAGES)
    old = lead.stage
    lead.stage = data.stage
    if data.stage == "Demo" and data.demo_date:
        lead.demo_date = data.demo_date
    if data.stage == "Revisit":
        lead.revisit_date, lead.revisit_reason = data.task.due_date, data.revisit_reason
    else:
        lead.revisit_date = lead.revisit_reason = None
    record_stage_change(db, lead_id=lead.id, from_stage=old, to_stage=data.stage, changed_by_id=by, note=data.note)
    auto_close_open_tasks(db, lead_id=lead.id)
    task = add_stage_task(db, data.task, owner_id=task_owner, record_owner_id=lead.owner_id, actor_id=by,
                          lead_id=lead.id)
    details = []
    if data.stage == "Revisit":
        details.append(f"Revisit on: {lead.revisit_date:%d %b %Y} ({lead.revisit_reason})")
    if data.stage == "Demo":
        if data.demo_date:  # the demo-time reminder ("Conduct demo", kept in step with the demo date) stays
            create_auto_task(db, stage="Demo", owner_id=lead.owner_id, record_name=lead.name, lead_id=lead.id,
                             due_date=data.demo_date)
        prep = schedule_demo_tasks(db, lead)  # "Conduct demo" reminder + day-before prep task
        if lead.demo_date:
            details.append(f"Demo date: {lead.demo_date:%d %b %Y %I:%M %p}")
        details += task_line("Prep reminder", prep)
    details.append(f"Note: {data.note}")
    stage_notice(db, kind="Lead", stage=data.stage, record_name=lead.name, owner_id=lead.owner_id,
                 actor_id=by, lead_id=lead.id, task=task, details=details)
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


@router.post("/{lead_id}/lost", response_model=schemas.LeadDetail)
def mark_lost(lead_id: int, data: schemas.MarkLost, db: Session = Depends(get_db)):
    """Close the lead as Lost from any open stage. A lost reason and notes are required (no new task)."""
    lead = get_for_update(db, Lead, lead_id, "Lead")
    ensure_open(lead)
    require_edit(lead.owner_id, "lead")
    lead.untouched = False  # someone is working on it now
    by = acting_user_id()
    old = lead.stage
    lead.stage = "Lost"
    lead.revisit_date = lead.revisit_reason = None
    lead.lost_reason = data.lost_reason
    lead.lost_notes = data.lost_notes
    lead.closed_at = now()
    record_stage_change(db, lead_id=lead.id, from_stage=old, to_stage="Lost", changed_by_id=by, note=data.lost_notes)
    auto_close_open_tasks(db, lead_id=lead.id)
    details = [f"Lost at stage: {old}", f"Reason: {data.lost_reason}", f"Notes: {data.lost_notes}"]
    stage_notice(db, kind="Lead", stage="Lost", record_name=lead.name, owner_id=lead.owner_id,
                 actor_id=by, lead_id=lead.id, details=details)
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


@router.post("/{lead_id}/unqualified", response_model=schemas.LeadDetail)
def mark_unqualified(lead_id: int, data: schemas.MarkUnqualified, db: Session = Depends(get_db)):
    """Close the lead as Unqualified (not eligible), from any open stage, like Salesforce "Closed - Not Converted".
    A reason and notes are required; open tasks are closed. The lead stays in the CRM (Unqualified Leads list) and can
    be reopened later if things change."""
    lead = get_for_update(db, Lead, lead_id, "Lead")
    ensure_open(lead)
    require_edit(lead.owner_id, "lead")
    lead.untouched = False
    by = acting_user_id()
    old = lead.stage
    lead.stage, lead.closed_at = "Unqualified", now()
    lead.unqualified_reason, lead.unqualified_notes = data.reason, data.notes
    lead.revisit_date = lead.revisit_reason = lead.demo_date = None
    record_stage_change(db, lead_id=lead.id, from_stage=old, to_stage="Unqualified", changed_by_id=by,
                        note=f"{data.reason}: {data.notes}")
    auto_close_open_tasks(db, lead_id=lead.id)
    stage_notice(db, kind="Lead", stage="Unqualified", record_name=lead.name, owner_id=lead.owner_id, actor_id=by,
                 lead_id=lead.id, details=[f"Was at: {old}", f"Reason: {data.reason}", f"Notes: {data.notes}"])
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


@router.post("/{lead_id}/reopen", response_model=schemas.LeadDetail)
def reopen(lead_id: int, data: schemas.ReopenLead, db: Session = Depends(get_db)):
    """Bring an Unqualified lead back to New (Salesforce "recycle": e.g. the budget is there now). A note and the
    user's new task are required."""
    lead = get_for_update(db, Lead, lead_id, "Lead")
    require_view(lead.owner_id, "lead")
    if lead.stage != "Unqualified":
        raise HTTPException(status_code=400, detail="Only an Unqualified lead can be reopened")
    require_edit(lead.owner_id, "lead")
    task_owner = stage_task_owner(db, data.task, lead.owner_id)
    by = acting_user_id()
    lead.stage, lead.closed_at = LEAD_START, None
    lead.unqualified_reason = lead.unqualified_notes = None
    record_stage_change(db, lead_id=lead.id, from_stage="Unqualified", to_stage=LEAD_START, changed_by_id=by,
                        note=f"Reopened: {data.note}")
    task = add_stage_task(db, data.task, owner_id=task_owner, record_owner_id=lead.owner_id, actor_id=by,
                          lead_id=lead.id)
    stage_notice(db, kind="Lead", stage=LEAD_START, record_name=lead.name, owner_id=lead.owner_id, actor_id=by,
                 lead_id=lead.id, task=task, details=[f"Reopened: {data.note}"], title="Lead reopened")
    db.commit()
    db.refresh(lead)
    return lead_detail(lead)


# ---------- Convert ----------

@router.post("/{lead_id}/convert", response_model=schemas.ConvertResult)
def convert_lead(lead_id: int, data: schemas.ConvertLead, db: Session = Depends(get_db)):
    """Convert an open lead, like Salesforce: creates (or reuses) the Account, creates the Contact
    and the Opportunity. Lead tasks are auto-closed. The note is required (saved in the stage history of the lead and
    of the new opportunity), and so is the user's new task: it is linked to the new opportunity, instead of the
    system's 'Send proposal' task."""
    forbid_admin_create("opportunities")
    lead = get_for_update(db, Lead, lead_id, "Lead")
    ensure_open(lead)
    require_edit(lead.owner_id, "lead")
    task_owner = stage_task_owner(db, data.task, lead.owner_id)  # the new opportunity's owner is the lead's
    lead.untouched = False  # someone is working on it now
    # Convert comes after Demo: every required stage up to Demo must be done (or confirmed as done)
    lead.stage = confirm_skipped(db, flow=LEAD_FLOW, current=lead.stage, target_index=len(LEAD_FLOW),
                                 completed=data.completed_stages, note=data.completed_note, by=acting_user_id(),
                                 lead_id=lead.id, what="converting", optional=LEAD_OPTIONAL_STAGES)
    require_edit(lead.owner_id, "lead")
    by = acting_user_id()

    if data.account_id is not None:
        account = get_or_404(db, Account, data.account_id, "Account")
    else:
        account = Account(
            name=lead.company or lead.name, industry=lead.industry, phone=lead.phone, owner_id=lead.owner_id,
            website=lead.company_website, linkedin_url=lead.company_linkedin_url, address=lead.location,
            annual_revenue=lead.annual_revenue, employees=lead.employees,
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
        linkedin_url=lead.linkedin_url,
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
    record_stage_change(db, lead_id=lead.id, from_stage=old, to_stage="Converted", changed_by_id=by, note=data.note)
    record_stage_change(db, opportunity_id=opportunity.id, from_stage=None, to_stage="Opportunity", changed_by_id=by,
                        note=data.note)
    task = add_stage_task(db, data.task, owner_id=task_owner, record_owner_id=opportunity.owner_id, actor_id=by,
                          opportunity_id=opportunity.id)
    details = [f"Converted from lead: {lead.name}", f"Account: {account.name}"]
    if opportunity.expected_value is not None:
        details.append(f"Amount: ${opportunity.expected_value:,.2f}")
    details.append(f"Close date: {opportunity.expected_close_date:%d %b %Y}")
    details += task_line("Close date reminder", schedule_close_date_task(db, opportunity))
    details.append(f"Note: {data.note}")
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


# ---------- delete ----------

@router.delete("/{lead_id}")
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    """Delete a lead that is not converted: its owner, a Manager or the Admin.
    Its tasks, notes, emails and stage history go with it. The Admin and the Managers are told,
    and it is recorded in the Activity Log (name, company, email, owner, stage)."""
    lead = get_or_404(db, Lead, lead_id, "Lead")
    me = require_edit(lead.owner_id, "lead")
    name, summary, owner_id = delete_one(db, lead, me.id)
    # the Admin and Managers, and the owner when someone else deleted it
    told = db.scalars(select(User).where(or_(User.role.in_(("Admin", "Manager")), User.id == owner_id),
                                          User.is_active.is_(True), User.id != me.id)).all()
    for user in told:
        notify(db, user.id, "Lead deleted", f'Lead "{name}" was deleted by {me.full_name}.\n{summary}', link="/leads")
    db.commit()
    return {"message": f'Lead "{name}" was deleted.'}


def delete_one(db: Session, lead: Lead, actor_id: int) -> tuple[str, str, int]:
    """Deletes a lead that is not converted, with its tasks, notes, emails and history, and logs it.
    Permission is checked by the caller. Returns (name, summary, owner id) for the notifications."""
    if lead.stage == "Converted" or lead.opportunity is not None:
        raise HTTPException(status_code=400, detail="A converted lead can't be deleted: it has an opportunity.")
    owner = lead.owner.full_name if lead.owner else "Unknown"
    summary = " • ".join(x for x in (lead.company, lead.email, f"Owner: {owner}", f"Stage: {lead.stage}") if x)
    name = lead.name
    owner_id = lead.owner_id
    email_ids = select(Email.id).where(Email.lead_id == lead.id)
    db.execute(delete(EmailAttachment).where(EmailAttachment.email_id.in_(email_ids)))
    db.execute(delete(Email).where(Email.lead_id == lead.id))
    task_ids = select(Task.id).where(Task.lead_id == lead.id)
    db.execute(delete(Notification).where(Notification.task_id.in_(task_ids)))
    db.execute(delete(Notification).where(Notification.link == record_link(lead_id=lead.id)))
    for model in (Task, Note, StageHistory, LeadTransfer):  # transfer history too, or a transferred lead can't be deleted
        db.execute(delete(model).where(model.lead_id == lead.id))
    db.expire(lead)
    db.delete(lead)
    log_activity(db, actor_id, "Lead deleted", name, summary)
    return name, summary, owner_id


@router.get("/{lead_id}/history", response_model=list[schemas.StageHistoryOut])
def lead_history(lead_id: int, db: Session = Depends(get_db)):
    lead = get_or_404(db, Lead, lead_id, "Lead")
    require_view(lead.owner_id, "lead")
    return [history_out(h) for h in sorted(lead.history, key=lambda h: h.id)]
