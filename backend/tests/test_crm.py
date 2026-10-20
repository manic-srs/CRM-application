"""Tests for the full CRM flow. Run from the backend folder:  pytest -v"""
from datetime import datetime, timedelta

LEAD = {"salutation": "Mr.", "first_name": "Arjun", "last_name": "Mehta", "company": "Bright Future Coaching",
        "title": "Owner", "industry": "Education", "email": "arjun@bf.in", "source": "Website", "owner_id": 2}


def new_lead(client, name=None, **extra):
    """name="Neha Gupta" is split into first_name / last_name, like the Salesforce form."""
    if name:
        first, _, last = name.rpartition(" ")
        extra = {"first_name": first or None, "last_name": last, **extra}
    res = client.post("/api/leads", json={**LEAD, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def convert(client, lead_id, **body):
    res = client.post(f"/api/leads/{lead_id}/convert", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def open_tasks(record):
    return [t for t in record["tasks"] if t["status"] == "Open"]


# ---------- login ----------

def test_login(client):
    ok = client.post("/api/auth/login", json={"email": "ravi@crm.test", "password": "Password@123"})
    assert ok.status_code == 200 and ok.json()["user"]["full_name"] == "Ravi Kumar"
    assert client.post("/api/auth/login", json={"email": "ravi@crm.test", "password": "nope"}).status_code == 401
    assert [u["full_name"] for u in client.get("/api/users").json()] == ["Priya Sharma", "Ravi Kumar"]


# ---------- leads ----------

def test_create_lead_starts_new_with_first_task(client):
    lead = new_lead(client)
    assert lead["stage"] == "New" and lead["owner_name"] == "Ravi Kumar"
    assert (lead["salutation"], lead["first_name"], lead["last_name"], lead["name"]) == ("Mr.", "Arjun", "Mehta", "Arjun Mehta")
    assert (lead["title"], lead["industry"]) == ("Owner", "Education")
    assert [t["title"] for t in lead["tasks"]] == ["Make first contact - Arjun Mehta"]
    assert lead["tasks"][0]["is_auto"] is True
    assert [h["to_stage"] for h in lead["history"]] == ["New"]


def test_lead_validation(client):
    assert client.post("/api/leads", json={"company": "x"}).status_code == 422  # last name required
    assert client.post("/api/leads", json={"last_name": "x"}).status_code == 422  # company required
    assert client.post("/api/leads", json={"last_name": "x", "company": "c", "source": "Fax"}).status_code == 422
    assert client.post("/api/leads", json={"last_name": "x", "company": "c", "salutation": "Sir"}).status_code == 422
    assert client.post("/api/leads", json={"last_name": "x", "company": "c", "owner_id": 99}).status_code == 400
    assert client.get("/api/leads/999").status_code == 404


def test_list_filter_search_and_edit(client):
    a = new_lead(client)
    new_lead(client, name="Neha Gupta", company="UrbanNest", email="neha@un.in")
    client.put(f"/api/leads/{a['id']}/stage", json={"stage": "Nurturing"})
    assert len(client.get("/api/leads").json()) == 2
    assert [l["name"] for l in client.get("/api/leads", params={"stage": "Nurturing"}).json()] == ["Arjun Mehta"]
    assert [l["name"] for l in client.get("/api/leads", params={"search": "urban"}).json()] == ["Neha Gupta"]
    assert client.get("/api/leads", params={"stage": "Won"}).status_code == 400
    edited = client.put(f"/api/leads/{a['id']}", json={"phone": "+91 90000 00000"}).json()
    assert edited["phone"] == "+91 90000 00000" and edited["stage"] == "Nurturing"


def test_stage_change_closes_old_task_and_creates_next(client):
    lead = new_lead(client)
    demo_at = "2026-12-01T11:00:00"
    nurt = client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Nurturing", "note": "call in 2 weeks"}).json()
    assert [t["title"] for t in open_tasks(nurt)] == ["Follow-up call - Arjun Mehta"]
    assert any(t["status"] == "Auto-closed" for t in nurt["tasks"])
    demo = client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Demo", "demo_date": demo_at}).json()
    assert demo["demo_date"] == demo_at
    assert [(t["title"], t["due_date"]) for t in open_tasks(demo)] == [("Conduct demo - Arjun Mehta", demo_at)]
    assert [h["to_stage"] for h in demo["history"]] == ["New", "Nurturing", "Demo"]
    assert demo["history"][1]["note"] == "call in 2 weeks"
    # manual correction back is allowed; same stage is not
    assert client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Nurturing"}).status_code == 200
    assert client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Nurturing"}).status_code == 400
    assert client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "Converted"}).status_code == 422


def test_mark_lead_lost(client):
    lead = new_lead(client)
    assert client.post(f"/api/leads/{lead['id']}/lost", json={}).status_code == 422
    assert client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Bored"}).status_code == 422
    lost = client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "No budget", "lost_notes": "next year"}).json()
    assert lost["stage"] == "Lost" and lost["lost_reason"] == "No budget" and lost["closed_at"]
    assert open_tasks(lost) == []
    assert client.put(f"/api/leads/{lead['id']}/stage", json={"stage": "New"}).status_code == 400
    assert client.post(f"/api/leads/{lead['id']}/convert").status_code == 400


