// Lead path (same as backend/app/constants.py): New -> Nurturing -> Revisit -> Demo -> Converted. New leads start at
// New. Revisit is optional ("not now": the lead asked to be contacted on a later date), so it can be passed over;
// every other stage must be done or confirmed as done. Closed without converting, from any open stage:
// Unqualified (not eligible, with a reason; can be reopened) or Lost.
// Shown in this order (path and board): Unqualified first, as the requirement lists it. New leads start at New;
// Unqualified is chosen for a lead that isn't eligible (a reason is required).
export const LEAD_STAGES = ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted", "Lost"];
// Leads Kanban: one column per status in that order; Unqualified, Converted and Lost are closed (terminal) columns
export const LEAD_OPEN_STAGES = ["New", "Nurturing", "Revisit", "Demo"];
export const LEAD_FLOW = LEAD_OPEN_STAGES; // then Convert
export const LEAD_OPTIONAL_STAGES = ["Revisit"];
export const LEAD_CLOSED_STAGES = ["Converted", "Unqualified", "Lost"];
// the stages each Leads list view contains (the same rule as LIST_VIEWS in backend/app/routers/lead_files.py)
const LEAD_VIEW_STAGES = {
  all_open: LEAD_OPEN_STAGES,
  my_open: LEAD_OPEN_STAGES,
  converted: ["Converted"],
  lost: ["Lost"],
  unqualified: ["Unqualified"],
  revisit_due: ["Revisit"],
};
// Per board column: whether the current list view and Lead Status filter can contain it ("" = yes, else why not)
export function leadBoardColumns(view, stageFilter) {
  return LEAD_STAGES.map((stage) => ({
    stage,
    closed: LEAD_CLOSED_STAGES.includes(stage),
    excluded: !(LEAD_VIEW_STAGES[view] || LEAD_STAGES).includes(stage)
      ? "Not in this list view"
      : stageFilter && stageFilter !== stage
        ? "Hidden by the Lead Status filter"
        : "",
  }));
}
// The existing popup a lead card opens for a stage (drop or Change Status menu), or null when that move isn't allowed:
// closed leads don't move, the same stage does nothing, and Convert needs the right to create opportunities.
export function leadStageAction(lead, stage, { canEdit, canConvert }) {
  if (!lead || !canEdit || !LEAD_OPEN_STAGES.includes(lead.stage) || lead.stage === stage) return null;
  if (stage === "Converted") return canConvert ? { type: "convert", record: lead } : null;
  if (stage === "Lost") return { type: "lost", collection: "leads", record: lead };
  if (stage === "Unqualified") return { type: "unqualified", record: lead };
  if (LEAD_OPEN_STAGES.includes(stage)) return { type: "stage", collection: "leads", record: lead, stage };
  return null;
}
// Opportunity path: Opportunity -> Discovery -> Proposal -> Won, or Lost from any open stage
export const OPPORTUNITY_STAGES = ["Opportunity", "Discovery", "Proposal", "Won", "Lost"];
export const OPPORTUNITY_OPEN_STAGES = ["Opportunity", "Discovery", "Proposal"];
export const OPPORTUNITY_FLOW = OPPORTUNITY_OPEN_STAGES; // then Won

// Stages a forward move passes over that must be confirmed as done (as the backend's confirm_skipped):
// everything between the current stage and the target, except optional stages. to = flow.length means
// past the end (Convert / Won). Going back skips nothing.
export function skippedStages(flow, from, to, optional = []) {
  const start = flow.indexOf(from), end = typeof to === "number" ? to : flow.indexOf(to);
  if (start < 0 || end <= start) return [];
  return flow.slice(start + 1, end).filter((stage) => !optional.includes(stage));
}
export const LEAD_SOURCES = [
  "Website",
  "Referral",
  "Phone",
  "Email",
  "Event",
  "Social Media",
  "Other",
];
// leads created by a bulk upload (not offered on the New Lead form)
export const UPLOAD_SOURCE = "Upload";
export const LOST_REASONS = [
  "Price",
  "Competitor",
  "No response",
  "No budget",
  "Not interested",
  "Other",
];
// Unqualified = not eligible (like Salesforce "Closed - Not Converted"); Not a fit and Bad data are permanent
export const UNQUALIFIED_REASONS = ["Not a fit", "No budget", "No authority", "No current need", "Bad timing", "Bad data", "Other"];
// Revisit = "not now": the lead asked to be contacted on a later date
export const REVISIT_REASONS = ["Bad timing", "Budget next period", "Asked to call back", "No response yet", "Other"];
export const SALUTATIONS = ["Mr.", "Ms.", "Mrs.", "Dr.", "Prof."];

