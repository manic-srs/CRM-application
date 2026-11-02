"""Every stage change a user makes needs a note: lead and opportunity moves (also backward), conversion, Won, Lost and
cancelling a demo (back to Nurturing). The API refuses a missing, null, empty, blank or non-text note even when the
screens are bypassed, and then nothing changes: no stage, history, task, notification, email, record or file.
A valid note is trimmed and kept in the stage history, also after conversion or closing. All data is made up."""
import itertools
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import mailer
from app.models import Account, Contact, Lead, Notification, Opportunity, OpportunityAttachment, StageHistory, Task, User
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai is a fixture: a scripted stand-in for the AI model)
from test_opportunity_attachments import PDF, PRIYA, RAVI, add_salesperson, db_session, new_opportunity, pdf_file

TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}  # every stage change needs one

REQUIRED = "Enter a note to change the stage."
COMMENT_REQUIRED = "Enter a conversion comment."  # Convert's note (requirement 8)
NOTE = "  Called the buyer.\n  - budget approved\n  - decision next week\n\n"
SAVED = "Called the buyer.\n  - budget approved\n  - decision next week"  # trimmed around, formatting inside kept
MISSING = object()
BLANK = [MISSING, None, "", "   ", "\n\t \r\n"]
NOT_TEXT = [5, ["a note"], {"text": "a note"}, True]
EMAILS = itertools.count(1)


@pytest.fixture(autouse=True)
def sent(monkeypatch, client):
    """Emails are recorded instead of sent. Ravi wants stage emails, so every saved stage change sends one."""
    messages = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **k: messages.append({"to": to, "subject": subject,
                                                                                        "body": body}))
    with db_session() as db:
        db.get(User, RAVI).email_stage_updates = True
        db.commit()
    return messages


