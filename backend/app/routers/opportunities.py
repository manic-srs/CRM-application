"""Opportunity APIs: the second half of the lifecycle.

Opportunity -> Discovery -> Proposal -> Won, or Lost at any open stage. Opportunities come from converting a lead,
or from New Opportunity (Opportunities or Account page), which reuses the company's account and the person's contact.
"""
import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import insert, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app import schemas
from app.constants import OPPORTUNITY_FLOW, OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES, STAGE_PROBABILITY
from app.database import get_db
from app.security import (acting_user, acting_user_id, check_owner_change, forbid_admin_create, owner_for_new,
                          require_edit, require_view, visible)
from app.models import Account, Contact, Lead, Opportunity, OpportunityAttachment, User
from app import opportunity_matches as matches
from app.routers.attachments import (MAX_REQUEST_BYTES, checked_type, clean_filename, header_login_only,
                                     locked_opportunity, read_upload)
from app.serializers import account_out, contact_out, history_out, opportunity_detail, opportunity_out, task_out
from app.services import (
    add_stage_task,
    confirm_skipped,
    auto_close_open_tasks,
    get_for_update,
    get_or_404,
    log_activity,
    notify,
    now,
    record_stage_change,
    reassign_system_tasks,
    handover_lines,
    resolve_user_id,
    schedule_close_date_task,
    stage_notice,
    stage_task_owner,
)
from app.constants import CLOSE_DATE_TASK

router = APIRouter(prefix="/api/opportunities", tags=["Opportunities"])


def ensure_open(opp: Opportunity):
    if opp.stage not in OPPORTUNITY_OPEN_STAGES:
        raise HTTPException(
            status_code=400, detail=f"Opportunity {opp.id} is {opp.stage} (closed); it can't change any more"
        )


@router.get("", response_model=list[schemas.OpportunityOut])
def list_opportunities(
    stage: str | None = Query(None, description="Opportunity, Proposal, Won or Lost"),
    owner_id: int | None = Query(None),
    account_id: int | None = Query(None),
    search: str | None = Query(None, description="Opportunity name"),
    db: Session = Depends(get_db),
):
    if stage and stage not in OPPORTUNITY_STAGES:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'. Use: {', '.join(OPPORTUNITY_STAGES)}")
    query = visible(select(Opportunity), Opportunity)
    if stage:
        query = query.where(Opportunity.stage == stage)
    if owner_id is not None:
        query = query.where(Opportunity.owner_id == owner_id)
    if account_id is not None:
        query = query.where(Opportunity.account_id == account_id)
    if search:
        query = query.where(Opportunity.name.ilike(f"%{search.strip()}%"))
    return [opportunity_out(o) for o in db.scalars(query.order_by(Opportunity.id.desc())).all()]


@router.get("/duplicate-check")
def duplicate_check(
    company: str | None = Query(None, max_length=200),
    account_id: int | None = Query(None),
    contact_id: int | None = Query(None),
    email: str | None = Query(None, max_length=255),
    first_name: str | None = Query(None, max_length=50),
    last_name: str | None = Query(None, max_length=50),
    name: str | None = Query(None, max_length=200, description="Opportunity name (blank = the default name)"),
    lead_id: int | None = Query(None, description="Converting this lead: its company, email and name are used"),
    db: Session = Depends(get_db),
):
    """Before New Opportunity or Convert: the account and contact that will be reused, and whether this person at
    this company already has an open opportunity with that name (it can't be created twice)."""
    if lead_id is not None:
        lead = get_or_404(db, Lead, lead_id, "Lead")
        require_view(lead.owner_id, "lead")
        company, email, first_name, last_name = lead.company or lead.name, lead.email, lead.first_name, lead.last_name
    return matches.check(db, company=company, account_id=account_id, contact_id=contact_id, email=email,
                         first_name=first_name, last_name=last_name, name=name)


