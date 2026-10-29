"""Phase 2 (small items): lead transfer, Admin creates leads, role changes with dates,
demo cancellation, company-only user emails."""
from conftest import login_as

LEAD = {"first_name": "Maria", "last_name": "Lopez", "company": "Bluebird", "email": "maria@bluebird.example", "source": "Website"}


def new_lead(client, **extra):
    res = client.post("/api/leads", json={**LEAD, **extra})
    assert res.status_code == 201, res.text
    return res.json()


# ---------- transfer (items 2, 3, 4, 5) ----------

def test_owner_transfers_own_lead_without_approval_and_history_is_saved(client):
    lead = new_lead(client)  # Ravi (Salesperson) owns it
    res = client.post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 1, "note": "Priya covers this region"})
    assert res.status_code == 200, res.text
    moved = res.json()
    assert moved["owner_id"] == 1 and moved["stage"] == lead["stage"]  # only the owner changes
    t = moved["transfers"][0]
    assert (t["from_user_name"], t["to_user_name"], t["transferred_by_name"]) == ("Ravi Kumar", "Priya Sharma", "Ravi Kumar")
    assert t["transferred_at"] and t["note"] == "Priya covers this region"
    assert moved["created_at"]  # lead generation date
    shown = next(x for x in login_as(client, 1).get("/api/leads").json() if x["id"] == lead["id"])
    assert shown["created_at"] and shown["last_transferred_at"] == t["transferred_at"]  # dates in the list
    login_as(client, 2)
    # the follow-up task moved with it, and Priya was told
    assert {x["owner_id"] for x in moved["tasks"] if x["status"] == "Open"} == {1}
    titles = [n["title"] for n in login_as(client, 1).get("/api/notifications").json()]
    assert "Lead assigned to you" in titles


def test_salesperson_cannot_transfer_someone_elses_lead(client):
    priyas = login_as(client, 1).post("/api/leads", json={**LEAD, "email": "p@x.example"}).json()
    # Ravi can't even see Priya's lead
    assert login_as(client, 2).post(f"/api/leads/{priyas['id']}/transfer", json={"to_user_id": 2}).status_code == 404


def test_admin_transfers_any_lead_and_previous_owner_is_told(client):
    lead = new_lead(client)
    res = login_as(client, 3).post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 1})
    assert res.status_code == 200 and res.json()["transfers"][0]["transferred_by_name"] == "Asha Rao"
    titles = [n["title"] for n in login_as(client, 2).get("/api/notifications").json()]
    assert "Lead transferred" in titles
    log = login_as(client, 3).get("/api/activity-log").json()
    assert any(r["action"] == "Lead reassigned" for r in log)


def test_transfer_checks(client):
    lead = new_lead(client)
    assert client.post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 2}).status_code == 400  # already the owner
    login_as(client, 3).put("/api/users/1", json={"is_active": False})
    assert login_as(client, 2).post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 1}).status_code == 400
    client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Price"})
    assert login_as(client, 3).post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 3}).status_code == 400


def test_admin_can_turn_off_transfer_for_salespeople(client):
    lead = new_lead(client)
    login_as(client, 3).put("/api/permissions", json={"role": "Salesperson", "permission": "transfer_leads", "allowed": False})
    assert login_as(client, 2).post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 1}).status_code == 403


# ---------- Admin creates leads (item 1) ----------

def test_admin_creates_and_edits_leads(client):
    made = login_as(client, 3).post("/api/leads", json={**LEAD, "owner_id": 2})
    assert made.status_code == 201 and made.json()["owner_name"] == "Ravi Kumar"
    assert client.put(f"/api/leads/{made.json()['id']}", json={"title": "CTO"}).json()["title"] == "CTO"


# ---------- roles and access dates (items 6, 7) ----------

def test_role_change_is_dated_logged_and_resets_team_access(client):
    login_as(client, 3)
    client.put("/api/users/2/team-access", json={"team_access": True})
    ravi = next(u for u in client.get("/api/users").json() if u["id"] == 2)
    assert ravi["created_at"] and ravi["access_changed_at"] and ravi["role_changed_at"] is None
    changed = client.put("/api/users/2", json={"role": "Manager"}).json()
    assert changed["role"] == "Manager" and changed["role_changed_at"] and changed["team_access"] is False
    log = client.get("/api/activity-log").json()
    assert log[0]["action"] == "Role changed" and log[0]["details"] == "Salesperson → Manager"
    titles = [n["title"] for n in login_as(client, 2).get("/api/notifications").json()]
    assert "Your role was changed" in titles


