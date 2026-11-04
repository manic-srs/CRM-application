"""Accurate numbers for the AI Assistant's statistics and reports: counted in the database (never from a capped list),
over the records the user may see (their own, or the team's with "View team records").

crm_report(period=..., owner_id=...) returns leads, opportunities and tasks figures for a period, plus a snapshot of
what is open right now. Amounts are USD. Rates are percentages with one decimal.
"""
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import LEAD_OPEN_STAGES, LEAD_STAGES, OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES
from app.models import Lead, Opportunity, Task, User
from app.security import acting_user

PERIODS = ["today", "this_week", "last_week", "this_month", "last_month", "this_quarter", "last_quarter",
           "this_year", "last_year", "last_7_days", "last_30_days", "last_90_days", "all_time"]


def period_range(period: str | None, date_from: str | None = None, date_to: str | None = None,
                 today: date | None = None) -> tuple[datetime | None, datetime | None, str]:
    """(start, end, label): start inclusive, end exclusive. Explicit dates win over the period name.
    Periods that run up to now ("today", "this month", "last 30 days"...) have no end, so nothing created today is
    missed, whichever clock (the app's or the database's) stamped it."""
    today = today or date.today()
    if date_from or date_to:
        try:
            start = datetime.combine(date.fromisoformat(date_from[:10]), time()) if date_from else None
            end = datetime.combine(date.fromisoformat(date_to[:10]) + timedelta(days=1), time()) if date_to else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Dates must look like 2026-11-30") from exc
        return start, end, f"{date_from or 'the start'} to {date_to or 'today'}"
    period = period or "all_time"
    if period not in PERIODS:
        raise HTTPException(status_code=400, detail=f"Unknown period. Use one of: {', '.join(PERIODS)}")
    day = lambda d: datetime.combine(d, time())  # noqa: E731
    month_start = today.replace(day=1)
    quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    week_start = today - timedelta(days=today.weekday())
    if period == "all_time":
        return None, None, "all time"
    if period == "today":
        return day(today), None, "today"
    if period == "this_week":
        return day(week_start), None, "this week"
    if period == "last_week":
        return day(week_start - timedelta(days=7)), day(week_start), "last week"
    if period == "this_month":
        return day(month_start), None, f"{today:%B %Y} so far"
    if period == "last_month":
        prev = (month_start - timedelta(days=1)).replace(day=1)
        return day(prev), day(month_start), f"{prev:%B %Y}"
    if period == "this_quarter":
        return day(quarter_start), None, f"Q{(today.month - 1) // 3 + 1} {today.year} so far"
    if period == "last_quarter":
        prev = (quarter_start - timedelta(days=1))
        prev_start = date(prev.year, 3 * ((prev.month - 1) // 3) + 1, 1)
        return day(prev_start), day(quarter_start), f"Q{(prev.month - 1) // 3 + 1} {prev.year}"
    if period == "this_year":
        return day(date(today.year, 1, 1)), None, f"{today.year} so far"
    if period == "last_year":
        return day(date(today.year - 1, 1, 1)), day(date(today.year, 1, 1)), str(today.year - 1)
    days = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90}[period]
    return day(today - timedelta(days=days - 1)), None, f"the last {days} days"


def _scope(query, model, owner_id: int | None):
    me = acting_user()
    if not me.sees_team:
        query = query.where(model.owner_id == me.id)
    if owner_id is not None:
        query = query.where(model.owner_id == owner_id)
    return query


def _between(query, column, start, end):
    if start is not None:
        query = query.where(column >= start)
    if end is not None:
        query = query.where(column < end)
    return query


def _rate(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _money(value) -> float:
    return round(float(value or 0), 2)


def crm_report(db: Session, *, period: str | None = None, date_from: str | None = None, date_to: str | None = None,
               owner_id: int | None = None) -> dict:
    start, end, label = period_range(period, date_from, date_to)
    names = dict(db.execute(select(User.id, User.full_name)).all())

    def count(query) -> int:
        return db.scalar(query) or 0

    def by(column, model, extra=(), when=None):
        query = _scope(select(column, func.count()).select_from(model), model, owner_id)
        for condition in extra:
            query = query.where(condition)
        if when is not None:
            query = _between(query, when, start, end)
        return {(names.get(k, f"User {k}") if column.key == "owner_id" else k): n
                for k, n in db.execute(query.group_by(column)).all()}

    lead_count = lambda *where, when=None: count(  # noqa: E731
        _between(_scope(select(func.count()).select_from(Lead), Lead, owner_id).where(*where), when, start, end)
        if when is not None else _scope(select(func.count()).select_from(Lead), Lead, owner_id).where(*where))

    created = lead_count(when=Lead.created_at)
    converted = lead_count(Lead.converted_at.is_not(None), when=Lead.converted_at)
    leads_lost = lead_count(Lead.stage == "Lost", when=Lead.closed_at)
    unqualified = lead_count(Lead.stage == "Unqualified", when=Lead.closed_at)
    leads = {
        "created_in_period": created,
        "converted_in_period": converted,
        "lost_in_period": leads_lost,
        "unqualified_in_period": unqualified,
        "conversion_rate_pct": _rate(converted, converted + leads_lost + unqualified),
        "created_by_source": by(Lead.source, Lead, when=Lead.created_at),
        "created_by_owner": by(Lead.owner_id, Lead, when=Lead.created_at),
        "open_now_total": lead_count(Lead.stage.in_(LEAD_OPEN_STAGES)),
        "open_now_by_stage": {s: n for s, n in by(Lead.stage, Lead, [Lead.stage.in_(LEAD_OPEN_STAGES)]).items()},
        "all_by_stage": {s: by(Lead.stage, Lead).get(s, 0) for s in LEAD_STAGES},
        "demos_scheduled_ahead": lead_count(Lead.stage == "Demo", Lead.demo_date >= datetime.now()),
    }

    def opp_sum(column, *where, when=None):
        query = _scope(select(func.count(), func.coalesce(func.sum(column), 0)).select_from(Opportunity),
                       Opportunity, owner_id).where(*where)
        if when is not None:
            query = _between(query, when, start, end)
        n, total = db.execute(query).one()
        return n or 0, _money(total)

    won_n, won_value = opp_sum(func.coalesce(Opportunity.final_value, Opportunity.expected_value),
                               Opportunity.stage == "Won", when=Opportunity.closed_at)
    lost_n, lost_value = opp_sum(Opportunity.expected_value, Opportunity.stage == "Lost", when=Opportunity.closed_at)
    new_n, new_value = opp_sum(Opportunity.expected_value, when=Opportunity.created_at)
    open_n, open_value = opp_sum(Opportunity.expected_value, Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES))
    open_by_stage = {}
    for stage in OPPORTUNITY_OPEN_STAGES:
        n, value = opp_sum(Opportunity.expected_value, Opportunity.stage == stage)
        open_by_stage[stage] = {"count": n, "value": value}
    won_by_owner = {}
    query = _between(_scope(select(Opportunity.owner_id, func.count(),
                                   func.coalesce(func.sum(func.coalesce(Opportunity.final_value, Opportunity.expected_value)), 0))
                            .where(Opportunity.stage == "Won"), Opportunity, owner_id), Opportunity.closed_at, start, end)
    for uid, n, value in db.execute(query.group_by(Opportunity.owner_id)).all():
        won_by_owner[names.get(uid, f"User {uid}")] = {"count": n, "value": _money(value)}
    lost_reasons = by(Opportunity.lost_reason, Opportunity, [Opportunity.stage == "Lost"], when=Opportunity.closed_at)
    top_open = db.execute(_scope(select(Opportunity.name, Opportunity.stage, Opportunity.expected_value,
                                        Opportunity.expected_close_date, Opportunity.owner_id)
                                 .where(Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES),
                                        Opportunity.expected_value.is_not(None)), Opportunity, owner_id)
                          .order_by(Opportunity.expected_value.desc()).limit(5)).all()
    closing_soon = count(_scope(select(func.count()).select_from(Opportunity), Opportunity, owner_id).where(
        Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES), Opportunity.expected_close_date >= date.today(),
        Opportunity.expected_close_date <= date.today() + timedelta(days=30)))
    opportunities = {
        "created_in_period": new_n, "created_value": new_value,
        "won_in_period": won_n, "won_value": won_value,
        "lost_in_period": lost_n, "lost_value": lost_value,
        "win_rate_pct": _rate(won_n, won_n + lost_n),
        "average_won_deal": _money(won_value / won_n) if won_n else None,
        "won_by_owner": won_by_owner,
        "lost_reasons": {k or "Not given": v for k, v in lost_reasons.items()},
        "open_now": {"count": open_n, "value": open_value, "by_stage": open_by_stage},
        "open_closing_in_next_30_days": closing_soon,
        "biggest_open_deals": [{"name": n, "stage": s, "amount": _money(v), "close_date": str(c) if c else None,
                                "owner": names.get(o)} for n, s, v, c, o in top_open],
        "all_by_stage": {s: by(Opportunity.stage, Opportunity).get(s, 0) for s in OPPORTUNITY_STAGES},
    }

    task_scope = lambda *where: _scope(select(func.count()).select_from(Task), Task, owner_id).where(*where)  # noqa: E731
    tasks = {
        "open_now": count(task_scope(Task.status == "Open")),
        "overdue_now": count(task_scope(Task.status == "Open", Task.due_date < datetime.now())),
        "due_today": count(task_scope(Task.status == "Open", Task.due_date >= datetime.combine(date.today(), time()),
                                      Task.due_date < datetime.combine(date.today() + timedelta(days=1), time()))),
        "completed_in_period": count(_between(task_scope(Task.status == "Done"), Task.completed_at, start, end)),
    }
    me = acting_user()
    return {
        "period": label, "from": start.date().isoformat() if start else None,
        "to": (end - timedelta(days=1)).date().isoformat() if end else (date.today().isoformat() if start else None),
        "scope": ("the whole team" if me.sees_team else "your own records") +
                 (f", owner {names.get(owner_id)}" if owner_id is not None else ""),
        "currency": "USD", "leads": leads, "opportunities": opportunities, "tasks": tasks,
    }
