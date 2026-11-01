"""Login tokens, roles (Admin / Manager / Salesperson), the bell (updates vs reminders) and email sender.
Users: 1 Priya (Manager), 2 Ravi (Salesperson, default), 3 Asha (Admin)."""
import itertools
from datetime import datetime, timedelta

import pytest

from app import mailer, scheduler
from app.database import get_db
from app.main import app
from app.models import User
from app.security import ensure_default_admin, make_token
from conftest import login_as

TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}  # every stage change needs one


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append({"to": to, "subject": subject, "body": body, **kw}))
    return sent


def db_session():
    return next(app.dependency_overrides[get_db]())


EMAILS = itertools.count(1)


def lead(client, owner_id=None, name="Lopez"):
    body = {"last_name": name, "company": "Bluebird", "email": f"{name.lower().replace(' ', '.')}{next(EMAILS)}@bluebird.example"}
    if owner_id is not None:
        body["owner_id"] = owner_id
    res = client.post("/api/leads", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# ---------- login tokens ----------

def test_every_api_needs_a_valid_token(client):
    for headers in ({}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Bearer " + make_token(99)}):
        client.headers.pop("Authorization", None)
        client.headers.update(headers)
        assert client.get("/api/leads").status_code == 401
        assert client.get("/api/home").status_code == 401
    assert client.get("/api/health/db").status_code == 200  # health check stays open
    assert client.post("/api/auth/login", json={"email": "ravi@crm.test", "password": "Password@123"}).status_code == 200


def test_deactivated_user_is_logged_out(client):
    assert client.get("/api/auth/me").json()["full_name"] == "Ravi Kumar"
    login_as(client, 3).put("/api/users/2", json={"is_active": False})
    assert login_as(client, 2).get("/api/leads").status_code == 401
    assert client.post("/api/auth/login", json={"email": "ravi@crm.test", "password": "Password@123"}).status_code == 403


def test_change_own_password(client):
    assert client.put("/api/auth/password", json={"current_password": "wrong", "new_password": "Better2026"}).status_code == 400
    assert client.put("/api/auth/password", json={"current_password": "Password@123", "new_password": "weakpass"}).status_code == 422
    assert client.put("/api/auth/password", json={"current_password": "Password@123", "new_password": "Better2026"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "ravi@crm.test", "password": "Better2026"}).status_code == 200


def test_default_admin_is_created_once(client, monkeypatch):
    db = db_session()
    assert ensure_default_admin(db) is None  # Asha is already an active Admin
    db.get(User, 3).is_active = False
    db.commit()
    monkeypatch.setenv("ADMIN_EMAIL", "Boss@Company.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "Start2026")
    admin = ensure_default_admin(db)
    assert (admin.email, admin.role) == ("boss@company.com", "Admin")
    assert ensure_default_admin(db) is None
    db.close()
    assert client.post("/api/auth/login", json={"email": "boss@company.com", "password": "Start2026"}).status_code == 200


# ---------- roles ----------

def test_salesperson_sees_and_changes_only_own_records(client):
    priyas = lead(login_as(client, 1), name="Priya Lead")  # Priya's own lead
    login_as(client, 2)
    mine = lead(client, name="Ravi Lead")
    assert mine["owner_name"] == "Ravi Kumar"  # owner defaults to the logged-in user
    # lists, search and Home show only Ravi's records
    assert [l["name"] for l in client.get("/api/leads").json()] == ["Ravi Lead"]
    assert [r["name"] for r in client.get("/api/search", params={"q": "Lead"}).json() if r["type"] == "Lead"] == ["Ravi Lead"]
    assert {t["owner_id"] for t in client.get("/api/tasks").json()} == {2}
    assert client.get("/api/home", params={"owner_id": 1}).json()["summary"]["total_leads"] == 1  # forced to "my records"
    # someone else's record can't be opened or changed
    lid = priyas["id"]
    for method, url, body in (
        ("get", f"/api/leads/{lid}", None),
        ("get", f"/api/leads/{lid}/history", None),
        ("put", f"/api/leads/{lid}", {"title": "CEO"}),
        ("put", f"/api/leads/{lid}/stage", {"stage": "Nurturing", "completed_stages": ["New"], "note": "Synthetic test note", "task": TASK}),
        ("post", f"/api/leads/{lid}/lost", {"lost_reason": "Price", "lost_notes": "Synthetic test note"}),
        ("post", f"/api/leads/{lid}/convert", {"note": "Synthetic test note", "task": TASK}),
        ("get", "/api/notes", None),
    ):
        res = client.request(method.upper(), url, json=body, params={"lead_id": lid} if url == "/api/notes" else None)
        assert res.status_code == 404, (url, res.text)
    assert client.put(f"/api/tasks/{priyas['tasks'][0]['id']}/complete").status_code == 404
    assert client.get("/api/emails", params={"lead_id": lid}).status_code == 404
    # own records work as before; a salesperson can transfer their own lead (Transfer leads) but can't
    # create records for someone else
    assert client.put(f"/api/leads/{mine['id']}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": "Synthetic test note"}).status_code == 200
    assert client.put(f"/api/leads/{mine['id']}", json={"owner_id": 1}).status_code == 200
    assert client.post("/api/leads", json={"last_name": "X", "company": "Y", "owner_id": 1}).status_code == 403
    assert client.post("/api/tasks", json={"title": "T", "due_date": "2026-12-01T10:00:00", "owner_id": 1}).status_code == 403


def test_manager_gives_team_access_to_view_not_edit(client, outbox):
    priyas = lead(login_as(client, 1), name="Priya Lead")
    assert client.put("/api/users/2/team-access", json={"team_access": True}).json()["team_access"] is True
    assert client.put("/api/users/3/team-access", json={"team_access": True}).status_code == 400  # Admin
    login_as(client, 2)
    me = client.get("/api/auth/me").json()
    assert "view_team_records" in me["permissions"] and "edit_team_records" not in me["permissions"]
    assert [l["name"] for l in client.get("/api/leads").json()] == ["Priya Lead"]
    assert client.get(f"/api/leads/{priyas['id']}").status_code == 200
    assert client.put(f"/api/leads/{priyas['id']}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": "Synthetic test note"}).status_code == 403  # view only
    assert client.put("/api/users/2/team-access", json={"team_access": False}).status_code == 403  # Ravi can't grant
    assert "Team access given" in [n["title"] for n in client.get("/api/notifications").json()]
    login_as(client, 1).put("/api/users/2/team-access", json={"team_access": False})
    assert login_as(client, 2).get(f"/api/leads/{priyas['id']}").status_code == 404


def test_roles_and_permissions_matrix(client):
    assert client.get("/api/permissions").status_code == 403  # Salesperson
    assert login_as(client, 1).put("/api/permissions", json={"role": "Salesperson", "permission": "view_team_records",
                                                              "allowed": True}).status_code == 403  # Manager
    login_as(client, 3)
    matrix = client.get("/api/permissions").json()
    rows = {r["key"]: r["roles"] for r in matrix["permissions"]}
    assert rows["view_team_records"]["Salesperson"]["allowed"] is False
    assert rows["view_team_records"]["Manager"]["allowed"] is True
    assert all(r["Admin"]["allowed"] and r["Admin"]["locked"] for r in rows.values())
    assert client.put("/api/permissions", json={"role": "Admin", "permission": "manage_users", "allowed": False}).status_code == 400
    # give every Salesperson the team view
    assert client.put("/api/permissions", json={"role": "Salesperson", "permission": "view_team_records",
                                                "allowed": True}).status_code == 200
    changed = {r["key"]: r["roles"] for r in client.get("/api/permissions").json()["permissions"]}["view_team_records"]
    assert changed["Salesperson"]["allowed"] is True and changed["Salesperson"]["changed_by"] == "Asha Rao"
    lead(login_as(client, 1), name="Priya Lead")
    assert [l["name"] for l in login_as(client, 2).get("/api/leads").json()] == ["Priya Lead"]
    # take reassign away from Managers
    login_as(client, 3).put("/api/permissions", json={"role": "Manager", "permission": "reassign_owner", "allowed": False})
    assert login_as(client, 1).post("/api/leads", json={"last_name": "X", "company": "Y", "owner_id": 2}).status_code == 403


def test_manager_edits_and_transfers_any_lead(client):
    ravis = lead(client)
    login_as(client, 1)
    assert client.put(f"/api/leads/{ravis['id']}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": "Synthetic test note"}).status_code == 200
    # a Manager can transfer any lead they can see (Reassign owner)
    moved = client.post(f"/api/leads/{ravis['id']}/transfer", json={"to_user_id": 1})
    assert moved.status_code == 200 and moved.json()["owner_id"] == 1
    assert client.put(f"/api/leads/{ravis['id']}", json={"owner_id": 2}).json()["owner_id"] == 2
    # the Admin can take it away from Managers on the Permissions page
    login_as(client, 3).put("/api/permissions", json={"role": "Manager", "permission": "reassign_owner", "allowed": False})
    assert login_as(client, 1).post(f"/api/leads/{ravis['id']}/transfer", json={"to_user_id": 1}).status_code == 403
    history = client.get(f"/api/leads/{ravis['id']}/history").json()
    assert history[-1]["changed_by_name"] == "Priya Sharma"  # the real user is recorded, not what the app sends


