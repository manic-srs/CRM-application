import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lead, Notification, Opportunity, Task

app = FastAPI(title="CRM API")

# Allow the React app to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:5173"), "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health/db")
def db_health(db: Session = Depends(get_db)):
    """Check the MySQL connection."""
    db.execute(text("SELECT 1"))
    return {"database": "connected"}


@app.get("/api/leads")
def list_leads(db: Session = Depends(get_db)):
    leads = db.scalars(select(Lead).order_by(Lead.id)).all()
    return [
        {"id": l.id, "name": l.name, "company": l.company, "stage": l.stage,
         "source": l.source, "owner": l.owner.full_name}
        for l in leads
    ]


@app.get("/api/opportunities")
def list_opportunities(db: Session = Depends(get_db)):
    opps = db.scalars(select(Opportunity).order_by(Opportunity.id)).all()
    return [
        {"id": o.id, "name": o.name, "stage": o.stage, "expected_value": o.expected_value,
         "final_value": o.final_value, "account": o.account.name,
         "contact": o.primary_contact.full_name if o.primary_contact else None,
         "owner": o.owner.full_name}
        for o in opps
    ]


@app.get("/api/tasks")
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.scalars(select(Task).order_by(Task.due_date)).all()
    return [
        {"id": t.id, "title": t.title, "status": t.status, "due_date": t.due_date,
         "related_to": t.lead.name if t.lead else (t.opportunity.name if t.opportunity else None),
         "related_type": "Lead" if t.lead_id else ("Opportunity" if t.opportunity_id else "General"),
         "owner": t.owner.full_name}
        for t in tasks
    ]


def rows(db: Session, sql: str, **params):
    """Run a query and return a list of dicts (JSON-ready)."""
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


@app.get("/api/home")
def home_page(db: Session = Depends(get_db)):
    """Everything the Home page (Sales Overview) needs, in one call."""
    return {
        "summary": rows(db, "SELECT * FROM v_home_summary")[0],
        "pipeline": rows(db, "SELECT stage, unit, total FROM v_sales_pipeline ORDER BY sort_order"),
        "todays_tasks": rows(db, "SELECT * FROM v_todays_tasks ORDER BY is_overdue DESC, due_date"),
        "won_vs_lost": rows(db, "SELECT * FROM v_won_vs_lost"),
    }


@app.get("/api/search")
def search(q: str, db: Session = Depends(get_db)):
    """The 'Search anything...' box: leads, opportunities and tasks."""
    return rows(db, """
        SELECT 'Lead' AS type, id, name, company AS detail FROM leads
          WHERE name LIKE :p OR company LIKE :p OR email LIKE :p
        UNION ALL
        SELECT 'Opportunity', id, name, stage FROM opportunities WHERE name LIKE :p
        UNION ALL
        SELECT 'Task', id, title, status FROM tasks WHERE title LIKE :p
        LIMIT 20""", p=f"%{q}%")


@app.get("/api/notifications")
def notifications(user_id: int, db: Session = Depends(get_db)):
    """The bell icon: unread notifications for one user (user_id comes from login later)."""
    items = db.scalars(
        select(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .order_by(Notification.created_at.desc())
    ).all()
    return [{"id": n.id, "title": n.title, "message": n.message, "created_at": n.created_at} for n in items]