// LinkedIn autofill on New Lead. The backend checks the address again and is the only one that talks to Apollo.
const PROFILE_HINT = "Enter a LinkedIn profile address like https://www.linkedin.com/in/name";
export function linkedInProfileUrl(value) {
  let raw = (value || "").trim();
  if (!raw || raw.length > 300 || /\s/.test(raw)) return { error: PROFILE_HINT };
  if (!raw.includes("://")) {
    if (raw.startsWith("/") || raw.split("/")[0].includes(":")) return { error: PROFILE_HINT };
    raw = `https://${raw}`;
  }
  let parts;
  try {
    parts = new URL(raw);
  } catch {
    return { error: PROFILE_HINT };
  }
  if (!["http:", "https:"].includes(parts.protocol)) return { error: "Only https:// LinkedIn profile addresses can be used" };
  const authority = raw.split("/")[2] || "";
  if (authority.includes("@") || authority.includes(":") || !/^(?:www\.|[a-z]{2}\.)?linkedin\.com$/.test(parts.hostname))
    return { error: "This isn't a linkedin.com profile address" };
  const match = /^\/in\/([^/]+)\/?$/.exec(parts.pathname);
  if (!match) return { error: "Use a person's profile address (linkedin.com/in/...), not a company, school or other page" };
  let name;
  try {
    name = decodeURIComponent(match[1]);
  } catch {
    name = "";
  }
  if (!/^[\p{L}\p{N}_-]{3,100}$/u.test(name)) return { error: "This LinkedIn profile address isn't valid" };
  return { url: `https://linkedin.com/in/${encodeURIComponent(name.toLowerCase())}` };
}
// The lead fields Apollo can fill (in form order). The company ones come from the person's current employer; the
// backend checks the two links with the form's own rules.
export const AUTOFILL_FIELDS = {
  first_name: "First Name",
  last_name: "Last Name",
  company: "Company",
  title: "Title",
  industry: "Industry",
  email: "Email",
  phone: "Phone",
  company_website: "Company Website",
  company_linkedin_url: "Company LinkedIn URL",
};
// current: the form's values now; previous: values Apollo filled earlier that are still unchanged; incoming: the
// current profile's values ({} removes the earlier profile's values). Fills empty fields, replaces or clears
// unchanged earlier autofill, and never changes what the user typed.
export function autofillPlan(current, previous, incoming) {
  const set = {},
    autofilled = {},
    filled = [],
    kept = [];
  for (const name of Object.keys(AUTOFILL_FIELDS)) {
    const now = current[name] ?? "";
    const untouched = previous[name] !== undefined && now === previous[name];
    const value = incoming[name];
    if (value && (!now.trim() || untouched)) {
      if (now !== value) set[name] = value;
      autofilled[name] = value;
      filled.push(name);
    } else if (value && now.trim() !== value) kept.push(name); // the user's own value stays
    else if (!value && untouched) set[name] = ""; // the earlier profile's value doesn't belong to this one
  }
  return { set, autofilled, filled, kept };
}
export const PRIORITIES = ["Low", "Normal", "High"];
export const dateKey = (date = new Date()) =>
  new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
// The current backend stores amounts without a currency field.
export const money = (value) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(
        value,
      );
export const localInput = (value) => (value ? value.slice(0, 16) : "");