def test_only_admin_manages_users(client):
    for user_id in (1, 2):
        login_as(client, user_id)
        assert client.put("/api/users/2", json={"role": "Manager"}).status_code == 403
        assert client.put("/api/users/2/password", json={"password": "Reset2026"}).status_code == 403
        assert client.post("/api/users/2/transfer", json={"to_user_id": 1}).status_code == 403
    login_as(client, 3)
    # the Admin can change name, email and role
    assert client.put("/api/users/2", json={"role": "Salesperson", "full_name": "Ravi K"}).json()["full_name"] == "Ravi K"
    assert client.put("/api/users/2/password", json={"password": "Reset2026"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "ravi@crm.test", "password": "Reset2026"}).status_code == 200
    # the Admin can't lock themselves out, and there is always an active Admin
    assert client.put("/api/users/3", json={"role": "Manager"}).status_code == 400
    assert client.put("/api/users/3", json={"is_active": False}).status_code == 400
    # roles can change after creation (item 6); the date and time are saved
    promoted = client.put("/api/users/1", json={"role": "Admin"}).json()
    assert promoted["role"] == "Admin" and promoted["role_changed_at"]
    assert len(client.get("/api/users", params={"include_inactive": True}).json()) == 3


def test_transfer_records_when_someone_leaves(client, outbox):
    open_lead = lead(client, name="Open One")
    lost = lead(client, name="Lost One")
    client.post(f"/api/leads/{lost['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic test note"})
    converted = lead(client, name="Deal One")
    opp = client.post(f"/api/leads/{converted['id']}/convert", json={"task": TASK, "completed_stages": ["New", "Nurturing", "Demo"], "expected_value": 5000, "note": "Synthetic test note"}).json()["opportunity"]

    login_as(client, 3)
    assert client.post("/api/users/2/transfer", json={"to_user_id": 2}).status_code == 400
    res = client.post("/api/users/2/transfer", json={"to_user_id": 1, "deactivate": True}).json()
    assert res["moved"]["leads"] == 1 and res["moved"]["opportunities"] == 1 and res["deactivated"] is True
    assert res["moved"]["accounts"] == 1 and res["moved"]["contacts"] == 1 and res["moved"]["tasks"] >= 2
    assert client.get(f"/api/leads/{open_lead['id']}").json()["owner_id"] == 1
    assert client.get(f"/api/leads/{lost['id']}").json()["owner_id"] == 2  # closed records keep their owner
    assert client.get(f"/api/opportunities/{opp['id']}").json()["owner_id"] == 1
    assert "Ravi Kumar" not in [u["full_name"] for u in client.get("/api/users").json()]
    titles = [n["title"] for n in login_as(client, 1).get("/api/notifications").json()]
    assert "Records assigned to you" in titles


