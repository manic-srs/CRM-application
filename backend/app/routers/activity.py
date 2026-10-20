"""Notes (call / demo notes), notifications (the bell icon) and the global search box."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import Account, Contact, Lead, Note, Notification, Opportunity, Task
from app.serializers import note_out
from app.services import get_or_404, resolve_user_id

router = APIRouter(prefix="/api", tags=["Notes, notifications and search"])


# ---------- Notes ----------

@router.get("/notes", response_model=list[schemas.NoteOut])
def list_notes(lead_id: int | None = Query(None), opportunity_id: int | None = Query(None), db: Session = Depends(get_db)):
    query = select(Note)
    if lead_id is not None:
        query = query.where(Note.lead_id == lead_id)
    if opportunity_id is not None:
        query = query.where(Note.opportunity_id == opportunity_id)
    return [note_out(n) for n in db.scalars(query.order_by(Note.id.desc())).all()]


@router.post("/notes", response_model=schemas.NoteOut, status_code=status.HTTP_201_CREATED)
def add_note(data: schemas.NoteCreate, db: Session = Depends(get_db)):
    """Add a note to a lead OR an opportunity (exactly one)."""
    if (data.lead_id is None) == (data.opportunity_id is None):
        raise HTTPException(status_code=400, detail="Give exactly one of lead_id or opportunity_id")
    parent = (
        get_or_404(db, Lead, data.lead_id, "Lead")
        if data.lead_id is not None
        else get_or_404(db, Opportunity, data.opportunity_id, "Opportunity")
    )
    note = Note(
        body=data.body,
        created_by_id=resolve_user_id(db, data.created_by_id, parent.owner_id),
        lead_id=data.lead_id,
        opportunity_id=data.opportunity_id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note_out(note)


# ---------- Notifications (bell icon) ----------

@router.get("/notifications", response_model=list[schemas.NotificationOut])
def notifications(
    user_id: int, unread_only: bool = Query(True), db: Session = Depends(get_db)
):
    """Notifications for one user, newest first (user_id comes from login)."""
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    return db.scalars(query.order_by(Notification.created_at.desc(), Notification.id.desc())).all()


@router.put("/notifications/{notification_id}/read", response_model=schemas.NotificationOut)
def mark_read(notification_id: int, db: Session = Depends(get_db)):
    item = get_or_404(db, Notification, notification_id, "Notification")
    item.is_read = True
    db.commit()
    db.refresh(item)
    return item


# ---------- Search ----------

@router.get("/search", response_model=list[schemas.SearchResult])
def search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    """The 'Search...' box: leads, opportunities, accounts, contacts and tasks (up to 20 results)."""
    like = f"%{q.strip()}%"
    results = []
    for lead in db.scalars(select(Lead).where(or_(Lead.name.ilike(like), Lead.company.ilike(like), Lead.email.ilike(like))).limit(20)):
        results.append({"type": "Lead", "id": lead.id, "name": lead.name, "detail": lead.company})
    for opp in db.scalars(select(Opportunity).where(Opportunity.name.ilike(like)).limit(20)):
        results.append({"type": "Opportunity", "id": opp.id, "name": opp.name, "detail": opp.stage})
    for acc in db.scalars(select(Account).where(Account.name.ilike(like)).limit(20)):
        results.append({"type": "Account", "id": acc.id, "name": acc.name, "detail": acc.industry})
    for con in db.scalars(select(Contact).where(or_(Contact.full_name.ilike(like), Contact.email.ilike(like))).limit(20)):
        results.append({"type": "Contact", "id": con.id, "name": con.full_name, "detail": con.job_title})
    for task in db.scalars(select(Task).where(Task.title.ilike(like)).limit(20)):
        results.append({"type": "Task", "id": task.id, "name": task.title, "detail": task.status})
    return results[:20]
