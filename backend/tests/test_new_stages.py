"""Stage paths, like Salesforce.
Lead: New -> Nurturing -> Revisit (optional, "not now": a date to come back) -> Demo -> Converted.
      Closed without converting: Unqualified (not eligible, with a reason; can be reopened) or Lost.
Opportunity: Opportunity -> Discovery (needs, budget, decision maker, timeline) -> Proposal -> Won, or Lost.
All data is made up."""
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import get_args

from app import constants, schemas

TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}
NOTE = "Synthetic stage note"
REVISIT_ON = "2030-03-02T09:00:00"


def new_lead(client, **extra):
    res = client.post("/api/leads", json={"last_name": "Stage", "company": "Stage Synthetic Co", **extra})
    assert res.status_code == 201, res.text
    return res.json()


def move(client, lead_id, stage, **extra):
    return client.put(f"/api/leads/{lead_id}/stage", json={"task": TASK, "stage": stage, "note": NOTE, **extra})


def to_stages(client, kind, record_id):
    return [h["to_stage"] for h in client.get(f"/api/{kind}/{record_id}/history").json()]


def test_a_new_lead_starts_at_new_with_a_first_contact_task(client):
    lead = new_lead(client)
    assert lead["stage"] == "New"
    assert [t["title"] for t in lead["tasks"]] == ["Make first contact - Stage"]
    assert client.get("/api/notifications").json()[0]["title"] == "Lead created"
    assert to_stages(client, "leads", lead["id"]) == ["New"]


def test_unqualified_is_a_closed_outcome_with_a_reason_and_can_be_reopened(client):
    lead = new_lead(client)
    assert move(client, lead["id"], "Nurturing").status_code == 200
    assert move(client, lead["id"], "Unqualified").status_code == 422  # not a stage you move to: it closes the lead
    assert client.post(f"/api/leads/{lead['id']}/unqualified", json={"reason": "Maybe", "notes": NOTE}).status_code == 422
    done = client.post(f"/api/leads/{lead['id']}/unqualified", json={"reason": "No budget", "notes": "No budget this year"})
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["stage"], body["unqualified_reason"], body["unqualified_notes"]) == ("Unqualified", "No budget",
                                                                                      "No budget this year")
    assert body["closed_at"] and all(t["status"] != "Open" for t in body["tasks"])  # its follow-ups are closed
    assert any(n["title"] == "Lead unqualified" for n in client.get("/api/notifications").json())
    # closed: no stage changes, listed under Unqualified Leads (not in the open lists)
    assert move(client, lead["id"], "Demo", completed_stages=["Nurturing"]).status_code == 400
    page = lambda view: [l["id"] for l in client.get("/api/leads/page", params={"view": view}).json()["items"]]  # noqa: E731
    assert page("unqualified") == [lead["id"]] and lead["id"] not in page("all_open")
    # reopen (Salesforce "recycle"): back to New with the user's task
    assert client.post(f"/api/leads/{lead['id']}/reopen", json={"note": NOTE}).status_code == 422  # task required
    again = client.post(f"/api/leads/{lead['id']}/reopen", json={"note": "Budget approved now", "task": TASK})
    assert again.status_code == 200, again.text
    assert (again.json()["stage"], again.json()["unqualified_reason"], again.json()["closed_at"]) == ("New", None, None)
    assert to_stages(client, "leads", lead["id"]) == ["New", "Nurturing", "Unqualified", "New"]
    assert client.post(f"/api/leads/{lead['id']}/reopen", json={"note": NOTE, "task": TASK}).status_code == 400


def test_revisit_needs_a_date_and_reason_and_the_task_is_due_that_day(client):
    lead = new_lead(client)
    assert move(client, lead["id"], "Revisit", completed_stages=["Nurturing"]).status_code == 422  # no date / reason
    past = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    assert move(client, lead["id"], "Revisit", completed_stages=["Nurturing"], revisit_date=past,
                revisit_reason="Bad timing").status_code == 400
    res = move(client, lead["id"], "Revisit", completed_stages=["Nurturing"], revisit_date=REVISIT_ON,
               revisit_reason="Budget next period")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["stage"], body["revisit_date"], body["revisit_reason"]) == ("Revisit", REVISIT_ON, "Budget next period")
    open_tasks = [t for t in body["tasks"] if t["status"] == "Open"]
    assert [(t["title"], t["due_date"], t["reminder_at"]) for t in open_tasks] == [(TASK["title"], REVISIT_ON, REVISIT_ON)]
    # moving on clears the revisit date
    demo = move(client, lead["id"], "Demo", demo_date="2030-03-05T11:00:00").json()
    assert (demo["revisit_date"], demo["revisit_reason"]) == (None, None)
    assert to_stages(client, "leads", lead["id"]) == ["New", "Nurturing", "Revisit", "Demo"]


