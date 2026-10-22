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
from app.routers import accounts, activity, auth, emails, home, leads, opportunities, tasks

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # With PostgreSQL the tables come from database/schema.sql. Only the local SQLite fallback creates them here.
    if engine.url.get_backend_name() == "sqlite":
        Base.metadata.create_all(bind=engine)
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

for router in (auth.router, emails.router, home.router, leads.router, opportunities.router, tasks.router, accounts.router, activity.router):
    app.include_router(router)


@app.get("/api/health/email", tags=["Health"])
def email_health():
    """Where notification emails go: the Mailpit test inbox or a real mail server (no secrets shown)."""
    return mailer.mode()


@app.post("/api/health/email/test", tags=["Health"])
def send_test_email(data: schemas.TestEmail):
    """Sends one email right away and reports the mail server's answer. Use it to check SMTP settings."""
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