# ---------- bell: updates vanish once seen, reminders stay until the task is done ----------

def test_bell_keeps_read_updates_and_reminders_until_done(client, outbox):
    record = lead(client)
    soon = (datetime.now() + timedelta(hours=2)).replace(microsecond=0)
    task = client.post("/api/tasks", json={"title": "Call back", "due_date": soon.isoformat(), "lead_id": record["id"],
                                            "reminder_at": (datetime.now() - timedelta(minutes=1)).replace(microsecond=0).isoformat()}).json()
    db = db_session()
    scheduler.run_checks(db)
    db.close()
    bell = client.get("/api/notifications").json()
    assert {(n["kind"], n["title"], n["is_read"]) for n in bell} == {("update", "Lead created", False),
                                                                     ("reminder", "Task reminder", False)}
    # Mark all read: the badge clears, but everything stays in the list
    assert client.put("/api/notifications/read-all").json() == {"marked": 2}
    bell = client.get("/api/notifications").json()
    assert {(n["title"], n["is_read"]) for n in bell} == {("Lead created", True), ("Task reminder", True)}
    # a finished task's reminder leaves the bell; the update stays (for 30 days)
    client.put(f"/api/tasks/{task['id']}/complete")
    assert [n["title"] for n in client.get("/api/notifications").json()] == ["Lead created"]


