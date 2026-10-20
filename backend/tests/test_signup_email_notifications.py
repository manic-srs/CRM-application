"""Sign up, emails with attachments, and notifications (bell + email to the owner)."""
from datetime import datetime, timedelta

import pytest

from app import mailer, scheduler
from app.database import get_db
from app.main import app
from app.models import Task


@pytest.fixture
def outbox(monkeypatch):
    """Captures emails instead of sending them."""
    sent = []

    def fake_send(to, subject, body, **kw):
        sent.append({"to": to, "subject": subject, "body": body, **kw})
        return None

    monkeypatch.setattr(mailer, "send", fake_send)
    return sent


def db_session():
    return next(app.dependency_overrides[get_db]())


# ---------- sign up ----------

def test_signup_creates_salesperson_and_can_log_in(client):
    res = client.post("/api/auth/signup", json={"full_name": "  Naga   Mani ", "email": "Naga@Example.com", "password": "Sales2026"})
    assert res.status_code == 201, res.text
    user = res.json()["user"]
    assert (user["full_name"], user["email"], user["role"]) == ("Naga Mani", "naga@example.com", "Salesperson")
    assert client.post("/api/auth/login", json={"email": "naga@example.com", "password": "Sales2026"}).status_code == 200


def test_signup_validation(client):
    ok = {"full_name": "A Person", "email": "a@b.co", "password": "Sales2026"}
    assert client.post("/api/auth/signup", json={**ok, "email": "not-an-email"}).status_code == 422
    assert client.post("/api/auth/signup", json={**ok, "password": "short1"}).status_code == 422
    assert client.post("/api/auth/signup", json={**ok, "password": "lettersonly"}).status_code == 422
    assert client.post("/api/auth/signup", json=ok).status_code == 201
    assert client.post("/api/auth/signup", json={**ok, "email": "A@B.co"}).status_code == 409


# ---------- emails ----------

