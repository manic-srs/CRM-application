"""Automatic tests for Task 1 (Lead APIs) and Task 2 (stage change and Lost).

Run from the backend folder:   pytest -v
Uses a temporary in-memory database, so your real data is never touched.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402

ARJUN = {
    "first_name": "Arjun",
    "last_name": "Mehta",
    "company": "Bright Future Coaching Centre",
    "title": "Owner",
    "email": "arjun@brightfuture.com",
    "phone": "9876543210",
    "lead_source": "Web",
    "description": "Interested in business fibre for 3 branches",
}


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def create(client, **overrides):
    res = client.post("/leads", json={**ARJUN, **overrides})
    assert res.status_code == 201, res.text
    return res.json()


# ---------- Task 1: Lead APIs ----------

def test_create_lead_starts_at_new(client):
    lead = create(client)
    assert lead["id"] > 0
    assert lead["stage"] == "New"
    assert lead["company"] == "Bright Future Coaching Centre"


def test_create_lead_requires_last_name_and_company(client):
    res = client.post("/leads", json={"first_name": "Only"})
    assert res.status_code == 422


def test_list_leads_with_filters_and_search(client):
    create(client)
    other = create(client, first_name="Ramesh", last_name="Reddy", company="Ramesh Tea Stall", email="ramesh@teastall.in")
    client.put(f"/leads/{other['id']}/stage", json={"stage": "Nurturing"})

    all_leads = client.get("/leads").json()
    assert all_leads["total"] == 2

    nurturing = client.get("/leads", params={"stage": "Nurturing"}).json()
    assert nurturing["total"] == 1 and nurturing["items"][0]["last_name"] == "Reddy"

    found = client.get("/leads", params={"search": "bright"}).json()
    assert found["total"] == 1 and found["items"][0]["last_name"] == "Mehta"

    assert client.get("/leads", params={"stage": "Nope"}).status_code == 400


def test_view_lead_and_404(client):
    lead = create(client)
    assert client.get(f"/leads/{lead['id']}").json()["last_name"] == "Mehta"
    assert client.get("/leads/9999").status_code == 404


def test_edit_lead_changes_only_sent_fields(client):
    lead = create(client)
    res = client.put(f"/leads/{lead['id']}", json={"phone": "9000000000"})
    assert res.status_code == 200
    body = res.json()
    assert body["phone"] == "9000000000"
    assert body["company"] == "Bright Future Coaching Centre"
    assert body["stage"] == "New"
    assert client.put(f"/leads/{lead['id']}", json={"company": None}).status_code == 400


# ---------- Task 2: stage change, Lost, history ----------

def test_stage_change_forward_and_manual_correction(client):
    lead = create(client)
    lid = lead["id"]
    assert client.put(f"/leads/{lid}/stage", json={"stage": "Nurturing"}).json()["stage"] == "Nurturing"
    assert client.put(f"/leads/{lid}/stage", json={"stage": "Demo"}).json()["stage"] == "Demo"
    # manual correction back to Nurturing is allowed
    assert client.put(f"/leads/{lid}/stage", json={"stage": "Nurturing"}).json()["stage"] == "Nurturing"
    # same stage again is rejected
    assert client.put(f"/leads/{lid}/stage", json={"stage": "Nurturing"}).status_code == 400


def test_stage_change_rejects_closed_stages(client):
    lead = create(client)
    for stage in ("Lost", "Converted", "Won"):
        assert client.put(f"/leads/{lead['id']}/stage", json={"stage": stage}).status_code == 422


def test_mark_lost_requires_reason(client):
    lead = create(client)
    assert client.post(f"/leads/{lead['id']}/lost", json={}).status_code == 422
    assert client.post(f"/leads/{lead['id']}/lost", json={"lost_reason": "   "}).status_code == 400


def test_mark_lost_at_any_stage_and_stops_there(client):
    lead = create(client)
    lid = lead["id"]
    client.put(f"/leads/{lid}/stage", json={"stage": "Demo"})
    res = client.post(f"/leads/{lid}/lost", json={"lost_reason": "Price too high"})
    assert res.status_code == 200
    assert res.json()["stage"] == "Lost"
    assert res.json()["lost_reason"] == "Price too high"
    # closed: no further stage changes or second Lost
    assert client.put(f"/leads/{lid}/stage", json={"stage": "Nurturing"}).status_code == 400
    assert client.post(f"/leads/{lid}/lost", json={"lost_reason": "Again"}).status_code == 400


def test_history_records_every_change(client):
    lead = create(client)
    lid = lead["id"]
    client.put(f"/leads/{lid}/stage", json={"stage": "Nurturing", "changed_by": None})
    client.post(f"/leads/{lid}/lost", json={"lost_reason": "No coverage in area"})
    history = client.get(f"/leads/{lid}/history").json()
    assert [(h["from_stage"], h["to_stage"]) for h in history] == [
        (None, "New"),
        ("New", "Nurturing"),
        ("Nurturing", "Lost"),
    ]
    assert client.get("/leads/9999/history").status_code == 404