def test_old_read_updates_leave_the_bell(client, outbox):
    lead(client)
    db = db_session()
    from app.models import Notification
    for n in db.query(Notification).all():
        n.created_at = datetime.now() - timedelta(days=31)
    db.commit()
    assert len(client.get("/api/notifications").json()) == 1  # unread: still shown
    client.put("/api/notifications/read-all")
    assert client.get("/api/notifications").json() == []       # read and older than 30 days: gone
    db.close()


def test_notifications_are_private(client, outbox):
    lead(login_as(client, 1))
    note = client.get("/api/notifications").json()[0]
    assert login_as(client, 2).get("/api/notifications").json() == []
    assert client.put(f"/api/notifications/{note['id']}/read").status_code == 404


# ---------- email: sent from the CRM mailbox, replies to the salesperson ----------

def test_email_from_crm_mailbox_with_reply_to(client, outbox, monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "crm@company.com")
    record = lead(client)
    settings = client.get("/api/emails/settings").json()
    assert settings["from_display"] == "Ravi Kumar via SalesTrack <crm@company.com>"
    assert settings["reply_to"] == "ravi@crm.test"
    base = {"to": "maria@bluebird.example", "subject": "Hi", "body": "Hello", "lead_id": str(record["id"])}
    client.post("/api/emails", data=base)
    assert outbox[-1]["sender_name"] == "Ravi Kumar via SalesTrack" and outbox[-1]["reply_to"] == "ravi@crm.test"
    client.post("/api/emails", data={**base, "reply_to": "ravi.personal@example.com"})
    assert outbox[-1]["reply_to"] == "ravi.personal@example.com"
    assert client.post("/api/emails", data={**base, "reply_to": "nope"}).status_code == 422


def test_open_in_outlook_saves_without_sending(client, outbox):
    record = lead(client)
    outbox.clear()
    res = client.post("/api/emails", data={"to": "maria@bluebird.example", "subject": "Hi", "body": "Hello",
                                           "lead_id": str(record["id"]), "open_in": "outlook"}).json()
    assert res["status"] == "Outlook" and outbox == []
    assert client.post("/api/emails", data={"to": "a@b.co", "subject": "Hi", "body": "x", "lead_id": str(record["id"]),
                                            "open_in": "gmail"}).status_code == 422  # Outlook only
    assert client.post("/api/emails", data={"to": "a@b.co", "subject": "Hi", "body": "x", "lead_id": str(record["id"]),
                                            "open_in": "yahoo"}).status_code == 422


def test_outlook_through_microsoft_graph(monkeypatch):
    calls = []

    def fake_post(url, data, headers):
        calls.append((url, data, headers))
        return {"access_token": "tok", "expires_in": 3600} if "oauth2" in url else {}

    monkeypatch.setattr(mailer, "_post_json", fake_post)
    monkeypatch.setattr(mailer, "_graph_token", {"value": "", "expires": 0.0})
    monkeypatch.setenv("MAIL_PROVIDER", "graph")
    monkeypatch.setenv("MAIL_FROM", "crm@company.com")
    for key in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert "MS_TENANT_ID" in mailer.send(["a@b.co"], "Hi", "Hello")
    for key in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET"):
        monkeypatch.setenv(key, "x")
    assert mailer.send(["a@b.co"], "Hi", "Hello", reply_to="ravi@company.com",
                       attachments=[("q.pdf", "application/pdf", b"%PDF")]) is None
    token_call, send_call = calls
    assert "login.microsoftonline.com/x/oauth2" in token_call[0]
    assert send_call[0] == "https://graph.microsoft.com/v1.0/users/crm%40company.com/sendMail"
    assert send_call[2]["Authorization"] == "Bearer tok"
    assert b'"replyTo": [{"emailAddress": {"address": "ravi@company.com"}}]' in send_call[1]
    assert mailer.mode()["mode"] == "real email"