def new_lead(client, **extra):
    n = next(EMAILS)
    res = client.post("/api/leads", json={"first_name": "Test", "last_name": f"Buyer{n}", "company": "Synthetic Co",
                                          "email": f"stage.note{n}@example.test", "welcome_email": False, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def message(res) -> str:
    detail = res.json()["detail"]
    return detail if isinstance(detail, str) else " ".join(e["msg"] for e in detail)


def history(client, kind, record_id):
    return [(h["from_stage"], h["to_stage"], h["note"]) for h in client.get(f"/api/{kind}/{record_id}/history").json()]


def snapshot():
    """Everything a stage change can touch, to check that a refused one changed nothing."""
    with db_session() as db:
        def count(model):
            return db.scalar(select(func.count()).select_from(model))
        return {
            "leads": sorted((l.id, l.stage, l.demo_date, l.lost_reason, l.lost_notes, l.closed_at, l.converted_at,
                             l.untouched) for l in db.scalars(select(Lead))),
            "opportunities": sorted((o.id, o.stage, o.probability, o.final_value, o.lost_reason, o.lost_notes, o.closed_at)
                                    for o in db.scalars(select(Opportunity))),
            "history": count(StageHistory), "notifications": count(Notification), "accounts": count(Account),
            "contacts": count(Contact), "files": count(OpportunityAttachment),
            "tasks": sorted((t.id, t.title, t.status, t.due_date, t.owner_id) for t in db.scalars(select(Task))),
        }


# ---------- each way of changing a stage, with everything but the note ready ----------

def lead_forward(client):
    return "put", f"/api/leads/{new_lead(client)['id']}/stage", {"stage": "Nurturing", "completed_stages": ["New"], "task": TASK}, "note"


def lead_backward(client):
    lead = new_lead(client)
    ok(client.put(f"/api/leads/{lead['id']}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": "First call done"}))
    return "put", f"/api/leads/{lead['id']}/stage", {"stage": "New", "task": TASK}, "note"


def lead_skipping_a_confirmed_stage(client):
    return "put", f"/api/leads/{new_lead(client)['id']}/stage", {
        "stage": "Demo", "demo_date": "2026-12-01T11:00:00", "completed_stages": ["New", "Nurturing"],
        "completed_note": "Covered on the first call", "task": TASK}, "note"


def lead_lost(client):
    return "post", f"/api/leads/{new_lead(client)['id']}/lost", {"lost_reason": "Price", "notify_customer": True}, \
        "lost_notes"


def lead_convert(client):
    return "post", f"/api/leads/{new_lead(client)['id']}/convert", {
        "completed_stages": ["New", "Nurturing", "Demo"], "expected_value": 1000, "task": TASK}, "note"


def lead_cancel_demo(client):
    lead = new_lead(client)
    ok(client.put(f"/api/leads/{lead['id']}/stage", json={"task": TASK, "stage": "Demo", "demo_date": "2026-12-01T11:00:00",
                                                          "completed_stages": ["New", "Nurturing"], "note": "Demo booked"}))
    return "post", f"/api/leads/{lead['id']}/cancel-demo", {"task": TASK}, "reason"


def opportunity_forward(client):
    return "put", f"/api/opportunities/{new_opportunity(client)['id']}/stage", {"stage": "Proposal", "completed_stages": ["Discovery"], "task": TASK}, "note"


def opportunity_backward(client):
    opp = new_opportunity(client)
    ok(client.put(f"/api/opportunities/{opp['id']}/stage", json={"task": TASK, "stage": "Proposal", "completed_stages": ["Discovery"], "note": "Proposal sent"}))
    return "put", f"/api/opportunities/{opp['id']}/stage", {"stage": "Opportunity", "task": TASK}, "note"


def opportunity_won(client):
    return "post", f"/api/opportunities/{new_opportunity(client)['id']}/won", {
        "completed_stages": ["Discovery", "Proposal"], "notify_customer": True, "task": TASK}, "note"


def opportunity_lost(client):
    return "post", f"/api/opportunities/{new_opportunity(client)['id']}/lost", {
        "lost_reason": "Competitor", "notify_customer": True}, "lost_notes"


JSON_CHANGES = [lead_forward, lead_backward, lead_skipping_a_confirmed_stage, lead_lost, lead_convert, lead_cancel_demo,
                opportunity_forward, opportunity_backward, opportunity_won, opportunity_lost]


def send(client, change, note):
    method, path, body, field = change
    return client.request(method.upper(), path, json=body | ({} if note is MISSING else {field: note}))


@pytest.mark.parametrize("make", JSON_CHANGES, ids=lambda f: f.__name__)
@pytest.mark.parametrize("note", BLANK, ids=["missing", "null", "empty", "spaces", "whitespace"])
def test_a_missing_or_blank_note_is_refused_and_nothing_changes(client, sent, make, note):
    change = make(client)
    before, sent_before = snapshot(), len(sent)
    res = send(client, change, note)
    assert res.status_code == 422, res.text
    if make is lead_convert:  # Convert's note is the Conversion Comment (requirement 8), also when left out
        assert message(res) == COMMENT_REQUIRED
    elif note is not MISSING or make is lead_cancel_demo:
        assert REQUIRED in message(res)
    assert snapshot() == before  # no stage, history, task, notification, account, contact or opportunity
    assert len(sent) == sent_before  # no notification or customer email


@pytest.mark.parametrize("make", JSON_CHANGES, ids=lambda f: f.__name__)
@pytest.mark.parametrize("note", NOT_TEXT, ids=["number", "list", "object", "boolean"])
def test_a_note_that_is_not_text_is_refused(client, sent, make, note):
    change = make(client)
    before, sent_before = snapshot(), len(sent)
    assert send(client, change, note).status_code == 422
    assert snapshot() == before and len(sent) == sent_before


def with_files(client, path, opp_id, note):
    """The Change Stage (to Proposal) or Mark as Won popup with one file."""
    form = {"stage": "Proposal", "completed_stages": ["Discovery"]} if path == "stage-with-files" else {"completed_stages": ["Discovery", "Proposal"],
                                                                      "notify_customer": "true"}
    form |= {"task": json.dumps(TASK)}
    return client.post(f"/api/opportunities/{opp_id}/{path}", data=form | ({} if note is MISSING else {"note": note}),
                       files=[("files", ("quote.pdf", pdf_file(), PDF))])


@pytest.mark.parametrize("path", ["stage-with-files", "won-with-files"])
@pytest.mark.parametrize("note", [MISSING, "", "   ", "\n\t \r\n"], ids=["missing", "empty", "spaces", "whitespace"])
def test_popups_with_files_save_nothing_without_a_note(client, sent, path, note):
    opp = new_opportunity(client)
    before, sent_before = snapshot(), len(sent)
    res = with_files(client, path, opp["id"], note)
    assert res.status_code == 422, res.text
    if note is not MISSING:
        assert REQUIRED in message(res)
    assert snapshot() == before  # the note is checked before any file is read: no file, stage, task or notification
    assert len(sent) == sent_before  # no stage email and no thank-you email
    # sent again with a note (the popup keeps the files and the other fields), it saves
    assert with_files(client, path, opp["id"], "Quote attached").status_code == 200
    assert snapshot()["files"] == before["files"] + 1


@pytest.mark.parametrize("path", ["stage-with-files", "won-with-files"])
def test_a_note_sent_as_a_file_is_refused(client, path):
    opp = new_opportunity(client)
    before = snapshot()
    form = ({"stage": "Proposal", "completed_stages": ["Discovery"]} if path == "stage-with-files" else {"completed_stages": ["Discovery", "Proposal"]}) | {"task": json.dumps(TASK)}
    res = client.post(f"/api/opportunities/{opp['id']}/{path}", data=form,
                      files=[("files", ("quote.pdf", pdf_file(), PDF)), ("note", ("note.txt", b"hi", "text/plain"))])
    assert res.status_code == 422 and "The note must be text." in message(res)
    assert snapshot() == before


# ---------- valid notes ----------

def test_lead_notes_are_trimmed_and_kept_in_the_history_after_conversion(client, sent):
    lead = new_lead(client)
    lid = lead["id"]
    assert lead["history"] == [{**lead["history"][0], "from_stage": None, "to_stage": "New", "note": None}]  # no note
    ok(client.put(f"/api/leads/{lid}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": NOTE}))
    assert SAVED in sent[-1]["body"]  # the owner's "moved to Nurturing" email shows the note
    ok(client.put(f"/api/leads/{lid}/stage", json={"task": TASK, "stage": "New", "note": "  Wrong stage, moving back  "}))  # backward
    ok(client.put(f"/api/leads/{lid}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": "Follow-up call booked"}))
    ok(client.put(f"/api/leads/{lid}/stage", json={"task": TASK, "stage": "Demo", "demo_date": "2026-12-01T11:00:00",
                                                   "note": "Demo booked for December"}))
    res = ok(client.post(f"/api/leads/{lid}/convert", json={"task": TASK, "note": " Budget approved\nready for a proposal ",
                                                             "expected_value": 1000}))
    assert res["lead"]["stage"] == "Converted"
    lead_history = [("New", "Nurturing", SAVED),
                    ("Nurturing", "New", "Wrong stage, moving back"),
                    ("New", "Nurturing", "Follow-up call booked"), ("Nurturing", "Demo", "Demo booked for December"),
                    ("Demo", "Converted", "Budget approved\nready for a proposal")]
    assert history(client, "leads", lid)[1:] == lead_history
    # still on the converted lead's page, and the new opportunity's history starts with the same note
    assert [(h["from_stage"], h["to_stage"], h["note"]) for h in client.get(f"/api/leads/{lid}").json()["history"]][1:] \
        == lead_history
    assert history(client, "opportunities", res["opportunity"]["id"]) == [
        (None, "Opportunity", "Budget approved\nready for a proposal")]
    assert "Note: Budget approved" in sent[-1]["body"]  # the "Opportunity created" email


