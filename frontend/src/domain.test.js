import test from "node:test";
import assert from "node:assert/strict";
import {
  api,
  apiRequest,
  leadPayload,
  taskPayload,
  opportunityPayload,
  normalizeTask,
  normalizeWorkspace,
} from "./api.js";
import {
  LEAD_STAGES,
  LEAD_SOURCES,
  PRIORITIES,
  LOST_REASONS,
  salesOverview,
  money,
} from "./domain.js";

test("lead form uses backend fields and only requires last name and company", () => {
  assert.deepEqual(
    leadPayload({
      last_name: " Smith ",
      company: " Example ",
      source: "Phone",
      owner_id: "3",
    }),
    {
      salutation: null,
      first_name: null,
      last_name: "Smith",
      company: "Example",
      title: null,
      industry: null,
      email: null,
      phone: null,
      source: "Phone",
      owner_id: 3,
    },
  );
  assert.ok(!LEAD_STAGES.includes("Won"));
  assert.ok(LEAD_SOURCES.includes("Social Media"));
  assert.deepEqual(PRIORITIES, ["Low", "Normal", "High"]);
  assert.ok(LOST_REASONS.includes("No budget"));
});
test("task updates cannot silently change relationship or status", () => {
  const values = {
    title: " Follow up ",
    due_date: "2026-10-20T10:00",
    priority: "Normal",
    owner_id: "2",
    relatedType: "leads",
    relatedId: "7",
    status: "Open",
  };
  assert.equal(taskPayload(values).lead_id, 7);
  assert.equal(
    taskPayload({ ...values, relatedType: "general" }).lead_id,
    null,
  );
  const edit = taskPayload(values, true);
  assert.ok(!("lead_id" in edit));
  assert.ok(!("status" in edit));
  assert.ok(!("opportunity_id" in edit));
});
test("opportunity values preserve blank fields and zero as different values", () => {
  const payload = opportunityPayload({
    name: "Deal",
    expected_value: "0",
    probability: "20",
    owner_id: "1",
    expected_close_date: "",
  });
  assert.equal(payload.expected_value, 0);
  assert.equal(payload.expected_close_date, null);
  assert.equal(
    opportunityPayload({ name: "Deal", probability: "20", expected_value: "" })
      .expected_value,
    null,
  );
  assert.equal(money(null), "—");
  assert.equal(money(1234.5), "1,234.5");
});
test("server Auto-closed and Done tasks stay terminal and IDs match frontend routes", () => {
  const task = normalizeTask({
    id: 2,
    status: "Auto-closed",
    priority: "Normal",
    due_date: "2026-10-20T10:00:00",
    lead_id: 4,
    reminder_at: null,
  });
  assert.equal(task.id, "2");
  assert.equal(task.relatedId, "4");
  assert.equal(task.completed, true);
  assert.equal(task.status, "Auto-closed");
  assert.equal(task.due, "2026-10-20");
  assert.equal(
    normalizeTask({
      ...task,
      id: 3,
      status: "Open",
      lead_id: null,
      opportunity_id: 8,
    }).relatedType,
    "opportunities",
  );
});
test("detail normalization retains backend notes, history and contact information", () => {
  const raw = {
    leads: [
      { id: 1, name: "Jane Smith", company: "Example", stage: "Converted" },
    ],
    opportunities: [
      {
        id: 2,
        name: "Deal",
        stage: "Won",
        final_value: 500,
        expected_value: 400,
        lead_id: 1,
        primary_contact_id: 3,
      },
    ],
    tasks: [],
    contacts: [{ id: 3, email: "jane@example.test" }],
  };
  const data = normalizeWorkspace(raw, {
    collection: "leads",
    record: {
      ...raw.leads[0],
      notes: [{ id: 4, body: "A note" }],
      history: [
        {
          from_stage: "Demo",
          to_stage: "Converted",
          changed_at: "2026-10-20T10:00",
          changed_by_name: "Owner",
        },
      ],
    },
  });
  assert.equal(data.leads[0].notes[0].body, "A note");
  assert.match(data.leads[0].activity[0].text, /Demo → Converted/);
  assert.equal(data.opportunities[0].leadId, "1");
  assert.equal(data.opportunities[0].value, 500);
  assert.equal(data.opportunities[0].email, "jane@example.test");
});
test("dashboard uses backend home counts and includes overdue follow-ups", () => {
  const data = {
    tasks: [
      normalizeTask({ id: 1, status: "Open", due_date: "2026-10-01T10:00" }),
    ],
    home: {
      summary: { total_leads: 4, open_opportunities: 2, tasks_due_today: 0 },
      pipeline: [
        { stage: "New", total: 4 },
        { stage: "Opportunity", total: 2 },
        { stage: "Won", total: 1 },
        { stage: "Lost", total: 2 },
      ],
      won_vs_lost: [
        { outcome: "Won", deals: 1, value: 500 },
        { outcome: "Lost", deals: 2, value: 200 },
      ],
      todays_tasks: [{ id: 1, is_overdue: true }],
    },
  };
  const overview = salesOverview(data);
  assert.equal(overview.totalLeads, 4);
  assert.equal(overview.dueToday, 0);
  assert.equal(overview.todayTasks.length, 1);
  assert.equal(overview.activeCount, 6);
  assert.equal(overview.winRate, 33);
  assert.equal(overview.wonValue, 500);
  assert.equal(salesOverview({ tasks: [], home: null }).wonCount, 0);
});
test("lifecycle actions call dedicated backend endpoints", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ id: 4 }), { status: 200 });
  });
  await api.convert("4", { expected_value: 200 });
  await api.won("6", { final_value: 225 });
  await api.completeTask("8");
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method]),
    [
      ["/api/leads/4/convert", "POST"],
      ["/api/opportunities/6/won", "POST"],
      ["/api/tasks/8/complete", "PUT"],
    ],
  );
  assert.equal(JSON.parse(calls[0].options.body).expected_value, 200);
});
test("API validation failures reach the form as readable errors", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          detail: [{ loc: ["body", "last_name"], msg: "Field required" }],
        }),
        { status: 422 },
      ),
  );
  await assert.rejects(apiRequest("/leads"), /last_name: Field required/);
});
test("failed network requests never fall back to browser demo records", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("network unavailable");
  });
  await assert.rejects(apiRequest("/leads"), /Cannot reach the backend/);
});
