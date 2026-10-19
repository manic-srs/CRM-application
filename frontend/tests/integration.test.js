// Run only against a disposable backend database. Never point this at shared data.
import test from "node:test";
import assert from "node:assert/strict";
import { api, apiRequest, normalizeWorkspace } from "../src/api.js";
import { salesOverview } from "../src/domain.js";

const origin = process.env.CRM_TEST_ORIGIN;
test(
  "frontend API adapter completes the real backend lifecycle",
  { skip: !origin },
  async (t) => {
    const realFetch = globalThis.fetch;
    t.mock.method(globalThis, "fetch", (url, options) =>
      realFetch(new URL(url, origin), options),
    );
    const users = await apiRequest("/users");
    assert.ok(users.length);
    const values = {
      first_name: "Integration",
      last_name: `Check ${Date.now()}`,
      company: "Temporary test company",
      source: "Phone",
      owner_id: String(users[0].id),
    };
    const lead = await api.saveLead(values);
    assert.equal(lead.stage, "New");
    assert.ok(lead.id);
    assert.equal(lead.tasks[0].status, "Open");
    assert.ok(lead.tasks[0].is_auto);
    const edited = await api.saveLead(
      { ...values, title: "Buyer" },
      String(lead.id),
    );
    assert.equal(edited.title, "Buyer");
    await api.note("leads", lead.id, "Integration check note");
    let detail = await api.stage("leads", lead.id, { stage: "Nurturing" });
    assert.ok(detail.tasks.some((task) => task.status === "Auto-closed"));
    const demo = await api.stage("leads", lead.id, {
      stage: "Demo",
      demo_date: "2026-12-20T11:00:00",
    });
    assert.match(
      demo.tasks.find((task) => task.status === "Open").due_date,
      /2026-12-20T11:00/,
    );
    const task = await api.saveTask({
      title: "Manual follow-up",
      due_date: "2026-12-21T10:00",
      priority: "Normal",
      owner_id: String(users[0].id),
      relatedType: "leads",
      relatedId: String(lead.id),
    });
    const completed = await api.completeTask(task.id);
    assert.equal(completed.status, "Done");
    await assert.rejects(api.completeTask(task.id), /already Done/);
    const converted = await api.convert(lead.id, {
      expected_value: 1000,
      expected_close_date: "2026-12-31",
    });
    assert.equal(converted.lead.stage, "Converted");
    assert.equal(converted.opportunity.probability, 20);
    assert.equal(converted.new_task.status, "Open");
    await assert.rejects(api.convert(lead.id, {}), /closed/);
    const opp = converted.opportunity;
    await api.saveOpportunity(
      {
        name: "Integration opportunity",
        expected_value: "1100",
        probability: "20",
        expected_close_date: "2026-12-31",
        owner_id: String(users[0].id),
        primary_contact_id: String(converted.contact.id),
      },
      opp.id,
    );
    const proposal = await api.stage("opportunities", opp.id, {
      stage: "Proposal",
    });
    assert.equal(proposal.probability, 75);
    const won = await api.won(opp.id, { final_value: 1200 });
    assert.equal(won.final_value, 1200);
    assert.equal(won.probability, 100);
    assert.ok(won.tasks.every((task) => task.status !== "Open"));
    const second = await api.saveLead({ ...values, last_name: "Lost check" });
    await assert.rejects(
      api.lost("leads", second.id, { lost_reason: "Unsupported" }),
      /lost_reason/,
    );
    const lost = await api.lost("leads", second.id, {
      lost_reason: "No budget",
      lost_notes: "Test only",
    });
    assert.equal(lost.stage, "Lost");
    const names = [
      "leads",
      "opportunities",
      "tasks",
      "users",
      "accounts",
      "contacts",
      "home",
    ];
    const raw = Object.fromEntries(
      await Promise.all(
        names.map(async (name) => [name, await apiRequest(`/${name}`)]),
      ),
    );
    detail = await apiRequest(`/leads/${lead.id}`);
    const workspace = normalizeWorkspace(raw, {
      collection: "leads",
      record: detail,
    });
    assert.ok(
      workspace.leads
        .find((item) => item.id === String(lead.id))
        .notes.some((note) => note.body === "Integration check note"),
    );
    assert.ok(
      workspace.opportunities.some(
        (item) => item.leadId === String(lead.id) && item.stage === "Won",
      ),
    );
    assert.equal(salesOverview(workspace).wonCount, raw.home.summary.won_deals);
    const notifications = await apiRequest(
      `/notifications?user_id=${users[0].id}`,
    );
    assert.ok(notifications.length);
    assert.equal(
      (await api.readNotification(notifications[0].id)).is_read,
      true,
    );
  },
);
