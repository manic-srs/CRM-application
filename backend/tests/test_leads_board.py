"""Leads Kanban: the board loads GET /api/leads/page once per status column (stage=...), with the same list view,
filters, search and access rules as the Leads table. These checks pin that contract. All data is made up."""
import itertools

from conftest import login_as

TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}  # every stage change needs one

EMAILS = itertools.count(1)
BOARD = ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted", "Lost"]


def lead(client, last_name, **extra):
    res = client.post("/api/leads", json={"last_name": last_name, "company": "Board Synthetic Co", "welcome_email": False,
                                          "email": f"board{next(EMAILS)}@example.test", **extra})
    assert res.status_code == 201, res.text
    return res.json()


def column(client, stage, **params):
    res = client.get("/api/leads/page", params={"view": "all", "stage": stage, "limit": 100, **params})
    assert res.status_code == 200, res.text
    return res.json()


def counts(client, **params):
    return {stage: column(client, stage, **params)["total"] for stage in BOARD}


def test_each_column_counts_only_its_status_within_the_list_view_and_search(client):
    lead(client, "Fresh")
    nurturing = lead(client, "Warm", title="Buyer")
    demo = lead(client, "Booked")
    converted = lead(client, "Won Over")
    lost = lead(client, "Gone")
    not_fit = lead(client, "Not Fit")
    note = {"note": "Synthetic board check"}
    assert client.post(f"/api/leads/{not_fit['id']}/unqualified", json={"reason": "Not a fit", "notes": "x"}).status_code == 200
    assert client.put(f"/api/leads/{nurturing['id']}/stage", json={"task": TASK, "stage": "Nurturing", "completed_stages": ["New"], **note}).status_code == 200
    assert client.put(f"/api/leads/{demo['id']}/stage", json={"task": TASK, "stage": "Demo", "completed_stages": ["New", "Nurturing"],
                                                              "demo_date": "2026-12-01T11:00:00", **note}).status_code == 200
    assert client.post(f"/api/leads/{converted['id']}/convert", json={"task": TASK, "completed_stages": ["New", "Nurturing", "Demo"],
                                                                      **note}).status_code == 200
    assert client.post(f"/api/leads/{lost['id']}/lost", json={"lost_reason": "Price", "lost_notes": "x",
                                                              "notify_customer": False}).status_code == 200

    assert counts(client) == {"New": 1, "Nurturing": 1, "Revisit": 0, "Demo": 1, "Converted": 1, "Unqualified": 1, "Lost": 1}
    assert [l["name"] for l in column(client, "Nurturing")["items"]] == ["Warm"]
    card = column(client, "Nurturing")["items"][0]
    assert (card["company"], card["title"], card["owner_name"]) == ("Board Synthetic Co", "Buyer", "Ravi Kumar")
    # open list views have no closed leads; closed views only their own status
    assert counts(client, view="all_open") == {"New": 1, "Nurturing": 1, "Revisit": 0, "Demo": 1,
                                               "Converted": 0, "Unqualified": 0, "Lost": 0}
    assert counts(client, view="unqualified") == {stage: int(stage == "Unqualified") for stage in BOARD}
    assert counts(client, view="converted") == {stage: int(stage == "Converted") for stage in BOARD}
    # search and filters narrow every column the same way
    assert counts(client, search="warm") == {stage: int(stage == "Nurturing") for stage in BOARD}
    assert counts(client, source="Upload") == {stage: 0 for stage in BOARD}


def test_columns_show_only_leads_the_user_may_see(client):
    lead(client, "Ravis")  # Ravi (Salesperson)
    lead(login_as(client, 1), "Priyas")  # Priya (Manager)
    assert counts(login_as(client, 2))["New"] == 1  # Ravi sees only his own
    assert [l["name"] for l in column(client, "New")["items"]] == ["Ravis"]
    assert counts(login_as(client, 1))["New"] == 2  # a Manager sees the team
    assert counts(login_as(client, 1), view="my_open")["New"] == 1