# ---------- convert ----------

def test_convert_creates_account_contact_opportunity(client):
    lead = new_lead(client)
    res = convert(client, lead["id"], opportunity_name="Business Fiber", expected_value=180000)
    assert res["lead"]["stage"] == "Converted" and res["lead"]["converted_at"]
    assert res["lead"]["opportunity_id"] == res["opportunity"]["id"]
    assert res["account"]["name"] == "Bright Future Coaching"
    assert res["contact"]["full_name"] == "Arjun Mehta" and res["contact"]["account_id"] == res["account"]["id"]
    assert (res["contact"]["salutation"], res["contact"]["first_name"], res["contact"]["last_name"], res["contact"]["job_title"]) == (
        "Mr.", "Arjun", "Mehta", "Owner")
    assert res["account"]["industry"] == "Education"
    assert res["opportunity"]["probability"] == 20
    opp = res["opportunity"]
    assert (opp["name"], opp["stage"], opp["expected_value"]) == ("Business Fiber", "Opportunity", 180000)
    assert opp["primary_contact_name"] == "Arjun Mehta" and opp["lead_id"] == lead["id"]
    assert res["tasks_auto_closed"] == 1
    assert res["new_task"]["title"] == "Send proposal - Business Fiber"
    assert client.post(f"/api/leads/{lead['id']}/convert").status_code == 400


def test_convert_into_existing_account(client):
    acc = client.post("/api/accounts", json={"name": "Existing Co", "industry": "Retail"}).json()
    res = convert(client, new_lead(client)["id"], account_id=acc["id"])
    assert res["account"]["id"] == acc["id"]
    page = client.get(f"/api/accounts/{acc['id']}").json()
    assert [c["full_name"] for c in page["contacts"]] == ["Arjun Mehta"] and len(page["opportunities"]) == 1


# ---------- opportunities ----------

def test_opportunity_proposal_won(client):
    oid = convert(client, new_lead(client)["id"], expected_value=180000)["opportunity"]["id"]
    prop = client.put(f"/api/opportunities/{oid}/stage", json={"stage": "Proposal"}).json()
    assert [t["title"] for t in open_tasks(prop)] == ["Follow up on proposal - Bright Future Coaching - Opportunity"]
    assert prop["probability"] == 75
    won = client.post(f"/api/opportunities/{oid}/won", json={}).json()
    assert won["stage"] == "Won" and won["final_value"] == 180000 and won["closed_at"] and won["probability"] == 100
    assert open_tasks(won) == []
    assert [h["to_stage"] for h in won["history"]] == ["Opportunity", "Proposal", "Won"]
    assert client.post(f"/api/opportunities/{oid}/lost", json={"lost_reason": "Price"}).status_code == 400


