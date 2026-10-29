"""Sign up, emails with attachments, and notifications (bell + email to the owner)."""
import itertools
from datetime import datetime, timedelta

import pytest

from app import mailer, scheduler
from app.database import get_db
from app.main import app
from app.models import Task
from conftest import login_as


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


# ---------- no public sign up: the Admin adds users ----------

def test_sign_up_is_gone(client):
    assert client.post("/api/auth/signup", json={"full_name": "X Y", "email": "x@y.co", "password": "Sales2026"}).status_code in (404, 405)


def test_admin_adds_user_who_can_log_in(client):
    new = {"full_name": "  Naga   Mani ", "email": "Naga@Example.com", "password": "Sales2026", "role": "Manager"}
    assert client.post("/api/users", json=new).status_code == 403  # Ravi is a Salesperson
    assert login_as(client, 1).post("/api/users", json=new).status_code == 403  # Priya is a Manager
    res = login_as(client, 3).post("/api/users", json=new)
    assert res.status_code == 201, res.text
    assert (res.json()["full_name"], res.json()["email"], res.json()["role"]) == ("Naga Mani", "naga@example.com", "Manager")
    login = client.post("/api/auth/login", json={"email": "naga@example.com", "password": "Sales2026"}).json()
    assert login["user"]["role"] == "Manager" and login["token"]


def test_add_user_validation(client):
    login_as(client, 3)
    ok = {"full_name": "A Person", "email": "a@b.co", "password": "Sales2026"}
    assert client.post("/api/users", json={**ok, "email": "not-an-email"}).status_code == 422
    assert client.post("/api/users", json={**ok, "password": "short1"}).status_code == 422
    assert client.post("/api/users", json={**ok, "password": "lettersonly"}).status_code == 422
    assert client.post("/api/users", json={**ok, "role": "Owner"}).status_code == 422
    assert client.post("/api/users", json=ok).json()["role"] == "Salesperson"
    assert client.post("/api/users", json={**ok, "email": "A@B.co"}).status_code == 409


# ---------- emails ----------

EMAILS = itertools.count(1)


def new_lead(client, **extra):
    # welcome_email off: these tests count the team's notification emails (customer emails are in test_roles_bell_email)
    body = {"first_name": "Maria", "last_name": "Lopez", "company": "Bluebird", "email": f"maria{next(EMAILS)}@bluebird.example",
            "owner_id": 2, "welcome_email": False, **extra}
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


def test_resend_failed_email_with_its_attachments(client, monkeypatch):
    lead = new_lead(client)
    base = {"to": "maria@bluebird.example", "cc": "boss@bluebird.example", "subject": "Quote", "body": "Hello",
            "sent_by_id": "2", "lead_id": str(lead["id"])}
    monkeypatch.setattr(mailer, "send", lambda *a, **k: "Connection unexpectedly closed")
    failed = client.post("/api/emails", data=base, files=[("files", ("quote.pdf", b"%PDF-1", "application/pdf"))]).json()
    assert failed["status"] == "Failed"
    # still failing: stays Failed with the new error
    assert client.post(f"/api/emails/{failed['id']}/resend").json()["status"] == "Failed"

    calls = []
    monkeypatch.setattr(mailer, "send", lambda *a, **k: calls.append((a, k)))
    sent = client.post(f"/api/emails/{failed['id']}/resend").json()
    assert (sent["status"], sent["error"], sent["id"]) == ("Sent", None, failed["id"])
    (to, subject, body), kwargs = calls[0]
    assert (to, subject, body) == (["maria@bluebird.example"], "Quote", "Hello")
    assert kwargs["cc"] == ["boss@bluebird.example"]
    assert kwargs["attachments"] == [("quote.pdf", "application/pdf", b"%PDF-1")]
    # only one email on the record, and a sent email can't be sent twice
    assert len(client.get("/api/emails", params={"lead_id": lead["id"]}).json()) == 1
    assert client.post(f"/api/emails/{failed['id']}/resend").status_code == 409
    assert client.post("/api/emails/9999/resend").status_code == 404


