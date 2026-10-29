"""CRM API - starts the server.

Run:   uvicorn app.main:app --reload          (from the backend folder)
       or: docker compose up --build          (PostgreSQL + API, data loaded from database/*.sql)
Docs:  http://localhost:8000/docs   (Docker: http://localhost:8001/docs)
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app import mailer, scheduler, schemas
from app.security import authenticate, ensure_default_admin, require_admin
from app.routers import accounts, activity, auth, emails, home, leads, opportunities, tasks, lead_files, opportunity_files

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")


def upgrade_database() -> None:
    """Adds columns that newer versions need to a database created by an older schema.sql (safe to repeat)."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS kind VARCHAR(10) NOT NULL DEFAULT 'update'"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS role_permissions (
            role VARCHAR(20) NOT NULL, permission VARCHAR(40) NOT NULL, allowed BOOLEAN NOT NULL,
            updated_by_id INT REFERENCES users(id), updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (role, permission))"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS activity_log (
            id SERIAL PRIMARY KEY, actor_id INT REFERENCES users(id), action VARCHAR(60) NOT NULL,
            target VARCHAR(200) NOT NULL, details TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"""))
        for column, default in (("email_stage_updates", "FALSE"), ("email_assignments", "TRUE"), ("email_reminders", "TRUE"),
                                ("team_access", "FALSE")):
            conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column} BOOLEAN NOT NULL DEFAULT {default}"))
        for table, column, kind in (
            ("leads", "linkedin_url", "VARCHAR(300)"), ("leads", "company_website", "VARCHAR(255)"),
            ("leads", "company_linkedin_url", "VARCHAR(300)"), ("leads", "annual_revenue", "NUMERIC(16,2)"),
            ("leads", "employees", "INT"), ("leads", "location", "VARCHAR(200)"),
            ("accounts", "linkedin_url", "VARCHAR(300)"), ("accounts", "annual_revenue", "NUMERIC(16,2)"),
            ("accounts", "employees", "INT"), ("contacts", "linkedin_url", "VARCHAR(300)"),
            ("leads", "untouched", "BOOLEAN NOT NULL DEFAULT FALSE"), ("leads", "uploaded_from", "VARCHAR(255)"),
        ):
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind}"))
        # 'Upload' lead source for leads created by a bulk upload
        conn.execute(text("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_source_check"))
        conn.execute(text("ALTER TABLE leads ADD CONSTRAINT leads_source_check CHECK (source IN "
                          "('Website','Referral','Phone','Email','Event','Social Media','Other','Upload'))"))
        # leads uploaded before 'uploaded_from' existed: take the file name from their first stage history note
        conn.execute(text("""UPDATE leads l SET uploaded_from = SUBSTRING(h.note FROM 15) FROM stage_history h
            WHERE h.lead_id = l.id AND h.from_stage IS NULL AND h.note LIKE 'Uploaded from %' AND l.uploaded_from IS NULL"""))
        conn.execute(text("UPDATE leads SET source = 'Upload' WHERE uploaded_from IS NOT NULL AND source = 'Other'"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_leads_untouched ON leads (owner_id, created_at DESC) WHERE untouched"))
        conn.execute(text("ALTER TABLE emails DROP CONSTRAINT IF EXISTS emails_status_check"))
        conn.execute(text("ALTER TABLE emails ADD CONSTRAINT emails_status_check "
                          "CHECK (status IN ('Sent','Failed','Gmail','Outlook'))"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # With PostgreSQL the tables come from database/schema.sql. Only the local SQLite fallback creates them here.
    if engine.url.get_backend_name() == "sqlite":
        Base.metadata.create_all(bind=engine)
    else:
        upgrade_database()
    with SessionLocal() as db:
        ensure_default_admin(db)  # first start: the Admin who adds everyone else
    # Task reminders and overdue alerts (set CHECK_INTERVAL_SECONDS=0 to turn off)
    checker = None
    if int(os.getenv("CHECK_INTERVAL_SECONDS", "60")) > 0:
        checker = asyncio.create_task(scheduler.loop(SessionLocal))
    yield
    if checker:
        checker.cancel()


app = FastAPI(title="CRM API", version="1.0.0", lifespan=lifespan)

# Allow the React app to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:5173"), "http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Login is open; every other API needs the token from login (see app/security.py)
app.include_router(auth.router)
app.include_router(auth.protected)
for router in (emails.router, home.router, lead_files.router, leads.router, opportunity_files.router, opportunities.router, tasks.router, accounts.router, activity.router):
    app.include_router(router, dependencies=[Depends(authenticate)])


@app.get("/api/health/email", tags=["Health"], dependencies=[Depends(authenticate)])
def email_health():
    """Where notification emails go: the Mailpit test inbox or a real mail server (no secrets shown)."""
    return mailer.mode()


@app.post("/api/health/email/test", tags=["Health"], dependencies=[Depends(authenticate)])
def send_test_email(data: schemas.TestEmail):
    """Admin: sends one email right away and reports the mail server's answer. Use it to check SMTP settings."""
    require_admin("send test emails")
    error = mailer.send([data.to], "[SalesTrack] Test email",
                        "This is a test email from SalesTrack CRM.\n\nIf you can read this, notification emails work.")
    if error:
        raise HTTPException(status_code=502, detail=f"Email not sent: {error}")
    return {"sent": True, "to": data.to, **mailer.mode()}


@app.get("/api/health/db", tags=["Health"])
def db_health(db: Session = Depends(get_db)):
    """Check the database connection."""
    db.execute(text("SELECT 1"))
    return {"database": "connected"}
