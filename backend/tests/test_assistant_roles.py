"""AI Assistant by role (each role is offered only its own actions; every change is in the Admin's Activity Log) and
Draft with AI in Email Campaigns. No real AI service is called. All data is made up."""
import json

import httpx
import pytest
from conftest import login_as

from app import ai_email, assistant, mailer


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_ENV_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(mailer, "send", lambda *a, **kw: None)


# ---------- role-based tools and the Admin's Activity Log ----------

def test_tools_follow_the_role(client):
    from app.security import Acting
    admin = Acting(id=3, role="Admin", full_name="Asha Rao", email="asha@crm.test", permissions=frozenset())
    names = {t["function"]["name"] for t in assistant.tools_for(admin)}
    assert "crm_report" in names and "list_users" in names
    assert not names & {"create_lead", "convert_lead", "mark_opportunity_won", "create_task"}
    seller = Acting(id=2, role="Salesperson", full_name="Ravi Kumar", email="ravi@crm.test", permissions=frozenset({"transfer_leads"}))
    names = {t["function"]["name"] for t in assistant.tools_for(seller)}
    assert {"create_lead", "convert_lead", "transfer_lead"} <= names
    no_transfer = Acting(id=2, role="Salesperson", full_name="Ravi Kumar", email="ravi@crm.test", permissions=frozenset())
    assert "transfer_lead" not in {t["function"]["name"] for t in assistant.tools_for(no_transfer)}


def test_ai_changes_are_in_the_admins_activity_log(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    replies = iter([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "create_lead", "arguments": json.dumps({"first_name": "Rhea", "last_name": "Kapoor", "company": "Lumen",
                                                            "email": "rhea@lumen.example", "company_website": "lumen.example",
                                                            "company_linkedin_url": "https://www.linkedin.com/company/lumen-example"})}}]},
        {"role": "assistant", "content": "Done: Rhea Kapoor."},
    ])
    monkeypatch.setattr(assistant, "call_model", lambda messages: next(replies))
    res = client.post("/api/assistant/chat", json={"message": "Create a lead Rhea Kapoor at Lumen, rhea@lumen.example"})
    assert res.status_code == 200, res.text
    log = login_as(client, 3).get("/api/activity", params={"category": "ai"}).json()
    assert log["total"] == 1 and log["rows"][0]["action"] == "AI Assistant: Create lead"
    assert log["rows"][0]["by"] == "Ravi Kumar" and "Rhea Kapoor" in log["rows"][0]["target"]


# ---------- Email Campaigns: Draft with AI ----------

def test_campaign_draft_uses_placeholders(client, monkeypatch):
    monkeypatch.setenv("EMAIL_DRAFT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    reply = json.dumps({"outcome": "draft", "subject": "A quick idea for {Company Name}",
                        "body": "Hi {First Name},\n\nWould {company} like a 20-minute demo of SalesTrack next week?\n\n"
                                "Thanks,\n{Your Name}\n{phone}"})
    captured = []
    real_client = httpx.AsyncClient

    def handler(req):
        captured.append(req)
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": reply}]}]})

    monkeypatch.setattr(ai_email.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    res = client.post("/api/campaigns/draft", json={"instructions": "Invite them to a 20-minute demo next week"})
    assert res.status_code == 200, res.text
    draft = res.json()
    assert draft["subject"] == "A quick idea for {company}"
    assert draft["body"].startswith("Hi {first_name},") and "{sender_name}" in draft["body"] and "{phone}" not in draft["body"]
    assert str(captured[0].url) == "https://api.openai.com/v1/responses"
    # empty requests and unrelated ones are refused before calling the AI
    assert client.post("/api/campaigns/draft", json={"instructions": ""}).status_code == 422
    assert client.post("/api/campaigns/draft", json={"action": "shorten", "current_body": ""}).status_code == 422
    assert len(captured) == 1
    # the drafted text is accepted by New Campaign
    made = client.post("/api/campaigns", json={"name": "Demo invite", "subject": draft["subject"], "body": draft["body"],
                                               "emails": [{"email": "asha.rao@acme-retail.example"}]})
    assert made.status_code == 201, made.text


def test_the_assistant_asks_for_the_required_fields_of_the_form(client, monkeypatch):
    """A lead missing fields the New Lead form requires isn't created; the model is told exactly which to ask for."""
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    seen = []
    replies = iter([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "create_lead", "arguments": json.dumps({"first_name": "Janu", "last_name": "Rao", "company": "Northwind",
                                                            "email": "janu@northwind.example"})}}]},
        {"role": "assistant", "content": "Please give the Company Website and Company LinkedIn URL."},
    ])
    monkeypatch.setattr(assistant, "call_model", lambda messages: seen.append(messages) or next(replies))
    res = client.post("/api/assistant/chat", json={"message": "New lead Janu Rao, Northwind, janu@northwind.example"}).json()
    assert res["links"] == []
    told = json.loads(seen[1][-1]["content"])["error"]
    assert "Company Website, Company LinkedIn URL" in told and "Email" not in told
    assert "New lead: Last Name, Company, Email, Company Website, Company LinkedIn URL" in seen[0][0]["content"]
    assert assistant.missing_required("create_task", {"title": "Call", "due_date": " "}) == ["Due Date"]
    assert assistant.missing_required("create_opportunity", {"name": "Deal", "account_name": "Northwind",
                                                             "contact_id": 4}) == []