# ---------- notifications ----------

def test_lead_created_notifies_owner_on_bell_and_email(client, outbox):
    client.put("/api/auth/me", json={"email_stage_updates": True})  # stage emails are off by default
    lead = new_lead(client)
    bell = client.get("/api/notifications", params={"user_id": 2}).json()
    assert len(bell) == 1 and bell[0]["title"] == "Lead created" and bell[0]["link"] == f"/leads/{lead['id']}"
    assert len(outbox) == 1  # one email per step (the follow-up task is inside it)
    mail = outbox[0]
    assert mail["to"] == ["ravi@crm.test"] and mail["subject"] == "[SalesTrack] Lead created"
    assert "Next follow-up: Make first contact - Maria Lopez" in mail["body"]


def test_every_step_sends_one_notification_and_email(client, outbox):
    client.put("/api/auth/me", json={"email_stage_updates": True})  # stage emails are off by default
    lead = new_lead(client)
    lid = lead["id"]
    demo = (datetime.now() + timedelta(days=2)).replace(microsecond=0, second=0).isoformat()
    assert client.put(f"/api/leads/{lid}/stage", json={"stage": "Nurturing"}).status_code == 200
    assert client.put(f"/api/leads/{lid}/stage", json={"completed_stages": ["Nurturing"], "stage": "Demo", "demo_date": demo}).status_code == 200
    opp = client.post(f"/api/leads/{lid}/convert", json={"completed_stages": ["Nurturing", "Demo"], "expected_value": 25000}).json()["opportunity"]
    assert client.put(f"/api/opportunities/{opp['id']}/stage", json={"stage": "Proposal"}).status_code == 200
    assert client.post(f"/api/opportunities/{opp['id']}/won", json={"completed_stages": ["Proposal"], "notify_customer": False}).status_code == 200

    subjects = [m["subject"].removeprefix("[SalesTrack] ") for m in outbox]
    assert subjects == ["Lead created", "Lead moved to Nurturing", "Lead moved to Demo",
                        "Opportunity created", "Opportunity moved to Proposal", "Opportunity won"]
    assert all(m["to"] == ["ravi@crm.test"] for m in outbox)
    assert "Demo date:" in outbox[2]["body"] and "Amount: $25,000.00" in outbox[3]["body"]
    assert "Final amount: $25,000.00" in outbox[5]["body"]
    bell = [n["title"] for n in client.get("/api/notifications", params={"user_id": 2}).json()]
    assert sorted(bell) == sorted(subjects)


def test_lost_steps_notify_owner(client, outbox):
    client.put("/api/auth/me", json={"email_stage_updates": True})  # stage emails are off by default
    lead = new_lead(client)
    client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "No budget", "lost_notes": "Next year", "notify_customer": False})
    assert outbox[-1]["subject"] == "[SalesTrack] Lead lost"
    assert "Reason: No budget" in outbox[-1]["body"] and "Notes: Next year" in outbox[-1]["body"]
    other = new_lead(client, last_name="Diaz")
    opp = client.post(f"/api/leads/{other['id']}/convert", json={"completed_stages": ["Nurturing", "Demo"], "expected_value": 1000}).json()["opportunity"]
    client.post(f"/api/opportunities/{opp['id']}/lost", json={"lost_reason": "Competitor", "notify_customer": False})
    assert outbox[-1]["subject"] == "[SalesTrack] Opportunity lost" and "Reason: Competitor" in outbox[-1]["body"]


