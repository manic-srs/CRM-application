"""Shared business rules used by several APIs.

- record_stage_change:   every stage change is saved in stage_history (who, when, from -> to)
- auto_close_open_tasks: open follow-ups are closed as "Auto-closed" when a record moves on or closes
- create_auto_task:      the system creates the next follow-up for the new stage (is_auto = TRUE); a stage change
                         the user makes saves the user's new task instead (add_stage_task)
- schedule_demo_tasks / schedule_close_date_task:
                         reminder tasks that follow the demo date and the expected close date
                         (created, moved when the date changes, closed when no longer needed)
- stage_notice:          at every step (lead created, each stage, converted, Discovery, Proposal, Won, Lost)
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
from app.security import owner_for_new


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


# ---------- the user's new task with a stage change (instead of the system follow-up) ----------

def stage_task_owner(db: Session, task, record_owner_id: int) -> int:
    """Who gets a stage change's new task: the record's owner unless the user chose someone; giving it to someone
    else follows the rule of POST /tasks (Reassign owner). Checked before anything is saved."""
    return resolve_user_id(db, owner_for_new(task.owner_id if task.owner_id is not None else record_owner_id))


def add_stage_task(db: Session, task, *, owner_id: int, record_owner_id: int, actor_id: int,
                   lead_id: int | None = None, opportunity_id: int | None = None) -> Task:
    """Saves the user's new task (schemas.StageTask) with the stage change, like a task added by hand: not automatic,
    the reminder as given. The record's owner hears about it in the stage notice; another assignee is told the way
    POST /tasks tells them."""
    new = Task(**task.model_dump(exclude={"owner_id"}), owner_id=owner_id, status="Open", is_auto=False,
               lead_id=lead_id, opportunity_id=opportunity_id)
    db.add(new)
    db.flush()
    if owner_id != record_owner_id:
        assignment_notice(db, owner_id=owner_id, actor_id=actor_id, kind="Task", name=new.title,
                          link=record_link(lead_id=lead_id, opportunity_id=opportunity_id))
    return new


def get_for_update(db: Session, model, record_id: int, label: str):
    """Like get_or_404, but the row stays locked until the save (PostgreSQL), so two stage changes of the same record
    run one after the other: the second one sees the new stage (no second transition, task, notification or email)."""
    record = db.get(model, record_id, with_for_update=True, populate_existing=True)
    if record is None:
        raise HTTPException(status_code=404, detail=f"{label} {record_id} not found")
    return record


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
                          opportunity_id: int | None = None, previous_owner_id: int | None = None) -> list[Task]:
    """When a record gets a new owner, its open follow-ups go with it, so work continues from the same stage:
    the system's tasks (demo, close-date and stage reminders) and every open task the previous owner had on the
    record (their own follow-ups), with the same due dates and reminders. Tasks someone else was given stay theirs.
    Returns the open tasks the new owner now has on the record."""
    on_record = Task.lead_id == lead_id if lead_id is not None else Task.opportunity_id == opportunity_id
    mine = Task.is_auto.is_(True)
    if previous_owner_id is not None:
        mine = mine | (Task.owner_id == previous_owner_id)
    db.execute(update(Task).where(Task.status == "Open", on_record, mine).values(owner_id=owner_id))
    return db.scalars(select(Task).where(Task.status == "Open", on_record, Task.owner_id == owner_id)
                      .order_by(Task.due_date)).all()


def handover_lines(db: Session, *, stage: str, tasks: list[Task], lead_id: int | None = None,
                   opportunity_id: int | None = None) -> list[str]:
    """What the new owner needs to carry on: the stage, the latest stage note and the open tasks with due dates."""
    lines = [f"Stage: {stage} (continue from here; the full history is on the record)."]
    last = db.scalars(select(StageHistory).where(
        StageHistory.lead_id == lead_id if lead_id is not None else StageHistory.opportunity_id == opportunity_id,
        StageHistory.note.is_not(None)).order_by(StageHistory.id.desc()).limit(1)).first()
    if last is not None:
        lines.append(f"Last note: {last.note[:200]}")
    if tasks:
        lines.append(f"Open tasks now yours ({len(tasks)}):")
        lines += [f"- {t.title}, due {t.due_date:%d %b %Y %I:%M %p}" for t in tasks[:8]]
        if len(tasks) > 8:
            lines.append(f"- and {len(tasks) - 8} more")
    else:
        lines.append("No open tasks: add the next follow-up.")
    return lines


def task_line(label: str, task: Task | None) -> list[str]:
    return [f"{label}: {task.title}, due {task.due_date:%d %b %Y %I:%M %p}."] if task is not None else []


# Title of the notification / email subject for each step. Titles start with "Lead" or "Opportunity"
# so the bell shows the matching icon.
STAGE_TITLES = {
    ("Lead", "New"): "Lead moved to New",
    ("Lead", "Unqualified"): "Lead unqualified",
    ("Lead", "Nurturing"): "Lead moved to Nurturing",
    ("Lead", "Revisit"): "Lead moved to Revisit",
    ("Lead", "Demo"): "Lead moved to Demo",
    ("Lead", "Lost"): "Lead lost",
    ("Opportunity", "Opportunity"): "Opportunity created",
    ("Opportunity", "Discovery"): "Opportunity moved to Discovery",
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

# A usable email address (also used by the Apollo lookup)
CUSTOMER_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


# ---------- a lead's email must belong to its company ----------

def website_host(url: str | None) -> str:
    """'https://www.Acme.com/about' -> 'acme.com' ('' when there is no website)."""
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", (url or "").strip().lower()).split("/")[0].split("?")[0].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def email_domain(email: str | None) -> str:
    return (email or "").strip().lower().rpartition("@")[2]


def email_matches_website(email: str | None, website: str | None) -> bool:
    """The email's domain is the company website's domain (or a subdomain of it, either way).
    True when either is missing: nothing to compare."""
    domain, host = email_domain(email), website_host(website)
    if not (email or "").strip() or not domain or not host:
        return True
    return domain == host or domain.endswith("." + host) or host.endswith("." + domain)


# personal mailboxes are never a company lead's email (the requirement: no gmail-like addresses)
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com",
    "pm.me", "gmx.com", "gmx.net", "mail.com", "yandex.com", "yandex.ru", "zohomail.com", "rediffmail.com",
    "tutanota.com", "hey.com", "fastmail.com", "qq.com", "163.com", "126.com",
}
PERSONAL_EMAIL_NAMES = {"gmail", "yahoo", "hotmail", "outlook", "live", "aol", "rediffmail", "ymail"}  # yahoo.co.in...


def is_personal_email(email: str | None) -> bool:
    domain = email_domain(email)
    if not domain:
        return False
    name, _, rest = domain.partition(".")
    return domain in PERSONAL_EMAIL_DOMAINS or (name in PERSONAL_EMAIL_NAMES and len(rest) <= 6)


def email_website_problem(email: str | None, website: str | None) -> str | None:
    """None when the email is on the company website's domain. A personal mailbox (gmail.com...) is refused; another
    company domain is asked about, since some companies email from one domain and host the website on another."""
    if email_matches_website(email, website):
        return None
    if is_personal_email(email):
        return (f"Personal emails (@{email_domain(email)}) aren't allowed for a lead. "
                f"Use the lead's work email, e.g. name@{website_host(website)}.")
    return (f"Please check the email: @{email_domain(email)} doesn't match the company website "
            f"({website_host(website)}). If this email is correct, click Save anyway.")


# ---------- stage order: no skipping ----------

def confirm_skipped(db: Session, *, flow: list[str], current: str, target_index: int, completed: list[str],
                    note: str | None, by: int, lead_id: int | None = None, opportunity_id: int | None = None,
                    what: str, optional: list[str] | tuple = ()) -> str:
    """Checks the stage order before moving forward to flow[target_index] (or past the end: Convert / Won).

    Every required stage between the current one and the target must have been done. A stage that was skipped in
    the CRM must be in `completed` (the salesperson confirms it was done); it is then saved in the stage history.
    Optional stages (e.g. Revisit) may be passed over; they are recorded only when confirmed.
    Returns the stage the record is at after the confirmed stages."""
    start = flow.index(current)
    skipped = [stage for stage in flow[start + 1:target_index] if stage not in optional or stage in completed]
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


def notify_data_owners(db: Session, actor, owner_ids, title: str, what: str, reason: str) -> None:
    """Someone outside a Manager's team (the Admin, another Manager or another team) downloaded records owned by that
    Manager or their team: the Manager is told. Their own team's downloads are in Team Activity instead, and the
    Admin is told about every download separately."""
    owner_ids = {i for i in owner_ids if i is not None}
    if not owner_ids:
        return
    people = db.execute(select(User.id, User.role, User.reports_to_id, User.is_active).where(User.id.in_(owner_ids))).all()
    managers = set()
    for user_id, role, reports_to_id, _ in people:
        if role == "Manager":
            managers.add(user_id)
        elif reports_to_id:
            managers.add(reports_to_id)
    managers.discard(actor.id)
    # the Manager's own team downloading is already in their Team Activity: tell them about everyone else
    managers.discard(db.scalar(select(User.reports_to_id).where(User.id == actor.id)))
    for manager_id in managers:
        manager = db.get(User, manager_id)
        if manager is None or not manager.is_active:
            continue
        notify(db, manager_id, "Your team's data was downloaded",
               f"{actor.full_name} ({actor.role}) downloaded {what}, including records owned by you or your team.\n"
               f"Reason: {reason}", link="/team-activity" if actor.role != "Admin" else None, category="assignment")


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