def test_won_needs_a_value(client):
    oid = convert(client, new_lead(client)["id"])["opportunity"]["id"]
    assert client.post(f"/api/opportunities/{oid}/won", json={}).status_code == 400
    assert client.post(f"/api/opportunities/{oid}/won", json={"final_value": 5000}).json()["final_value"] == 5000


def test_opportunity_lost_list_and_edit(client):
    oid = convert(client, new_lead(client)["id"], expected_value=50000)["opportunity"]["id"]
    edited = client.put(f"/api/opportunities/{oid}", json={"expected_value": 60000, "expected_close_date": "2026-12-31"}).json()
    assert edited["expected_value"] == 60000 and edited["expected_close_date"] == "2026-12-31"
    lost = client.post(f"/api/opportunities/{oid}/lost", json={"lost_reason": "Competitor", "lost_notes": "cheaper"}).json()
    assert lost["stage"] == "Lost" and lost["lost_reason"] == "Competitor" and lost["probability"] == 0
    assert [o["id"] for o in client.get("/api/opportunities", params={"stage": "Lost"}).json()] == [oid]
    assert client.get("/api/opportunities/999").status_code == 404


# ---------- tasks, notes, notifications ----------

def test_tasks(client):
    lead = new_lead(client)
    yesterday = (datetime.now() - timedelta(days=1)).replace(microsecond=0).isoformat()
    later = (datetime.now() + timedelta(days=5)).replace(microsecond=0).isoformat()
    t = client.post("/api/tasks", json={"title": "Call back", "due_date": yesterday, "lead_id": lead["id"], "priority": "High"}).json()
    assert t["owner_name"] == "Ravi Kumar" and t["related_type"] == "Lead" and t["is_overdue"] is True
    g = client.post("/api/tasks", json={"title": "Pipeline review", "due_date": later}).json()
    assert g["related_type"] == "General" and g["is_auto"] is False
    assert [x["title"] for x in client.get("/api/tasks", params={"due": "overdue"}).json()] == ["Call back"]
    assert "Pipeline review" in [x["title"] for x in client.get("/api/tasks", params={"due": "upcoming"}).json()]
    done = client.put(f"/api/tasks/{t['id']}/complete").json()
    assert done["status"] == "Done" and done["completed_at"]
    assert client.put(f"/api/tasks/{t['id']}/complete").status_code == 400
    assert client.post("/api/tasks", json={"title": "x", "due_date": later, "lead_id": 1, "opportunity_id": 1}).status_code == 400
    assert client.put(f"/api/tasks/{g['id']}", json={"priority": "Low"}).json()["priority"] == "Low"


def test_notes_and_notifications(client):
    lead = new_lead(client)
    note = client.post("/api/notes", json={"body": "Demo went well", "lead_id": lead["id"]}).json()
    assert note["created_by_name"] == "Ravi Kumar"
    assert client.post("/api/notes", json={"body": "x"}).status_code == 400
    assert [n["body"] for n in client.get(f"/api/leads/{lead['id']}").json()["notes"]] == ["Demo went well"]
    # task alerts are kept as read (not on the bell); an assignment from someone else is on the bell
    assert client.get("/api/notifications", params={"user_id": 2}).json() == []
    new_lead(client, name="Given Away", created_by_id=1)
    bell = client.get("/api/notifications", params={"user_id": 2}).json()
    assert len(bell) == 1 and bell[0]["title"] == "Lead assigned to you"
    client.put(f"/api/notifications/{bell[0]['id']}/read")
    assert client.get("/api/notifications", params={"user_id": 2}).json() == []


# ---------- home and search ----------