def test_assignment_notifies_new_owner(client, outbox):
    lead = new_lead(client)  # Ravi's lead
    login_as(client, 3).put(f"/api/leads/{lead['id']}", json={"owner_id": 1})  # the Admin gives it to Priya
    titles = [n["title"] for n in login_as(client, 1).get("/api/notifications").json()]
    assert "Lead assigned to you" in titles
    outbox.clear()
    login_as(client, 3).put(f"/api/leads/{lead['id']}", json={"owner_id": 2})  # the Admin gives it back to Ravi
    bell = login_as(client, 2).get("/api/notifications").json()
    assert bell[0]["title"] == "Lead assigned to you" and "by Asha Rao" in bell[0]["message"]
    assert any(m["to"] == ["ravi@crm.test"] for m in outbox)
    # setting the owner it already has sends nothing
    before = len(client.get("/api/notifications", params={"user_id": 2, "unread_only": False}).json())
    client.put(f"/api/leads/{lead['id']}", json={"owner_id": 2, "title": "CEO"})
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
    # both are reminders on the bell (they stay until the task is done)
    bell = client.get("/api/notifications").json()
    assert sorted(n["title"] for n in bell) == ["Task overdue", "Task reminder"] and {n["kind"] for n in bell} == {"reminder"}
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
        login_as(client, 1)
        new_lead(client, last_name=name)  # assigned to Ravi by Priya
        login_as(client, 2)
    assert len(client.get("/api/notifications", params={"user_id": 2}).json()) == 2
    assert client.put("/api/notifications/read-all", params={"user_id": 2}).json() == {"marked": 2}
    bell = client.get("/api/notifications", params={"user_id": 2}).json()
    assert len(bell) == 2 and all(n["is_read"] for n in bell)  # still listed, no longer unread


def test_no_email_when_save_fails(client, outbox):
    outbox.clear()
    assert login_as(client, 1).post("/api/leads", json={"last_name": "X", "company": "Y", "owner_id": 99}).status_code == 400
    assert outbox == []


def test_lead_emails_move_to_opportunity_on_convert(client, outbox):
    lead = new_lead(client)
    client.post("/api/emails", data={"to": "maria@bluebird.example", "subject": "Intro", "body": "Hi",
                                     "sent_by_id": "2", "lead_id": str(lead["id"])})
    result = client.post(f"/api/leads/{lead['id']}/convert", json={"completed_stages": ["Nurturing", "Demo"]}).json()
    for field, record in (("opportunity_id", "opportunity"), ("contact_id", "contact"), ("account_id", "account")):
        assert [e["subject"] for e in client.get("/api/emails", params={field: result[record]["id"]}).json()] == ["Intro"]
    assert client.get("/api/emails", params={"lead_id": lead["id"]}).json()[0]["subject"] == "Intro"


def test_demo_reminder_is_sent_before_the_demo(client, outbox):
    lead = new_lead(client)
    demo = (datetime.now() + timedelta(minutes=30)).replace(microsecond=0)  # reminder time (1 hour before) has passed
    client.put(f"/api/leads/{lead['id']}/stage", json={"completed_stages": ["Nurturing"], "stage": "Demo", "demo_date": demo.isoformat()})
    outbox.clear()
    db = db_session()
    assert scheduler.run_checks(db)["reminders"] == 1
    db.close()
    assert outbox[-1]["subject"] == "[SalesTrack] Task reminder" and "Conduct demo - Maria Lopez" in outbox[-1]["body"]


def test_email_health_and_test_email(client, outbox, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("SMTP_PORT", "1025")
    assert client.get("/api/health/email").json()["mode"] == "test inbox"
    assert client.post("/api/health/email/test", json={"to": "me@example.com"}).status_code == 403  # Admin only
    login_as(client, 3)
    res = client.post("/api/health/email/test", json={"to": "me@example.com"})
    assert res.status_code == 200 and outbox[-1]["to"] == ["me@example.com"]
    assert client.post("/api/health/email/test", json={"to": "nope"}).status_code == 422
    monkeypatch.setattr(mailer, "send", lambda *a, **k: "Authentication failed")
    assert client.post("/api/health/email/test", json={"to": "me@example.com"}).status_code == 502


def test_gmail_app_password_spaces_are_removed(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    assert mailer.settings()["password"] == "abcdefghijklmnop"
    monkeypatch.setenv("SMTP_HOST", "smtp.office365.com")
    assert mailer.settings()["password"] == "abcd efgh ijkl mnop"
