"""Shared business rules used by several APIs.

- record_stage_change:   every stage change is saved in stage_history (who, when, from -> to)
- auto_close_open_tasks: open follow-ups are closed as "Auto-closed" when a record moves on or closes
- create_auto_task:      the system creates the next follow-up for the new stage (is_auto = TRUE)
                         and puts a notification on the owner's bell icon
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.constants import AUTO_TASKS
from app import mailer
from app.models import Notification, StageHistory, Task, User


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def start_of_today() -> datetime:
    """Overdue = due before today (a task due today is "today", not overdue - like Salesforce)."""
    return datetime.combine(date.today(), datetime.min.time())


def get_or_404(db: Session, model, record_id: int, label: str):
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"{label} {record_id} not found")
    return record


def resolve_user_id(db: Session, user_id: int | None, fallback: int | None = None) -> int:
    """Uses the given user, else the fallback (usually the record owner), else the first user."""
    chosen = user_id if user_id is not None else fallback
    if chosen is None:
        chosen = db.scalar(select(User.id).order_by(User.id).limit(1))
        if chosen is None:
            raise HTTPException(status_code=400, detail="No users exist yet")
    if db.get(User, chosen) is None:
        raise HTTPException(status_code=400, detail=f"User {chosen} not found")
    return chosen


def record_stage_change(
    db: Session,
    *,
    lead_id: int | None = None,
    opportunity_id: int | None = None,
    from_stage: str | None,
    to_stage: str,
    changed_by_id: int,
    note: str | None = None,
) -> None:
    db.add(
        StageHistory(
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            from_stage=from_stage,
            to_stage=to_stage,
            changed_by_id=changed_by_id,
            note=note,
        )
    )


def auto_close_open_tasks(db: Session, *, lead_id: int | None = None, opportunity_id: int | None = None) -> int:
    """Closes every Open task of a lead or an opportunity as Auto-closed. Returns how many."""
    query = update(Task).where(Task.status == "Open")
    if lead_id is not None:
        query = query.where(Task.lead_id == lead_id)
    elif opportunity_id is not None:
        query = query.where(Task.opportunity_id == opportunity_id)
    else:
        return 0
    result = db.execute(query.values(status="Auto-closed", completed_at=now()))
    return result.rowcount or 0


def create_auto_task(
    db: Session,
    *,
    stage: str,
    owner_id: int,
    record_name: str,
    lead_id: int | None = None,
    opportunity_id: int | None = None,
    due_date: datetime | None = None,
) -> Task | None:
    """Creates the system follow-up for a stage (see AUTO_TASKS) and notifies the owner."""
    if stage not in AUTO_TASKS:
        return None
    title, days, priority = AUTO_TASKS[stage]
    due = due_date or (now() + timedelta(days=days))
    task = Task(
        title=f"{title} - {record_name}",
        due_date=due,
        reminder_at=due - timedelta(hours=1),
        status="Open",
        priority=priority,
        is_auto=True,
        owner_id=owner_id,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
    )
    db.add(task)
    db.flush()
    notify(
        db,
        owner_id,
        "New follow-up task",
        f"{task.title} (due {due:%d %b %Y %I:%M %p})",
        task_id=task.id,
        link=record_link(lead_id=lead_id, opportunity_id=opportunity_id),
        bell=False,
    )
    return task


def record_link(*, lead_id: int | None = None, opportunity_id: int | None = None) -> str:
    """App page for a record, used by notifications."""
    if lead_id is not None:
        return f"/leads/{lead_id}"
    if opportunity_id is not None:
        return f"/opportunities/{opportunity_id}"
    return "/tasks"


def notify(db: Session, user_id: int, title: str, message: str, *, task_id: int | None = None,
           link: str | None = None, bell: bool = True) -> None:
    """Emails the user (after the save is committed) and keeps a record in notifications.

    bell=False: task alerts. They are saved as already read, so they don't show on the bell
    (the Tasks page and Home already show due and overdue tasks), but the email still goes out.
    """
    db.add(Notification(user_id=user_id, task_id=task_id, title=title, message=message[:500], link=link,
                        is_read=not bell))
    user = db.get(User, user_id)
    if user and user.email:
        mailer.queue(
            db,
            user.email,
            f"[SalesTrack] {title}",
            f"Hi {user.full_name.split()[0]},\n\n{message}\n\nOpen in SalesTrack: {mailer.app_link(link)}\n\n"
            "You get this email because you are the owner in SalesTrack CRM.",
        )


def assignment_notice(db: Session, *, owner_id: int, actor_id: int | None, kind: str, name: str, link: str) -> None:
    """Tells the new owner when someone else assigns a lead, opportunity or task to them."""
    if actor_id is None or actor_id == owner_id:
        return
    actor = db.get(User, actor_id)
    by = f" by {actor.full_name}" if actor else ""
    notify(db, owner_id, f"{kind} assigned to you", f"{kind} \"{name}\" was assigned to you{by}.", link=link)


def task_related(task: Task) -> tuple[str, str | None]:
    """('Lead' | 'Opportunity' | 'General', name of the related record)."""
    if task.lead_id is not None:
        return "Lead", task.lead.name if task.lead else None
    if task.opportunity_id is not None:
        return "Opportunity", task.opportunity.name if task.opportunity else None
    return "General", None