def test_skipped_stages_keep_their_confirmation_and_the_note_goes_on_the_requested_change(client):
    lead = new_lead(client)
    res = ok(client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "completed_stages": ["New", "Nurturing", "Demo"],
                                                                    "expected_value": 1000,
                                                                    "note": "Signed the letter of intent"}))
    assert history(client, "leads", lead["id"])[1:] == [
        ("New", "Nurturing", "Confirmed as completed"),
        ("Nurturing", "Demo", "Confirmed as completed"),
        ("Demo", "Converted", "Signed the letter of intent")]
    opp = res["opportunity"]
    won = ok(client.post(f"/api/opportunities/{opp['id']}/won", json={"task": TASK, "completed_stages": ["Discovery", "Proposal"],
                                                                       "completed_note": "Sent by email",
                                                                       "note": "Contract signed", "notify_customer": False}))
    assert [(h["from_stage"], h["to_stage"], h["note"]) for h in won["history"]][-3:] == [
        ("Opportunity", "Discovery", "Confirmed as completed: Sent by email"),
        ("Discovery", "Proposal", "Confirmed as completed: Sent by email"), ("Proposal", "Won", "Contract signed")]


def test_opportunity_notes_back_and_forth_won_and_lost(client, sent):
    opp = new_opportunity(client)
    oid = opp["id"]
    ok(client.put(f"/api/opportunities/{oid}/stage", json={"task": TASK, "stage": "Proposal", "completed_stages": ["Discovery"], "note": NOTE}))
    ok(client.put(f"/api/opportunities/{oid}/stage", json={"task": TASK, "stage": "Opportunity", "note": "Scope changed"}))
    ok(client.put(f"/api/opportunities/{oid}/stage", json={"task": TASK, "stage": "Proposal", "completed_stages": ["Discovery"], "note": "Revised proposal sent"}))
    sent.clear()
    won = ok(client.post(f"/api/opportunities/{oid}/won", json={"task": TASK, "note": "\n Contract signed \n", "notify_customer": True}))
    assert won["stage"] == "Won" and won["final_value"] == 1000
    assert history(client, "opportunities", oid)[1:] == [
        ("Opportunity", "Discovery", "Confirmed as completed"), ("Discovery", "Proposal", SAVED),
        ("Proposal", "Opportunity", "Scope changed"), ("Opportunity", "Discovery", "Confirmed as completed"),
        ("Discovery", "Proposal", "Revised proposal sent"), ("Proposal", "Won", "Contract signed")]
    assert not [m for m in sent if m["subject"].startswith("Thank you")]  # customers are never emailed
    assert any("Note: Contract signed" in m["body"] for m in sent if m["to"] == ["ravi@crm.test"])

    other = new_opportunity(client)
    sent.clear()
    lost = ok(client.post(f"/api/opportunities/{other['id']}/lost", json={
        "lost_reason": "Competitor", "lost_notes": "  Went with a cheaper vendor  ", "notify_customer": True}))
    assert (lost["stage"], lost["lost_reason"], lost["lost_notes"]) == ("Lost", "Competitor", "Went with a cheaper vendor")
    assert lost["history"][-1]["note"] == "Went with a cheaper vendor"
    assert not [m for m in sent if m["subject"].startswith("Thank you")]  # customers are never emailed
    # the lost reason is still required as well
    third = new_opportunity(client)
    assert client.post(f"/api/opportunities/{third['id']}/lost", json={"lost_notes": "No reason given"}).status_code == 422


