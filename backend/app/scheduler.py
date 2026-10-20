"""Background checks for task reminders and overdue tasks (runs every minute while the API is up).

- Reminder: when a task's reminder time is reached, the owner gets an email (once).
- Overdue:  once a day, the owner of each open task that is past its due date gets an email.
Task alerts are not shown on the bell: the Tasks page and Home already list due and overdue tasks.
"""
import asyncio
import logging
import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, Task
from app.services import notify, now, record_link, start_of_today

log = logging.getLogger("crm.scheduler")


def run_checks(db: Session) -> dict:
    current = now()
    reminders = db.scalars(
        select(Task).where(Task.status == "Open", Task.reminder_at.is_not(None),
                           Task.reminder_at <= current, Task.reminder_sent.is_(False))
    ).all()
    for task in reminders:
        notify(db, task.owner_id, "Task reminder", f"{task.title} is due {task.due_date:%d %b %Y %I:%M %p}.",
               task_id=task.id, link=record_link(lead_id=task.lead_id, opportunity_id=task.opportunity_id), bell=False)
        task.reminder_sent = True

    today = start_of_today()
    overdue = db.scalars(select(Task).where(Task.status == "Open", Task.due_date < today)).all()
    sent_today = set(db.scalars(
        select(Notification.task_id).where(Notification.title == "Task overdue", Notification.created_at >= today)
    ).all())
    count = 0
    for task in overdue:
        if task.id in sent_today:
            continue
        days = (today.date() - task.due_date.date()).days
        notify(db, task.owner_id, "Task overdue",
               f"{task.title} was due {task.due_date:%d %b %Y} ({days} day{'s' if days != 1 else ''} ago).",
               task_id=task.id, link=record_link(lead_id=task.lead_id, opportunity_id=task.opportunity_id), bell=False)
        count += 1
    db.commit()
    return {"reminders": len(reminders), "overdue": count}


async def loop(session_factory) -> None:
    interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
    while True:
        try:
            def work():
                with session_factory() as db:
                    return run_checks(db)
            result = await asyncio.to_thread(work)
            if any(result.values()):
                log.info("Notifications sent at %s: %s", datetime.now(), result)
        except Exception:  # keep the loop alive; the next run tries again
            log.exception("Reminder check failed")
        await asyncio.sleep(interval)