def new_lead(client, **extra):
    body = {"first_name": "Maria", "last_name": "Lopez", "company": "Bluebird", "email": "maria@bluebird.example", "owner_id": 2, **extra}
    res = client.post("/api/leads", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_send_email_with_attachments(client, outbox):
    lead = new_lead(client)
    outbox.clear()
    res = client.post(
        "/api/emails",
        data={"to": "maria@bluebird.example", "cc": "boss@bluebird.example", "subject": "Proposal",
              "body": "Hi Maria, please find the proposal attached.", "sent_by_id": "2", "lead_id": str(lead["id"])},
        files=[("files", ("proposal.pdf", b"%PDF-1.4 test", "application/pdf")),
               ("files", ("pricing.csv", b"item,price\nCRM,100", "text/csv"))],
    )
    assert res.status_code == 201, res.text
    email = res.json()
    assert email["status"] == "Sent" and email["sent_by_name"] == "Ravi Kumar"
    assert [a["filename"] for a in email["attachments"]] == ["proposal.pdf", "pricing.csv"]
    sent = outbox[-1]
    assert sent["to"] == ["maria@bluebird.example"] and sent["cc"] == ["boss@bluebird.example"]
    assert sent["reply_to"] == "ravi@crm.test" and len(sent["attachments"]) == 2

    listed = client.get("/api/emails", params={"lead_id": lead["id"]}).json()
    assert [e["subject"] for e in listed] == ["Proposal"]
    file = client.get(f"/api/emails/attachments/{email['attachments'][0]['id']}")
    assert file.status_code == 200 and file.content == b"%PDF-1.4 test"
    assert "proposal.pdf" in file.headers["content-disposition"]


def test_email_validation_and_failed_send(client, monkeypatch):
    lead = new_lead(client)
    base = {"to": "maria@bluebird.example", "subject": "Hi", "body": "Hello", "sent_by_id": "2", "lead_id": str(lead["id"])}
    assert client.post("/api/emails", data={**base, "to": "nope"}).status_code == 422
    assert client.post("/api/emails", data={k: v for k, v in base.items() if k != "lead_id"}).status_code == 400
    big = ("files", ("big.bin", b"0" * (10 * 1024 * 1024 + 1), "application/octet-stream"))
    assert client.post("/api/emails", data=base, files=[big]).status_code == 413
    monkeypatch.setattr(mailer, "send", lambda *a, **k: "Connection refused")
    failed = client.post("/api/emails", data=base).json()
    assert (failed["status"], failed["error"]) == ("Failed", "Connection refused")


# ---------- notifications ----------

def test_follow_up_task_emails_owner_but_not_on_bell(client, outbox):
    lead = new_lead(client)
    assert client.get("/api/notifications", params={"user_id": 2}).json() == []  # bell: nothing
    log = client.get("/api/notifications", params={"user_id": 2, "unread_only": False}).json()
    assert log[0]["title"] == "New follow-up task" and log[0]["link"] == f"/leads/{lead['id']}"
    assert outbox[-1]["to"] == ["ravi@crm.test"] and "[SalesTrack] New follow-up task" in outbox[-1]["subject"]


def test_assignment_notifies_new_owner(client, outbox):
    lead = new_lead(client, owner_id=1, created_by_id=2)  # Ravi creates a lead for Priya
    titles = [n["title"] for n in client.get("/api/notifications", params={"user_id": 1}).json()]
    assert "Lead assigned to you" in titles
    outbox.clear()
    client.put(f"/api/leads/{lead['id']}", json={"owner_id": 2, "changed_by_id": 1})
    bell = client.get("/api/notifications", params={"user_id": 2}).json()
    assert bell[0]["title"] == "Lead assigned to you" and "by Priya Sharma" in bell[0]["message"]
    assert outbox[-1]["to"] == ["ravi@crm.test"]
    # assigning to yourself sends nothing
    before = len(client.get("/api/notifications", params={"user_id": 2, "unread_only": False}).json())
    client.put(f"/api/leads/{lead['id']}", json={"owner_id": 2, "changed_by_id": 2, "title": "CEO"})
    assert len(client.get("/api/notifications", params={"user_id": 2, "unread_only": False}).json()) == before


def test_reminder_and_overdue_checks(client, outbox):
    soon = (datetime.now() + timedelta(hours=2)).replace(microsecond=0)
    task = client.post("/api/tasks", json={"title": "Call back", "due_date": soon.isoformat(),
                                            "reminder_at": (datetime.now() - timedelta(minutes=1)).replace(microsecond=0).isoformat(),
                                            "owner_id": 2}).json()
    db = db_session()
    late = Task(title="Send contract", due_date=datetime.now() - timedelta(days=3), owner_id=2, status="Open")
    db.add(late)
    db.commit()
    outbox.clear()

    assert scheduler.run_checks(db) == {"reminders": 1, "overdue": 1}
    assert client.get("/api/notifications", params={"user_id": 2}).json() == []  # not on the bell
    titles = [n["title"] for n in client.get("/api/notifications", params={"user_id": 2, "unread_only": False}).json()]
    assert {"Task reminder", "Task overdue"} <= set(titles)
    assert {m["subject"] for m in outbox} == {"[SalesTrack] Task reminder", "[SalesTrack] Task overdue"}
    # second run on the same day: nothing new
    assert scheduler.run_checks(db) == {"reminders": 0, "overdue": 0}
    # a new reminder time sends a new reminder
    client.put(f"/api/tasks/{task['id']}", json={"reminder_at": datetime.now().replace(microsecond=0).isoformat()})
    assert scheduler.run_checks(db)["reminders"] == 1
    db.close()


def test_mark_all_read(client, outbox):
    for name in ("A", "B"):
        new_lead(client, last_name=name, created_by_id=1)  # assigned to Ravi by Priya
    assert len(client.get("/api/notifications", params={"user_id": 2}).json()) == 2
    assert client.put("/api/notifications/read-all", params={"user_id": 2}).json() == {"marked": 2}
    assert client.get("/api/notifications", params={"user_id": 2}).json() == []


def test_no_email_when_save_fails(client, outbox):
    outbox.clear()
    assert client.post("/api/leads", json={"last_name": "X", "company": "Y", "owner_id": 99}).status_code == 400
    assert outbox == []


def test_lead_emails_move_to_opportunity_on_convert(client, outbox):
    lead = new_lead(client)
    client.post("/api/emails", data={"to": "maria@bluebird.example", "subject": "Intro", "body": "Hi",
                                     "sent_by_id": "2", "lead_id": str(lead["id"])})
    result = client.post(f"/api/leads/{lead['id']}/convert", json={}).json()
    for field, record in (("opportunity_id", "opportunity"), ("contact_id", "contact"), ("account_id", "account")):
        assert [e["subject"] for e in client.get("/api/emails", params={field: result[record]["id"]}).json()] == ["Intro"]
    assert client.get("/api/emails", params={"lead_id": lead["id"]}).json()[0]["subject"] == "Intro"