@router.post("", response_model=schemas.OpportunityCreated, status_code=201)
def create_opportunity(data: schemas.OpportunityCreate, db: Session = Depends(get_db)):
    """New Opportunity without a lead. No duplicates: an existing account with the company name and an existing contact
    with the email (or name) are reused, and the same open opportunity for the same person and company is refused."""
    me = forbid_admin_create("opportunities")
    owner_id = resolve_user_id(db, owner_for_new(data.owner_id))
    task_owner = stage_task_owner(db, data.task, owner_id)
    if data.account_id is not None:
        account = get_or_404(db, Account, data.account_id, "Account")
    else:
        account = matches.find_account(db, data.account_name)
    reused_account = account is not None
    contact = None
    if data.primary_contact_id is not None:
        contact = get_or_404(db, Contact, data.primary_contact_id, "Contact")
        if account is not None and contact.account_id != account.id:
            raise HTTPException(status_code=400, detail="That contact belongs to a different account")
    elif account is not None:
        contact = matches.find_contact(db, account.id, email=data.contact_email, first_name=data.contact_first_name,
                                       last_name=data.contact_last_name)
    reused_contact = contact is not None
    matches.ensure_no_duplicate(db, account, contact, data.name)
    if account is None:
        account = Account(name=data.account_name.strip(), owner_id=owner_id)
        db.add(account)
        db.flush()
    if contact is None:
        contact = Contact(salutation=data.contact_salutation, first_name=(data.contact_first_name or "").strip() or None,
                          last_name=data.contact_last_name.strip(), email=(data.contact_email or "").strip() or None,
                          job_title=(data.contact_title or "").strip() or None,
                          phone=(data.contact_phone or "").strip() or None, account_id=account.id, owner_id=owner_id)
        db.add(contact)
        db.flush()
    opp = Opportunity(
        name=data.name.strip(), stage="Opportunity", probability=STAGE_PROBABILITY["Opportunity"],
        expected_value=data.expected_value,
        expected_close_date=data.expected_close_date or (date.today() + timedelta(days=30)),
        account_id=account.id, primary_contact_id=contact.id, owner_id=owner_id,
    )
    db.add(opp)
    db.flush()
    record_stage_change(db, opportunity_id=opp.id, from_stage=None, to_stage="Opportunity", changed_by_id=me.id,
                        note=data.note)
    task = add_stage_task(db, data.task, owner_id=task_owner, record_owner_id=owner_id, actor_id=me.id,
                          opportunity_id=opp.id)
    details = [f"Account: {account.name}" + (" (existing account)" if reused_account else ""),
               f"Contact: {contact.full_name}" + (" (existing contact)" if reused_contact else "")]
    if opp.expected_value is not None:
        details.append(f"Amount: ${opp.expected_value:,.2f}")
    details.append(f"Close date: {opp.expected_close_date:%d %b %Y}")
    schedule_close_date_task(db, opp)
    details.append(f"Note: {data.note}")
    stage_notice(db, kind="Opportunity", stage="Opportunity", record_name=opp.name, owner_id=owner_id, actor_id=me.id,
                 opportunity_id=opp.id, task=task, details=details,
                 title="Opportunity assigned to you" if owner_id != me.id else None)
    log_activity(db, me.id, "Opportunity created", opp.name, " • ".join(details[:2]))
    db.commit()
    for record in (opp, account, contact):
        db.refresh(record)
    if task:
        db.refresh(task)
    return {"opportunity": opportunity_out(opp), "account": account_out(account), "contact": contact_out(contact),
            "new_task": task_out(task) if task else None,
            "reused": {"account": reused_account, "contact": reused_contact}}


