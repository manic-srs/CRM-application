"""New Account needs Phone and Industry; New Contact needs Email (a valid address) and Phone. The rules apply to direct
creation (the API and the Assistant's tools) only: lead conversion, New Opportunity and older records with empty
fields keep working. All data is made up."""
import json

import pytest
from sqlalchemy import func, select

from app import assistant, schemas
from app.database import get_db
from app.main import app
from app.models import Account, Contact
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai: a scripted stand-in for the AI model)
from test_assistant_workspace import chat, tool

PRIYA, RAVI, ASHA = 1, 2, 3
TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}
ACCOUNT = {"name": "Synthetic Harbor Co", "industry": "Logistics", "phone": "+1 555 0140"}
CONTACT = {"first_name": "Ana Maria", "last_name": "Okafor", "email": "ana.okafor@harbor.example", "phone": "+1 555 0141"}
BLANKS = [None, "", "   ", "\t\n"]


def db_count(model) -> int:
    with next(app.dependency_overrides[get_db]()) as db:
        return db.scalar(select(func.count()).select_from(model))


def account(client, **changes):
    res = client.post("/api/accounts", json={**ACCOUNT, **changes})
    assert res.status_code == 201, res.text
    return res.json()


def errors(res) -> dict:
    return {e["loc"][-1]: e["msg"] for e in res.json()["detail"]}


# ---------- New Account ----------

@pytest.mark.parametrize("field, message", [("phone", schemas.ACCOUNT_PHONE_REQUIRED),
                                            ("industry", schemas.ACCOUNT_INDUSTRY_REQUIRED)])
@pytest.mark.parametrize("value", ["missing", *BLANKS])
def test_an_account_needs_phone_and_industry(client, field, message, value):
    body = {k: v for k, v in ACCOUNT.items() if not (k == field and value == "missing")}
    if value != "missing":
        body[field] = value
    res = client.post("/api/accounts", json=body)
    assert res.status_code == 422 and errors(res)[field] == message
    assert db_count(Account) == 0  # nothing saved


def test_a_valid_account_is_created_with_its_values_as_typed(client):
    created = account(client, phone="  +44 (20) 7946-0958 ext. 12 ", industry=" Retail ")
    assert (created["phone"], created["industry"]) == ("+44 (20) 7946-0958 ext. 12", "Retail")  # no format imposed
    assert created["owner_id"] == RAVI


def test_the_existing_length_limits_still_apply(client):
    assert client.post("/api/accounts", json={**ACCOUNT, "phone": "1" * 31}).status_code == 422
    assert client.post("/api/accounts", json={**ACCOUNT, "industry": "x" * 101}).status_code == 422
    assert account(client, phone="1" * 30, industry="x" * 100)
    assert db_count(Account) == 1


def test_a_salesperson_still_cant_create_an_account_for_someone_else(client):
    assert client.post("/api/accounts", json={**ACCOUNT, "owner_id": PRIYA}).status_code == 403
    assert db_count(Account) == 0


# ---------- New Contact ----------

@pytest.mark.parametrize("field, message", [("email", schemas.CONTACT_EMAIL_REQUIRED),
                                            ("phone", schemas.CONTACT_PHONE_REQUIRED)])
@pytest.mark.parametrize("value", ["missing", *BLANKS])
def test_a_contact_needs_email_and_phone(client, field, message, value):
    body = {**CONTACT, "account_id": account(client)["id"]}
    if value == "missing":
        del body[field]
    else:
        body[field] = value
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 422 and errors(res)[field] == message
    assert db_count(Contact) == 0


@pytest.mark.parametrize("email", ["ana.okafor", "ana@harbor", "@harbor.example", "ana okafor@harbor.example",
                                   "ana@harbor.example, bo@harbor.example", "ana@@harbor.example"])
def test_a_contact_email_must_be_a_valid_address(client, email):
    res = client.post("/api/contacts", json={**CONTACT, "email": email, "account_id": account(client)["id"]})
    assert res.status_code == 422 and errors(res)["email"] == schemas.CONTACT_EMAIL_INVALID
    assert db_count(Contact) == 0


def test_a_valid_contact_is_created(client):
    acc = account(client)
    res = client.post("/api/contacts", json={**CONTACT, "email": " ana.okafor@harbor.example ", "account_id": acc["id"]})
    assert res.status_code == 201, res.text
    contact = res.json()
    assert (contact["email"], contact["phone"], contact["account_name"]) == (
        "ana.okafor@harbor.example", "+1 555 0141", "Synthetic Harbor Co")


def test_no_new_email_uniqueness_or_domain_rule_for_contacts(client):
    acc = account(client)
    for _ in range(2):  # the same address twice, on a domain unlike the account's: both allowed, as before
        assert client.post("/api/contacts", json={**CONTACT, "email": "shared@other-domain.example",
                                                  "account_id": acc["id"]}).status_code == 201
    assert db_count(Contact) == 2


