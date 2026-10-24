"""Notes (call / demo notes), notifications (the bell icon) and the global search box."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import Account, Contact, Lead, Note, Notification, Opportunity, Task
from app.serializers import note_out
from app.security import acting_user, acting_user_id, require_view, visible
from app.services import get_or_404

router = APIRouter(prefix="/api", tags=["Notes, notifications and search"])


# ---------- Notes ----------

@router.get("/notes", response_model=list[schemas.NoteOut])
def list_notes(lead_id: int | None = Query(None), opportunity_id: int | None = Query(None), db: Session = Depends(get_db)):
    query = select(Note)
    if lead_id is not None:
        require_view(get_or_404(db, Lead, lead_id, "Lead").owner_id, "lead")
        query = query.where(Note.lead_id == lead_id)
    if opportunity_id is not None:
        require_view(get_or_404(db, Opportunity, opportunity_id, "Opportunity").owner_id, "opportunity")
        query = query.where(Note.opportunity_id == opportunity_id)
    if lead_id is None and opportunity_id is None and not acting_user().sees_team:
        query = query.where(Note.created_by_id == acting_user_id())
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
    require_view(parent.owner_id, "record")
    note = Note(
        body=data.body,
        created_by_id=acting_user_id(),
        lead_id=data.lead_id,
        opportunity_id=data.opportunity_id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note_out(note)


# ---------- Notifications (bell icon) ----------
# Two kinds:
#   update    stage changes, assignments...: pop up when they arrive; stay in the bell list for BELL_DAYS
#             (read or not); the red badge counts only the unread ones
#   reminder  task / demo / close-date reminders and overdue tasks: stay on the bell until the task is done
BELL_DAYS = 30
BELL_MAX_UPDATES = 50

def bell_items(db: Session, user_id: int) -> list[Notification]:
    since = datetime.now() - timedelta(days=BELL_DAYS)
    updates = db.scalars(select(Notification).where(
        Notification.user_id == user_id, Notification.kind == "update",
        or_(Notification.is_read.is_(False), Notification.created_at >= since))
        .order_by(Notification.id.desc()).limit(BELL_MAX_UPDATES)).all()
    reminders = db.scalars(
        select(Notification).outerjoin(Task, Notification.task_id == Task.id).where(
            Notification.user_id == user_id, Notification.kind == "reminder",
            or_(Task.status == "Open", Notification.task_id.is_(None) & (Notification.created_at >= since)))
        .order_by(Notification.id.desc())
    ).all()
    latest, seen = [], set()
    for item in reminders:  # one reminder per task: the newest
        key = item.task_id or f"n{item.id}"
        if key not in seen:
            seen.add(key)
            latest.append(item)
    items = list(updates) + latest
    return sorted(items, key=lambda n: (n.created_at or datetime.min, n.id), reverse=True)


@router.get("/notifications", response_model=list[schemas.NotificationOut])
def notifications(unread_only: bool = Query(True, description="false = full history"), db: Session = Depends(get_db)):
    """The logged-in user's bell: updates of the last 30 days (read or not) + reminders for open tasks, newest first."""
    me = acting_user_id()
    if unread_only:
        return bell_items(db, me)
    return db.scalars(select(Notification).where(Notification.user_id == me)
                      .order_by(Notification.created_at.desc(), Notification.id.desc())).all()


@router.put("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db)):
    """'Mark all read' on the bell: clears the unread dots and the badge. Nothing is removed from the list."""
    items = db.scalars(select(Notification).where(Notification.user_id == acting_user_id(),
                                                  Notification.is_read.is_(False))).all()
    for item in items:
        item.is_read = True
    db.commit()
    return {"marked": len(items)}


@router.put("/notifications/{notification_id}/read", response_model=schemas.NotificationOut)
def mark_read(notification_id: int, db: Session = Depends(get_db)):
    item = get_or_404(db, Notification, notification_id, "Notification")
    if item.user_id != acting_user_id():
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")
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
    for lead in db.scalars(visible(select(Lead), Lead).where(or_(Lead.name.ilike(like), Lead.company.ilike(like), Lead.email.ilike(like))).limit(20)):
        results.append({"type": "Lead", "id": lead.id, "name": lead.name, "detail": lead.company})
    for opp in db.scalars(visible(select(Opportunity), Opportunity).where(Opportunity.name.ilike(like)).limit(20)):
        results.append({"type": "Opportunity", "id": opp.id, "name": opp.name, "detail": opp.stage})
    for acc in db.scalars(visible(select(Account), Account).where(Account.name.ilike(like)).limit(20)):
        results.append({"type": "Account", "id": acc.id, "name": acc.name, "detail": acc.industry})
    for con in db.scalars(visible(select(Contact), Contact).where(or_(Contact.full_name.ilike(like), Contact.email.ilike(like))).limit(20)):
        results.append({"type": "Contact", "id": con.id, "name": con.full_name, "detail": con.job_title})
    for task in db.scalars(visible(select(Task), Task).where(Task.title.ilike(like)).limit(20)):
        results.append({"type": "Task", "id": task.id, "name": task.title, "detail": task.status})
    return results[:20]