def test_edit_profiles(client):
    # anyone can rename themselves, but not change their email or role
    assert client.put("/api/auth/me", json={"full_name": "  Ravi   K "}).json()["full_name"] == "Ravi K"
    assert client.put("/api/auth/me", json={"full_name": "R"}).status_code == 422
    assert client.put("/api/users/2", json={"email": "x@y.co"}).status_code == 403
    # the Admin edits name and email (the new email is the new username)
    login_as(client, 3)
    assert client.put("/api/users/2", json={"email": "Ravi.Kumar@Company.com"}).json()["email"] == "ravi.kumar@company.com"
    assert client.put("/api/users/2", json={"email": "priya@crm.test"}).status_code == 409
    assert client.put("/api/users/2", json={"email": "nope"}).status_code == 422
    assert client.post("/api/auth/login", json={"email": "ravi.kumar@company.com", "password": "Password@123"}).status_code == 200


def test_new_user_and_password_reset_are_emailed(client, outbox):
    login_as(client, 3)
    client.post("/api/users", json={"full_name": "Samhit E", "email": "samhit@company.com", "password": "Start2026"})
    mail = outbox[-1]
    assert mail["to"] == ["samhit@company.com"] and mail["subject"] == "[SalesTrack] Your account is ready"
    assert "Username: samhit@company.com" in mail["body"] and "Temporary password: Start2026" in mail["body"]
    assert "as Salesperson" in mail["body"]
    client.put("/api/users/2/password", json={"password": "Reset2026"})
    assert outbox[-1]["to"] == ["ravi@crm.test"] and "Temporary password: Reset2026" in outbox[-1]["body"]
    # nothing is sent when the user can't be created
    count = len(outbox)
    assert client.post("/api/users", json={"full_name": "X Y", "email": "samhit@company.com", "password": "Start2026"}).status_code == 409
    assert len(outbox) == count


# ---------- emails to the customer (lead / contact) ----------

def test_customers_are_never_emailed_automatically(client, outbox):
    """The CRM is internal: no welcome, won or lost email goes to a lead or customer. Only salespeople get emails
    (notifications); a salesperson emails a customer from Send Email."""
    lead = client.post("/api/leads", json={"first_name": "Mani", "last_name": "Reddy", "company": "Acme",
                                           "email": "mani.personal@example.com", "welcome_email": True}).json()
    opp = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "completed_stages": ["New", "Nurturing", "Demo"], "expected_value": 1000, "note": "Synthetic test note"}).json()["opportunity"]
    client.post(f"/api/opportunities/{opp['id']}/won", json={"task": TASK, "completed_stages": ["Discovery", "Proposal"], "note": "Synthetic test note", "notify_customer": True})
    other = client.post("/api/leads", json={"first_name": "Tara", "last_name": "N", "company": "Beta",
                                            "email": "tara@example.com"}).json()
    client.post(f"/api/leads/{other['id']}/lost", json={"lost_reason": "No budget", "lost_notes": "cheap client", "notify_customer": True})
    assert not [m for m in outbox if m["to"] != ["ravi@crm.test"]]  # only the salesperson was emailed


def test_customer_emails_can_be_turned_off(client, outbox):
    lead = client.post("/api/leads", json={"last_name": "Quiet", "company": "Q", "email": "q@example.com",
                                           "welcome_email": False}).json()
    client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Price", "notify_customer": False, "lost_notes": "Synthetic test note"})
    no_email = client.post("/api/leads", json={"last_name": "NoMail", "company": "Q"}).json()  # no address: skipped
    client.post(f"/api/leads/{no_email['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic test note"})
    assert not [m for m in outbox if not m["subject"].startswith("[SalesTrack]")]


# ---------- each user picks which notifications also come by email ----------

def test_email_settings(client, outbox):
    me = client.get("/api/auth/me").json()
    assert (me["email_stage_updates"], me["email_assignments"], me["email_reminders"]) == (False, True, True)
    record = lead(client)
    client.put(f"/api/leads/{record['id']}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": "Synthetic test note"})
    assert not [m for m in outbox if m["subject"].startswith("[SalesTrack] Lead")]  # bell only
    assert {n["title"] for n in client.get("/api/notifications").json()} >= {"Lead created", "Lead moved to Nurturing"}
    # assignments are still emailed
    lead(login_as(client, 1), owner_id=2)
    assert [m["subject"] for m in outbox if m["to"] == ["ravi@crm.test"]] == ["[SalesTrack] Lead assigned to you"]
    # turn stage emails on, assignments off
    login_as(client, 2)
    saved = client.put("/api/auth/me", json={"email_stage_updates": True, "email_assignments": False}).json()
    assert (saved["email_stage_updates"], saved["email_assignments"], saved["full_name"]) == (True, False, "Ravi Kumar")
    outbox.clear()
    client.put(f"/api/leads/{record['id']}/stage", json={"task": TASK, "completed_stages": ["New", "Nurturing"], "stage": "Demo", "demo_date": "2026-12-01T10:00:00", "note": "Synthetic test note"})
    assert [m["subject"] for m in outbox if m["to"] == ["ravi@crm.test"]] == ["[SalesTrack] Lead moved to Demo"]
    outbox.clear()
    lead(login_as(client, 1), owner_id=2)
    assert not [m for m in outbox if m["to"] == ["ravi@crm.test"]]