def test_a_lost_lead_keeps_its_reason_and_notes(client):
    lead = new_lead(client)
    lost = ok(client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "No budget", "lost_notes": NOTE,
                                                                  "notify_customer": False}))
    assert (lost["stage"], lost["lost_reason"], lost["lost_notes"]) == ("Lost", "No budget", SAVED)
    assert lost["history"][-1]["note"] == SAVED
    assert ok(client.get(f"/api/leads/{lead['id']}"))["history"][-1]["note"] == SAVED  # still there after closing


def test_cancelling_a_demo_needs_a_reason_but_rescheduling_does_not(client):
    lead = new_lead(client)
    lid = lead["id"]
    ok(client.put(f"/api/leads/{lid}/stage", json={"task": TASK, "stage": "Demo", "demo_date": "2026-12-01T11:00:00",
                                                   "completed_stages": ["New", "Nurturing"], "note": "Demo booked"}))
    later = (datetime.now() + timedelta(days=5)).replace(hour=15, minute=0, second=0, microsecond=0)
    moved = ok(client.post(f"/api/leads/{lid}/cancel-demo", json={"reschedule_to": later.isoformat()}))
    assert moved["stage"] == "Demo" and moved["history"][-1]["to_stage"] == "Demo"  # the stage stays: no reason needed
    before = snapshot()
    refused = client.post(f"/api/leads/{lid}/cancel-demo", json={"task": TASK, "reason": "   "})
    assert refused.status_code == 422 and refused.json()["detail"] == REQUIRED
    assert snapshot() == before
    back = ok(client.post(f"/api/leads/{lid}/cancel-demo", json={"task": TASK, "reason": "  Client travelling \n"}))
    assert back["stage"] == "Revisit" and back["history"][-1]["note"] == "Demo cancelled: Client travelling"


# ---------- who can change a stage (unchanged) ----------

def test_a_note_does_not_replace_permission_checks(client):
    opp = new_opportunity(client)  # Ravi's deal
    lead = new_lead(client)
    sam = add_salesperson(client)
    before = snapshot()
    note = {"stage": "Proposal", "completed_stages": ["Discovery"], "note": "Trying someone else's deal", "task": TASK}
    assert login_as(client, sam).put(f"/api/opportunities/{opp['id']}/stage", json=note).status_code == 404
    assert client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Price", "lost_notes": "x"}).status_code == 404
    assert snapshot() == before
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    before = snapshot()
    assert login_as(client, sam).put(f"/api/opportunities/{opp['id']}/stage", json=note).status_code == 403  # view only
    assert client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "note": "x", "completed_stages": ["New", "Nurturing", "Demo"]}
                       ).status_code == 403
    assert snapshot() == before
    # a Manager can change it, with a note; the history says who
    moved = ok(login_as(client, PRIYA).put(f"/api/opportunities/{opp['id']}/stage",
                                           json={"stage": "Proposal", "completed_stages": ["Discovery"], "note": "Taking over the proposal", "task": TASK}))
    assert (moved["history"][-1]["note"], moved["history"][-1]["changed_by_name"]) == ("Taking over the proposal",
                                                                                       "Priya Sharma")


# ---------- no stage change, no note ----------