def test_revisit_due_lists_leads_whose_date_has_come(client):
    from app.database import get_db
    from app.main import app
    from app.models import Lead
    due, later = new_lead(client, last_name="Due"), new_lead(client, last_name="Later")
    for lead in (due, later):
        move(client, lead["id"], "Revisit", completed_stages=["Nurturing"], revisit_date=REVISIT_ON,
             revisit_reason="Bad timing")
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, due["id"]).revisit_date = datetime.combine(date.today(), datetime.min.time())  # it's today now
    db.commit()
    items = client.get("/api/leads/page", params={"view": "revisit_due"}).json()["items"]
    assert [l["last_name"] for l in items] == ["Due"]


def test_new_cannot_be_skipped_but_revisit_is_optional(client):
    lead = new_lead(client)
    refused = move(client, lead["id"], "Demo")
    assert refused.status_code == 409 and "Complete Nurturing before Demo" in refused.json()["detail"]
    assert move(client, lead["id"], "Nurturing").status_code == 200
    demo = move(client, lead["id"], "Demo", demo_date="2030-02-01T11:00:00")  # Revisit passed over, no confirmation
    assert demo.status_code == 200, demo.text
    assert to_stages(client, "leads", lead["id"]) == ["New", "Nurturing", "Demo"]


def test_converting_from_new_needs_nurturing_and_demo_confirmed(client):
    lead = new_lead(client)
    refused = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "note": NOTE})
    assert refused.status_code == 409 and "Complete Nurturing and Demo" in refused.json()["detail"]
    ok = client.post(f"/api/leads/{lead['id']}/convert",
                     json={"task": TASK, "note": NOTE, "completed_stages": ["Nurturing", "Demo"]})
    assert ok.status_code == 200, ok.text
    assert to_stages(client, "leads", lead["id"]) == ["New", "Nurturing", "Demo", "Converted"]


def test_a_cancelled_demo_goes_back_to_revisit_on_the_task_date(client):
    lead = new_lead(client)
    move(client, lead["id"], "Demo", completed_stages=["Nurturing"], demo_date="2030-02-01T11:00:00")
    res = client.post(f"/api/leads/{lead['id']}/cancel-demo", json={"reason": "Client asked to wait", "task": TASK})
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["stage"], body["demo_date"], body["revisit_date"], body["revisit_reason"]) == (
        "Revisit", None, TASK["due_date"], "Demo cancelled")


def opportunity(client):
    lead = new_lead(client)
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "task": TASK, "note": NOTE, "expected_value": 1000, "completed_stages": ["Nurturing", "Demo"]})
    assert res.status_code == 200, res.text
    return res.json()["opportunity"]


def test_discovery_records_needs_budget_decision_maker_and_timeline(client):
    opp = opportunity(client)
    stage = lambda name, **extra: client.put(f"/api/opportunities/{opp['id']}/stage",  # noqa: E731
                                             json={"task": TASK, "stage": name, "note": NOTE, **extra})
    refused = stage("Proposal")
    assert refused.status_code == 409 and "Complete Discovery before Proposal" in refused.json()["detail"]
    assert stage("Discovery").status_code == 422  # what the customer needs is required
    discovery = stage("Discovery", discovery_needs="Faster month-end reporting", discovery_budget="$40k this year",
                      discovery_decision_maker="CFO, Dana", discovery_timeline="Live by Q2")
    assert discovery.status_code == 200, discovery.text
    body = discovery.json()
    assert body["probability"] == 40
    assert (body["discovery_needs"], body["discovery_budget"], body["discovery_decision_maker"],
            body["discovery_timeline"]) == ("Faster month-end reporting", "$40k this year", "CFO, Dana", "Live by Q2")
    bell = client.get("/api/notifications").json()
    assert any(n["title"] == "Opportunity moved to Discovery" and "Needs: Faster month-end reporting" in n["message"]
               for n in bell)
    # editable afterwards with the deal
    edited = client.put(f"/api/opportunities/{opp['id']}", json={"discovery_budget": "$55k"}).json()
    assert edited["discovery_budget"] == "$55k"
    proposal = stage("Proposal")
    assert proposal.status_code == 200 and proposal.json()["probability"] == 75
    won = client.post(f"/api/opportunities/{opp['id']}/won", json={"task": TASK, "note": NOTE})
    assert won.status_code == 200, won.text
    assert to_stages(client, "opportunities", opp["id"]) == ["Opportunity", "Discovery", "Proposal", "Won"]


