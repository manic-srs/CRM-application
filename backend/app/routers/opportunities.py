"""Opportunity APIs: the second half of the lifecycle.

Opportunity -> Proposal -> Won, or Lost at any open stage. Opportunities come from converting a lead.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import insert, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app import schemas
from app.constants import OPPORTUNITY_FLOW, OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES, STAGE_PROBABILITY
from app.database import get_db
from app.security import acting_user_id, check_owner_change, require_edit, require_view, visible
from app.models import Contact, Opportunity, OpportunityAttachment
from app.routers.attachments import (MAX_REQUEST_BYTES, checked_type, clean_filename, header_login_only,
                                     locked_opportunity, read_upload)
from app.serializers import history_out, opportunity_detail, opportunity_out
from app.services import (
    confirm_skipped,
    customer_email,
    assignment_notice,
    auto_close_open_tasks,
    create_auto_task,
    get_or_404,
    now,
    record_stage_change,
    reassign_system_tasks,
    resolve_user_id,
    schedule_close_date_task,
    stage_notice,
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
    if opp.owner_id != old_owner:
        db.flush()
        reassign_system_tasks(db, opp.owner_id, opportunity_id=opp.id)  # follow-ups and reminders go to the new owner
        assignment_notice(db, owner_id=opp.owner_id, actor_id=actor, kind="Opportunity", name=opp.name, link=f"/opportunities/{opp.id}")
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


def move_stage(db: Session, opp: Opportunity, stage: str, note: str | None, by: int) -> None:
    """Opportunity <-> Proposal: stage history, follow-up tasks and the owner's notification (the caller saves)."""
    old = opp.stage
    opp.stage = stage
    opp.probability = STAGE_PROBABILITY[stage]
    record_stage_change(db, opportunity_id=opp.id, from_stage=old, to_stage=stage, changed_by_id=by, note=note)
    auto_close_open_tasks(db, opportunity_id=opp.id, keep=(CLOSE_DATE_TASK,))  # the close-date reminder stays
    task = create_auto_task(db, stage=stage, owner_id=opp.owner_id, record_name=opp.name, opportunity_id=opp.id)
    details = []
    if note:
        details.append(f"Note: {note}")
    stage_notice(
        db, kind="Opportunity", stage=stage, record_name=opp.name, owner_id=opp.owner_id, actor_id=by,
        opportunity_id=opp.id, task=task, details=details,
        title="Opportunity moved back to Opportunity" if stage == "Opportunity" else None,
    )


@router.put("/{opportunity_id}/stage", response_model=schemas.OpportunityDetail)
def change_stage(opportunity_id: int, data: schemas.OpportunityStageChange, db: Session = Depends(get_db)):
    """Move between Opportunity and Proposal. Old follow-ups are auto-closed, the next one is created."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    by = check_stage_change(opp, data.stage)
    move_stage(db, opp, data.stage, data.note, by)
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


# The Change Stage and Mark as Won popups can add files: they are saved with the stage change in one request
# (all or nothing). Files from Mark as Won are labelled Proposal: they are added while closing that stage.
STAGE_MAX_FILES = 5  # more can be added on the Attachments card afterwards (while the deal is open)
STAGE_MAX_REQUEST_BYTES = STAGE_MAX_FILES * MAX_REQUEST_BYTES + 1024 * 1024  # the files, the form and the note
WON_FILES_STAGE = "Proposal"
WON_FORM_FIELDS = {"final_value", "note", "notify_customer", "completed_stages", "completed_note", "files"}
FILES_FIELD ={"type": "array", "items": {"type": "string", "format": "binary"},
               "description": f"1 to {STAGE_MAX_FILES} PDF, Word (.docx), JPG or PNG files, up to 20 MB each"}
STAGE_FILES_FORM = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["stage", "files"],
    "properties": {"stage": {"type": "string", "enum": OPPORTUNITY_OPEN_STAGES}, "note": {"type": "string"},
                   "files": FILES_FIELD}}}}}}
WON_FILES_FORM = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["files"],
    "properties": {"final_value": {"type": "number", "minimum": 0}, "note": {"type": "string"},
                   "notify_customer": {"type": "boolean", "default": True},
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
    """The same stage change as PUT /stage, plus files (form fields stage, note, files) saved with it.
    The files are checked like the Attachments card's uploads and get the new stage. Every file is checked before
    anything is saved: if one is refused, nothing changes (no stage, note, task, notification or file)."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    require_edit(opp.owner_id, "opportunity")  # before the files are read
    check_request_size(request)
    async with request.form(max_files=STAGE_MAX_FILES, max_fields=2) as form:
        refuse_unknown_fields(form, {"stage", "note", "files"})
        try:
            data = schemas.OpportunityStageChange(stage=form.get("stage"), note=form.get("note") or None)
        except ValidationError as error:
            raise invalid_form(error)
        checked = await checked_files(form, without="PUT /stage")

        opp = locked_opportunity(db, opportunity_id)
        by = check_stage_change(opp, data.stage)  # again: another save may have changed the deal meanwhile
        await save_files(db, opp, data.stage, checked, by)
        move_stage(db, opp, data.stage, data.note, by)
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


