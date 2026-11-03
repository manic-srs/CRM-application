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
  STAGE_FILES_MAX,
  AUTOFILL_FIELDS,
  autofillPlan,
  linkedInProfileUrl,
  attachmentProblem,
  attachmentType,
  pickStageFiles,
  STAGE_NOTE_REQUIRED,
  CONVERSION_COMMENT_REQUIRED,
  stageNote,
  stageNoteField,
  stageNoteMessage,
  leadBoardColumns,
  leadStageAction,
  TASK_SUBJECT_REQUIRED,
  TASK_DUE_REQUIRED,
  stageTaskNeeded,
  stageTaskPayload,
  stageTaskProblems,
  LEAD_FLOW,
  LEAD_OPTIONAL_STAGES,
  OPPORTUNITY_FLOW,
  skippedStages,
  emailWebsiteProblem,
  isPersonalEmail,
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
    },
  );
  assert.ok(!("welcome_email" in leadPayload({ last_name: "A", company: "B" }))); // leads are never emailed automatically
  const links = leadPayload({ last_name: "A", company: "B", linkedin_url: " linkedin.com/in/a ", employees: "250", annual_revenue: "" });
  assert.equal(links.linkedin_url, "linkedin.com/in/a"); // the backend adds https://
  assert.equal(links.employees, 250);
  assert.equal(links.annual_revenue, null);
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
  await api.convert("4", { note: "Budget approved", expected_value: 200 });
  await api.won("6", { final_value: 225, note: "Contract signed" });
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
  assert.equal(JSON.parse(calls[0].options.body).note, "Budget approved");
  assert.equal(JSON.parse(calls[1].options.body).note, "Contract signed");
});
test("every stage change popup has a required note; creating and editing records don't", () => {
  assert.equal(stageNoteField("stage"), "note"); // path bar, Mark as Complete, Kanban
  assert.equal(stageNoteField("convert"), "note");
  assert.equal(stageNoteField("won"), "note"); // the Closing Note
  assert.equal(stageNoteField("lost"), "lost_notes"); // the Lost Notes (the Lost Reason stays required too)
  assert.equal(stageNoteField("cancelDemo", "nurturing"), "reason"); // the lead goes back to Nurturing
  assert.equal(stageNoteField("cancelDemo", "reschedule"), null); // the lead stays at Demo
  for (const type of ["lead", "opportunity", "task", "account", "contact", "note", "transfer", "delete"])
    assert.equal(stageNoteField(type), null);
  assert.equal(STAGE_NOTE_REQUIRED, "Enter a note to change the stage.");
});
test("the Leads board has seven columns in order; Converted, Unqualified and Lost are closed; the list view decides which can fill", () => {
  const all = leadBoardColumns("all", null);
  assert.deepEqual(all.map((c) => c.stage), ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted", "Lost"]);
  assert.deepEqual(all.filter((c) => c.closed).map((c) => c.stage), ["Unqualified", "Converted", "Lost"]);
  assert.ok(all.every((c) => c.excluded === ""));
  const excluded = (view, stage) => leadBoardColumns(view, stage).filter((c) => c.excluded).map((c) => c.stage);
  const open = ["New", "Nurturing", "Revisit", "Demo"];
  assert.deepEqual(excluded("all_open"), ["Unqualified", "Converted", "Lost"]);
  assert.deepEqual(excluded("my_open"), ["Unqualified", "Converted", "Lost"]);
  assert.deepEqual(excluded("converted"), ["Unqualified", ...open, "Lost"]);
  assert.deepEqual(excluded("lost"), ["Unqualified", ...open, "Converted"]);
  assert.deepEqual(excluded("unqualified"), [...open, "Converted", "Lost"]);
  assert.deepEqual(excluded("revisit_due"), ["Unqualified", "New", "Nurturing", "Demo", "Converted", "Lost"]);
  assert.deepEqual(excluded("uploaded"), []);
  assert.deepEqual(excluded("all", "Demo"), ["Unqualified", "New", "Nurturing", "Revisit", "Converted", "Lost"]); // the Lead Status filter
  assert.equal(leadBoardColumns("all_open", "Demo").find((c) => c.stage === "New").excluded, "Hidden by the Lead Status filter");
  assert.equal(leadBoardColumns("all_open", null).find((c) => c.stage === "Lost").excluded, "Not in this list view");
});
test("stage order: skipped stages must be confirmed, Revisit is optional, going back skips nothing", () => {
  assert.deepEqual(skippedStages(LEAD_FLOW, "New", "Demo", LEAD_OPTIONAL_STAGES), ["Nurturing"]);
  assert.deepEqual(skippedStages(LEAD_FLOW, "Nurturing", "Demo", LEAD_OPTIONAL_STAGES), []); // Revisit may be passed over
  assert.deepEqual(skippedStages(LEAD_FLOW, "New", LEAD_FLOW.length, LEAD_OPTIONAL_STAGES), ["Nurturing", "Demo"]);
  assert.deepEqual(skippedStages(LEAD_FLOW, "Demo", "New", LEAD_OPTIONAL_STAGES), []);
  assert.deepEqual(skippedStages(OPPORTUNITY_FLOW, "Opportunity", "Proposal"), ["Discovery"]);
  assert.deepEqual(skippedStages(OPPORTUNITY_FLOW, "Opportunity", OPPORTUNITY_FLOW.length), ["Discovery", "Proposal"]);
  assert.deepEqual(skippedStages(OPPORTUNITY_FLOW, "Proposal", OPPORTUNITY_FLOW.length), []);
});
test("a lead card opens the existing popups and only for moves the lead page allows", () => {
  const lead = { id: 7, stage: "Nurturing" };
  const both = { canEdit: true, canConvert: true };
  assert.deepEqual(leadStageAction(lead, "Demo", both), { type: "stage", collection: "leads", record: lead, stage: "Demo" });
  assert.deepEqual(leadStageAction(lead, "New", both), { type: "stage", collection: "leads", record: lead, stage: "New" }); // back
  assert.deepEqual(leadStageAction(lead, "Converted", both), { type: "convert", record: lead });
  assert.deepEqual(leadStageAction(lead, "Lost", both), { type: "lost", collection: "leads", record: lead });
  assert.equal(leadStageAction(lead, "Nurturing", both), null); // the same column does nothing
  assert.equal(leadStageAction(lead, "Demo", { canEdit: false, canConvert: false }), null); // view-only
  assert.equal(leadStageAction(lead, "Converted", { canEdit: true, canConvert: false }), null); // e.g. an Admin
  assert.deepEqual(leadStageAction(lead, "Lost", { canEdit: true, canConvert: false }).type, "lost");
  for (const closed of ["Converted", "Lost"])
    for (const to of ["New", "Nurturing", "Demo", "Converted", "Lost"])
      assert.equal(leadStageAction({ id: 8, stage: closed }, to, both), null); // closed leads don't move
  assert.equal(leadStageAction(lead, "Won", both), null);
  assert.equal(leadStageAction(null, "Demo", both), null);
});
test("Convert's note is the Conversion Comment, with its own message; other popups keep theirs", () => {
  assert.equal(stageNoteField("convert"), "note"); // the same field the backend reads
  assert.equal(CONVERSION_COMMENT_REQUIRED, "Enter a conversion comment.");
  assert.equal(stageNoteMessage("convert"), CONVERSION_COMMENT_REQUIRED);
  for (const type of ["stage", "won", "lost", "cancelDemo"]) assert.equal(stageNoteMessage(type), STAGE_NOTE_REQUIRED);
});
test("every stage change but Lost needs a New Task with a subject and a due date", () => {
  for (const type of ["stage", "convert", "won"]) assert.equal(stageTaskNeeded(type), true);
  assert.equal(stageTaskNeeded("cancelDemo", "nurturing"), true); // back to Nurturing is a stage change
  assert.equal(stageTaskNeeded("cancelDemo", "reschedule"), false); // the lead stays at Demo
  for (const type of ["lost", "lead", "task", "note", "transfer", "opportunity"]) assert.equal(stageTaskNeeded(type), false);
  assert.deepEqual(stageTaskProblems({}), { task_title: TASK_SUBJECT_REQUIRED, task_due_date: TASK_DUE_REQUIRED });
  assert.deepEqual(stageTaskProblems({ task_title: "   ", task_due_date: "2030-01-15T10:00" }), { task_title: TASK_SUBJECT_REQUIRED });
  assert.deepEqual(stageTaskProblems({ task_title: "Call", task_due_date: "2030-01-15T10:00" }), {});
});
test("the New Task is sent as the task form sends it: trimmed subject, optional fields left empty", () => {
  assert.deepEqual(
    stageTaskPayload({ task_title: "  Call the buyer ", task_due_date: "2030-01-15T10:00", task_priority: "High",
                       task_reminder_at: "", task_description: "  ", task_owner_id: "3" }),
    { title: "Call the buyer", due_date: "2030-01-15T10:00", priority: "High", reminder_at: null, description: null, owner_id: 3 },
  );
  assert.deepEqual(stageTaskPayload({ task_title: "Call", task_due_date: "2030-01-15T10:00" }), {
    title: "Call", due_date: "2030-01-15T10:00", priority: "Normal", reminder_at: null, description: null, owner_id: null,
  }); // no assignee chosen: the server gives it to the record's owner
});
test("the popups with files send the New Task as one JSON form field", async (t) => {
  const forms = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    forms.push(options.body);
    return new Response(JSON.stringify({ id: 1 }), { status: 200 });
  });
  const task = { title: "Handover", due_date: "2030-01-20T10:00", priority: "Normal", reminder_at: null, description: null, owner_id: null };
  const file = new File(["%PDF-1.4"], "quote.pdf", { type: "application/pdf" });
  await api.stageWithFiles("5", { stage: "Proposal", note: "Sent", task }, [file]);
  await api.wonWithFiles("5", { final_value: 10, note: "Signed", task }, [file]);
  for (const form of forms) assert.deepEqual(JSON.parse(form.get("task")), task);
});
test("a blank stage note is caught; a real one keeps its formatting inside", () => {
  for (const blank of [undefined, null, "", "   ", "\n\t \n", 5]) assert.equal(stageNote(blank), "");
  assert.equal(stageNote("  Called Priya.\n  - budget ok\n\n"), "Called Priya.\n  - budget ok");
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
test("files chosen in the Change Stage popup are checked, kept once and limited", () => {
  const file = (name, size, lastModified = 1) => ({ name, size, lastModified });
  const proposal = file("proposal.pdf", 10);
  let picked = pickStageFiles([], [proposal, file("old.doc", 10), file("empty.png", 0), file("big.pdf", ATTACHMENT_MAX_BYTES + 1)]);
  assert.deepEqual(picked.files, [proposal]);
  assert.equal(picked.problems.length, 3);
  assert.match(picked.problems.join("\n"), /\.doc[\s\S]*is empty[\s\S]*larger than 20 MB/);
  // the same file chosen again is not added twice; another file with the same name is
  picked = pickStageFiles(picked.files, [proposal, file("proposal.pdf", 10, 2)]);
  assert.equal(picked.files.length, 2);
  assert.deepEqual(picked.problems, []);
  assert.equal(STAGE_FILES_MAX, 5);
  picked = pickStageFiles(picked.files, ["a.png", "b.jpg", "c.jpeg", "d.docx"].map((n) => file(n, 5)));
  assert.equal(picked.files.length, 5);
  assert.match(picked.problems[0], /^d\.docx: up to 5 files/);
  assert.deepEqual(
    ["a.PDF", "b.docx", "c.JPG", "d.jpeg", "e.png", "f.doc", "g.txt", "pdf"].map(attachmentType),
    ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "image/jpeg",
     "image/jpeg", "image/png", "", "", ""],
  );
});
test("a stage change with files is one request, sent with the login header", async (t) => {
  const calls = [];
  let reply = () => new Response(JSON.stringify({ id: 6, stage: "Proposal" }), { status: 200 });
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return reply();
  });
  const files = [new File(["%PDF-"], "quote.pdf"), new File(["png"], "chart.png")];
  setToken("secret-token");
  try {
    await api.stageWithFiles("6", { stage: "Proposal", note: "Sent the quote" }, files);
    await api.stageWithFiles("6", { stage: "Opportunity", note: null }, files.slice(0, 1));
    await api.stage("opportunities", "6", { stage: "Proposal", note: null }); // without files: unchanged JSON call
  } finally {
    setToken("");
  }
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method]),
    [
      ["/api/opportunities/6/stage-with-files", "POST"],
      ["/api/opportunities/6/stage-with-files", "POST"],
      ["/api/opportunities/6/stage", "PUT"],
    ],
  );
  const form = calls[0].options.body;
  assert.equal(form.get("stage"), "Proposal");
  assert.equal(form.get("note"), "Sent the quote");
  assert.deepEqual(form.getAll("files").map((f) => f.name), ["quote.pdf", "chart.png"]);
  assert.equal(calls[1].options.body.get("note"), null); // an empty note is not sent
  assert.equal(calls[0].options.headers.Authorization, "Bearer secret-token");
  assert.ok(!calls[0].url.includes("secret-token"));
  assert.deepEqual(JSON.parse(calls[2].options.body), { stage: "Proposal", note: null });

  reply = () => new Response(JSON.stringify({ detail: "chart.png is named as a PNG image but is really a PDF." }), { status: 415 });
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /chart\.png .* really a PDF/);
  reply = () => new Response("<html>Request Entity Too Large</html>", { status: 413 });
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /Each file can be up to 20 MB/);
  reply = () => new Response("", { status: 500 });
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /The stage could not be changed/);
  reply = () => {
    throw new TypeError("network unavailable");
  };
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /Cannot reach the backend/);
});
test("Mark as Won with files is one request with the amount, note, email choice and files", async (t) => {
  const calls = [];
  let reply = () => new Response(JSON.stringify({ id: 6, stage: "Won" }), { status: 200 });
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return reply();
  });
  const files = [new File(["%PDF-"], "signed.pdf"), new File(["png"], "photo.png")];
  setToken("secret-token");
  try {
    await api.wonWithFiles("6", { final_value: 1500.5, note: "Signed", completed_stages: ["Proposal"],
                                  completed_note: "Sent by email" }, files);
    await api.wonWithFiles("6", { final_value: 0, note: null }, files.slice(0, 1));
    await api.won("6", { final_value: null, note: null }); // without files: unchanged JSON call
  } finally {
    setToken("");
  }
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method]),
    [
      ["/api/opportunities/6/won-with-files", "POST"],
      ["/api/opportunities/6/won-with-files", "POST"],
      ["/api/opportunities/6/won", "POST"],
    ],
  );
  const form = calls[0].options.body;
  assert.deepEqual(
    [...form.entries()].map(([name, value]) => [name, typeof value === "string" ? value : value.name]),
    [["final_value", "1500.5"], ["note", "Signed"], ["completed_stages", "Proposal"],
     ["completed_note", "Sent by email"], ["files", "signed.pdf"], ["files", "photo.png"]],
  );
  const second = calls[1].options.body;
  assert.equal(second.get("final_value"), "0"); // 0 is an amount, not "empty"
  assert.equal(second.get("notify_customer"), null); // customers are never emailed automatically
  assert.equal(second.get("note"), null);
  assert.equal(calls[0].options.headers.Authorization, "Bearer secret-token");
  assert.ok(!calls[0].url.includes("secret-token"));
  assert.deepEqual(JSON.parse(calls[2].options.body), { final_value: null, note: null });

  reply = () => new Response(JSON.stringify({ detail: "final_value: Input should be greater than or equal to 0" }), { status: 422 });
  await assert.rejects(api.wonWithFiles("6", { final_value: -5 }, files), /final_value: Input should be greater/);
  reply = () => new Response("<html>Request Entity Too Large</html>", { status: 413 });
  await assert.rejects(api.wonWithFiles("6", {}, files), /Each file can be up to 20 MB/);
  reply = () => new Response("", { status: 500 });
  await assert.rejects(api.wonWithFiles("6", {}, files), /could not be marked as Won/);
});
test("only LinkedIn person profiles are looked up, in one form", () => {
  const url = (value) => linkedInProfileUrl(value).url;
  assert.equal(url("https://www.linkedin.com/in/Jane-Doe-123/"), "https://linkedin.com/in/jane-doe-123");
  assert.equal(url("  linkedin.com/in/jane-doe-123?trk=public#about "), "https://linkedin.com/in/jane-doe-123");
  assert.equal(url("http://uk.linkedin.com/in/jane_doe"), "https://linkedin.com/in/jane_doe");
  assert.equal(url("https://www.linkedin.com/in/j%C3%BCrgen-m"), "https://linkedin.com/in/j%C3%BCrgen-m");
  for (const bad of [
    "",
    "https://www.linkedin.com/company/acme",
    "https://www.linkedin.com/school/some-school",
    "https://www.linkedin.com/in/",
    "https://www.linkedin.com/in/jane/details/experience",
    "https://www.linkedin.com/sales/lead/abc123",
    "https://linkedin.com.example.test/in/jane-doe",
    "https://evil-linkedin.com/in/jane-doe",
    "https://www.linkedin.com@example.test/in/jane-doe",
    "https://www.linkedin.com:443/in/jane-doe",
    "javascript:alert(1)",
    "ftp://linkedin.com/in/jane-doe",
    "https://lnkd.in/abc123",
    "https://www.linkedin.com/in/jane doe",
    "https://www.linkedin.com/in/ab",
    `https://www.linkedin.com/in/${"a".repeat(300)}`,
  ])
    assert.ok(linkedInProfileUrl(bad).error, `should refuse ${bad}`);
});
test("Apollo autofill fills empty fields and never overwrites what the user typed", () => {
  const empty = { first_name: "", last_name: "", company: "", title: "", industry: "", email: "", phone: "" };
  const jane = { first_name: "Jane", last_name: "Doe", company: "Synthetic Co", title: "CTO" };
  // a first profile: empty fields are filled; the user's own company stays
  let plan = autofillPlan({ ...empty, company: "Typed Co" }, {}, jane);
  assert.deepEqual(plan.set, { first_name: "Jane", last_name: "Doe", title: "CTO" });
  assert.deepEqual(plan.filled, ["first_name", "last_name", "title"]);
  assert.deepEqual(plan.kept, ["company"]);
  // the user then edits the title; a second profile replaces only the untouched autofill
  const form = { ...empty, first_name: "Jane", last_name: "Doe", company: "Typed Co", title: "Chief Technology Officer" };
  plan = autofillPlan(form, plan.autofilled, { first_name: "Sam", last_name: "Lee", title: "VP Sales", email: "sam@example.test" });
  assert.deepEqual(plan.set, { first_name: "Sam", last_name: "Lee", email: "sam@example.test" });
  assert.deepEqual(plan.kept, ["title"]);
  // a profile without a last name removes the old profile's untouched last name
  plan = autofillPlan({ ...form, first_name: "Sam", last_name: "Lee", email: "sam@example.test" }, plan.autofilled, { first_name: "Sam" });
  assert.deepEqual(plan.set, { last_name: "", email: "" });
  // clearing the address ({}) removes untouched autofill only
  plan = autofillPlan({ ...form, first_name: "Sam" }, plan.autofilled, {});
  assert.deepEqual(plan.set, { first_name: "" });
  assert.deepEqual(plan.autofilled, {});
});
test("company details follow the same rules: empty fields only, manual entries kept, untouched autofill replaced", () => {
  assert.deepEqual(
    Object.entries(AUTOFILL_FIELDS).slice(-2),
    [["company_website", "Company Website"], ["company_linkedin_url", "Company LinkedIn URL"]],
  );
  const synthetic = { company: "Synthetic Co", industry: "Software", company_website: "https://synthetic-co.example",
                      company_linkedin_url: "https://www.linkedin.com/company/synthetic-co" };
  // the user typed a website before pasting: it stays; the other company details are filled
  let plan = autofillPlan({ company_website: "https://typed.example" }, {}, synthetic);
  assert.deepEqual(plan.set, { company: "Synthetic Co", industry: "Software",
                               company_linkedin_url: "https://www.linkedin.com/company/synthetic-co" });
  assert.deepEqual(plan.kept, ["company_website"]);
  // the user edits the company name; another profile (another employer, no LinkedIn page) replaces only untouched values
  const form = { company: "Synthetic Company Ltd", industry: "Software", company_website: "https://typed.example",
                 company_linkedin_url: "https://www.linkedin.com/company/synthetic-co" };
  plan = autofillPlan(form, plan.autofilled, { company: "Other Co", industry: "Retail", company_website: "https://other.example" });
  assert.deepEqual(plan.set, { industry: "Retail", company_linkedin_url: "" }); // the old page doesn't belong to Other Co
  assert.deepEqual(plan.kept, ["company", "company_website"]);
  // clearing the profile address removes only the untouched autofill
  plan = autofillPlan({ ...form, industry: "Retail", company_linkedin_url: "" }, plan.autofilled, {});
  assert.deepEqual(plan.set, { industry: "" });
  assert.deepEqual(plan.autofilled, {});
});
test("LinkedIn autofill calls only the backend, with the login header, and keeps the error status", async (t) => {
  const calls = [];
  let reply = () => new Response(JSON.stringify({ enabled: true }), { status: 200 });
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return reply();
  });
  setToken("secret-token");
  try {
    await api.leadEnrichmentStatus();
    reply = () => new Response(JSON.stringify({ status: "no_match", linkedin_url: "x", fields: {} }), { status: 200 });
    await api.enrichLead("https://www.linkedin.com/in/jane-doe");
    reply = () => new Response(JSON.stringify({ detail: "LinkedIn autofill isn't set up on this server." }), { status: 503 });
    await assert.rejects(api.enrichLead("https://www.linkedin.com/in/jane-doe"), (err) => err.status === 503 && /isn't set up/.test(err.message));
    reply = () => {
      throw new TypeError("network unavailable");
    };
    await assert.rejects(api.enrichLead("https://www.linkedin.com/in/jane-doe"), (err) => err.status === 0 && /Cannot reach the backend/.test(err.message));
  } finally {
    setToken("");
  }
  assert.deepEqual(calls.map((c) => [c.url, c.options.method || "GET"]), [
    ["/api/leads/enrichment", "GET"],
    ["/api/leads/enrichment", "POST"],
    ["/api/leads/enrichment", "POST"],
    ["/api/leads/enrichment", "POST"],
  ]);
  assert.deepEqual(JSON.parse(calls[1].options.body), { linkedin_url: "https://www.linkedin.com/in/jane-doe" });
  for (const call of calls) {
    assert.ok(call.url.startsWith("/api/") && !call.url.includes("apollo") && !call.url.includes("secret-token"));
    assert.equal(call.options.headers.Authorization, "Bearer secret-token");
  }
});

test("a lead's email must use the company website's domain", () => {
  assert.equal(emailWebsiteProblem("asha@acme.com", "https://www.acme.com/about"), null);
  assert.equal(emailWebsiteProblem("asha@mail.acme.com", "acme.com"), null);
  assert.equal(emailWebsiteProblem("asha@acme.com", "shop.acme.com"), null);
  assert.equal(emailWebsiteProblem("", "acme.com"), null); // nothing to compare
  assert.equal(emailWebsiteProblem("asha@acme.com", ""), null);
  assert.match(emailWebsiteProblem("asha@gmail.com", "acme.com"), /Personal emails \(@gmail\.com\) aren't allowed/);
  assert.match(emailWebsiteProblem("asha@acme-group.com", "acme.com"), /@acme-group\.com doesn't match the company website \(acme\.com\)\. If this email is correct, click Save anyway/);
  assert.equal(isPersonalEmail("a@yahoo.co.in"), true);
  assert.equal(isPersonalEmail("a@srsconsultinginc.com"), false);
  assert.match(emailWebsiteProblem("asha@notacme.com", "acme.com"), /doesn't match/);
});