@router.get("/{opportunity_id}", response_model=schemas.OpportunityDetail)
def get_opportunity(opportunity_id: int, db: Session = Depends(get_db)):
    """The opportunity record page: details, tasks, notes and stage history."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    require_view(opp.owner_id, "opportunity")
    return opportunity_detail(opp)


@router.put("/{opportunity_id}", response_model=schemas.OpportunityOut)
def update_opportunity(opportunity_id: int, data: schemas.OpportunityUpdate, db: Session = Depends(get_db)):
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    require_edit(opp.owner_id, "opportunity")
    changes = data.model_dump(exclude_unset=True)
    changes.pop("changed_by_id", None)
    actor = acting_user_id()
    check_owner_change(opp.owner_id, changes.get("owner_id"))
    old_owner = opp.owner_id
    if "name" in changes and not changes["name"]:
        raise HTTPException(status_code=400, detail="name can't be empty")
    if changes.get("primary_contact_id") is not None:
        get_or_404(db, Contact, changes["primary_contact_id"], "Contact")
    if "owner_id" in changes:
        changes["owner_id"] = resolve_user_id(db, changes["owner_id"])
    for field, value in changes.items():
        setattr(opp, field, value)
    if ("name" in changes or "primary_contact_id" in changes) and opp.stage in OPPORTUNITY_OPEN_STAGES:
        # renaming or changing the contact can't turn it into a copy of another open opportunity
        matches.ensure_no_duplicate(db, opp.account, db.get(Contact, opp.primary_contact_id) if opp.primary_contact_id
                                    else None, opp.name, exclude_id=opp.id)
    if opp.owner_id != old_owner:
        db.flush()
        # the deal keeps its stage and history; its open follow-ups and reminders go to the new owner
        tasks = reassign_system_tasks(db, opp.owner_id, opportunity_id=opp.id, previous_owner_id=old_owner)
        if opp.owner_id != actor:
            by = db.get(User, actor)
            notify(db, opp.owner_id, "Opportunity assigned to you", "\n".join([
                f'{by.full_name if by else "Someone"} gave you opportunity "{opp.name}".',
                *handover_lines(db, stage=opp.stage, tasks=tasks, opportunity_id=opp.id)]),
                link=f"/opportunities/{opp.id}", category="assignment")
        log_activity(db, actor, "Opportunity reassigned", opp.name, f"{len(tasks)} open task(s) moved")
    if "expected_close_date" in changes and opp.stage in OPPORTUNITY_OPEN_STAGES:
        schedule_close_date_task(db, opp)  # move the close-date reminder to the new date
    db.commit()
    db.refresh(opp)
    return opportunity_out(opp)


def check_stage_change(opp: Opportunity, stage: str) -> int:
    """The deal is open, the stage is a new one and the user can edit the deal. Returns the user's id."""
    ensure_open(opp)
    if opp.stage == stage:
        raise HTTPException(status_code=400, detail=f"Opportunity {opp.id} is already at {stage}")
    require_edit(opp.owner_id, "opportunity")
    return acting_user_id()


# Discovery (Salesforce "Needs Analysis"): saved on the deal when it moves to Discovery; editable afterwards (Edit)
DISCOVERY_FIELDS = ("discovery_needs", "discovery_budget", "discovery_decision_maker", "discovery_timeline")
DISCOVERY_LABELS = (("discovery_needs", "Needs"), ("discovery_budget", "Budget"),
                    ("discovery_decision_maker", "Decision maker"), ("discovery_timeline", "Timeline"))


def move_stage(db: Session, opp: Opportunity, data: schemas.OpportunityStageChange, task_owner: int, by: int) -> None:
    """Between Opportunity, Discovery and Proposal: stage history (with the user's note), the user's new task (instead
    of the system follow-up), old follow-ups closed and the owner's notification (the caller saves). Moving forward
    can't skip a stage: a skipped one must be confirmed as already done (saved in the history)."""
    stage, note = data.stage, data.note
    if OPPORTUNITY_FLOW.index(stage) > OPPORTUNITY_FLOW.index(opp.stage):  # forward; going back is allowed
        opp.stage = confirm_skipped(db, flow=OPPORTUNITY_FLOW, current=opp.stage,
                                    target_index=OPPORTUNITY_FLOW.index(stage), completed=data.completed_stages,
                                    note=data.completed_note, by=by, opportunity_id=opp.id, what=stage)
    details = [f"Note: {note}"]
    if stage == "Discovery":  # Salesforce "Needs Analysis": what the customer needs is required
        needs = (data.discovery_needs or "").strip()
        if len(needs) < 5:
            raise HTTPException(status_code=422, detail="Describe what the customer needs (Discovery)")
        for field in DISCOVERY_FIELDS:
            value = getattr(data, field)
            if value is not None and value.strip():
                setattr(opp, field, value.strip())
        details += [f"{label}: {getattr(opp, field)}" for field, label in DISCOVERY_LABELS if getattr(opp, field)]
    old = opp.stage
    opp.stage = stage
    opp.probability = STAGE_PROBABILITY[stage]
    record_stage_change(db, opportunity_id=opp.id, from_stage=old, to_stage=stage, changed_by_id=by, note=note)
    auto_close_open_tasks(db, opportunity_id=opp.id, keep=(CLOSE_DATE_TASK,))  # the close-date reminder stays
    task = add_stage_task(db, data.task, owner_id=task_owner, record_owner_id=opp.owner_id, actor_id=by,
                          opportunity_id=opp.id)
    stage_notice(
        db, kind="Opportunity", stage=stage, record_name=opp.name, owner_id=opp.owner_id, actor_id=by,
        opportunity_id=opp.id, task=task, details=details,
        title="Opportunity moved back to Opportunity" if stage == "Opportunity" else None,
    )


