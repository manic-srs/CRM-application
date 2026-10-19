"""CRM API - starts the server.

Run:   uvicorn app.main:app --reload          (from the backend folder)
       or: docker compose up --build          (PostgreSQL + API, data loaded from database/*.sql)
Docs:  http://localhost:8000/docs   (Docker: http://localhost:8001/docs)
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import models
from app.database import Base, SessionLocal, engine, get_db
from app.routers import accounts, activity, auth, home, leads, opportunities, tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # With PostgreSQL the tables come from database/schema.sql. Only the local SQLite fallback creates them here.
    if engine.url.get_backend_name() == "sqlite":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            if db.scalar(select(models.User.id).limit(1)) is None:
                db.add(models.User(full_name="Demo User", email="demo@crm.test", role="Manager",
                                   password_hash=auth.hash_password("Password@123")))
                db.commit()
    yield


app = FastAPI(title="CRM API", version="1.0.0", lifespan=lifespan)

# Allow the React app to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:5173"), "http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth.router, home.router, leads.router, opportunities.router, tasks.router, accounts.router, activity.router):
    app.include_router(router)


@app.get("/api/health/db", tags=["Health"])
def db_health(db: Session = Depends(get_db)):
    """Check the database connection."""
    db.execute(text("SELECT 1"))
    return {"database": "connected"}
