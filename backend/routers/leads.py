"""Lead APIs.

Task 1 - Lead APIs:          create, list, view, edit
Task 2 - Stage and Lost:     change stage (New / Nurturing / Demo), Mark as Lost, stage history
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from database import get_db
from models import LEAD_CLOSED_STAGES, LEAD_STAGES, Lead, StageHistory
from schemas import LeadCreate, LeadList, LeadOut, LeadUpdate, MarkLost, StageChange, StageHistoryOut

router = APIRouter(prefix="/leads", tags=["Leads"])


# ---------- helpers ----------

def get_lead_or_404(db: Session, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    return lead


def ensure_open(lead: Lead):
    """Converted and Lost leads are closed: their stage can't change any more."""
    if lead.stage in LEAD_CLOSED_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Lead {lead.id} is {lead.stage} (closed); its stage can't be changed",
        )


def record_stage_change(db: Session, lead: Lead, from_stage: str | None, to_stage: str, changed_by: int | None):
    db.add(
        StageHistory(
            record_type="lead",
            record_id=lead.id,
            from_stage=from_stage,
            to_stage=to_stage,
            changed_by=changed_by,
        )
    )
    # Day 2: auto-complete this lead's open tasks here (business rule 7).


# ---------- Task 1: Lead APIs ----------

@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(data: LeadCreate, db: Session = Depends(get_db)):
    """Create a lead. Every new lead starts at stage New."""
    lead = Lead(**data.model_dump(), stage="New")
    db.add(lead)
    db.flush()  # gives the lead its id
    record_stage_change(db, lead, None, "New", data.owner_id)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("", response_model=LeadList)
def list_leads(
    stage: str | None = Query(None, description="Filter by stage, e.g. Nurturing"),
    owner_id: int | None = Query(None, description="Filter by salesperson"),
    search: str | None = Query(None, description="Search name, company or email"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List leads, newest first, with optional filters."""
    if stage is not None and stage not in LEAD_STAGES:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'. Use one of: {', '.join(LEAD_STAGES)}")

    query = select(Lead)
    if stage:
        query = query.where(Lead.stage == stage)
    if owner_id is not None:
        query = query.where(Lead.owner_id == owner_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.where(
            or_(
                Lead.first_name.ilike(like),
                Lead.last_name.ilike(like),
                Lead.company.ilike(like),
                Lead.email.ilike(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Lead.created_at.desc(), Lead.id.desc()).offset(skip).limit(limit)).all()
    return {"total": total, "items": items}


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """View one lead."""
    return get_lead_or_404(db, lead_id)


@router.put("/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, data: LeadUpdate, db: Session = Depends(get_db)):
    """Edit a lead's details. Only the fields sent are changed."""
    lead = get_lead_or_404(db, lead_id)
    changes = data.model_dump(exclude_unset=True)
    for field in ("last_name", "company"):  # required fields can't be cleared
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=400, detail=f"{field} can't be empty")
    for field, value in changes.items():
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead


# ---------- Task 2: Stage change, Mark as Lost, history ----------

@router.put("/{lead_id}/stage", response_model=LeadOut)
def change_stage(lead_id: int, data: StageChange, db: Session = Depends(get_db)):
    """Move a lead to New, Nurturing or Demo. Also used to correct a wrong stage manually."""
    lead = get_lead_or_404(db, lead_id)
    ensure_open(lead)
    if lead.stage == data.stage:
        raise HTTPException(status_code=400, detail=f"Lead {lead_id} is already at {data.stage}")

    old_stage = lead.stage
    lead.stage = data.stage
    record_stage_change(db, lead, old_stage, data.stage, data.changed_by)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/lost", response_model=LeadOut)
def mark_lost(lead_id: int, data: MarkLost, db: Session = Depends(get_db)):
    """Mark a lead as Lost from any open stage. A Lost Reason is required."""
    lead = get_lead_or_404(db, lead_id)
    ensure_open(lead)
    reason = data.lost_reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="lost_reason is required")

    old_stage = lead.stage
    lead.stage = "Lost"
    lead.lost_reason = reason
    record_stage_change(db, lead, old_stage, "Lost", data.changed_by)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/{lead_id}/history", response_model=list[StageHistoryOut])
def lead_history(lead_id: int, db: Session = Depends(get_db)):
    """All stage changes of a lead, oldest first."""
    get_lead_or_404(db, lead_id)
    return db.scalars(
        select(StageHistory)
        .where(StageHistory.record_type == "lead", StageHistory.record_id == lead_id)
        .order_by(StageHistory.changed_at, StageHistory.id)
    ).all()