# ---------- duplicate email and stage order ----------

def test_duplicate_email_on_new_lead(client, outbox):
    """Each email belongs to one lead or contact only: no duplicates, whatever the stage (no "returning customer")."""
    first = client.post("/api/leads", json={"last_name": "Reddy", "company": "Styra", "email": "Mani@Example.com"}).json()
    check = client.get("/api/leads/duplicates", params={"email": "mani@example.com"}).json()
    assert check["has_open_lead"] is True and check["matches"][0]["name"] == "Reddy"
    res = client.post("/api/leads", json={"last_name": "Again", "company": "Styra", "email": "mani@example.com"})
    assert res.status_code == 409 and "already in the CRM" in res.json()["detail"] and "Reddy" in res.json()["detail"]
    # still blocked after it is lost, even when the old "confirm" flag is sent
    client.post(f"/api/leads/{first['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic test note"})
    for extra in ({}, {"confirm_duplicate": True}):
        res = client.post("/api/leads", json={"last_name": "Again", "company": "Styra", "email": "MANI@example.com", **extra})
        assert res.status_code == 409
    # changing another lead's email to a taken one is blocked too
    other = client.post("/api/leads", json={"last_name": "Other", "company": "X", "email": "other@example.com"}).json()
    assert client.put(f"/api/leads/{other['id']}", json={"email": "mani@example.com"}).status_code == 409
    assert client.put(f"/api/leads/{other['id']}", json={"email": "other@example.com", "title": "CTO"}).status_code == 200
    # someone else's lead with that email is reported but not described to a salesperson who can't open it
    login_as(client, 1)
    client.post("/api/leads", json={"last_name": "Priya's", "company": "P", "email": "p@example.com"})
    match = login_as(client, 2).get("/api/leads/duplicates", params={"email": "p@example.com"}).json()["matches"][0]
    assert match["owner_name"] == "Priya Sharma" and match["can_open"] is False
    res = client.post("/api/leads", json={"last_name": "Mine", "company": "P", "email": "p@example.com"})
    assert res.status_code == 409 and "a lead, owner Priya Sharma" in res.json()["detail"]


def test_lead_email_must_be_on_the_company_website_domain(client):
    def create(email, website, **extra):
        return client.post("/api/leads", json={"last_name": "Domain", "company": "Acme", "email": email,
                                               "company_website": website, **extra})
    bad = create("asha.personal@gmail.com", "https://www.acme-example.com")
    assert bad.status_code == 400 and "@gmail.com doesn't match the company website (acme-example.com)" in bad.json()["detail"]
    assert create("asha@acme-example.com", "https://www.acme-example.com").status_code == 201
    assert create("ravi@mail.acme-example.com", "acme-example.com").status_code == 201  # a subdomain is fine
    assert create("no-website@other.example", None).status_code == 201  # nothing to compare with
    lead = create("kiran@acme-example.com", "acme-example.com").json()
    assert client.put(f"/api/leads/{lead['id']}", json={"email": "kiran@yahoo.com"}).status_code == 400
    assert client.put(f"/api/leads/{lead['id']}", json={"company_website": "other-example.com"}).status_code == 400
    assert client.put(f"/api/leads/{lead['id']}", json={"email": "kiran@other-example.com",
                                                         "company_website": "other-example.com"}).status_code == 200


