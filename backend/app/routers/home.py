"""Home page API: everything the dashboard needs in one call.

- summary, pipeline, todays_tasks, won_vs_lost: same as the SQL views in database/home-page-views.sql
- seller_home: the Salesforce "Seller Home" cards (Close Deals, Plan My Accounts,
  Grow Relationships, Build Pipeline, Key Deals, Today's Events, Recent Records)
Pass owner_id to see only one salesperson's records ("owned by me").
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Contact, Lead, Opportunity, Task
from app.serializers import task_out
from app.services import now

router = APIRouter(prefix="/api", tags=["Home"])

PIPELINE = [
    ("New", "leads"), ("Nurturing", "leads"), ("Demo", "leads"),
    ("Opportunity", "opportunities"), ("Proposal", "opportunities"),
    ("Won", "closed deals"), ("Lost", "closed deals"),
]


def this_quarter() -> tuple[date, date]:
    """First day of this quarter and first day of the next one."""
    today = date.today()
    start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    end = date(start.year + (start.month == 10), (start.month + 2) % 12 + 1, 1)
    return start, end


def activity_split(task_lists: list[list[Task]]) -> dict:
    """For each record: upcoming = has an open task due later; past = only past/finished tasks; none = no tasks."""
    current = now()
    split = {"upcoming_activity": 0, "past_activity": 0, "no_activity": 0}
    for tasks in task_lists:
        if any(t.status == "Open" and t.due_date >= current for t in tasks):
            split["upcoming_activity"] += 1
        elif tasks:
            split["past_activity"] += 1
        else:
            split["no_activity"] += 1
    return split


@router.get("/home")
def home_page(owner_id: int | None = Query(None, description="Only this salesperson's records"), db: Session = Depends(get_db)):
    def owned(query, model):
        return query.where(model.owner_id == owner_id) if owner_id is not None else query

    def count(query) -> int:
        return db.scalar(select(func.count()).select_from(query.subquery())) or 0

    def total(column, model, *conditions) -> float:
        query = owned(select(func.coalesce(func.sum(column), 0)).where(*conditions), model)
        return float(db.scalar(query) or 0)

    leads_q = owned(select(Lead), Lead)
    opps_q = owned(select(Opportunity), Opportunity)
    lead_count = {s: count(leads_q.where(Lead.stage == s)) for s in ("New", "Nurturing", "Demo", "Converted", "Lost")}
    opp_count = {s: count(opps_q.where(Opportunity.stage == s)) for s in ("Opportunity", "Proposal", "Won", "Lost")}

    # ----- today's tasks (open, due today or overdue), like v_todays_tasks -----
    tomorrow = datetime.combine(date.today() + timedelta(days=1), datetime.min.time())
    todays = db.scalars(
        owned(select(Task), Task).where(Task.status == "Open", Task.due_date < tomorrow).order_by(Task.due_date)
    ).all()
    todays_tasks = sorted((task_out(t) for t in todays), key=lambda t: (not t.is_overdue, t.due_date))

    # ----- Salesforce Seller Home cards -----
    won_amount = total(Opportunity.final_value, Opportunity, Opportunity.stage == "Won")
    lost_amount = total(Opportunity.expected_value, Opportunity, Opportunity.stage == "Lost")

    # Close Deals: opportunities closing this quarter (open ones by expected close date, closed ones by close date)
    q_start, q_end = this_quarter()
    my_opps = db.scalars(opps_q).all()

    def close_day(o: Opportunity) -> date | None:
        return o.closed_at.date() if o.closed_at else o.expected_close_date

    quarter_opps = [o for o in my_opps if close_day(o) and q_start <= close_day(o) < q_end]

    def amount(stage_names, field="expected_value") -> float:
        return float(sum(getattr(o, field) or 0 for o in quarter_opps if o.stage in stage_names))

    quarter_open = amount(("Opportunity", "Proposal"))
    quarter_won = amount(("Won",), "final_value")
    quarter_lost = amount(("Lost",))
    key_deals = sorted(
        (o for o in my_opps if o.stage in ("Opportunity", "Proposal")),
        key=lambda o: float(o.expected_value or 0), reverse=True,
    )[:5]

    accounts = db.scalars(owned(select(Account), Account)).all()
    contacts = db.scalars(owned(select(Contact), Contact).where(Contact.created_at >= now() - timedelta(days=90))).all()
    opps_by_contact: dict[int, list[Task]] = {}
    for opp in db.scalars(select(Opportunity).where(Opportunity.primary_contact_id.is_not(None))).all():
        opps_by_contact.setdefault(opp.primary_contact_id, []).extend(opp.tasks)
    recent_leads = db.scalars(leads_q.where(Lead.created_at >= now() - timedelta(days=30))).all()

    # Today's Events: demos booked for today
    today_start = datetime.combine(date.today(), datetime.min.time())
    demos = db.scalars(
        leads_q.where(Lead.demo_date >= today_start, Lead.demo_date < tomorrow).order_by(Lead.demo_date)
    ).all()

    recent = []
    for model, kind, label in (
        (Lead, "Lead", lambda r: r.name),
        (Opportunity, "Opportunity", lambda r: r.name),
        (Account, "Account", lambda r: r.name),
        (Contact, "Contact", lambda r: r.full_name),
    ):
        for r in db.scalars(owned(select(model), model).order_by(model.updated_at.desc(), model.id.desc()).limit(5)):
            recent.append({"type": kind, "id": r.id, "name": label(r), "updated_at": r.updated_at})
    recent.sort(key=lambda r: (r["updated_at"] or datetime.min, r["id"]), reverse=True)

    return {
        "summary": {
            "total_leads": sum(lead_count.values()),
            "open_opportunities": opp_count["Opportunity"] + opp_count["Proposal"],
            "won_deals": opp_count["Won"],
            "tasks_due_today": sum(1 for t in todays_tasks if not t.is_overdue),
        },
        "pipeline": [
            {
                "stage": stage,
                "unit": unit,
                "total": (lead_count["Lost"] + opp_count["Lost"]) if stage == "Lost"
                else lead_count.get(stage, opp_count.get(stage, 0)),
            }
            for stage, unit in PIPELINE
        ],
        "todays_tasks": todays_tasks,
        "won_vs_lost": [
            {"outcome": "Won", "deals": opp_count["Won"], "value": won_amount},
            {"outcome": "Lost", "deals": lead_count["Lost"] + opp_count["Lost"], "value": lost_amount},
        ],
        "seller_home": {
            "close_deals": {
                "quarter_start": q_start,
                "total_pipeline": quarter_open + quarter_won,
                "open": quarter_open,
                "won": quarter_won,
                "lost": quarter_lost,
            },
            "key_deals": [
                {"id": o.id, "name": o.name, "account_name": o.account.name if o.account else None, "stage": o.stage,
                 "amount": float(o.expected_value) if o.expected_value is not None else None,
                 "close_date": o.expected_close_date}
                for o in key_deals
            ],
            "todays_events": [
                {"type": "Demo", "lead_id": lead.id, "name": lead.name, "company": lead.company, "start": lead.demo_date}
                for lead in demos
            ],
            "accounts": {"total": len(accounts), **activity_split([[t for o in a.opportunities for t in o.tasks] for a in accounts])},
            "contacts": {"total": len(contacts), **activity_split([opps_by_contact.get(c.id, []) for c in contacts])},
            "build_pipeline": {
                "leads_last_30_days": len(recent_leads),
                **activity_split([lead.tasks for lead in recent_leads]),
            },
            "recent_records": recent[:8],
        },
    }