@router.put("/{opportunity_id}/stage", response_model=schemas.OpportunityDetail)
def change_stage(opportunity_id: int, data: schemas.OpportunityStageChange, db: Session = Depends(get_db)):
    """Move between Opportunity, Discovery and Proposal. A note (saved in the stage history) and the user's new task are
    required. Old follow-ups are auto-closed; the new task takes the place of the system follow-up."""
    opp = get_for_update(db, Opportunity, opportunity_id, "Opportunity")
    by = check_stage_change(opp, data.stage)
    move_stage(db, opp, data, stage_task_owner(db, data.task, opp.owner_id), by)
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


# The Change Stage and Mark as Won popups can add files: they are saved with the stage change in one request
# (all or nothing). Files from Mark as Won are labelled Proposal: they are added while closing that stage.
STAGE_MAX_FILES = 5  # more can be added on the Attachments card afterwards (while the deal is open)
STAGE_MAX_REQUEST_BYTES = STAGE_MAX_FILES * MAX_REQUEST_BYTES + 1024 * 1024  # the files, the form and the note
WON_FILES_STAGE = "Proposal"
# notify_customer is still accepted (older pages send it) but ignored: the CRM never emails customers itself
WON_FORM_FIELDS = {"final_value", "note", "task", "notify_customer", "completed_stages", "completed_note", "files"}
FILES_FIELD ={"type": "array", "items": {"type": "string", "format": "binary"},
               "description": f"1 to {STAGE_MAX_FILES} PDF, Word (.docx), JPG or PNG files, up to 20 MB each"}
TASK_FIELD = {"type": "string", "description": 'The new task as JSON, as in PUT /stage: {"title": ..., "due_date": ..., '
                                               '"priority", "reminder_at", "description", "owner_id" optional}'}
STAGE_FILES_FORM = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["stage", "note", "task", "files"],
    "properties": {"stage": {"type": "string", "enum": OPPORTUNITY_OPEN_STAGES}, "note": {"type": "string"},
                   "task": TASK_FIELD, "files": FILES_FIELD,
                   "completed_stages": {"type": "array", "items": {"type": "string"}},
                   "completed_note": {"type": "string", "maxLength": 500}}}}}}}
WON_FILES_FORM = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["note", "task", "files"],
    "properties": {"final_value": {"type": "number", "minimum": 0}, "note": {"type": "string"}, "task": TASK_FIELD,
                   "completed_stages": {"type": "array", "items": {"type": "string"}},
                   "completed_note": {"type": "string", "maxLength": 500}, "files": FILES_FIELD}}}}}}


def check_request_size(request: Request) -> None:
    """The size is checked before anything is read; the server never accepts more than Content-Length."""
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(status_code=411, detail="The request has no size. Try again.")
    if int(length) > STAGE_MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail=f"Up to {STAGE_MAX_FILES} files of up to 20 MB each can be "
                                                    "added at a time.")


def refuse_unknown_fields(form, allowed: set[str]) -> None:
    unknown = set(form.keys()) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown form field: {', '.join(sorted(unknown))}")


def invalid_form(error: ValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail="; ".join(
        f"{e['loc'][0]}: {e['msg']}" for e in error.errors(include_url=False)))


def form_task(value):
    """The New Task of a popup with files: the form field "task" holds it as JSON (checked by the schema)."""
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except ValueError:
            return value  # not JSON: refused by the schema
    return None if value in (None, "") else value


