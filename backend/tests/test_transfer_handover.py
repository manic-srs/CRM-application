"""A transferred lead or deal carries on from the same stage: the new owner sees the history, and gets the open
follow-ups (the previous owner's and the system's) with their due dates and reminders. All data is made up."""
from tests.conftest import login_as

TASK = {"title": "Call back about pricing", "due_date": "2030-01-15T10:00:00", "reminder_at": "2030-01-15T09:00:00"}
NOTE = "Interested, wants pricing"


def test_transfer_keeps_the_stage_and_moves_the_open_tasks_to_the_new_owner(client):
    ravi = login_as(client, 2)
    lead = ravi.post("/api/leads", json={"last_name": "Handover", "company": "Relay Co"}).json()
    ravi.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Nurturing", "note": NOTE, "task": TASK})
    # a task a Manager gave someone else on this lead stays theirs
    other = login_as(client, 1).post("/api/tasks", json={"title": "Manager check", "due_date": "2030-01-20T10:00:00",
                                                         "lead_id": lead["id"], "owner_id": 1}).json()
    # the Admin moves it to Priya (e.g. Ravi is away)
    res = login_as(client, 3).post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 1, "note": "Ravi on leave"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["stage"], body["owner_id"]) == ("Nurturing", 1)  # same stage, new owner
    assert [h["to_stage"] for h in body["history"]] == ["New", "Nurturing"]  # history kept
    open_tasks = [t for t in body["tasks"] if t["status"] == "Open"]
    moved = next(t for t in open_tasks if t["title"] == TASK["title"])
    assert (moved["owner_id"], moved["due_date"], moved["reminder_at"]) == (1, TASK["due_date"], TASK["reminder_at"])
    assert next(t for t in open_tasks if t["id"] == other["id"])["owner_id"] == 1
    # Priya is told where to carry on
    note = next(n for n in login_as(client, 1).get("/api/notifications").json() if n["title"] == "Lead assigned to you")
    assert "Stage: Nurturing" in note["message"] and "Call back about pricing" in note["message"]
    assert f"Last note: {NOTE}" in note["message"] and "Ravi on leave" in note["message"]
    # Ravi no longer has the follow-up
    assert all(t["title"] != TASK["title"] for t in login_as(client, 2).get("/api/tasks").json())


def test_a_task_given_to_a_third_person_stays_with_them(client):
    from app.database import get_db
    from app.main import app
    from app.models import Task
    ravi = login_as(client, 2)
    lead = ravi.post("/api/leads", json={"last_name": "Third", "company": "Relay Co"}).json()
    db = next(app.dependency_overrides[get_db]())
    db.add(Task(title="Admin review", due_date=__import__("datetime").datetime(2030, 2, 1, 10), owner_id=3,
                status="Open", is_auto=False, lead_id=lead["id"]))
    db.commit()
    login_as(client, 1).post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": 1})
    owners = {t["title"]: t["owner_id"] for t in login_as(client, 1).get(f"/api/leads/{lead['id']}").json()["tasks"]}
    assert owners["Admin review"] == 3 and owners["Make first contact - Third"] == 1


def test_admin_moves_someones_records_with_transfer_history(client):
    ravi = login_as(client, 2)
    lead = ravi.post("/api/leads", json={"last_name": "Leaver", "company": "Relay Co"}).json()
    res = login_as(client, 3).post("/api/users/2/transfer", json={"to_user_id": 1, "deactivate": False})
    assert res.status_code == 200, res.text
    detail = login_as(client, 1).get(f"/api/leads/{lead['id']}").json()
    assert detail["owner_id"] == 1 and detail["stage"] == "New"
    assert [(t["from_user_id"], t["to_user_id"]) for t in detail["transfers"]] == [(2, 1)]
    assert all(t["owner_id"] == 1 for t in detail["tasks"] if t["status"] == "Open")


def test_opportunity_owner_change_moves_its_follow_ups(client):
    ravi = login_as(client, 2)
    lead = ravi.post("/api/leads", json={"last_name": "Deal", "company": "Relay Co"}).json()
    opp = ravi.post(f"/api/leads/{lead['id']}/convert", json={
        "note": NOTE, "task": TASK, "completed_stages": ["Nurturing", "Demo"], "expected_value": 1000}).json()["opportunity"]
    res = login_as(client, 3).put(f"/api/opportunities/{opp['id']}", json={"owner_id": 1})
    assert res.status_code == 200, res.text
    tasks = login_as(client, 1).get(f"/api/opportunities/{opp['id']}").json()["tasks"]
    assert all(t["owner_id"] == 1 for t in tasks if t["status"] == "Open")
    note = next(n for n in login_as(client, 1).get("/api/notifications").json() if n["title"] == "Opportunity assigned to you")
    assert "Stage: Opportunity" in note["message"]
