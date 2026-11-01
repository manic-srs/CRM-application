"""Every stage change except Lost needs a new task from the user (its subject and due date at least): moves between
active stages (also backward), conversion (the task goes on the new opportunity), Won (a post-sale task that stays
open) and cancelling a demo back to Nurturing. The task takes the place of the system follow-up for that change;
reminders tied to dates (demo, close date) stay. Nothing is saved when anything is refused. All data is made up."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import leads as leads_router, opportunities as opportunities_router
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai: a scripted stand-in for the AI model)
from test_mandatory_stage_notes import history, message, new_lead, ok, sent, snapshot  # noqa: F401 (sent: autouse)
from test_opportunity_attachments import ASHA, PDF, PRIYA, RAVI, add_salesperson, db_session, new_opportunity, pdf_file

TASK = {"title": "  Call the buyer about the budget  ", "due_date": "2030-02-03T11:30:00", "priority": "High",
        "reminder_at": "2030-02-03T10:30:00", "description": "Ask about Q1 timing"}
HANDOVER = {"title": "Hand over to onboarding", "due_date": "2030-02-10T09:00:00"}
SUBJECT, DUE, NEEDED = "Enter a task subject.", "Choose a due date for the task.", "Add a new task for this stage change."
NOTE = "Synthetic stage note"


def open_tasks(record):
    return [t for t in record["tasks"] if t["status"] == "Open"]


def mine(record):
    """The user's tasks (not the system's reminders)."""
    return [t for t in open_tasks(record) if not t["is_auto"]]


# ---------- each stage change that needs a task, with everything but the task ready ----------

def lead_forward(client):
    return "put", f"/api/leads/{new_lead(client)['id']}/stage", {"stage": "Nurturing", "completed_stages": ["New"], "note": NOTE}


def lead_backward(client):
    lead = new_lead(client)
    ok(client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Nurturing", "completed_stages": ["New"], "note": NOTE, "task": HANDOVER}))
    return "put", f"/api/leads/{lead['id']}/stage", {"stage": "New", "note": NOTE}


def lead_convert(client):
    return "post", f"/api/leads/{new_lead(client)['id']}/convert", {"note": NOTE, "completed_stages": ["New", "Nurturing", "Demo"]}


def lead_cancel_demo(client):
    lead = new_lead(client)
    ok(client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Demo", "demo_date": "2030-01-01T11:00:00",
                                                          "completed_stages": ["New", "Nurturing"], "note": NOTE, "task": HANDOVER}))
    return "post", f"/api/leads/{lead['id']}/cancel-demo", {"reason": "Client travelling"}


def opportunity_forward(client):
    return "put", f"/api/opportunities/{new_opportunity(client)['id']}/stage", {"stage": "Proposal", "completed_stages": ["Discovery"], "note": NOTE}


def opportunity_won(client):
    return "post", f"/api/opportunities/{new_opportunity(client)['id']}/won", {"note": NOTE,
                                                                            "completed_stages": ["Discovery", "Proposal"]}


CHANGES = [lead_forward, lead_backward, lead_convert, lead_cancel_demo, opportunity_forward, opportunity_won]
MISSING = object()
BAD_TASKS = [
    (MISSING, NEEDED), (None, NEEDED), ({}, SUBJECT), ({"due_date": "2030-01-01T10:00"}, SUBJECT),
    ({"title": "   ", "due_date": "2030-01-01T10:00"}, SUBJECT), ({"title": "Call", "due_date": ""}, DUE),
    ({"title": "Call"}, DUE), ({"title": "Call", "due_date": "next week"}, "valid datetime"),
    ({"title": 5, "due_date": "2030-01-01T10:00"}, "must be text"), ({"title": "C" * 201, "due_date": "2030-01-01T10:00"}, "200"),
    ({"title": "Call", "due_date": "2030-01-01T10:00", "priority": "Urgent"}, "Low"),
    ({"title": "Call", "due_date": "2030-01-01T10:00", "lead_id": 1}, "Extra inputs"),  # the server links the task
    ("Call tomorrow", "valid dictionary"),
]


@pytest.mark.parametrize("make", CHANGES, ids=lambda f: f.__name__)
@pytest.mark.parametrize("task, expected", BAD_TASKS, ids=["missing", "null", "empty", "no subject", "blank subject",
                                                            "blank due", "no due", "bad due", "subject not text",
                                                            "subject too long", "bad priority", "own link", "not an object"])
def test_a_missing_or_invalid_task_is_refused_and_nothing_changes(client, sent, make, task, expected):
    method, path, body = make(client)
    before, mails = snapshot(), len(sent)
    res = client.request(method.upper(), path, json=body | ({} if task is MISSING else {"task": task}))
    assert res.status_code == 422, res.text
    assert expected in message(res)
    assert snapshot() == before and len(sent) == mails  # no stage, history, task, record, notification or email


@pytest.mark.parametrize("path", ["stage-with-files", "won-with-files"])
@pytest.mark.parametrize("task, expected", [(None, NEEDED), (json.dumps({"title": " ", "due_date": "2030-01-01T10:00"}), SUBJECT),
                                            (json.dumps({"title": "Call"}), DUE), ("{not json", "valid dictionary")],
                         ids=["missing", "blank subject", "no due", "not json"])
def test_popups_with_files_need_the_task_too(client, sent, path, task, expected):
    opp = new_opportunity(client)
    form = ({"stage": "Proposal", "completed_stages": ["Discovery"]} if path == "stage-with-files" else {"completed_stages": ["Discovery", "Proposal"]}) | {"note": NOTE}
    before, mails = snapshot(), len(sent)
    res = client.post(f"/api/opportunities/{opp['id']}/{path}", data=form | ({"task": task} if task else {}),
                      files=[("files", ("quote.pdf", pdf_file(), PDF))])
    assert res.status_code == 422 and f"task: {expected}" in res.json()["detail"] if expected != "valid dictionary" \
        else res.status_code == 422 and "task:" in res.json()["detail"]
    assert snapshot() == before and len(sent) == mails  # no file either


# ---------- the assignee ----------

def test_the_assignee_follows_the_task_rules(client, sent):
    lead = new_lead(client)  # Ravi's
    before = snapshot()
    body = {"stage": "Nurturing", "completed_stages": ["New"], "note": NOTE}
    for owner in (PRIYA, 999):  # a Salesperson can't give tasks to others (as on the Tasks page)
        res = client.put(f"/api/leads/{lead['id']}/stage", json=body | {"task": HANDOVER | {"owner_id": owner}})
        assert res.status_code == 403, res.text
    unknown = login_as(client, PRIYA).put(f"/api/leads/{lead['id']}/stage",
                                          json=body | {"task": HANDOVER | {"owner_id": 999}})
    assert unknown.status_code == 400 and "User 999 not found" in unknown.json()["detail"]
    assert snapshot() == before
    login_as(client, RAVI)
    # a Manager can: the task goes to the chosen user, who is told; the lead's owner hears about the move as before
    sent.clear()
    moved = ok(login_as(client, PRIYA).put(f"/api/leads/{lead['id']}/stage",
                                           json=body | {"task": HANDOVER | {"owner_id": ASHA}}))
    [task] = mine(moved)
    assert (task["title"], task["owner_id"]) == (HANDOVER["title"], ASHA)
    assert any(m["subject"] == "[SalesTrack] Task assigned to you" and m["to"] == ["asha@crm.test"] for m in sent)
    # by default the task goes to the record's owner, also when a Manager makes the change
    back = ok(client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "New", "note": NOTE, "task": HANDOVER}))
    assert [t["owner_id"] for t in mine(back)] == [RAVI]


# ---------- valid tasks ----------

def test_a_lead_move_saves_the_users_task_instead_of_the_system_follow_up(client, sent):
    lead = new_lead(client)
    moved = ok(client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Nurturing", "completed_stages": ["New"], "note": NOTE, "task": TASK}))
    [task] = open_tasks(moved)  # no "Follow-up call" next to it; "Make first contact" is closed
    assert (task["title"], task["due_date"], task["priority"], task["reminder_at"], task["description"], task["is_auto"],
            task["lead_id"], task["owner_id"]) == ("Call the buyer about the budget", TASK["due_date"], "High",
                                                   TASK["reminder_at"], "Ask about Q1 timing", False, lead["id"], RAVI)
    assert [t["status"] for t in moved["tasks"] if t["is_auto"]] == ["Auto-closed"]
    assert moved["history"][-1]["note"] == NOTE
    assert "Next follow-up: Call the buyer about the budget" in sent[-1]["body"]  # the owner's notice names it
    # backward: the same rule
    back = ok(client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "New", "note": NOTE, "task": HANDOVER}))
    assert [t["title"] for t in open_tasks(back)] == [HANDOVER["title"]]


def test_demo_reminders_stay_with_the_demo_date(client):
    lead = new_lead(client)
    demo = ok(client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Demo", "demo_date": "2030-03-04T15:00:00",
                                                                 "completed_stages": ["New", "Nurturing"], "note": NOTE, "task": TASK}))
    assert sorted((t["title"].split(" - ")[0], t["is_auto"]) for t in open_tasks(demo)) == [
        ("Call the buyer about the budget", False), ("Conduct demo", True), ("Prepare for demo", True)]
    # without a demo date there is no demo to remind about: only the user's task
    other = new_lead(client)
    no_date = ok(client.put(f"/api/leads/{other['id']}/stage", json={"stage": "Demo", "completed_stages": ["New", "Nurturing"],
                                                                     "note": NOTE, "task": TASK}))
    assert [t["title"] for t in open_tasks(no_date)] == ["Call the buyer about the budget"]


def test_conversion_puts_the_task_on_the_new_opportunity(client):
    lead = new_lead(client)
    res = ok(client.post(f"/api/leads/{lead['id']}/convert", json={"note": NOTE, "completed_stages": ["New", "Nurturing", "Demo"],
                                                                    "expected_value": 900, "task": TASK}))
    opp = client.get(f"/api/opportunities/{res['opportunity']['id']}").json()
    assert res["new_task"]["opportunity_id"] == opp["id"] and res["new_task"]["lead_id"] is None
    assert sorted((t["title"].split(" - ")[0], t["is_auto"], t["owner_id"]) for t in open_tasks(opp)) == [
        ("Call the buyer about the budget", False, RAVI), ("Close date coming up", True, RAVI)]  # no "Send proposal"
    assert open_tasks(client.get(f"/api/leads/{lead['id']}").json()) == []  # the converted lead keeps none


def test_an_opportunity_move_keeps_the_close_date_reminder(client):
    opp = new_opportunity(client)
    moved = ok(client.put(f"/api/opportunities/{opp['id']}/stage", json={"stage": "Proposal", "completed_stages": ["Discovery"], "note": NOTE, "task": TASK}))
    assert sorted(t["title"].split(" - ")[0] for t in open_tasks(moved)) == ["Call the buyer about the budget",
                                                                            "Close date coming up"]


def test_the_won_task_stays_open_and_can_be_managed_after_closing(client, sent):
    opp = new_opportunity(client)
    ok(client.put(f"/api/opportunities/{opp['id']}/stage", json={"stage": "Proposal", "completed_stages": ["Discovery"], "note": NOTE, "task": TASK}))
    won = ok(client.post(f"/api/opportunities/{opp['id']}/won", json={"note": NOTE, "task": HANDOVER,
                                                                       "notify_customer": False}))
    assert won["stage"] == "Won"
    [task] = open_tasks(won)  # every earlier task is closed; only the post-sale task is open
    assert (task["title"], task["opportunity_id"], task["owner_id"], task["is_auto"]) == (HANDOVER["title"], opp["id"],
                                                                                          RAVI, False)
    assert task in client.get("/api/tasks", params={"status": "Open"}).json()
    edited = ok(client.put(f"/api/tasks/{task['id']}", json={"due_date": "2030-02-12T09:00:00"}))
    assert edited["due_date"] == "2030-02-12T09:00:00"
    done = ok(client.put(f"/api/tasks/{task['id']}/complete"))
    assert done["status"] == "Done" and done["completed_at"]
    # the won deal itself stays closed: no stage change and no new files
    assert client.put(f"/api/opportunities/{opp['id']}/stage",
                      json={"stage": "Opportunity", "note": NOTE, "task": TASK}).status_code == 400
    assert client.post(f"/api/opportunities/{opp['id']}/attachments",
                       files={"file": ("late.pdf", pdf_file(), PDF)}).status_code == 409


def test_lost_needs_no_task_and_creates_none(client):
    lead = new_lead(client)
    lost = ok(client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Price", "lost_notes": NOTE,
                                                                  "notify_customer": False}))
    assert lost["stage"] == "Lost" and open_tasks(lost) == []
    opp = new_opportunity(client)
    lost = ok(client.post(f"/api/opportunities/{opp['id']}/lost", json={"lost_reason": "Price", "lost_notes": NOTE,
                                                                         "notify_customer": False, "task": TASK}))
    assert lost["stage"] == "Lost" and open_tasks(lost) == []  # a task sent along is not used


def test_cancelling_a_demo_needs_a_task_but_rescheduling_does_not(client):
    method, path, body = lead_cancel_demo(client)
    lead_id = int(path.split("/")[3])
    moved = ok(client.post(f"/api/leads/{lead_id}/cancel-demo", json={"reschedule_to": "2030-01-05T11:00:00"}))
    assert moved["stage"] == "Demo"
    back = ok(client.post(path, json=body | {"task": TASK}))
    assert back["stage"] == "Revisit" and [t["title"] for t in open_tasks(back)] == ["Call the buyer about the budget"]


# ---------- all or nothing ----------

def test_a_failure_while_saving_leaves_nothing_behind(client, sent, monkeypatch):
    lead = new_lead(client)
    opp = new_opportunity(client)
    before, mails = snapshot(), len(sent)

    def broken(*args, **kwargs):
        raise RuntimeError("task could not be saved")
    with monkeypatch.context() as patch:  # the task fails after the stage, history and old tasks were changed
        patch.setattr(leads_router, "add_stage_task", broken)
        with pytest.raises(RuntimeError):
            client.post(f"/api/leads/{lead['id']}/convert", json={"note": NOTE, "task": TASK,
                                                                   "completed_stages": ["New", "Nurturing", "Demo"]})
    with monkeypatch.context() as patch:  # the files fail
        patch.setattr(opportunities_router, "save_files", broken)
        with pytest.raises(RuntimeError):
            client.post(f"/api/opportunities/{opp['id']}/won-with-files", files=[("files", ("q.pdf", pdf_file(), PDF))],
                        data={"note": NOTE, "task": json.dumps(HANDOVER), "completed_stages": ["Discovery", "Proposal"]})
    with monkeypatch.context() as patch:  # the save itself fails
        from sqlalchemy.orm import Session
        patch.setattr(Session, "commit", broken)
        with pytest.raises(RuntimeError):
            client.put(f"/api/opportunities/{opp['id']}/stage", json={"stage": "Proposal", "completed_stages": ["Discovery"], "note": NOTE, "task": TASK})
    assert snapshot() == before and len(sent) == mails


def test_double_submissions_create_one_transition_and_one_task(client):
    lead = new_lead(client)
    body = {"stage": "Nurturing", "completed_stages": ["New"], "note": NOTE, "task": TASK}
    assert client.put(f"/api/leads/{lead['id']}/stage", json=body).status_code == 200
    again = client.put(f"/api/leads/{lead['id']}/stage", json=body)
    assert again.status_code == 400 and "already at Nurturing" in again.json()["detail"]
    assert len(mine(client.get(f"/api/leads/{lead['id']}").json())) == 1
    convert = {"note": NOTE, "task": TASK, "completed_stages": ["Demo"]}
    first = ok(client.post(f"/api/leads/{lead['id']}/convert", json=convert))
    assert client.post(f"/api/leads/{lead['id']}/convert", json=convert).status_code == 400  # closed now
    won = {"note": NOTE, "task": HANDOVER, "completed_stages": ["Discovery", "Proposal"], "final_value": 10}
    assert client.post(f"/api/opportunities/{first['opportunity']['id']}/won", json=won).status_code == 200
    assert client.post(f"/api/opportunities/{first['opportunity']['id']}/won", json=won).status_code == 400
    opp = client.get(f"/api/opportunities/{first['opportunity']['id']}").json()
    assert [t["title"] for t in mine(opp)] == [HANDOVER["title"]]


def test_view_only_users_cannot_change_stages_even_with_a_task(client):
    lead = new_lead(client)
    sam = add_salesperson(client)
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    before = snapshot()
    res = login_as(client, sam).put(f"/api/leads/{lead['id']}/stage", json={"stage": "Nurturing", "completed_stages": ["New"], "note": NOTE, "task": TASK})
    assert res.status_code == 403 and snapshot() == before


def test_two_saves_at_the_same_time_make_one_transition(client, monkeypatch):
    """The record row is locked during the save (PostgreSQL), so the second save waits and then sees the new stage.
    SQLite has no row locks, so this runs only against PostgreSQL."""
    with db_session() as db:
        if db.bind.dialect.name != "postgresql":
            pytest.skip("row locks need PostgreSQL")
    lead = new_lead(client)
    slow_owner = leads_router.stage_task_owner

    def slow(*args):
        time.sleep(0.4)  # both requests would pass the stage check during this pause without the lock
        return slow_owner(*args)
    monkeypatch.setattr(leads_router, "stage_task_owner", slow)
    token = client.headers["Authorization"]
    results = []

    def save():
        other = TestClient(app)  # no "with": skips startup, as in conftest.py (the app database is never opened)
        other.headers["Authorization"] = token
        results.append(other.put(f"/api/leads/{lead['id']}/stage",
                                 json={"stage": "Nurturing", "completed_stages": ["New"], "note": NOTE, "task": TASK}).status_code)
    threads = [threading.Thread(target=save) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200, 400]
    assert len(mine(client.get(f"/api/leads/{lead['id']}").json())) == 1


# ---------- AI Assistant ----------

def test_assistant_needs_the_users_task(client, ai):
    script, seen = ai
    opp = new_opportunity(client)
    lead = new_lead(client)
    before = snapshot()
    script += [[call("move_lead_stage", lead_id=lead["id"], stage="Nurturing", note=NOTE)], "What task should I add?",
               [call("mark_opportunity_won", opportunity_id=opp["id"], completed_stages=["Discovery", "Proposal"], note=NOTE,
                     task_title="  ")], "What is the post-sale task?"]
    client.post("/api/assistant/chat", json={"message": "Move it to nurturing"})
    assert NEEDED in json.loads(seen[-1][-1]["content"])["error"]
    reply = client.post("/api/assistant/chat", json={"message": "Mark the deal won"}).json()
    assert reply["pending"] is None and NEEDED in json.loads(seen[-1][-1]["content"])["error"]
    assert snapshot() == before


def test_assistant_shows_the_task_before_confirming_and_creates_it(client, ai):
    script, _ = ai
    opp = new_opportunity(client)
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], completed_stages=["Discovery", "Proposal"], note=NOTE,
                     task_title="Kick-off call", task_due_date="2030-02-20T10:00")]]
    first = client.post("/api/assistant/chat", json={"message": "Won; kick-off call on 20 Feb"}).json()
    assert 'New task: "Kick-off call", due 2030-02-20T10:00.' in first["pending"]["summary"]
    before = snapshot()  # a Confirm whose task was removed in the browser is refused by the API
    tampered = {**first["pending"], "args": {k: v for k, v in first["pending"]["args"].items() if not k.startswith("task")}}
    script += ["I couldn't do that: a task is needed."]
    client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": tampered, "confirmed": True})
    assert snapshot() == before
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], completed_stages=["Discovery", "Proposal"], note=NOTE,
                     task_title="Kick-off call", task_due_date="2030-02-20T10:00")]]
    again = client.post("/api/assistant/chat", json={"message": "Try again"}).json()
    script += ["Done."]
    client.post("/api/assistant/confirm", json={"messages": again["messages"], "pending": again["pending"], "confirmed": True})
    won = client.get(f"/api/opportunities/{opp['id']}").json()
    assert won["stage"] == "Won" and [(t["title"], t["due_date"]) for t in mine(won)] == [("Kick-off call",
                                                                                         "2030-02-20T10:00:00")]
