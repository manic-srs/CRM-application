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
  setToken,
} from "./api.js";
import {
  LEAD_STAGES,
  LEAD_SOURCES,
  PRIORITIES,
  LOST_REASONS,
  salesOverview,
  money,
  ATTACHMENT_MAX_BYTES,
  attachmentProblem,
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
      linkedin_url: null,
      company_website: null,
      company_linkedin_url: null,
      annual_revenue: null,
      employees: null,
      location: null,
      source: "Phone",
      owner_id: 3,
      welcome_email: false, // the "welcome email to the lead" box was not ticked
    },
  );
  assert.equal(leadPayload({ last_name: "A", company: "B", welcome_email: "on" }).welcome_email, true);
  const links = leadPayload({ last_name: "A", company: "B", linkedin_url: " linkedin.com/in/a ", employees: "250", annual_revenue: "" });
  assert.equal(links.linkedin_url, "linkedin.com/in/a"); // the backend adds https://
  assert.equal(links.employees, 250);
  assert.equal(links.annual_revenue, null);
  assert.ok(!("welcome_email" in leadPayload({ last_name: "A", company: "B" }, true))); // editing: not sent
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
test("attachment files are checked before upload (the backend checks again)", () => {
  const file = (name, size) => ({ name, size });
  assert.equal(ATTACHMENT_MAX_BYTES, 20 * 1024 * 1024);
  for (const name of ["a.pdf", "b.DOCX", "c.jpg", "d.JPEG", "e.png"]) assert.equal(attachmentProblem(file(name, 10)), "");
  assert.equal(attachmentProblem(file("max.pdf", ATTACHMENT_MAX_BYTES)), "");
  assert.match(attachmentProblem(file("big.pdf", ATTACHMENT_MAX_BYTES + 1)), /larger than 20 MB/);
  assert.match(attachmentProblem(file("empty.png", 0)), /is empty/);
  assert.match(attachmentProblem(file("old.doc", 10)), /\.doc.*save it as \.docx/i);
  for (const name of ["notes.txt", "page.html", "archive.zip", "pdf", ".pdf", "macro.docm"])
    assert.match(attachmentProblem(file(name, 10)), /only PDF, Word \(\.docx\), JPG and PNG/);
});
test("attachments use their own endpoints and send the login only in a header", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return url.endsWith("/file") || url.endsWith("?download=true")
      ? new Response(new Uint8Array([37, 80, 68, 70]), { status: 200, headers: { "Content-Type": "application/pdf" } })
      : new Response(JSON.stringify([]), { status: 200 });
  });
  setToken("secret-token");
  try {
    await api.attachments("4");
    const blob = await api.attachmentFile("4", "9");
    await api.attachmentFile("4", "9", true);
    await api.uploadAttachment("4", new File([new Uint8Array([1])], "quote.pdf", { type: "application/pdf" }));
    await api.deleteAttachment("4", "9");
    assert.equal(blob.type, "application/pdf");
    assert.equal(blob.size, 4);
  } finally {
    setToken("");
  }
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method || "GET"]),
    [
      ["/api/opportunities/4/attachments", "GET"],
      ["/api/opportunities/4/attachments/9/file", "GET"],
      ["/api/opportunities/4/attachments/9/file?download=true", "GET"],
      ["/api/opportunities/4/attachments", "POST"],
      ["/api/opportunities/4/attachments/9", "DELETE"],
    ],
  );
  for (const call of calls) {
    assert.ok(!call.url.includes("secret-token")); // never in the address
    assert.equal(call.options.headers.Authorization, "Bearer secret-token");
  }
  const form = calls[3].options.body;
  assert.equal(form.getAll("file").length, 1); // one file per request
  assert.equal(form.get("file").name, "quote.pdf");
  assert.equal(calls[3].options.headers["Content-Type"], undefined); // the browser sets the multipart boundary
});
test("attachment errors reach the card as readable messages", async (t) => {
  let reply;
  t.mock.method(globalThis, "fetch", async () => reply());
  reply = () => new Response("<html>Request Entity Too Large</html>", { status: 413 });
  await assert.rejects(api.uploadAttachment("4", new File(["x"], "big.pdf")), /larger than 20 MB/);
  reply = () => new Response(JSON.stringify({ detail: "logo.png is named as a PNG image but is really a PDF." }), { status: 415 });
  await assert.rejects(api.uploadAttachment("4", new File(["x"], "logo.png")), /really a PDF/);
  reply = () => new Response(JSON.stringify({ detail: "Attachment 9 not found" }), { status: 404 });
  await assert.rejects(api.attachmentFile("4", "9"), /Attachment 9 not found/);
  reply = () => {
    throw new TypeError("network unavailable");
  };
  await assert.rejects(api.attachmentFile("4", "9"), /Cannot reach the backend/);
  await assert.rejects(api.uploadAttachment("4", new File(["x"], "a.pdf")), /Cannot reach the backend/);
  // an expired login sends the app back to the login page
  const events = new EventTarget();
  let loggedOut = 0;
  events.addEventListener("crm-logout", () => loggedOut++);
  globalThis.window = events;
  setToken("old-token");
  try {
    reply = () => new Response(JSON.stringify({ detail: "Please log in again" }), { status: 401 });
    await assert.rejects(api.attachmentFile("4", "9"), /Please log in again/);
    await assert.rejects(api.attachments("4"), /Please log in again/);
  } finally {
    setToken("");
    delete globalThis.window;
  }
  assert.equal(loggedOut, 2);
});
test("email uploads keep their own messages", async (t) => {
  let status;
  t.mock.method(globalThis, "fetch", async () => new Response("", { status }));
  status = 413;
  await assert.rejects(api.sendEmail(new FormData()), /The attachments are too large\./);
  status = 500;
  await assert.rejects(api.sendEmail(new FormData()), /The email could not be sent\./);
});
