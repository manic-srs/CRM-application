"""Shared business rules used by several APIs.

- record_stage_change:   every stage change is saved in stage_history (who, when, from -> to)
- auto_close_open_tasks: open follow-ups are closed as "Auto-closed" when a record moves on or closes
- create_auto_task:      the system creates the next follow-up for the new stage (is_auto = TRUE)
- schedule_demo_tasks / schedule_close_date_task:
                         reminder tasks that follow the demo date and the expected close date
                         (created, moved when the date changes, closed when no longer needed)
- stage_notice:          at every step (lead created, Nurturing, Demo, converted, Proposal, Won, Lost)
                         the owner gets a bell notification and an email with the next follow-up task
"""
import re
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import not_, or_, select, update
from sqlalchemy.orm import Session

from app.constants import (
    AUTO_TASKS,
    CLOSE_DATE_NOTICE_DAYS,
    CLOSE_DATE_TASK,
    DEMO_PREP_TASK,
    DEMO_REMINDER_MINUTES,
    WORKDAY_START_HOUR,
)
from app import mailer
from app.models import ActivityLog, Lead, Notification, StageHistory, Task, User


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


def auto_close_open_tasks(db: Session, *, lead_id: int | None = None, opportunity_id: int | None = None,
                          keep: tuple[str, ...] = ()) -> int:
    """Closes every Open task of a lead or an opportunity as Auto-closed. Returns how many.
    keep: system task titles to leave open (e.g. the close-date reminder survives Opportunity <-> Proposal)."""
    query = update(Task).where(Task.status == "Open")
    if keep:
        query = query.where(not_(Task.is_auto.is_(True) & or_(*(Task.title.startswith(f"{t} - ") for t in keep))))
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
    """Creates the system follow-up for a stage (see AUTO_TASKS).
    The owner hears about it in the stage_notice for the same step (one email per step, not two)."""
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
    return task


# ---------- timeline reminders (demo date, close date) ----------

def open_system_task(db: Session, title: str, *, lead_id: int | None = None,
                     opportunity_id: int | None = None) -> Task | None:
    """The open system task of a record whose title starts with "<title> - "."""
    query = select(Task).where(Task.status == "Open", Task.is_auto.is_(True), Task.title.startswith(f"{title} - "))
    query = query.where(Task.lead_id == lead_id) if lead_id is not None else query.where(Task.opportunity_id == opportunity_id)
    return db.scalars(query.order_by(Task.id.desc()).limit(1)).first()


def move_task(task: Task, due: datetime, reminder_at: datetime) -> None:
    """New due time and reminder; the reminder is sent again for the new time."""
    task.due_date = due
    task.reminder_at = reminder_at
    task.reminder_sent = False


def upsert_timeline_task(
    db: Session,
    *,
    title: str,
    record_name: str,
    due: datetime | None,
    owner_id: int,
    description: str,
    priority: str = "High",
    lead_id: int | None = None,
    opportunity_id: int | None = None,
) -> Task | None:
    """Creates or moves a system reminder task. due=None (date gone or already past) closes it instead.
    The reminder fires at the due time."""
    task = open_system_task(db, title, lead_id=lead_id, opportunity_id=opportunity_id)
    if due is None:
        if task is not None:
            task.status, task.completed_at = "Auto-closed", now()
        return None
    if task is None:
        task = Task(title=f"{title} - {record_name}", status="Open", priority=priority, is_auto=True,
                    owner_id=owner_id, lead_id=lead_id, opportunity_id=opportunity_id, due_date=due)
        db.add(task)
    task.description = description
    move_task(task, due, due)
    db.flush()
    return task


def at_workday_start(day: date) -> datetime:
    return datetime.combine(day, time(hour=WORKDAY_START_HOUR))


def schedule_demo_tasks(db: Session, lead) -> Task | None:
    """Keeps a lead's demo reminders in step with lead.demo_date:
    - "Conduct demo" is due at the demo, with a reminder DEMO_REMINDER_MINUTES before it
    - "Prepare for demo" is due at 9 AM the day before (skipped when that time has already passed)
    Returns the prep task, if there is one."""
    demo = lead.demo_date
    conduct = open_system_task(db, AUTO_TASKS["Demo"][0], lead_id=lead.id)
    if conduct is not None and demo is not None:
        move_task(conduct, demo, demo - timedelta(minutes=DEMO_REMINDER_MINUTES))
    prep_due = at_workday_start(demo.date() - timedelta(days=1)) if demo is not None else None
    if prep_due is not None and prep_due <= now():
        prep_due = None
    return upsert_timeline_task(
        db, title=DEMO_PREP_TASK, record_name=lead.name, due=prep_due, owner_id=lead.owner_id, lead_id=lead.id,
        description=f"Demo with {lead.name} ({lead.company}) on {demo:%d %b %Y at %I:%M %p}." if demo else "",
    )


