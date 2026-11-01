"""Stage paths. Lead: Unqualified -> New -> Nurturing -> Revisit (optional) -> Demo -> Converted, or Lost.
Opportunity: Opportunity -> Discovery -> Proposal -> Won, or Lost. All data is made up."""
import re
from pathlib import Path
from typing import get_args

from app import constants, schemas

TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}
NOTE = "Synthetic stage note"


def new_lead(client, **extra):
    res = client.post("/api/leads", json={"last_name": "Stage", "company": "Stage Synthetic Co", **extra})
    assert res.status_code == 201, res.text
    return res.json()


def move(client, lead_id, stage, **extra):
    return client.put(f"/api/leads/{lead_id}/stage", json={"task": TASK, "stage": stage, "note": NOTE, **extra})


def to_stages(client, kind, record_id):
    return [h["to_stage"] for h in client.get(f"/api/{kind}/{record_id}/history").json()]


def test_a_new_lead_starts_at_unqualified_with_a_qualify_task(client):
    lead = new_lead(client)
    assert lead["stage"] == "Unqualified"
    assert [t["title"] for t in lead["tasks"]] == ["Qualify lead - Stage"]
    assert client.get("/api/notifications").json()[0]["title"] == "Lead created"


def test_new_cannot_be_skipped_but_revisit_is_optional(client):
    lead = new_lead(client)
    refused = move(client, lead["id"], "Nurturing")
    assert refused.status_code == 409 and "Complete New before Nurturing" in refused.json()["detail"]
    assert move(client, lead["id"], "New").status_code == 200
    assert move(client, lead["id"], "Nurturing").status_code == 200
    # Nurturing -> Demo passes over Revisit without a confirmation
    demo = move(client, lead["id"], "Demo", demo_date="2030-02-01T11:00:00")
    assert demo.status_code == 200, demo.text
    assert to_stages(client, "leads", lead["id"]) == ["Unqualified", "New", "Nurturing", "Demo"]


def test_revisit_can_be_used_and_moved_on_from(client):
    lead = new_lead(client)
    assert move(client, lead["id"], "Revisit", completed_stages=["New", "Nurturing"]).status_code == 200
    assert client.get(f"/api/leads/{lead['id']}").json()["stage"] == "Revisit"
    assert move(client, lead["id"], "Demo").status_code == 200  # nothing left to confirm
    convert = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "note": NOTE, "expected_value": 500})
    assert convert.status_code == 200, convert.text
    assert to_stages(client, "leads", lead["id"]) == ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted"]


def test_converting_from_unqualified_needs_new_nurturing_and_demo_confirmed(client):
    lead = new_lead(client)
    refused = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "note": NOTE})
    assert refused.status_code == 409 and "Complete New and Nurturing and Demo" in refused.json()["detail"]
    ok = client.post(f"/api/leads/{lead['id']}/convert",
                     json={"task": TASK, "note": NOTE, "completed_stages": ["New", "Nurturing", "Demo"]})
    assert ok.status_code == 200, ok.text
    assert "Revisit" not in to_stages(client, "leads", lead["id"])  # optional and not confirmed: not recorded


def test_a_cancelled_demo_goes_back_to_revisit(client):
    lead = new_lead(client)
    move(client, lead["id"], "Demo", completed_stages=["New", "Nurturing"], demo_date="2030-02-01T11:00:00")
    res = client.post(f"/api/leads/{lead['id']}/cancel-demo", json={"reason": "Client asked to wait", "task": TASK})
    assert res.status_code == 200, res.text
    assert (res.json()["stage"], res.json()["demo_date"]) == ("Revisit", None)


def opportunity(client):
    lead = new_lead(client)
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "task": TASK, "note": NOTE, "expected_value": 1000, "completed_stages": ["New", "Nurturing", "Demo"]})
    assert res.status_code == 200, res.text
    return res.json()["opportunity"]


def test_opportunity_goes_through_discovery(client):
    opp = opportunity(client)
    stage = lambda name, **extra: client.put(f"/api/opportunities/{opp['id']}/stage",  # noqa: E731
                                             json={"task": TASK, "stage": name, "note": NOTE, **extra})
    refused = stage("Proposal")
    assert refused.status_code == 409 and "Complete Discovery before Proposal" in refused.json()["detail"]
    discovery = stage("Discovery")
    assert discovery.status_code == 200 and discovery.json()["probability"] == 40
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
    assert pipeline == ["Unqualified", "New", "Nurturing", "Revisit", "Demo",
                        "Opportunity", "Discovery", "Proposal", "Won", "Lost"]


def test_stage_lists_agree_everywhere():
    """constants.py, the API's request types and database/schema.sql must list the same stages."""
    assert list(get_args(schemas.LeadOpenStage)) == constants.LEAD_FLOW == constants.LEAD_OPEN_STAGES
    assert list(get_args(schemas.OpportunityOpenStage)) == constants.OPPORTUNITY_FLOW == constants.OPPORTUNITY_OPEN_STAGES
    assert set(constants.LEAD_OPTIONAL_STAGES) <= set(constants.LEAD_FLOW)
    assert set(constants.STAGE_PROBABILITY) == set(constants.OPPORTUNITY_STAGES)
    sql = (Path(__file__).resolve().parents[2] / "database" / "schema.sql").read_text()

    def checked(column_default):
        match = re.search(rf"DEFAULT '{column_default}'\s*CHECK \(stage IN \(([^)]*)\)\)", sql)
        return [s.strip(" '") for s in match.group(1).split(",")]
    assert checked("Unqualified") == constants.LEAD_STAGES
    assert checked("Opportunity") == constants.OPPORTUNITY_STAGES