// Every stage change needs the user's note, saved in the Stage History (the backend refuses a blank one too).
// The popup field that holds it: Note (Change Stage, Convert), Closing Note (Won), Lost Notes (Lost), and the Reason
// when a cancelled demo moves the lead back to Revisit. Rescheduling keeps the stage, so its reason stays optional.
export const STAGE_NOTE_REQUIRED = "Enter a note to change the stage.";
// Convert uses the same note, labelled "Conversion Comment", with its own message (as the backend says)
export const CONVERSION_COMMENT_REQUIRED = "Enter a conversion comment.";
export const stageNoteMessage = (type) => (type === "convert" ? CONVERSION_COMMENT_REQUIRED : STAGE_NOTE_REQUIRED);
export function stageNoteField(type, demoChoice) {
  if (["stage", "won", "convert", "newOpportunity"].includes(type)) return "note";
  if (type === "lost") return "lost_notes";
  if (type === "unqualified") return "notes";
  if (type === "reopen") return "note";
  if (type === "cancelDemo" && demoChoice === "nurturing") return "reason";
  return null;
}
// The note as saved: spaces and line breaks around it are trimmed, the formatting inside is kept ("" = blank)
export const stageNote = (value) => (typeof value === "string" ? value.trim() : "");

// Every stage change except Lost also needs a New Task (the backend refuses one without it): the next follow-up,
// the first task of the new opportunity on Convert, a post-sale task on Won. Fields as on the task form (task_*).
export const TASK_SUBJECT_REQUIRED = "Enter a task subject.";
export const TASK_DUE_REQUIRED = "Choose a due date for the task.";
export const stageTaskNeeded = (type, demoChoice) =>
  ["stage", "convert", "won", "reopen", "newOpportunity"].includes(type) || (type === "cancelDemo" && demoChoice === "nurturing");
export function stageTaskProblems(values) {
  const problems = {};
  if (!stageNote(values.task_title)) problems.task_title = TASK_SUBJECT_REQUIRED;
  if (!stageNote(values.task_due_date)) problems.task_due_date = TASK_DUE_REQUIRED;
  return problems;
}
export function stageTaskPayload(values) {
  const optional = (value) => stageNote(value) || null;
  return {
    title: stageNote(values.task_title),
    due_date: values.task_due_date,
    priority: values.task_priority || "Normal",
    reminder_at: optional(values.task_reminder_at),
    description: optional(values.task_description),
    owner_id: values.task_owner_id ? Number(values.task_owner_id) : null,
  };
}

// Opportunity attachments. The backend checks the same rules again, and the real file content.
export const ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024; // shown as "20 MB per file"
export const ATTACHMENT_EXTENSIONS = [".pdf", ".docx", ".jpg", ".jpeg", ".png"];
export const ATTACHMENT_STAGES = OPPORTUNITY_OPEN_STAGES; // files can't be added or deleted after Won / Lost
export const WON_FILES_STAGE = "Proposal"; // files added in the Mark as Won popup close the Proposal stage
export const PREVIEW_TYPES = ["application/pdf", "image/jpeg", "image/png"]; // open in a new tab; Word files download
const extension = (name) => {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
};
// Type of a file chosen on this computer, from its extension (used for its local preview only)
export const attachmentType = (name) =>
  ({
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
  })[extension(name || "")] || "";
export function attachmentProblem(file) {
  const name = file.name || "";
  const ext = extension(name);
  if (ext === ".doc")
    return `${name}: old Word files (.doc) can't be uploaded. Save it as .docx first.`;
  if (!ATTACHMENT_EXTENSIONS.includes(ext))
    return `${name}: only PDF, Word (.docx), JPG and PNG files can be uploaded.`;
  if (!file.size) return `${name} is empty.`;
  if (file.size > ATTACHMENT_MAX_BYTES) return `${name} is larger than 20 MB.`;
  return "";
}
// Files chosen in the Change Stage popup (saved with the stage change). Refused files are explained,
// and the same file chosen twice is added once.
export const STAGE_FILES_MAX = 5;
export function pickStageFiles(current, picked) {
  const files = [...current],
    problems = [];
  const same = (a, b) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
  for (const file of picked) {
    const problem = attachmentProblem(file);
    if (problem) problems.push(problem);
    else if (files.some((f) => same(f, file))) continue;
    else if (files.length >= STAGE_FILES_MAX)
      problems.push(`${file.name}: up to ${STAGE_FILES_MAX} files can be added here. Add more on the Attachments card after saving.`);
    else files.push(file);
  }
  return { files, problems };
}
export function salesOverview(data) {
  const home = data.home;
  const result = (outcome) =>
    home?.won_vs_lost?.find((item) => item.outcome === outcome);
  const wonCount = result("Won")?.deals || 0,
    lostCount = result("Lost")?.deals || 0;
  return {
    totalLeads: home?.summary?.total_leads || 0,
    openOpportunities: home?.summary?.open_opportunities || 0,
    wonCount,
    lostCount,
    wonValue: result("Won")?.value,
    lostValue: result("Lost")?.value,
    stages: (
      home?.pipeline ||
      [...LEAD_OPEN_STAGES, ...OPPORTUNITY_OPEN_STAGES, "Won", "Lost"].map((stage) => ({ stage, total: 0 }))
    ).map((item) => ({ stage: item.stage, count: item.total })),
    activeCount: (home?.pipeline || [])
      .filter((item) => !["Won", "Lost"].includes(item.stage))
      .reduce((sum, item) => sum + item.total, 0),
    todayTasks: (home?.todays_tasks || [])
      .map((task) => data.tasks.find((item) => item.id === String(task.id)))
      .filter(Boolean),
    dueToday: home?.summary?.tasks_due_today || 0,
    winRate:
      wonCount + lostCount
        ? Math.round((wonCount / (wonCount + lostCount)) * 100)
        : 0,
  };
}