def test_won_from_opportunity_needs_discovery_and_proposal_confirmed(client):
    opp = opportunity(client)
    refused = client.post(f"/api/opportunities/{opp['id']}/won", json={"task": TASK, "note": NOTE})
    assert refused.status_code == 409 and "Complete Discovery and Proposal" in refused.json()["detail"]
    won = client.post(f"/api/opportunities/{opp['id']}/won",
                      json={"task": TASK, "note": NOTE, "completed_stages": ["Discovery", "Proposal"]})
    assert won.status_code == 200, won.text


def test_home_pipeline_lists_every_open_stage_in_order(client):
    new_lead(client)
    pipeline = [p["stage"] for p in client.get("/api/home").json()["pipeline"]]
    assert pipeline == ["New", "Nurturing", "Revisit", "Demo", "Opportunity", "Discovery", "Proposal", "Won", "Lost"]


def test_stage_lists_agree_everywhere():
    """constants.py, the API's request types and database/schema.sql must list the same stages and reasons."""
    assert list(get_args(schemas.LeadOpenStage)) == constants.LEAD_FLOW == constants.LEAD_OPEN_STAGES
    assert list(get_args(schemas.OpportunityOpenStage)) == constants.OPPORTUNITY_FLOW == constants.OPPORTUNITY_OPEN_STAGES
    assert list(get_args(schemas.UnqualifiedReason)) == constants.UNQUALIFIED_REASONS
    assert list(get_args(schemas.RevisitReason)) == constants.REVISIT_REASONS
    assert set(constants.LEAD_OPTIONAL_STAGES) <= set(constants.LEAD_FLOW)
    assert constants.LEAD_STAGES == constants.LEAD_OPEN_STAGES + constants.LEAD_CLOSED_STAGES
    assert set(constants.STAGE_PROBABILITY) == set(constants.OPPORTUNITY_STAGES)
    sql = (Path(__file__).resolve().parents[2] / "database" / "schema.sql").read_text()

    def checked(column_default):
        match = re.search(rf"DEFAULT '{column_default}'\s*CHECK \(stage IN \(([^)]*)\)\)", sql)
        return [s.strip(" '") for s in match.group(1).split(",")]
    assert checked("New") == constants.LEAD_STAGES
    assert checked("Opportunity") == constants.OPPORTUNITY_STAGES
    reasons = re.search(r"CHECK \(unqualified_reason IN \(([^)]*)\)\)", sql, re.S).group(1)
    assert [r.strip(" '\n") for r in reasons.split(",")] == constants.UNQUALIFIED_REASONS


def test_bulk_change_owner_and_mark_lost_for_opportunities(client):
    from tests.conftest import login_as
    mine, other = opportunity(client), opportunity(client)
    lost_one = opportunity(client)
    client.post(f"/api/opportunities/{lost_one['id']}/lost", json={"lost_reason": "Price", "lost_notes": NOTE})
    # Ravi (Salesperson) can move his own open deals; the closed one is skipped with the reason
    res = client.post("/api/opportunities/bulk-transfer",
                      json={"opportunity_ids": [mine["id"], lost_one["id"]], "to_user_id": 1, "note": "Covering"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["transferred"] == 1 and body["skipped"][0]["id"] == lost_one["id"]
    priya = login_as(client, 1)
    assert priya.get(f"/api/opportunities/{mine['id']}").json()["owner_id"] == 1
    assert any(n["title"] == "Opportunities assigned to you" for n in priya.get("/api/notifications").json())
    assert priya.post("/api/opportunities/bulk-transfer", json={"opportunity_ids": [mine["id"]], "to_user_id": 3}).status_code == 400
    # bulk Mark as Lost: reason and notes required, each deal follows the single rules
    login_as(client, 2)
    assert client.post("/api/opportunities/bulk-lost", json={"opportunity_ids": [other["id"]], "lost_reason": "Price"}).status_code == 422
    res = client.post("/api/opportunities/bulk-lost", json={"opportunity_ids": [other["id"], mine["id"]],
                                                            "lost_reason": "No response", "lost_notes": "Stale deals"}).json()
    assert res["closed"] == 1 and [s["id"] for s in res["skipped"]] == [mine["id"]]  # Priya's now: Ravi can't close it
    assert client.get(f"/api/opportunities/{other['id']}").json()["stage"] == "Lost"
