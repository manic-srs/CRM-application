"""No duplicate accounts, contacts or opportunities: New Opportunity (Opportunities and Account pages) and Convert reuse the
company's account and the person's contact, and the same open opportunity for the same person at the same company can't
be handled by two salespeople. All data is made up."""
from conftest import login_as
from test_opportunity_attachments import add_salesperson

TASK = {"title": "Synthetic first call", "due_date": "2030-01-15T10:00:00"}
DONE = {"completed_stages": ["New", "Nurturing", "Demo"]}
PRIYA, RAVI, ASHA = 1, 2, 3


def new_lead(client, email, company="Brightline Logistics", first="Mira", last="Shah", **extra):
    res = client.post("/api/leads", json={"first_name": first, "last_name": last, "company": company, "email": email,
                                          "welcome_email": False, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def convert(client, lead_id, **body):
    return client.post(f"/api/leads/{lead_id}/convert", json={"task": TASK, "note": "Synthetic conversion note", **DONE, **body})


def create(client, **body):
    return client.post("/api/opportunities", json={"task": TASK, "note": "Synthetic opening note", **body})


def counts(client):
    login_as(client, PRIYA)  # the Manager sees everything
    return len(client.get("/api/accounts").json()), len(client.get("/api/contacts").json())


# ---------- New Opportunity ----------

def test_new_opportunity_creates_account_contact_first_task_and_history(client):
    res = create(client, name="Brightline CRM rollout", account_name="Brightline Logistics", expected_value=5000,
                 contact_first_name="Mira", contact_last_name="Shah", contact_email="mira@brightline.test")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["reused"] == {"account": False, "contact": False}
    opp = body["opportunity"]
    assert (opp["stage"], opp["owner_id"], opp["account_name"], opp["primary_contact_name"]) == \
        ("Opportunity", RAVI, "Brightline Logistics", "Mira Shah")
    assert body["new_task"]["title"] == "Synthetic first call"
    detail = client.get(f"/api/opportunities/{opp['id']}").json()
    assert detail["history"][0]["to_stage"] == "Opportunity" and detail["history"][0]["note"] == "Synthetic opening note"


def test_new_opportunity_reuses_the_company_account_and_the_person_contact(client):
    first = create(client, name="Deal one", account_name="Brightline Logistics, Inc.",
                   contact_last_name="Shah", contact_email="mira@brightline.test").json()
    # another salesperson, same company (different spelling) and same person: nothing is created twice
    sam = add_salesperson(client)
    res = create(login_as(client, sam), name="Deal two", account_name="brightline logistics",
                 contact_last_name="Shah", contact_email="MIRA@brightline.test")
    assert res.status_code == 201, res.text
    second = res.json()
    assert second["reused"] == {"account": True, "contact": True}
    assert second["account"]["id"] == first["account"]["id"] and second["contact"]["id"] == first["contact"]["id"]
    assert counts(client) == (1, 1)


def test_the_same_open_opportunity_cant_be_handled_by_two_salespeople(client):
    create(client, name="Brightline CRM Rollout", account_name="Brightline Logistics",
           contact_last_name="Shah", contact_email="mira@brightline.test")
    sam = add_salesperson(client)
    res = create(login_as(client, sam), name="brightline  crm rollout!", account_name="Brightline Logistics",
                 contact_last_name="Shah", contact_email="mira@brightline.test")
    assert res.status_code == 409
    assert "Ravi Kumar already has the open opportunity \"Brightline CRM Rollout\"" in res.json()["detail"]
    assert counts(client) == (1, 1)
    # the owner can't open it twice either
    again = create(login_as(client, RAVI), name="Brightline CRM rollout", account_name="Brightline Logistics",
                   contact_last_name="Shah", contact_email="mira@brightline.test")
    assert again.status_code == 409 and again.json()["detail"].startswith("You already have")


def test_a_different_opportunity_or_person_is_allowed_and_a_closed_one_can_be_reopened(client):
    first = create(client, name="Rollout", account_name="Brightline Logistics", contact_last_name="Shah",
                   contact_email="mira@brightline.test").json()
    assert create(client, name="Support contract", account_name="Brightline Logistics", contact_last_name="Shah",
                  contact_email="mira@brightline.test").status_code == 201
    assert create(client, name="Rollout", account_name="Brightline Logistics", contact_last_name="Iyer",
                  contact_email="dev@brightline.test").status_code == 201
    client.post(f"/api/opportunities/{first['opportunity']['id']}/lost",
                json={"lost_reason": "Price", "lost_notes": "Synthetic note", "notify_customer": False})
    assert create(client, name="Rollout", account_name="Brightline Logistics", contact_last_name="Shah",
                  contact_email="mira@brightline.test").status_code == 201  # the old one is closed


def test_from_the_account_page_with_an_existing_contact(client):
    acc = client.post("/api/accounts", json={"name": "Northwind Health"}).json()
    contact = client.post("/api/contacts", json={"last_name": "Fernandes", "account_id": acc["id"]}).json()
    res = create(client, name="Northwind pilot", account_id=acc["id"], primary_contact_id=contact["id"])
    assert res.status_code == 201 and res.json()["reused"] == {"account": True, "contact": True}
    assert create(client, name="Northwind pilot", account_id=acc["id"], primary_contact_id=contact["id"]).status_code == 409
    other = client.post("/api/accounts", json={"name": "Other Co"}).json()
    assert create(client, name="X", account_id=other["id"], primary_contact_id=contact["id"]).status_code == 400


def test_new_opportunity_rules(client):
    assert create(client, name="X", contact_last_name="Shah").status_code == 422  # no account
    assert create(client, name="X", account_name="Acme").status_code == 422  # no contact
    res = client.post("/api/opportunities", json={"name": "X", "account_name": "Acme", "contact_last_name": "S", "task": TASK})
    assert res.status_code == 422  # no note
    res = client.post("/api/opportunities", json={"name": "X", "account_name": "Acme", "contact_last_name": "S", "note": "n"})
    assert res.status_code == 422  # no first task
    assert create(login_as(client, ASHA), name="X", account_name="Acme", contact_last_name="S").status_code == 403
    # a Salesperson can't give it to someone else; a Manager can
    assert create(login_as(client, RAVI), name="X", account_name="Acme", contact_last_name="S",
                  owner_id=PRIYA).status_code == 403
    res = create(login_as(client, PRIYA), name="X", account_name="Acme", contact_last_name="S", owner_id=RAVI)
    assert res.status_code == 201 and res.json()["opportunity"]["owner_id"] == RAVI


# ---------- Convert ----------

def test_convert_reuses_the_account_and_contact_and_blocks_a_second_salesperson(client):
    lead = new_lead(client, "mira@brightline.test")
    first = convert(client, lead["id"])
    assert first.status_code == 200, first.text
    assert first.json()["reused"] == {"account": False, "contact": False}
    # the same person (same name, same company) comes in again as another salesperson's lead, with another email
    sam = add_salesperson(client)
    again = new_lead(login_as(client, sam), "mira.shah@brightline.test", company="Brightline Logistics LLC")
    res = convert(client, again["id"])
    assert res.status_code == 409
    assert "Ravi Kumar already has the open opportunity \"Brightline Logistics - Opportunity\"" in res.json()["detail"]
    assert client.get(f"/api/leads/{again['id']}").json()["stage"] == "New"  # nothing changed
    assert counts(client) == (1, 1)
    # a different opportunity for the same person is fine, on the same account and contact
    res = convert(login_as(client, sam), again["id"], opportunity_name="Brightline warehouse add-on")
    assert res.status_code == 200, res.text
    assert res.json()["reused"] == {"account": True, "contact": True}
    assert counts(client) == (1, 1)


def test_convert_with_a_chosen_account_still_reuses_the_contact(client):
    acc = client.post("/api/accounts", json={"name": "Northwind Health"}).json()
    contact = client.post("/api/contacts", json={"first_name": "Mira", "last_name": "Shah", "email": "mira@northwind.test",
                                                 "account_id": acc["id"]}).json()
    lead = new_lead(client, "mira.s@northwind.test", company="Something Else")
    res = convert(client, lead["id"], account_id=acc["id"])
    assert res.status_code == 200, res.text
    assert res.json()["contact"]["id"] == contact["id"] and res.json()["reused"] == {"account": True, "contact": True}


def test_renaming_into_a_duplicate_is_refused(client):
    one = create(client, name="Rollout", account_name="Acme", contact_last_name="S", contact_email="s@acme.test").json()
    two = create(client, name="Support", account_name="Acme", contact_last_name="S", contact_email="s@acme.test").json()
    res = client.put(f"/api/opportunities/{two['opportunity']['id']}", json={"name": "ROLLOUT"})
    assert res.status_code == 409
    assert client.put(f"/api/opportunities/{one['opportunity']['id']}", json={"name": "Rollout"}).status_code == 200


# ---------- the check shown before saving ----------

def test_duplicate_check_hides_what_the_user_cant_open(client):
    create(login_as(client, PRIYA), name="Rollout", account_name="Brightline Logistics", contact_first_name="Mira",
           contact_last_name="Shah", contact_email="mira@brightline.test")
    login_as(client, RAVI)  # sees only his own records
    res = client.get("/api/opportunities/duplicate-check",
                     params={"company": "Brightline Logistics Inc", "email": "mira@brightline.test", "name": "rollout"}).json()
    assert res["account"]["owner"] == "Priya Sharma" and res["account"]["id"] is None and not res["account"]["can_open"]
    assert res["contact"]["name"] == "Mira Shah"
    assert res["duplicate"]["name"] == "Rollout" and res["duplicate"]["id"] is None and res["duplicate"]["owner"] == "Priya Sharma"
    res = client.get("/api/opportunities/duplicate-check",
                     params={"company": "Brightline Logistics", "email": "mira@brightline.test", "name": "Other deal"}).json()
    assert res["duplicate"] is None and [r["name"] for r in res["related"]] == ["Rollout"]
    lead = new_lead(client, "mira.shah@brightline.test")  # same name and company, another email
    res = client.get("/api/opportunities/duplicate-check", params={"lead_id": lead["id"]}).json()
    assert res["account"]["name"] == "Brightline Logistics" and res["contact"]["name"] == "Mira Shah"
    assert res["duplicate"] is None and [r["name"] for r in res["related"]] == ["Rollout"]  # the default name differs
    res = client.get("/api/opportunities/duplicate-check", params={"lead_id": lead["id"], "name": "Rollout"}).json()
    assert res["duplicate"]["owner"] == "Priya Sharma"


def test_a_salesperson_can_open_the_shared_account_of_their_deal(client):
    acc = login_as(client, PRIYA).post("/api/accounts", json={"name": "Northwind Health"}).json()
    login_as(client, RAVI)
    assert client.get(f"/api/accounts/{acc['id']}").status_code == 404
    assert acc["id"] not in [a["id"] for a in client.get("/api/accounts").json()]
    create(client, name="Pilot", account_name="Northwind Health", contact_last_name="Rao")
    detail = client.get(f"/api/accounts/{acc['id']}")
    assert detail.status_code == 200 and [o["name"] for o in detail.json()["opportunities"]] == ["Pilot"]
    assert acc["id"] in [a["id"] for a in client.get("/api/accounts").json()]
