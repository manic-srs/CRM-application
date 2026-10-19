"""Home page API: everything the dashboard needs in one call.

- summary, pipeline, todays_tasks, won_vs_lost: same as the SQL views in database/home-page-views.sql
- seller_home: the Salesforce "Seller Home" cards (Close Deals, Plan My Accounts,
  Grow Relationships, Build Pipeline, Recent Records)
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
    open_amount = total(Opportunity.expected_value, Opportunity, Opportunity.stage.in_(["Opportunity", "Proposal"]))
    won_amount = total(Opportunity.final_value, Opportunity, Opportunity.stage == "Won")
    lost_amount = total(Opportunity.expected_value, Opportunity, Opportunity.stage == "Lost")

    accounts = db.scalars(owned(select(Account), Account)).all()
    contacts = db.scalars(owned(select(Contact), Contact)).all()
    opps_by_contact: dict[int, list[Task]] = {}
    for opp in db.scalars(select(Opportunity).where(Opportunity.primary_contact_id.is_not(None))).all():
        opps_by_contact.setdefault(opp.primary_contact_id, []).extend(opp.tasks)
    recent_leads = db.scalars(leads_q.where(Lead.created_at >= now() - timedelta(days=30))).all()

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
                "total_pipeline": open_amount + won_amount,
                "open": open_amount,
                "won": won_amount,
                "lost": lost_amount,
            },
            "accounts": {"total": len(accounts), **activity_split([[t for o in a.opportunities for t in o.tasks] for a in accounts])},
            "contacts": {"total": len(contacts), **activity_split([opps_by_contact.get(c.id, []) for c in contacts])},
            "build_pipeline": {
                "leads_last_30_days": len(recent_leads),
                **activity_split([lead.tasks for lead in recent_leads]),
            },
            "recent_records": recent[:8],
        },
    }