async def checked_files(form, without: str) -> list[tuple[UploadFile, str, str]]:
    """The form's files (field "files"), each checked like the Attachments card's uploads, with its name and the
    type the server detected. Nothing is saved here."""
    uploads = form.getlist("files")
    if not uploads or not all(isinstance(u, UploadFile) for u in uploads):
        raise HTTPException(status_code=422, detail=f'Choose at least one file (form field "files"). '
                                                    f"Without files, use {without}.")
    checked = []
    for upload in uploads:
        filename = clean_filename(upload.filename)
        if not filename:
            raise HTTPException(status_code=422, detail="Every file needs a name.")
        checked.append((upload, filename, checked_type(filename, await read_upload(upload, filename))))
    return checked


async def save_files(db: Session, opp: Opportunity, stage: str, checked: list, by: int) -> None:
    """Adds the checked files to the deal with this stage (saved with the rest of the request)."""
    for upload, filename, content_type in checked:
        await upload.seek(0)
        content = await upload.read()  # checked before: at most 20 MB
        db.execute(insert(OpportunityAttachment).values(
            opportunity_id=opp.id, stage=stage, filename=filename, content_type=content_type,
            size_bytes=len(content), data=content, uploaded_by_id=by,
        ))


@router.post("/{opportunity_id}/stage-with-files", response_model=schemas.OpportunityDetail,
             dependencies=[Depends(header_login_only)], openapi_extra=STAGE_FILES_FORM)
async def change_stage_with_files(opportunity_id: int, request: Request, db: Session = Depends(get_db)):
    """The same stage change as PUT /stage, plus files (form fields stage, note, task, files) saved with it.
    The files are checked like the Attachments card's uploads and get the new stage. The note and the new task are
    checked first, then every file, before anything is saved: if one is refused, nothing changes (no stage, note,
    task, notification or file)."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    require_edit(opp.owner_id, "opportunity")  # before the files are read
    check_request_size(request)
    async with request.form(max_files=STAGE_MAX_FILES, max_fields=12) as form:
        refuse_unknown_fields(form, {"stage", "note", "task", "files", "completed_stages", "completed_note",
                                     *DISCOVERY_FIELDS})
        try:
            data = schemas.OpportunityStageChange(stage=form.get("stage"), note=form.get("note") or None,
                                                  task=form_task(form.get("task")),
                                                  completed_stages=form.getlist("completed_stages"),
                                                  completed_note=form.get("completed_note") or None,
                                                  **{f: form.get(f) or None for f in DISCOVERY_FIELDS})
        except ValidationError as error:
            raise invalid_form(error)
        stage_task_owner(db, data.task, opp.owner_id)  # the assignee is checked before the files are read
        checked = await checked_files(form, without="PUT /stage")

        opp = locked_opportunity(db, opportunity_id)
        by = check_stage_change(opp, data.stage)  # again: another save may have changed the deal meanwhile
        task_owner = stage_task_owner(db, data.task, opp.owner_id)
        await save_files(db, opp, data.stage, checked, by)
        move_stage(db, opp, data, task_owner, by)
        db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


def check_won(opp: Opportunity, data: schemas.MarkWon) -> tuple[float, int]:
    """The deal is open, has a final amount and the user can edit it. Returns the final amount and the user's id."""
    ensure_open(opp)
    final_value = data.final_value if data.final_value is not None else opp.expected_value
    if final_value is None:
        raise HTTPException(status_code=400, detail="final_value is required (the deal has no expected value)")
    require_edit(opp.owner_id, "opportunity")
    return final_value, acting_user_id()


def close_won(db: Session, opp: Opportunity, data: schemas.MarkWon, final_value: float, task_owner: int,
              by: int) -> None:
    """Won: stage history, open tasks closed, the user's post-sale task (created after that, so it stays open on the
    won deal), the owner's notification and, if chosen, the customer's thank-you email (sent only after the save is
    committed; the caller saves)."""
    # Won comes after Proposal: every stage up to Proposal must be done (or confirmed as done)
    opp.stage = confirm_skipped(db, flow=OPPORTUNITY_FLOW, current=opp.stage, target_index=len(OPPORTUNITY_FLOW),
                                completed=data.completed_stages, note=data.completed_note, by=by,
                                opportunity_id=opp.id, what="marking it as Won")
    old = opp.stage
    opp.stage = "Won"
    opp.probability = STAGE_PROBABILITY["Won"]
    opp.final_value = final_value
    opp.closed_at = now()
    record_stage_change(db, opportunity_id=opp.id, from_stage=old, to_stage="Won", changed_by_id=by, note=data.note)
    auto_close_open_tasks(db, opportunity_id=opp.id)
    add_stage_task(db, data.task, owner_id=task_owner, record_owner_id=opp.owner_id, actor_id=by,
                   opportunity_id=opp.id)
    details = [f"Final amount: ${final_value:,.2f}", f"Note: {data.note}"]
    stage_notice(db, kind="Opportunity", stage="Won", record_name=opp.name, owner_id=opp.owner_id,
                 actor_id=by, opportunity_id=opp.id, details=details)