def schedule_close_date_task(db: Session, opp) -> Task | None:
    """Reminder before an open opportunity's expected close date: 9 AM, CLOSE_DATE_NOTICE_DAYS before it,
    or 9 AM on the close date when that is sooner. Closed if the date is removed or already past."""
    close = opp.expected_close_date
    due = None
    if close is not None:
        for candidate in (at_workday_start(close - timedelta(days=CLOSE_DATE_NOTICE_DAYS)), at_workday_start(close)):
            if candidate > now():
                due = candidate
                break
    return upsert_timeline_task(
        db, title=CLOSE_DATE_TASK, record_name=opp.name, due=due, owner_id=opp.owner_id, opportunity_id=opp.id,
        description=f"Expected close date: {close:%d %b %Y}. Update the stage or the close date." if close else "",
    )


def reassign_system_tasks(db: Session, owner_id: int, *, lead_id: int | None = None,
                          opportunity_id: int | None = None) -> None:
    """When a record gets a new owner, its open system tasks (and their reminders) go to the new owner."""
    query = update(Task).where(Task.status == "Open", Task.is_auto.is_(True))
    query = query.where(Task.lead_id == lead_id) if lead_id is not None else query.where(Task.opportunity_id == opportunity_id)
    db.execute(query.values(owner_id=owner_id))


def task_line(label: str, task: Task | None) -> list[str]:
    return [f"{label}: {task.title}, due {task.due_date:%d %b %Y %I:%M %p}."] if task is not None else []


# Title of the notification / email subject for each step. Titles start with "Lead" or "Opportunity"
# so the bell shows the matching icon.
STAGE_TITLES = {
    ("Lead", "New"): "Lead created",
    ("Lead", "Nurturing"): "Lead moved to Nurturing",
    ("Lead", "Demo"): "Lead moved to Demo",
    ("Lead", "Lost"): "Lead lost",
    ("Opportunity", "Opportunity"): "Opportunity created",
    ("Opportunity", "Proposal"): "Opportunity moved to Proposal",
    ("Opportunity", "Won"): "Opportunity won",
    ("Opportunity", "Lost"): "Opportunity lost",
}


def stage_notice(
    db: Session,
    *,
    kind: str,
    stage: str,
    record_name: str,
    owner_id: int,
    actor_id: int | None = None,
    lead_id: int | None = None,
    opportunity_id: int | None = None,
    task: Task | None = None,
    details: list[str] | None = None,
    title: str | None = None,
) -> None:
    """Bell notification + email to the owner after a step in the lifecycle.

    kind: "Lead" or "Opportunity". details: extra lines (demo date, amount, lost reason...).
    task: the follow-up the system just created for this step, if any.
    The email goes out only after the save is committed (see mailer.queue).
    """
    actor = db.get(User, actor_id) if actor_id is not None else None
    title = title or STAGE_TITLES.get((kind, stage), f"{kind} moved to {stage}")
    lines = [f'{kind} "{record_name}" is now at {stage}.']
    if actor:
        lines[0] = f'{kind} "{record_name}" is now at {stage} (by {actor.full_name}).'
    lines += details or []
    if task is not None:
        lines.append(f"Next follow-up: {task.title}, due {task.due_date:%d %b %Y %I:%M %p}.")
    notify(
        db,
        owner_id,
        title,
        "\n".join(lines),
        task_id=task.id if task is not None else None,
        link=record_link(lead_id=lead_id, opportunity_id=opportunity_id),
        category="assignment" if "assigned" in title.lower() else "stage",
    )


# ---------- emails to the customer (the lead / contact), no-reply ----------

CUSTOMER_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def customer_email(db: Session, kind: str, *, to: str | None, first_name: str, owner_id: int,
                   after_proposal: bool = True) -> bool:
    """No-reply email to the customer at the important moments (sent only after the save succeeds):
      welcome  a new lead: their details were received, who will contact them
      won      the deal is won (proposal accepted): thank you, next steps
      lost     the lead / deal is closed: a polite thank-you. The lost reason and notes are internal
               and are never included.
    Returns False when there is no valid email address."""
    if not to or not CUSTOMER_EMAIL_RE.match(to.strip()):
        return False
    company = mailer.company_name()
    owner = db.get(User, owner_id)
    contact = f"{owner.full_name} ({owner.email})"
    subject, text = {
        "welcome": (f"Thank you for your interest in {company}",
                    "We have received your details and created your profile.\n\n"
                    f"{owner.full_name} will contact you soon. If you have any questions, you can reach {contact}."),
        "won": (f"Thank you for choosing {company}",
                "Thank you for accepting our proposal. We're excited to work with you.\n\n"
                f"{owner.full_name} will contact you shortly about the next steps. You can reach {contact} at any time."),
        "lost": (f"Thank you for considering {company}",
                 f"Thank you for taking the time to consider {'our proposal' if after_proposal else 'our services'}. "
                 "We understand this isn't the right time, and we respect your decision.\n\n"
                 f"If anything changes or you'd like to talk again, please contact {contact}. We'd be glad to help."),
    }[kind]
    body = (f"Hi {first_name},\n\n{text}\n\nBest regards,\n{company}\n\n"
            "This is an automatic email. Please don't reply to it.")
    mailer.queue(db, to.strip(), subject, body, sender_name=f"{company} (no-reply)")  # customers see the company
    return True