def test_home_page(client):
    new_lead(client)
    lost = new_lead(client, name="B")
    client.post(f"/api/leads/{lost['id']}/lost", json={"lost_reason": "Price"})
    won = convert(client, new_lead(client, name="C", company="Won Co")["id"], expected_value=100000)["opportunity"]["id"]
    client.post(f"/api/opportunities/{won}/won", json={"final_value": 90000})
    today = datetime.now().date().isoformat()
    convert(client, new_lead(client, name="D", company="Open Co")["id"], expected_value=40000, expected_close_date=today)
    later = (datetime.now() + timedelta(days=200)).date().isoformat()  # next quarter or later: not in Close Deals
    convert(client, new_lead(client, name="F", company="Later Co")["id"], expected_value=5000, expected_close_date=later)
    demo = new_lead(client, name="E", company="Demo Co")
    client.put(f"/api/leads/{demo['id']}/stage", json={"stage": "Demo", "demo_date": f"{today}T23:30:00"})

    home = client.get("/api/home").json()
    assert home["summary"]["total_leads"] == 6 and home["summary"]["won_deals"] == 1
    assert {p["stage"]: p["total"] for p in home["pipeline"]} == {
        "New": 1, "Nurturing": 0, "Demo": 1, "Opportunity": 2, "Proposal": 0, "Won": 1, "Lost": 1}
    assert home["won_vs_lost"][0] == {"outcome": "Won", "deals": 1, "value": 90000}
    cards = home["seller_home"]
    deals = cards["close_deals"]
    assert (deals["total_pipeline"], deals["open"], deals["won"], deals["lost"]) == (130000, 40000, 90000, 0)
    assert [d["name"] for d in cards["key_deals"]] == ["Open Co - Opportunity", "Later Co - Opportunity"]
    assert [(e["type"], e["name"]) for e in cards["todays_events"]] == [("Demo", "E")]
    assert cards["accounts"]["total"] == 3 and cards["contacts"]["total"] == 3
    assert cards["build_pipeline"]["leads_last_30_days"] == 6
    assert cards["recent_records"]
    assert client.get("/api/home", params={"owner_id": 1}).json()["summary"]["total_leads"] == 0


def test_search(client):
    lead = new_lead(client)
    convert(client, lead["id"], opportunity_name="Fiber deal")
    types = {r["type"] for r in client.get("/api/search", params={"q": "bright"}).json()}
    assert {"Lead", "Account"} <= types
    assert client.get("/api/search", params={"q": "fiber"}).json()[0]["type"] == "Opportunity"


def test_edit_lead_name_updates_full_name(client):
    lead = new_lead(client)
    edited = client.put(f"/api/leads/{lead['id']}", json={"first_name": "Arjun K.", "salutation": "Dr."}).json()
    assert edited["name"] == "Arjun K. Mehta" and edited["salutation"] == "Dr."
    assert client.put(f"/api/leads/{lead['id']}", json={"last_name": ""}).status_code == 422
    assert client.put(f"/api/leads/{lead['id']}", json={"company": None}).status_code == 400


def test_lead_without_first_name(client):
    lead = new_lead(client, first_name=None, last_name="Gupta")
    assert lead["name"] == "Gupta"


def test_contacts_and_probability_edit(client):
    acc = client.post("/api/accounts", json={"name": "Sunrise Hospitals", "industry": "Healthcare"}).json()
    c = client.post("/api/contacts", json={"salutation": "Dr.", "first_name": "Meera", "last_name": "Iyer",
                                           "job_title": "Director", "account_id": acc["id"]}).json()
    assert c["full_name"] == "Meera Iyer" and c["account_name"] == "Sunrise Hospitals"
    assert client.post("/api/contacts", json={"first_name": "x", "account_id": acc["id"]}).status_code == 422
    assert [x["full_name"] for x in client.get("/api/contacts", params={"search": "meera"}).json()] == ["Meera Iyer"]
    oid = convert(client, new_lead(client)["id"])["opportunity"]["id"]
    assert client.put(f"/api/opportunities/{oid}", json={"probability": 40}).json()["probability"] == 40
    assert client.put(f"/api/opportunities/{oid}", json={"probability": 140}).status_code == 422