def test_stages_cannot_be_skipped(client, outbox):
    record = lead(client)
    lid = record["id"]
    res = client.put(f"/api/leads/{lid}/stage", json={"task": TASK, "stage": "Demo", "note": "Synthetic test note"})
    assert res.status_code == 409 and "Complete New and Nurturing" in res.json()["detail"]
    assert client.post(f"/api/leads/{lid}/convert", json={"task": TASK, "note": "Synthetic test note"}).status_code == 409
    # confirm the skipped stage: saved in the history
    res = client.put(f"/api/leads/{lid}/stage", json={"task": TASK, "stage": "Demo", "completed_stages": ["New", "Nurturing"],
                                                       "completed_note": "Discussed on the first call", "note": "Synthetic test note"})
    assert res.status_code == 200
    history = [(h["from_stage"], h["to_stage"], h["note"]) for h in res.json()["history"]]
    assert history[-2] == ("New", "Nurturing", "Confirmed as completed: Discussed on the first call")
    assert history[-1][:2] == ("Nurturing", "Demo")
    # going back is allowed, and from Demo convert needs nothing more
    opp = client.post(f"/api/leads/{lid}/convert", json={"task": TASK, "expected_value": 1000, "note": "Synthetic test note"}).json()["opportunity"]
    res = client.post(f"/api/opportunities/{opp['id']}/won", json={"task": TASK, "note": "Synthetic test note"})
    assert res.status_code == 409 and "Complete Discovery and Proposal" in res.json()["detail"]
    won = client.post(f"/api/opportunities/{opp['id']}/won", json={"task": TASK, "completed_stages": ["Discovery", "Proposal"], "note": "Synthetic test note"}).json()
    assert won["stage"] == "Won" and [h["to_stage"] for h in won["history"]][-2:] == ["Proposal", "Won"]
    # Lost is allowed from any stage
    other = lead(client, name="Other")
    assert client.post(f"/api/leads/{other['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic test note"}).status_code == 200


def test_admin_creates_leads_but_not_opportunities(client, outbox):
    ravis = lead(client, name="Ravi Lead")
    login_as(client, 3)
    made = client.post("/api/leads", json={"last_name": "Admin", "company": "X", "owner_id": 2})
    assert made.status_code == 201 and made.json()["owner_id"] == 2  # the Admin picks the owner
    assert client.put(f"/api/leads/{ravis['id']}", json={"title": "CTO"}).json()["title"] == "CTO"
    res = client.post(f"/api/leads/{ravis['id']}/convert", json={"task": TASK, "completed_stages": ["New", "Nurturing", "Demo"], "expected_value": 10, "note": "Synthetic test note"})
    assert res.status_code == 403 and "Admins can't create opportunities" in res.json()["detail"]


def test_permission_matrix_has_groups_and_defaults(client):
    matrix = login_as(client, 3).get("/api/permissions").json()
    row = next(p for p in matrix["permissions"] if p["key"] == "send_emails")
    assert row["group"] == "Email" and row["roles"]["Salesperson"]["default"] is True


def test_bell_is_personal_managers_are_not_told_about_team_activity(client, outbox):
    ravis = lead(client, name="Team Deal")
    opp = client.post(f"/api/leads/{ravis['id']}/convert", json={"task": TASK, "completed_stages": ["New", "Nurturing", "Demo"],
                                                                  "expected_value": 900, "note": "Synthetic test note"}).json()["opportunity"]
    client.post(f"/api/opportunities/{opp['id']}/won", json={"task": TASK, "completed_stages": ["Discovery", "Proposal"], "final_value": 900, "note": "Synthetic test note"})
    assert login_as(client, 1).get("/api/notifications").json() == []  # Priya (Manager) owns none of it
    # a lead given to the Manager is his, so he is told
    other = lead(login_as(client, 2), name="Moved Lead")
    login_as(client, 3).put(f"/api/leads/{other['id']}", json={"owner_id": 1})
    titles = [n["title"] for n in login_as(client, 1).get("/api/notifications").json()]
    assert titles == ["Lead assigned to you"]
    assert login_as(client, 3).get("/api/activity-log").json()[0]["action"] == "Lead reassigned"


def test_activity_log_records_admin_changes(client, outbox):
    login_as(client, 3)
    client.post("/api/users", json={"full_name": "New Seller", "email": "new@crm.test", "password": "Sales2026",
                                    "role": "Salesperson"})
    client.put("/api/users/2/team-access", json={"team_access": True})
    client.put("/api/permissions", json={"role": "Salesperson", "permission": "send_emails", "allowed": False})
    log = client.get("/api/activity-log").json()
    assert [r["action"] for r in log[:3]] == ["Permission changed", "Team access given", "User added"]
    assert log[2]["by"] == "Asha Rao" and log[2]["target"] == "New Seller"
    assert login_as(client, 1).get("/api/activity-log").status_code == 403
