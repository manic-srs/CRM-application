"""Task manager APIs: follow-ups with due dates, reminders and priorities.

A task belongs to a lead OR an opportunity, or to neither (a general task) - never both.
Status: Open -> Done (by the user) or Auto-closed (by the system when the record moves on).
"""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.security import acting_user_id, check_owner_change, owner_for_new, require_edit, require_view, visible
from app.models import Lead, Opportunity, Task
from app.serializers import task_out
from app.services import assignment_notice, get_or_404, now, record_link, resolve_user_id, start_of_today

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


@router.get("", response_model=list[schemas.TaskOut])
def list_tasks(
    status_filter: Literal["Open", "Done", "Auto-closed"] | None = Query(None, alias="status"),
    due: Literal["overdue", "today", "upcoming"] | None = Query(
        None, description="overdue = open and due before today; today = open and due today; upcoming = open and due later"
    ),
    owner_id: int | None = Query(None),
    lead_id: int | None = Query(None),
    opportunity_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Tasks, soonest first."""
    query = visible(select(Task), Task)
    if status_filter:
        query = query.where(Task.status == status_filter)
    if owner_id is not None:
        query = query.where(Task.owner_id == owner_id)
    if lead_id is not None:
        query = query.where(Task.lead_id == lead_id)
    if opportunity_id is not None:
        query = query.where(Task.opportunity_id == opportunity_id)
    start = start_of_today()
    end = start + timedelta(days=1)
    if due == "overdue":
        query = query.where(Task.status == "Open", Task.due_date < start)
    elif due == "today":
        query = query.where(Task.status == "Open", Task.due_date >= start, Task.due_date < end)
    elif due == "upcoming":
        query = query.where(Task.status == "Open", Task.due_date >= end)
    return [task_out(t) for t in db.scalars(query.order_by(Task.due_date, Task.id)).all()]


@router.post("", response_model=schemas.TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(data: schemas.TaskCreate, db: Session = Depends(get_db)):
    """Add a follow-up. Link it to a lead OR an opportunity (or neither for a general task)."""
    if data.lead_id is not None and data.opportunity_id is not None:
        raise HTTPException(status_code=400, detail="A task can belong to a lead or an opportunity, not both")
    fallback = None
    if data.lead_id is not None:
        fallback = get_or_404(db, Lead, data.lead_id, "Lead").owner_id
        require_view(fallback, "lead")
    if data.opportunity_id is not None:
        fallback = get_or_404(db, Opportunity, data.opportunity_id, "Opportunity").owner_id
        require_view(fallback, "opportunity")
    # default owner: the related record's owner, else you; only Managers/Admins assign tasks to others
    owner_id = resolve_user_id(db, owner_for_new(data.owner_id if data.owner_id is not None else fallback))
    task = Task(**data.model_dump(exclude={"owner_id", "created_by_id"}), owner_id=owner_id, status="Open", is_auto=False)
    db.add(task)
    db.flush()
    assignment_notice(db, owner_id=owner_id, actor_id=acting_user_id(), kind="Task", name=task.title,
                      link=record_link(lead_id=task.lead_id, opportunity_id=task.opportunity_id))
    db.commit()
    db.refresh(task)
    return task_out(task)


@router.get("/{task_id}", response_model=schemas.TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = get_or_404(db, Task, task_id, "Task")
    require_view(task.owner_id, "task")
    return task_out(task)


@router.put("/{task_id}", response_model=schemas.TaskOut)
def update_task(task_id: int, data: schemas.TaskUpdate, db: Session = Depends(get_db)):
    task = get_or_404(db, Task, task_id, "Task")
    require_edit(task.owner_id, "task")
    changes = data.model_dump(exclude_unset=True)
    changes.pop("changed_by_id", None)
    actor = acting_user_id()
    check_owner_change(task.owner_id, changes.get("owner_id"))
    old_owner = task.owner_id
    for field in ("title", "due_date", "priority"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=400, detail=f"{field} can't be empty")
    if "owner_id" in changes:
        changes["owner_id"] = resolve_user_id(db, changes["owner_id"])
    if "reminder_at" in changes and changes["reminder_at"] != task.reminder_at:
        task.reminder_sent = False  # a new reminder time sends a new reminder
    for field, value in changes.items():
        setattr(task, field, value)
    if task.owner_id != old_owner:
        assignment_notice(db, owner_id=task.owner_id, actor_id=actor, kind="Task", name=task.title,
                          link=record_link(lead_id=task.lead_id, opportunity_id=task.opportunity_id))
    db.commit()
    db.refresh(task)
    return task_out(task)


@router.put("/{task_id}/complete", response_model=schemas.TaskOut)
def complete_task(task_id: int, db: Session = Depends(get_db)):
    """Mark an open task as Done."""
    task = get_or_404(db, Task, task_id, "Task")
    require_edit(task.owner_id, "task")
    if task.status != "Open":
        raise HTTPException(status_code=400, detail=f"Task {task_id} is already {task.status}")
    task.status = "Done"
    task.completed_at = now()
    db.commit()
    db.refresh(task)
    return task_out(task)