def test_contact_access_and_ownership_rules_are_unchanged(client):
    other = account(login_as(client, PRIYA), name="Synthetic Private Co")
    login_as(client, RAVI)
    assert client.post("/api/contacts", json={**CONTACT, "account_id": other["id"]}).status_code == 404
    mine = account(client)
    assert client.post("/api/contacts", json={**CONTACT, "account_id": mine["id"], "owner_id": PRIYA}).status_code == 403
    assert client.post("/api/contacts", json={**CONTACT, "account_id": 999999}).status_code == 404
    assert client.post("/api/contacts", json={**CONTACT, "email": "x" * 250 + "@a.example",
                                              "account_id": mine["id"]}).status_code == 422  # length limit kept
    assert db_count(Contact) == 0


# ---------- the other ways accounts and contacts are made ----------

def test_lead_conversion_still_creates_an_account_and_contact_without_phone_or_industry(client):
    lead = client.post("/api/leads", json={"first_name": "Bo", "last_name": "Lindqvist", "company": "Synthetic Fjord AB",
                                           "email": "bo@fjord.example", "welcome_email": False}).json()
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "note": "Synthetic conversion", "task": TASK, "completed_stages": ["New", "Nurturing", "Demo"]})
    assert res.status_code == 200, res.text
    assert (res.json()["account"]["phone"], res.json()["account"]["industry"]) == (None, None)
    assert res.json()["contact"]["phone"] is None


def test_new_opportunity_still_accepts_a_contact_without_email_or_phone(client):
    res = client.post("/api/opportunities", json={
        "name": "Synthetic pilot", "account_name": "Synthetic Delta Ltd", "contact_last_name": "Moreau",
        "note": "Synthetic opening note", "task": TASK})
    assert res.status_code == 201, res.text


def test_older_records_with_empty_fields_still_open_list_and_take_conversions(client):
    with next(app.dependency_overrides[get_db]()) as db:
        legacy = Account(name="Synthetic Legacy Co", owner_id=RAVI)  # created before Phone and Industry were required
        db.add(legacy)
        db.flush()
        db.add(Contact(last_name="Legacy", account_id=legacy.id, owner_id=RAVI))
        db.commit()
        legacy_id = legacy.id
    assert client.get(f"/api/accounts/{legacy_id}").status_code == 200
    assert [c["last_name"] for c in client.get("/api/contacts", params={"account_id": legacy_id}).json()] == ["Legacy"]
    lead = client.post("/api/leads", json={"last_name": "Iyer", "company": "Synthetic Legacy Co",
                                           "email": "iyer@legacy.example", "welcome_email": False}).json()
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "note": "Synthetic conversion", "task": TASK, "completed_stages": ["New", "Nurturing", "Demo"],
        "account_id": legacy_id})
    assert res.status_code == 200 and res.json()["account"]["id"] == legacy_id
    # a contact can still be added to the older account, with the new rules
    assert client.post("/api/contacts", json={**CONTACT, "account_id": legacy_id}).status_code == 201


# ---------- the Assistant's tools ----------

def test_the_assistant_tools_mark_the_fields_required():
    defined = {t["function"]["name"]: t["function"]["parameters"]["required"] for t in assistant.TOOLS}
    assert {"name", "industry", "phone"} <= set(defined["create_account"])
    assert {"account_id", "last_name", "email", "phone"} <= set(defined["create_contact"])


def test_the_assistant_cant_create_an_account_or_contact_without_them(client, ai):
    script, seen = ai
    acc = account(client)
    script += [[tool("create_account", {"name": "Synthetic Gap Co", "industry": "  "}),
                call("create_contact", account_id=acc["id"], last_name="Rao", email="not-an-email")],
               "I need a few more details."]
    chat(client, "add Synthetic Gap Co and Dev Rao")
    results = [json.loads(m["content"]) for m in seen[-1] if m["role"] == "tool"]
    assert schemas.ACCOUNT_INDUSTRY_REQUIRED in results[0]["error"] and schemas.ACCOUNT_PHONE_REQUIRED in results[0]["error"]
    assert schemas.CONTACT_EMAIL_INVALID in results[1]["error"] and schemas.CONTACT_PHONE_REQUIRED in results[1]["error"]
    assert (db_count(Account), db_count(Contact)) == (1, 0)


def test_the_assistant_creates_them_with_the_required_fields(client, ai):
    script, seen = ai
    acc = account(client)
    script += [[tool("create_account", {"name": "Synthetic Gap Co", "industry": "Retail", "phone": "+1 555 0150"}),
                call("create_contact", account_id=acc["id"], last_name="Rao", email="dev.rao@harbor.example",
                     phone="+1 555 0151")],
               "Done."]
    chat(client, "add Synthetic Gap Co (retail, +1 555 0150) and Dev Rao, dev.rao@harbor.example, +1 555 0151")
    results = [json.loads(m["content"]) for m in seen[-1] if m["role"] == "tool"]
    assert "error" not in results[0] and "error" not in results[1]
    assert (db_count(Account), db_count(Contact)) == (2, 1)