# ---------- demo cancellation (item 9) ----------

def test_cancel_demo(client):
    lead = new_lead(client)
    client.put(f"/api/leads/{lead['id']}/stage",
               json={"stage": "Demo", "demo_date": "2026-12-01T11:00:00", "completed_stages": ["Nurturing"]})
    res = client.post(f"/api/leads/{lead['id']}/cancel-demo", json={"reason": "Client travelling"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["stage"] == "Nurturing" and out["demo_date"] is None
    open_titles = [t["title"] for t in out["tasks"] if t["status"] == "Open"]
    assert open_titles == ["Follow-up call - Maria Lopez"]  # demo reminders closed, rebook follow-up created
    assert out["history"][-1]["note"] == "Demo cancelled: Client travelling"
    assert client.post(f"/api/leads/{lead['id']}/cancel-demo").status_code == 400  # no demo any more


# ---------- company emails only (item 19) ----------

def test_only_company_emails_for_users(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "srsconsultinginc.com")
    login_as(client, 3)
    new = {"full_name": "New Person", "password": "Sales2026", "role": "Salesperson"}
    bad = client.post("/api/users", json={**new, "email": "someone@gmail.com"})
    assert bad.status_code == 422 and "@srsconsultinginc.com" in bad.json()["detail"]
    assert client.post("/api/users", json={**new, "email": "New.Person@SRSConsultingInc.com"}).status_code == 201
    assert client.put("/api/users/2", json={"email": "ravi@yahoo.com"}).status_code == 422
    # existing users with other addresses keep working when only their name changes
    assert client.put("/api/users/2", json={"full_name": "Ravi K", "email": "ravi@crm.test"}).status_code == 200


def test_reschedule_demo_instead_of_cancelling(client):
    from datetime import datetime, timedelta
    lead = new_lead(client)
    first = (datetime.now() + timedelta(days=3)).replace(hour=11, minute=0, second=0, microsecond=0)
    client.put(f"/api/leads/{lead['id']}/stage",
               json={"stage": "Demo", "demo_date": first.isoformat(), "completed_stages": ["Nurturing"]})
    new = first + timedelta(days=2, hours=3)
    res = client.post(f"/api/leads/{lead['id']}/cancel-demo", json={"reason": "Client asked", "reschedule_to": new.isoformat()})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["stage"] == "Demo" and out["demo_date"] == new.isoformat()  # still at Demo, new date
    conduct = next(t for t in out["tasks"] if t["status"] == "Open" and t["title"].startswith("Conduct demo"))
    assert conduct["due_date"] == new.isoformat()  # the demo reminder moved
    assert out["history"][-1]["note"].startswith("Demo rescheduled to") and out["history"][-1]["to_stage"] == "Demo"
    titles = [n["title"] for n in client.get("/api/notifications").json()]
    assert "Lead demo rescheduled" in titles
    # a past date is refused
    past = (datetime.now() - timedelta(hours=1)).replace(microsecond=0).isoformat()
    assert client.post(f"/api/leads/{lead['id']}/cancel-demo", json={"reschedule_to": past}).status_code == 400


def test_managers_and_admins_are_told_about_transfers(client, monkeypatch):
    sent = []
    from app import mailer
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append((to, subject, body)))
    lead = new_lead(client)  # Ravi (Salesperson) owns it
    client.post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 1, "note": "Region change"})
    # Priya (Manager) is the new owner: "assigned to you"; Asha (Admin) gets "Lead transferred"
    admin_bell = login_as(client, 3).get("/api/notifications").json()
    assert admin_bell[0]["title"] == "Lead transferred"
    assert "from Ravi Kumar to Priya Sharma by Ravi Kumar" in admin_bell[0]["message"] and "Region change" in admin_bell[0]["message"]
    assert any(to == ["asha@crm.test"] and "Lead transferred" in subject for to, subject, _ in sent)  # emailed too
    # the Admin moves it on: the Manager (previous owner) is told once, not twice
    login_as(client, 3).post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 2})
    priya = [n["title"] for n in login_as(client, 1).get("/api/notifications", params={"unread_only": False}).json()]
    assert priya.count("Lead transferred") == 1