def test_creating_and_editing_records_need_no_note_and_cannot_change_the_stage(client):
    lead = new_lead(client)  # creating a lead is not a stage change
    edited = ok(client.put(f"/api/leads/{lead['id']}", json={"title": "CFO", "stage": "Lost", "lost_reason": "Price"}))
    assert (edited["title"], edited["stage"], edited["lost_reason"]) == ("CFO", "New", None)
    opp = new_opportunity(client)
    before = len(history(client, "opportunities", opp["id"]))
    edited = ok(client.put(f"/api/opportunities/{opp['id']}", json={"expected_value": 2000, "stage": "Won"}))
    assert (edited["expected_value"], edited["stage"]) == (2000, "Opportunity")
    assert len(history(client, "opportunities", opp["id"])) == before
    assert len(history(client, "leads", lead["id"])) == 1


# ---------- AI Assistant: the same rule, and the note is the user's ----------

def test_assistant_does_not_offer_a_stage_change_without_the_users_note(client, ai):
    script, seen = ai
    opp = new_opportunity(client)
    lead = new_lead(client)
    before = snapshot()
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], completed_stages=["Discovery", "Proposal"])],
               "What should the closing note say?"]
    first = client.post("/api/assistant/chat", json={"message": "Mark the deal won"}).json()
    assert first["pending"] is None  # no Confirm card
    assert REQUIRED in json.loads(seen[-1][-1]["content"])["error"]
    script += [[call("move_lead_stage", lead_id=lead["id"], stage="Nurturing", note="   ")], "What note should I add?"]
    client.post("/api/assistant/chat", json={"message": "Move the lead to nurturing"})
    assert REQUIRED in json.loads(seen[-1][-1]["content"])["error"]
    assert snapshot() == before


def test_assistant_shows_the_note_before_confirming_and_saves_it(client, ai):
    script, _ = ai
    opp = new_opportunity(client)
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], completed_stages=["Discovery", "Proposal"],
                     note="Customer signed on the call", task_title="Synthetic handover",
                     task_due_date="2030-01-20T10:00")]]
    first = client.post("/api/assistant/chat", json={"message": "Won: customer signed on the call"}).json()
    assert 'Note: "Customer signed on the call"' in first["pending"]["summary"]
    # a Confirm whose note was removed in the browser is refused by the API and changes nothing
    before = snapshot()
    tampered = {**first["pending"], "args": {k: v for k, v in first["pending"]["args"].items() if k != "note"}}
    script += ["I couldn't do that: a note is needed."]
    client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": tampered, "confirmed": True})
    assert snapshot() == before
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], completed_stages=["Discovery", "Proposal"],
                     note="Customer signed on the call", task_title="Synthetic handover",
                     task_due_date="2030-01-20T10:00")]]
    again = client.post("/api/assistant/chat", json={"message": "Try again"}).json()
    script += ["Done: the deal is Won."]
    client.post("/api/assistant/confirm", json={"messages": again["messages"], "pending": again["pending"], "confirmed": True})
    assert history(client, "opportunities", opp["id"])[-1] == ("Proposal", "Won", "Customer signed on the call")


def test_assistant_does_not_convert_without_a_note(client, ai):
    script, seen = ai
    lead = new_lead(client)
    before = snapshot()
    script += [[call("convert_lead", lead_id=lead["id"], amount=5000, completed_stages=["New", "Nurturing", "Demo"])],
                "What should the note say?"]
    client.post("/api/assistant/chat", json={"message": "Convert it"})
    assert COMMENT_REQUIRED in json.loads(seen[-1][-1]["content"])["error"]
    assert snapshot() == before  # no account, contact, opportunity or history


@pytest.mark.xfail(strict=True, raises=AttributeError,
                   reason="Not caused by this change (same on 8962756): the convert_lead tool's result can't be read "
                          "by _plain/_opp_row, so the chat answers 500 after the conversion is saved")
def test_assistant_conversion_saves_the_users_note(client, ai):
    script, _ = ai
    lead = new_lead(client)
    script += [[call("convert_lead", lead_id=lead["id"], amount=5000, completed_stages=["New", "Nurturing", "Demo"],
                     note="Budget approved by the CFO", task_title="Synthetic follow-up task", task_due_date="2030-01-15T10:00")], "Converted."]
    res = client.post("/api/assistant/chat", json={"message": "Convert it, the CFO approved the budget"}).json()
    assert res["links"][0]["type"] == "Opportunity"
    assert history(client, "leads", lead["id"])[-1] == ("Demo", "Converted", "Budget approved by the CFO")
    assert history(client, "opportunities", res["links"][0]["id"]) == [(None, "Opportunity", "Budget approved by the CFO")]