@router.post("/{opportunity_id}/won", response_model=schemas.OpportunityDetail)
def mark_won(opportunity_id: int, data: schemas.MarkWon, db: Session = Depends(get_db)):
    """Close as Won from any open stage. The closing note and a post-sale task (e.g. handover or onboarding) are
    required; final_value defaults to the expected value."""
    opp = get_for_update(db, Opportunity, opportunity_id, "Opportunity")
    final_value, by = check_won(opp, data)
    close_won(db, opp, data, final_value, stage_task_owner(db, data.task, opp.owner_id), by)
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


@router.post("/{opportunity_id}/won-with-files", response_model=schemas.OpportunityDetail,
             dependencies=[Depends(header_login_only)], openapi_extra=WON_FILES_FORM)
async def mark_won_with_files(opportunity_id: int, request: Request, db: Session = Depends(get_db)):
    """The same as POST /won, plus files from the Mark as Won popup (form fields final_value, note, task,
    completed_stages, completed_note, files). The files are checked like the Attachments card's
    uploads and labelled Proposal, the stage being closed. They are saved while the deal is still open and it moves
    to Won in the same save: if anything is refused, nothing changes (no amount, note, file, task, notification or
    email)."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    require_edit(opp.owner_id, "opportunity")  # before the files are read
    check_request_size(request)
    async with request.form(max_files=STAGE_MAX_FILES, max_fields=10) as form:
        refuse_unknown_fields(form, WON_FORM_FIELDS)
        values = {name: form.get(name) for name in ("final_value", "completed_note")
                  if form.get(name) not in (None, "")}
        try:
            data = schemas.MarkWon(**values, note=form.get("note"), task=form_task(form.get("task")),
                                   completed_stages=form.getlist("completed_stages"))
        except ValidationError as error:
            raise invalid_form(error)
        stage_task_owner(db, data.task, opp.owner_id)  # the assignee is checked before the files are read
        checked = await checked_files(form, without="POST /won")

        opp = locked_opportunity(db, opportunity_id)
        final_value, by = check_won(opp, data)  # again: another save may have changed the deal meanwhile
        task_owner = stage_task_owner(db, data.task, opp.owner_id)
        await save_files(db, opp, WON_FILES_STAGE, checked, by)
        close_won(db, opp, data, final_value, task_owner, by)
        db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


def close_lost(db: Session, opp: Opportunity, lost_reason: str, lost_notes: str, by: int) -> None:
    """Closes an open deal as Lost: stage history, open tasks closed, the owner's notification (the caller saves)."""
    old = opp.stage
    opp.stage = "Lost"
    opp.probability = STAGE_PROBABILITY["Lost"]
    opp.lost_reason = lost_reason
    opp.lost_notes = lost_notes
    opp.closed_at = now()
    record_stage_change(db, opportunity_id=opp.id, from_stage=old, to_stage="Lost", changed_by_id=by, note=lost_notes)
    auto_close_open_tasks(db, opportunity_id=opp.id)
    details = [f"Lost at stage: {old}", f"Reason: {lost_reason}", f"Notes: {lost_notes}"]
    stage_notice(db, kind="Opportunity", stage="Lost", record_name=opp.name, owner_id=opp.owner_id,
                 actor_id=by, opportunity_id=opp.id, details=details)