def close_won(db: Session, opp: Opportunity, data: schemas.MarkWon, final_value: float, by: int) -> None:
    """Won: stage history, open tasks closed, the owner's notification and, if chosen, the customer's thank-you
    email (sent only after the save is committed; the caller saves)."""
    # Won comes after Proposal: it must be done (or confirmed as done)
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
    details = [f"Final amount: ${final_value:,.2f}"]
    if data.note:
        details.append(f"Note: {data.note}")
    stage_notice(db, kind="Opportunity", stage="Won", record_name=opp.name, owner_id=opp.owner_id,
                 actor_id=by, opportunity_id=opp.id, details=details)
    if data.notify_customer:
        email_contact(db, opp, "won")


@router.post("/{opportunity_id}/won", response_model=schemas.OpportunityDetail)
def mark_won(opportunity_id: int, data: schemas.MarkWon | None = None, db: Session = Depends(get_db)):
    """Close as Won from any open stage. final_value defaults to the expected value."""
    data = data or schemas.MarkWon()
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    final_value, by = check_won(opp, data)
    close_won(db, opp, data, final_value, by)
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


@router.post("/{opportunity_id}/won-with-files", response_model=schemas.OpportunityDetail,
             dependencies=[Depends(header_login_only)], openapi_extra=WON_FILES_FORM)
async def mark_won_with_files(opportunity_id: int, request: Request, db: Session = Depends(get_db)):
    """The same as POST /won, plus files from the Mark as Won popup (form fields final_value, note, notify_customer,
    completed_stages, completed_note, files). The files are checked like the Attachments card's uploads and labelled
    Proposal, the stage being closed. They are saved while the deal is still open and it moves to Won in the same
    save: if anything is refused, nothing changes (no amount, note, file, task, notification or email)."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    require_edit(opp.owner_id, "opportunity")  # before the files are read
    check_request_size(request)
    async with request.form(max_files=STAGE_MAX_FILES, max_fields=10) as form:
        refuse_unknown_fields(form, WON_FORM_FIELDS)
        values = {name: form.get(name) for name in ("final_value", "note", "notify_customer", "completed_note")
                  if form.get(name) not in (None, "")}
        try:
            data = schemas.MarkWon(**values, completed_stages=form.getlist("completed_stages"))
        except ValidationError as error:
            raise invalid_form(error)
        checked = await checked_files(form, without="POST /won")

        opp = locked_opportunity(db, opportunity_id)
        final_value, by = check_won(opp, data)  # again: another save may have changed the deal meanwhile
        await save_files(db, opp, WON_FILES_STAGE, checked, by)
        close_won(db, opp, data, final_value, by)
        db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


@router.post("/{opportunity_id}/lost", response_model=schemas.OpportunityDetail)
def mark_lost(opportunity_id: int, data: schemas.MarkLost, db: Session = Depends(get_db)):
    """Close as Lost from any open stage. A lost reason is required."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    require_edit(opp.owner_id, "opportunity")
    by = acting_user_id()
    old = opp.stage
    opp.stage = "Lost"
    opp.probability = STAGE_PROBABILITY["Lost"]
    opp.lost_reason = data.lost_reason
    opp.lost_notes = data.lost_notes
    opp.closed_at = now()
    record_stage_change(
        db, opportunity_id=opp.id, from_stage=old, to_stage="Lost", changed_by_id=by, note=data.lost_notes
    )
    auto_close_open_tasks(db, opportunity_id=opp.id)
    details = [f"Lost at stage: {old}", f"Reason: {data.lost_reason}"]
    if data.lost_notes:
        details.append(f"Notes: {data.lost_notes}")
    stage_notice(db, kind="Opportunity", stage="Lost", record_name=opp.name, owner_id=opp.owner_id,
                 actor_id=by, opportunity_id=opp.id, details=details)
    if data.notify_customer:
        email_contact(db, opp, "lost", after_proposal=old == "Proposal")
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


def email_contact(db: Session, opp: Opportunity, kind: str, **extra) -> None:
    """Customer email to the deal's primary contact (the person the lead became)."""
    contact = db.get(Contact, opp.primary_contact_id) if opp.primary_contact_id else None
    if contact is not None:
        customer_email(db, kind, to=contact.email, first_name=contact.first_name or contact.full_name,
                       owner_id=opp.owner_id, **extra)


@router.get("/{opportunity_id}/history", response_model=list[schemas.StageHistoryOut])
def opportunity_history(opportunity_id: int, db: Session = Depends(get_db)):
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    require_view(opp.owner_id, "opportunity")
    return [history_out(h) for h in sorted(opp.history, key=lambda h: h.id)]
