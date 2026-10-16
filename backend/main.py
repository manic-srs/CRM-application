"""CRM back end - starts the API server.

Run:   uvicorn main:app --reload
Docs:  http://localhost:8000/docs   (see and test every API in the browser)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import models  # noqa: F401  (registers the tables)
from database import Base, engine
from routers import leads

# Creates any missing tables. Fine for development; the MySQL schema lives in database/schema.sql.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="CRM Application API", version="0.1.0")

# Lets the React front end (running on another port) call these APIs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads.router)


@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "message": "CRM API is running. Open /docs to see all APIs."}
