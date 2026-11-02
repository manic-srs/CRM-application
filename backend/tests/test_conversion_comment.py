"""One mandatory Conversion Comment when a lead is converted. It is the conversion's note from the stage-note rule (the
same request field, `note`, and the same check), with its own label and message. All data is made up."""
import json

import pytest

from app.assistant import TOOLS
from app.main import app
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai: a scripted stand-in for the AI model)
from test_mandatory_stage_notes import history, message, new_lead, sent, snapshot  # noqa: F401 (sent: autouse)
from test_opportunity_attachments import ASHA, PRIYA, add_salesperson

TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}  # every stage change needs one

COMMENT_REQUIRED = "Enter a conversion comment."
DONE = {"completed_stages": ["New", "Nurturing", "Demo"], "expected_value": 2500}


def convert(client, lead_id, **body):
    return client.post(f"/api/leads/{lead_id}/convert", json={"task": TASK, **DONE, **body})


@pytest.mark.parametrize("body", [{}, {"note": None}, {"note": ""}, {"note": "   "}, {"note": "\n\t \r\n"}],
                         ids=["missing", "null", "empty", "spaces", "whitespace"])
def test_a_missing_or_blank_conversion_comment_is_refused_and_nothing_is_created(client, sent, body):
    lead = new_lead(client)
    before, mails = snapshot(), len(sent)
    res = convert(client, lead["id"], **body)
    assert res.status_code == 422, res.text
    assert [(e["loc"], e["msg"]) for e in res.json()["detail"]] == [(["body", "note"], COMMENT_REQUIRED)]
    assert snapshot() == before  # no account, contact, opportunity, history, task, notification or file
    assert len(sent) == mails  # no email
    assert client.get(f"/api/leads/{lead['id']}").json()["stage"] == "New"


@pytest.mark.parametrize("note", [7, ["a comment"], {"text": "a comment"}, False])
def test_a_conversion_comment_must_be_text(client, note):
    lead = new_lead(client)
    before = snapshot()
    res = convert(client, lead["id"], note=note)
    assert res.status_code == 422 and "The note must be text." in message(res)
    assert snapshot() == before


def test_the_comment_is_saved_in_both_histories(client, sent):
    lead = new_lead(client)
    res = convert(client, lead["id"], note="  Budget approved by the CFO.\n  - pilot first  \n")
    assert res.status_code == 200, res.text
    saved = "Budget approved by the CFO.\n  - pilot first"  # trimmed around, formatting inside kept
    assert history(client, "leads", lead["id"])[-1] == ("Demo", "Converted", saved)
    assert history(client, "opportunities", res.json()["opportunity"]["id"]) == [(None, "Opportunity", saved)]
    # skipped stages keep their own confirmation rows; the comment goes only on the conversion
    assert [note for *_, note in history(client, "leads", lead["id"])[1:-1]] == ["Confirmed as completed"] * 2  # Nurturing, Demo


def test_conversion_rules_and_permissions_are_unchanged(client):
    lead = new_lead(client)  # Ravi's, at New
    before = snapshot()
    skipped = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "note": "Ready to buy"})
    assert skipped.status_code == 409 and "Complete Nurturing and Demo" in skipped.json()["detail"]
    assert snapshot() == before
    sam = add_salesperson(client)
    before = snapshot()
    assert convert(login_as(client, sam), lead["id"], note="Not my lead").status_code == 404  # can't see it
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    before = snapshot()
    assert convert(login_as(client, sam), lead["id"], note="View only").status_code == 403
    admin = convert(login_as(client, ASHA), lead["id"], note="Admins don't create opportunities")
    assert admin.status_code == 403
    assert snapshot() == before
    assert convert(login_as(client, PRIYA), lead["id"], note="Manager converting for the team").status_code == 200


def test_other_stage_notes_keep_their_own_message(client):
    lead = new_lead(client)
    res = client.put(f"/api/leads/{lead['id']}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], "note": " "})
    assert res.status_code == 422 and message(res) == "Enter a note to change the stage."
    res = client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Price", "lost_notes": ""})
    assert res.status_code == 422 and message(res) == "Enter a note to change the stage."


def test_the_api_still_lists_the_comment_as_required(client):
    schema = app.openapi()["components"]["schemas"]["ConvertLead"]
    assert "note" in schema["required"]
    tool = next(t["function"] for t in TOOLS if t["function"]["name"] == "convert_lead")
    assert "note" in tool["parameters"]["required"] and "Conversion Comment" in tool["parameters"]["properties"]["note"]["description"]


def test_assistant_asks_for_the_comment_instead_of_converting(client, ai):
    script, seen = ai
    lead = new_lead(client)
    before = snapshot()
    script += [[call("convert_lead", lead_id=lead["id"], completed_stages=["New", "Nurturing", "Demo"], note="  ")],
               "What is your conversion comment?"]
    reply = client.post("/api/assistant/chat", json={"message": "Convert it"}).json()
    assert reply["pending"] is None and COMMENT_REQUIRED in json.loads(seen[-1][-1]["content"])["error"]
    assert snapshot() == before
