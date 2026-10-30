"""AI Assistant: the tool loop, permissions and the Confirm step, with a scripted stand-in for the AI model."""
import json

import pytest

from app import assistant
from conftest import login_as


def call(name, **args):
    return {"id": f"call_{name}_{len(json.dumps(args))}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def ai(monkeypatch):
    """Replaces the OpenAI call: each item in `script` is what the model answers next."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    script, seen = [], []

    def fake(messages):
        seen.append(messages)
        step = script.pop(0)
        return {"role": "assistant", "content": step} if isinstance(step, str) else {"role": "assistant", "content": "", "tool_calls": step}

    monkeypatch.setattr(assistant, "call_model", fake)
    return script, seen


def test_off_without_api_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert client.get("/api/assistant/status").json()["enabled"] is False
    res = client.post("/api/assistant/chat", json={"message": "hi"})
    assert res.status_code == 503 and "OPENAI_API_KEY" in res.json()["detail"]


def test_create_lead_from_one_sentence(client, ai):
    script, seen = ai
    script += [[call("create_lead", first_name="Mohan", last_name="Reddy", company="PwC", title="Senior Consultant",
                     email="mohan@pwc.example", source="Referral")],
               "Created lead Mohan Reddy (PwC)."]
    res = client.post("/api/assistant/chat", json={"message": "Create a lead Mohan Reddy, Senior Consultant at PwC"}).json()
    assert res["reply"] == "Created lead Mohan Reddy (PwC)." and res["pending"] is None
    assert res["links"][0]["type"] == "Lead" and res["links"][0]["name"] == "Mohan Reddy"
    lead = client.get(f"/api/leads/{res['links'][0]['id']}").json()
    assert lead["owner_name"] == "Ravi Kumar" and lead["stage"] == "New" and lead["source"] == "Referral"
    # the model saw who the user is, and the tool result
    assert "Ravi Kumar (Salesperson)" in seen[0][0]["content"]
    assert json.loads(seen[1][-1]["content"])["company"] == "PwC"
    # no welcome email unless asked
    assert not any(e for e in client.get("/api/emails", params={"lead_id": lead["id"]}).json())


def test_missing_permission_is_explained_not_done(client, ai):
    script, seen = ai
    priyas = login_as(client, 1).post("/api/leads", json={"last_name": "Shah", "company": "Orbit"}).json()
    script += [[call("move_lead_stage", lead_id=priyas["id"], stage="Nurturing")], "You can't change that lead."]
    res = login_as(client, 2).post("/api/assistant/chat", json={"message": "Move Shah to nurturing"}).json()
    assert "error" in json.loads(seen[1][-1]["content"])  # Ravi can't see Priya's lead: the API refused
    assert login_as(client, 1).get(f"/api/leads/{priyas['id']}").json()["stage"] == "New"


def test_won_waits_for_confirm(client, ai):
    script, _ = ai
    lead = client.post("/api/leads", json={"last_name": "Iyer", "company": "Sunrise"}).json()
    opp = client.post(f"/api/leads/{lead['id']}/convert",
                      json={"expected_value": 25000, "completed_stages": ["Nurturing", "Demo"]}).json()["opportunity"]
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], final_amount=24000,
                     completed_stages=["Proposal"])]]
    first = client.post("/api/assistant/chat", json={"message": "Mark the Sunrise deal won for 24k"}).json()
    p = first["pending"]
    assert p["tool"] == "mark_opportunity_won" and "24,000" in p["summary"]
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Opportunity"  # nothing happened yet
    script += ["Done: the deal is Won."]
    done = client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": p, "confirmed": True}).json()
    assert done["reply"] == "Done: the deal is Won." and done["links"][0]["type"] == "Opportunity"
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Won"
    # the same confirmation can't be replayed
    again = client.post("/api/assistant/confirm", json={"messages": done["messages"], "pending": p, "confirmed": True})
    assert again.status_code == 400


def test_cancel_leaves_record_alone(client, ai):
    script, _ = ai
    lead = client.post("/api/leads", json={"last_name": "Das", "company": "Acme"}).json()
    script += [[call("mark_lead_lost", lead_id=lead["id"], reason="No budget")], "OK, I left it open."]
    first = client.post("/api/assistant/chat", json={"message": "Das has no budget, close it"}).json()
    done = client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": first["pending"],
                                                       "confirmed": False}).json()
    assert done["reply"] == "OK, I left it open."
    assert client.get(f"/api/leads/{lead['id']}").json()["stage"] == "New"


def test_new_message_instead_of_confirm_keeps_conversation_valid(client, ai):
    script, seen = ai
    lead = client.post("/api/leads", json={"last_name": "Sen", "company": "Acme"}).json()
    script += [[call("delete_lead", lead_id=lead["id"])], "Sure, here are your tasks."]
    first = client.post("/api/assistant/chat", json={"message": "delete Sen"}).json()
    client.post("/api/assistant/chat", json={"messages": first["messages"], "message": "actually, show my tasks"})
    # the unconfirmed call was answered as "not confirmed" before the new message, and the lead still exists
    tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
    assert "Not confirmed" in tool_msgs[-1]["content"]
    assert client.get(f"/api/leads/{lead['id']}").status_code == 200


def test_stage_rule_comes_back_as_a_question(client, ai):
    script, seen = ai
    lead = client.post("/api/leads", json={"last_name": "Rao", "company": "Acme"}).json()
    script += [[call("move_lead_stage", lead_id=lead["id"], stage="Demo", demo_date="2026-12-01T11:00")],
               "Was Nurturing already done?",
               [call("move_lead_stage", lead_id=lead["id"], stage="Demo", demo_date="2026-12-01T11:00",
                     completed_stages=["Nurturing"])],
               "Booked the demo for 1 Dec 2026, 11:00 AM."]
    first = client.post("/api/assistant/chat", json={"message": "book a demo with Rao on 1 Dec 11am"}).json()
    assert "Nurturing" in json.loads(seen[1][-1]["content"])["error"]
    client.post("/api/assistant/chat", json={"messages": first["messages"], "message": "yes, nurturing was done"})
    assert client.get(f"/api/leads/{lead['id']}").json()["stage"] == "Demo"


def test_lookups_and_transfer_by_name(client, ai):
    script, _ = ai
    lead = client.post("/api/leads", json={"last_name": "Nair", "company": "Globex"}).json()
    script += [[call("search", query="Globex"), call("list_users")],
               [call("transfer_lead", lead_id=lead["id"], to_user_name="Priya")]]
    first = client.post("/api/assistant/chat", json={"message": "give the Globex lead to Priya"}).json()
    assert first["pending"]["tool"] == "transfer_lead" and "Priya" in first["pending"]["summary"]
    script += ["Transferred."]
    client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": first["pending"], "confirmed": True})
    assert client.get("/api/leads", params={"search": "Nair"}).json() == []  # Ravi no longer owns it
    assert login_as(client, 1).get(f"/api/leads/{lead['id']}").json()["owner_name"] == "Priya Sharma"