@router.post("/{opportunity_id}/lost", response_model=schemas.OpportunityDetail)
def mark_lost(opportunity_id: int, data: schemas.MarkLost, db: Session = Depends(get_db)):
    """Close as Lost from any open stage. A lost reason and notes are required (no new task)."""
    opp = get_for_update(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    require_edit(opp.owner_id, "opportunity")
    close_lost(db, opp, data.lost_reason, data.lost_notes, acting_user_id())
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


# ---------- bulk: the opportunities ticked in the list (Actions menu) ----------

def _bulk(db: Session, ids: list[int]):
    seen = set()
    for opp_id in ids:
        if opp_id not in seen:
            seen.add(opp_id)
            yield opp_id, db.get(Opportunity, opp_id)


def _skipped(opp_id: int, opp: Opportunity | None, exc: HTTPException) -> dict:
    hidden = opp is None or exc.status_code == 404
    return {"id": opp_id, "name": f"Opportunity {opp_id}" if hidden else opp.name,
            "reason": "Not found, or you don't have access to it" if hidden else str(exc.detail)}


@router.post("/bulk-transfer")
def bulk_transfer(data: schemas.BulkOpportunityTransfer, db: Session = Depends(get_db)):
    """Change the owner of several open opportunities (Salesforce "Change Owner"). The Admin and users with Reassign
    owner can move any deal they can see; a user with Transfer own leads can move their own. Follow-ups and reminders
    go to the new owner. Deals that can't be moved are skipped with the reason. One notification to the new owner."""
    me = acting_user()
    target = db.get(User, data.to_user_id)
    if target is None or not target.is_active or target.role == "Admin":
        raise HTTPException(status_code=400, detail="Choose an active Manager or Salesperson")
    moved, skipped = [], []
    for opp_id, opp in _bulk(db, data.opportunity_ids):
        try:
            if opp is None:
                raise HTTPException(status_code=404, detail="Not found")
            require_view(opp.owner_id, "opportunity")
            ensure_open(opp)
            if not (me.is_admin or me.can("reassign_owner") or (me.can("transfer_leads") and opp.owner_id == me.id)):
                raise HTTPException(status_code=403, detail="You can only transfer your own opportunities")
            if opp.owner_id == target.id:
                raise HTTPException(status_code=400, detail=f"Already owned by {target.full_name}")
            previous_owner = opp.owner_id
            opp.owner_id = target.id
            db.flush()
            reassign_system_tasks(db, target.id, opportunity_id=opp.id, previous_owner_id=previous_owner)
            log_activity(db, me.id, "Opportunity reassigned", opp.name,
                         f"New owner: {target.full_name} (bulk)" + (f" • Note: {data.note}" if data.note else ""))
            moved.append({"id": opp.id, "name": opp.name})
        except HTTPException as exc:
            skipped.append(_skipped(opp_id, opp, exc))
    if moved and target.id != me.id:
        names = ", ".join(m["name"] for m in moved[:10]) + (f" and {len(moved) - 10} more" if len(moved) > 10 else "")
        notify(db, target.id, "Opportunities assigned to you",
               f"{me.full_name} gave you {len(moved)} opportunit{'ies' if len(moved) != 1 else 'y'}: {names}."
               + (f"\nNote: {data.note}" if data.note else ""), link="/opportunities", category="assignment")
    db.commit()
    return {"transferred": len(moved), "to": target.full_name, "moved": moved, "skipped": skipped}


@router.post("/bulk-lost")
def bulk_lost(data: schemas.BulkOpportunityLost, db: Session = Depends(get_db)):
    """Close several open opportunities as Lost with one reason and note (e.g. cleaning up stale deals). Each follows
    the Mark as Lost rules; deals that can't be closed are skipped with the reason."""
    by = acting_user_id()
    closed, skipped = [], []
    for opp_id, opp in _bulk(db, data.opportunity_ids):
        try:
            if opp is None:
                raise HTTPException(status_code=404, detail="Not found")
            require_edit(opp.owner_id, "opportunity")
            ensure_open(opp)
            close_lost(db, opp, data.lost_reason, data.lost_notes, by)
            closed.append({"id": opp.id, "name": opp.name})
        except HTTPException as exc:
            skipped.append(_skipped(opp_id, opp, exc))
    db.commit()
    return {"closed": len(closed), "lost": closed, "skipped": skipped}


@router.get("/{opportunity_id}/history", response_model=list[schemas.StageHistoryOut])
def opportunity_history(opportunity_id: int, db: Session = Depends(get_db)):
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    require_view(opp.owner_id, "opportunity")
    return [history_out(h) for h in sorted(opp.history, key=lambda h: h.id)]
