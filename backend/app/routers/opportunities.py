"""Opportunity APIs: the second half of the lifecycle.

Opportunity -> Proposal -> Won, or Lost at any open stage. Opportunities come from converting a lead.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.constants import OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES, STAGE_PROBABILITY
from app.database import get_db
from app.models import Contact, Opportunity
from app.serializers import history_out, opportunity_detail, opportunity_out
from app.services import (
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
    query = select(Opportunity)
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
    return opportunity_detail(get_or_404(db, Opportunity, opportunity_id, "Opportunity"))


@router.put("/{opportunity_id}", response_model=schemas.OpportunityOut)
def update_opportunity(opportunity_id: int, data: schemas.OpportunityUpdate, db: Session = Depends(get_db)):
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    changes = data.model_dump(exclude_unset=True)
    actor = changes.pop("changed_by_id", None)
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


@router.put("/{opportunity_id}/stage", response_model=schemas.OpportunityDetail)
def change_stage(opportunity_id: int, data: schemas.OpportunityStageChange, db: Session = Depends(get_db)):
    """Move between Opportunity and Proposal. Old follow-ups are auto-closed, the next one is created."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    if opp.stage == data.stage:
        raise HTTPException(status_code=400, detail=f"Opportunity {opportunity_id} is already at {data.stage}")
    by = resolve_user_id(db, data.changed_by_id, opp.owner_id)
    old = opp.stage
    opp.stage = data.stage
    opp.probability = STAGE_PROBABILITY[data.stage]
    record_stage_change(db, opportunity_id=opp.id, from_stage=old, to_stage=data.stage, changed_by_id=by, note=data.note)
    auto_close_open_tasks(db, opportunity_id=opp.id, keep=(CLOSE_DATE_TASK,))  # the close-date reminder stays
    task = create_auto_task(db, stage=data.stage, owner_id=opp.owner_id, record_name=opp.name, opportunity_id=opp.id)
    details = [f"Probability: {opp.probability}%"]
    if data.note:
        details.append(f"Note: {data.note}")
    stage_notice(
        db, kind="Opportunity", stage=data.stage, record_name=opp.name, owner_id=opp.owner_id, actor_id=by,
        opportunity_id=opp.id, task=task, details=details,
        title="Opportunity moved back to Opportunity" if data.stage == "Opportunity" else None,
    )
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


@router.post("/{opportunity_id}/won", response_model=schemas.OpportunityDetail)
def mark_won(opportunity_id: int, data: schemas.MarkWon | None = None, db: Session = Depends(get_db)):
    """Close as Won from any open stage. final_value defaults to the expected value."""
    data = data or schemas.MarkWon()
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    final_value = data.final_value if data.final_value is not None else opp.expected_value
    if final_value is None:
        raise HTTPException(status_code=400, detail="final_value is required (the deal has no expected value)")
    by = resolve_user_id(db, data.changed_by_id, opp.owner_id)
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
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


@router.post("/{opportunity_id}/lost", response_model=schemas.OpportunityDetail)
def mark_lost(opportunity_id: int, data: schemas.MarkLost, db: Session = Depends(get_db)):
    """Close as Lost from any open stage. A lost reason is required."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    ensure_open(opp)
    by = resolve_user_id(db, data.changed_by_id, opp.owner_id)
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
    db.commit()
    db.refresh(opp)
    return opportunity_detail(opp)


@router.get("/{opportunity_id}/history", response_model=list[schemas.StageHistoryOut])
def opportunity_history(opportunity_id: int, db: Session = Depends(get_db)):
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    return [history_out(h) for h in sorted(opp.history, key=lambda h: h.id)]