# ---------- stage order: no skipping ----------

def confirm_skipped(db: Session, *, flow: list[str], current: str, target_index: int, completed: list[str],
                    note: str | None, by: int, lead_id: int | None = None, opportunity_id: int | None = None,
                    what: str) -> str:
    """Checks the stage order before moving forward to flow[target_index] (or past the end: Convert / Won).

    Every stage between the current one and the target must have been done. A stage that was skipped in the CRM
    must be in `completed` (the salesperson confirms it was done); it is then saved in the stage history.
    Returns the stage the record is at after the confirmed stages."""
    start = flow.index(current)
    skipped = flow[start + 1:target_index]
    missing = [stage for stage in skipped if stage not in completed]
    if missing:
        raise HTTPException(status_code=409, detail=(
            f"Complete {' and '.join(missing)} before {what}. Stages can't be skipped; "
            f"if {'they were' if len(missing) > 1 else 'it was'} already done, confirm it."))
    previous = current
    for stage in skipped:
        record_stage_change(db, lead_id=lead_id, opportunity_id=opportunity_id, from_stage=previous, to_stage=stage,
                            changed_by_id=by, note=f"Confirmed as completed{': ' + note if note else ''}")
        previous = stage
    return previous


def record_link(*, lead_id: int | None = None, opportunity_id: int | None = None) -> str:
    """App page for a record, used by notifications."""
    if lead_id is not None:
        return f"/leads/{lead_id}"
    if opportunity_id is not None:
        return f"/opportunities/{opportunity_id}"
    return "/tasks"


# Which user setting decides whether a notification is also emailed (see User.email_*)
EMAIL_SETTING = {"stage": "email_stage_updates", "assignment": "email_assignments", "reminder": "email_reminders"}


def notify(db: Session, user_id: int, title: str, message: str, *, task_id: int | None = None,
           link: str | None = None, bell: bool = True, kind: str = "update", category: str | None = None) -> None:
    """Puts a notification on the user's bell and, if their settings say so, emails it (after the save is committed).

    category: "stage" (lead/deal moved on), "assignment" (assigned to you) or "reminder";
              default: "reminder" for kind="reminder", otherwise "stage".
    bell=False: saved as already read (no badge), the email still follows the settings.
    """
    db.add(Notification(user_id=user_id, task_id=task_id, title=title, message=message[:500], link=link,
                        kind=kind, is_read=not bell))
    user = db.get(User, user_id)
    category = category or ("reminder" if kind == "reminder" else "stage")
    if user and user.email and getattr(user, EMAIL_SETTING[category], True):
        mailer.queue(
            db,
            user.email,
            f"[SalesTrack] {title}",
            f"Hi {user.full_name.split()[0]},\n\n{message}\n\nOpen in SalesTrack: {mailer.app_link(link)}\n\n"
            "You get this email because you are the owner in SalesTrack CRM.",
        )


def touch_lead(db: Session, lead_id: int | None) -> None:
    """Someone worked on the lead (edit, stage, task, note, email...): it leaves the 'not worked yet' uploads."""
    if lead_id is not None:
        db.execute(update(Lead).where(Lead.id == lead_id, Lead.untouched.is_(True)).values(untouched=False))


def log_activity(db: Session, actor_id: int | None, action: str, target: str, details: str | None = None) -> None:
    """Adds a line to the Admin's Activity Log (saved with the rest of the request)."""
    db.add(ActivityLog(actor_id=actor_id, action=action, target=target[:200], details=details))


def assignment_notice(db: Session, *, owner_id: int, actor_id: int | None, kind: str, name: str, link: str) -> None:
    """Tells the new owner when someone else assigns a lead, opportunity or task to them.
    Reassigned leads and opportunities also go in the Admin's Activity Log.
    The bell is personal: only the owner is told, never the whole team."""
    if actor_id is None or actor_id == owner_id:
        return
    actor = db.get(User, actor_id)
    owner = db.get(User, owner_id)
    by = f" by {actor.full_name}" if actor else ""
    notify(db, owner_id, f"{kind} assigned to you", f"{kind} \"{name}\" was assigned to you{by}.", link=link,
           category="assignment")
    if kind in ("Lead", "Opportunity"):
        to = owner.full_name if owner else "another user"
        log_activity(db, actor_id, f"{kind} reassigned", name, f"New owner: {to}")


def task_related(task: Task) -> tuple[str, str | None]:
    """('Lead' | 'Opportunity' | 'General', name of the related record)."""
    if task.lead_id is not None:
        return "Lead", task.lead.name if task.lead else None
    if task.opportunity_id is not None:
        return "Opportunity", task.opportunity.name if task.opportunity else None
    return "General", None
