"""A Manager's team (Reports To): Managers add and deactivate their own Salespeople, see only their team's activity,
and are told when someone else downloads their team's data. The Admin sees everything. All data is made up."""
import pytest
from conftest import login_as

from app import mailer

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin
PASSWORD = "Synthetic@2026"


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append({"to": to, "subject": subject}))
    return sent


def add_user(client, name, email, role="Salesperson", **extra):
    return client.post("/api/users", json={"full_name": name, "email": email, "password": PASSWORD, "role": role, **extra})


def activity(client, **params):
    res = client.get("/api/activity", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_manager_adds_a_salesperson_to_their_own_team(client, outbox):
    res = add_user(login_as(client, PRIYA), "Kiran Rao", "kiran@crm.test")
    assert res.status_code == 201, res.text
    kiran = res.json()
    assert (kiran["role"], kiran["reports_to_id"], kiran["reports_to_name"]) == ("Salesperson", PRIYA, "Priya Sharma")
    # a Manager can't add Managers or Admins, and can't put someone in another team
    assert add_user(client, "Sam Lee", "sam@crm.test", role="Manager").status_code == 403
    other = add_user(login_as(client, ASHA), "Mona Das", "mona@crm.test", role="Manager").json()
    res = add_user(login_as(client, PRIYA), "Tara Iyer", "tara@crm.test", reports_to_id=other["id"])
    assert res.status_code == 201 and res.json()["reports_to_id"] == PRIYA
    # Salespeople can't add anyone
    assert add_user(login_as(client, RAVI), "Ned Roy", "ned@crm.test").status_code == 403
    # the Admin's Activity Log shows who added them
    log = login_as(client, ASHA).get("/api/activity-log").json()
    added = [r for r in log if r["action"] == "User added" and r["target"] == "Kiran Rao"][0]
    assert added["by"] == "Priya Sharma" and "Reports to Priya Sharma" in added["details"]


def test_a_manager_deactivates_only_their_own_team(client, outbox):
    kiran = add_user(login_as(client, PRIYA), "Kiran Rao", "kiran@crm.test").json()
    assert client.put(f"/api/users/{kiran['id']}", json={"is_active": False}).json()["is_active"] is False
    assert client.put(f"/api/users/{kiran['id']}", json={"is_active": True}).json()["is_active"] is True
    # nothing else about the user, and nobody outside the team
    assert client.put(f"/api/users/{kiran['id']}", json={"full_name": "K Rao"}).status_code == 403
    assert client.put(f"/api/users/{RAVI}", json={"is_active": False}).status_code == 403  # Ravi has no Manager yet
    assert client.put(f"/api/users/{ASHA}", json={"is_active": False}).status_code == 403
    log = login_as(client, ASHA).get("/api/activity-log").json()
    assert {(r["action"], r["details"]) for r in log if r["target"] == "Kiran Rao"} >= {
        ("User deactivated", "By their Manager"), ("User activated", "By their Manager")}


def test_the_admin_sets_and_clears_reports_to(client, outbox):
    login_as(client, ASHA)
    res = client.put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    assert res.status_code == 200 and res.json()["reports_to_name"] == "Priya Sharma"
    assert client.put(f"/api/users/{RAVI}", json={"reports_to_id": ASHA}).status_code == 400  # not a Manager
    assert client.put(f"/api/users/{PRIYA}", json={"reports_to_id": PRIYA}).status_code == 400  # Managers report to nobody
    assert client.put(f"/api/users/{RAVI}", json={"reports_to_id": 0}).json()["reports_to_id"] is None
    client.put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    # moving Ravi to Manager clears his Manager
    assert client.put(f"/api/users/{RAVI}", json={"role": "Manager"}).json()["reports_to_id"] is None
    bell = login_as(client, PRIYA).get("/api/notifications").json()
    assert any(n["title"] == "Salesperson added to your team" for n in bell)


def test_a_manager_moves_a_team_members_records_within_the_team(client, outbox):
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    other = add_user(client, "Mona Das", "mona@crm.test", role="Manager").json()
    login_as(client, PRIYA)
    assert client.post(f"/api/users/{RAVI}/transfer", json={"to_user_id": other["id"]}).status_code == 403
    res = client.post(f"/api/users/{RAVI}/transfer", json={"to_user_id": PRIYA, "deactivate": True})
    assert res.status_code == 200 and res.json()["deactivated"] is True


def test_activity_history_by_role(client, outbox):
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    login_as(client, RAVI).get("/api/leads/export", params={"reason": "Call list for today"})
    login_as(client, ASHA).get("/api/leads/export", params={"reason": "Board pack for Friday"})
    # the Admin sees everything, in tabs
    everything = activity(client)
    assert everything["scope"] == "all" and everything["counts"]["data"] == 2 and everything["counts"]["access"] == 1
    data = activity(client, category="data")
    assert {r["by"] for r in data["rows"]} == {"Ravi Kumar", "Asha Rao"}
    assert activity(client, category="data", actor_id=RAVI)["total"] == 1
    assert activity(client, q="board pack")["total"] == 1
    # the Manager sees only their team (never the Admin's actions)
    team = activity(login_as(client, PRIYA))
    assert team["scope"] == "team" and {r["by"] for r in team["rows"]} == {"Ravi Kumar"}
    # Salespeople don't see activity history
    assert login_as(client, RAVI).get("/api/activity").status_code == 403


def test_activity_pages(client, outbox):
    login_as(client, ASHA)
    for i in range(30):
        client.put(f"/api/users/{RAVI}", json={"full_name": f"Ravi Kumar {i}"})
    first = activity(client, page_size=25)
    assert (first["total"], first["pages"], len(first["rows"])) == (30, 2, 25)
    assert len(activity(client, page_size=25, page=2)["rows"]) == 5


def test_the_manager_is_told_when_someone_else_downloads_their_teams_data(client, outbox):
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    login_as(client, RAVI).post("/api/leads", json={"first_name": "Mira", "last_name": "Shah", "company": "Brightline",
                                                    "email": "mira@brightline.test", "welcome_email": False})
    login_as(client, ASHA).get("/api/leads/export", params={"reason": "Board pack for Friday"})
    bell = login_as(client, PRIYA).get("/api/notifications").json()
    told = [n for n in bell if n["title"] == "Your team's data was downloaded"]
    assert told and "Asha Rao (Admin) downloaded 1 lead" in told[0]["message"]
    # the Manager downloading their own team's data isn't told about it
    client.get("/api/leads/export", params={"reason": "My weekly review"})
    bell = client.get("/api/notifications").json()
    assert len([n for n in bell if n["title"] == "Your team's data was downloaded"]) == 1


# ---------- Tasks page: tick several tasks, Mark as Done or Reassign ----------

def new_task(client, title, owner_id=None):
    body = {"title": title, "due_date": "2030-01-15T10:00:00", **({"owner_id": owner_id} if owner_id else {})}
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def test_bulk_complete_and_reassign_tasks(client, outbox):
    one, two = new_task(client, "Synthetic call one"), new_task(client, "Synthetic call two")
    priya_task = new_task(login_as(client, PRIYA), "Priya's own task")
    # a Salesperson completes their own tasks; someone else's is skipped with the reason
    res = login_as(client, RAVI).post("/api/tasks/bulk", json={"ids": [one, priya_task], "action": "complete"}).json()
    assert res["done"] == [one] and res["skipped"][0]["id"] == priya_task
    again = client.post("/api/tasks/bulk", json={"ids": [one], "action": "complete"}).json()
    assert again["skipped"][0]["reason"] == "Already Done"
    # only a Manager or Admin reassigns
    assert client.post("/api/tasks/bulk", json={"ids": [two], "action": "reassign", "owner_id": PRIYA}).status_code == 403
    res = login_as(client, PRIYA).post("/api/tasks/bulk", json={"ids": [two], "action": "reassign", "owner_id": PRIYA}).json()
    assert res["done"] == [two]
    assert client.get(f"/api/tasks/{two}").json()["owner_id"] == PRIYA
    assert client.post("/api/tasks/bulk", json={"ids": [two], "action": "reassign"}).status_code == 422


# ---------- Accounts list: Last Activity ----------

def test_accounts_list_shows_the_last_activity(client, outbox):
    acc = client.post("/api/accounts", json={"name": "Northwind Health", "industry": "Healthcare", "phone": "+1 415 555 0101"})
    assert acc.status_code == 201, acc.text
    row = [a for a in client.get("/api/accounts").json() if a["name"] == "Northwind Health"][0]
    assert row["last_activity_at"] is not None


# ---------- Home > Whole team graphs ----------

def test_team_charts(client, outbox):
    login_as(client, RAVI).post("/api/leads", json={"first_name": "Mira", "last_name": "Shah", "company": "Brightline",
                                                    "email": "mira@brightline.test", "welcome_email": False})
    assert client.get("/api/home/team-charts").status_code == 403  # Salespeople: no team dashboard
    everyone = login_as(client, PRIYA).get("/api/home/team-charts").json()
    assert everyone["scope"] == "all"
    assert {r["stage"]: r["count"] for r in everyone["leads_by_stage"]}["New"] == 1
    assert [p["name"] for p in everyone["people"]] == ["Priya Sharma", "Ravi Kumar"]
    # once Priya has a team, she sees her team only
    kiran = add_user(client, "Kiran Rao", "kiran@crm.test").json()
    team = client.get("/api/home/team-charts").json()
    assert team["scope"] == "team" and {p["name"] for p in team["people"]} == {"Priya Sharma", "Kiran Rao"}
    assert {r["stage"]: r["count"] for r in team["leads_by_stage"]}["New"] == 0
    assert set(team["won_lost_month"]) == {"won", "lost"}


def test_a_team_members_own_download_is_in_team_activity_not_the_bell(client, outbox):
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    login_as(client, RAVI).post("/api/leads", json={"first_name": "Mira", "last_name": "Shah", "company": "Brightline",
                                                    "email": "mira@brightline.test", "welcome_email": False})
    client.get("/api/leads/export", params={"reason": "My call list"})
    bell = login_as(client, PRIYA).get("/api/notifications").json()
    assert not [n for n in bell if n["title"] == "Your team's data was downloaded"]
    assert activity(client, category="data")["total"] == 1