// A lead's email is expected on the company's domain, as its Company Website (the same rule as the backend's
// services.email_matches_website): "name@acme.com" for acme.com; a subdomain either way is fine. Another domain is
// asked about once (Save anyway), since some companies email from a different domain than their website;
// a personal mailbox (gmail.com...) is refused.
export const websiteHost = (url) => {
  const host = (url || "").trim().toLowerCase().replace(/^[a-z][a-z0-9+.-]*:\/\//, "").split(/[/?:#]/)[0];
  return host.startsWith("www.") ? host.slice(4) : host;
};
const PERSONAL_EMAIL_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com", "hotmail.com", "outlook.com",
  "live.com", "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com",
  "pm.me", "gmx.com", "gmx.net", "mail.com", "yandex.com", "yandex.ru", "zohomail.com", "rediffmail.com",
  "tutanota.com", "hey.com", "fastmail.com", "qq.com", "163.com", "126.com",
]);
const PERSONAL_EMAIL_NAMES = new Set(["gmail", "yahoo", "hotmail", "outlook", "live", "aol", "rediffmail", "ymail"]);
// a personal mailbox (gmail.com, yahoo.co.in...): never a lead's email (same list as the backend)
export function isPersonalEmail(email) {
  const domain = (email || "").trim().toLowerCase().split("@").pop();
  if (!(email || "").includes("@") || !domain) return false;
  const [name, ...rest] = domain.split(".");
  return PERSONAL_EMAIL_DOMAINS.has(domain) || (PERSONAL_EMAIL_NAMES.has(name) && rest.join(".").length <= 6);
}
export function emailWebsiteProblem(email, website) {
  const domain = (email || "").trim().toLowerCase().split("@").pop();
  const host = websiteHost(website);
  if (!(email || "").includes("@") || !domain || !host) return null;
  if (domain === host || domain.endsWith(`.${host}`) || host.endsWith(`.${domain}`)) return null;
  if (isPersonalEmail(email))
    return `Personal emails (@${domain}) aren't allowed for a lead. Use the lead's work email, e.g. name@${host}.`;
  return `Please check the email: @${domain} doesn't match the company website (${host}). If this email is correct, click Save anyway.`;
}

// New Campaign's "To" field: what was typed or pasted, split into recipients. Addresses are separated by new lines,
// commas, semicolons or spaces; "Asha Rao <asha@acme.com>" keeps the name. Validity is checked by the caller.
export function parseRecipients(text) {
  const out = [];
  for (const raw of (text || "").split(/[\n,;]+/)) {
    const part = raw.trim();
    if (!part) continue;
    const named = part.match(/^"?([^"<]*?)"?\s*<([^>]+)>$/);
    if (named) {
      out.push({ email: named[2].trim(), name: named[1].trim() || null });
      continue;
    }
    for (const word of part.split(/\s+/)) out.push({ email: word.replace(/^<|>$/g, "") });
  }
  return out;
}

// {company} for someone typed in without one: from the email's domain ("asha@acme-retail.com" -> "Acme Retail"),
// nothing for personal mailboxes (same as the backend's campaigns.company_from_email)
export function companyFromEmail(email) {
  if (!(email || "").includes("@") || isPersonalEmail(email)) return "";
  const name = email.trim().toLowerCase().split("@").pop().split(".")[0];
  return name
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}
