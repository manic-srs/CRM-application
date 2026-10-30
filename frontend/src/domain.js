export const LEAD_STAGES = ["New", "Nurturing", "Demo", "Converted", "Lost"];
export const OPPORTUNITY_STAGES = ["Opportunity", "Proposal", "Won", "Lost"];
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
// The lead fields Apollo can fill (in form order)
export const AUTOFILL_FIELDS = {
  first_name: "First Name",
  last_name: "Last Name",
  company: "Company",
  title: "Title",
  industry: "Industry",
  email: "Email",
  phone: "Phone",
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

// Opportunity attachments. The backend checks the same rules again, and the real file content.
export const ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024; // shown as "20 MB per file"
export const ATTACHMENT_EXTENSIONS = [".pdf", ".docx", ".jpg", ".jpeg", ".png"];
export const ATTACHMENT_STAGES = ["Opportunity", "Proposal"]; // files can't be added or deleted after Won / Lost
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
      [
        "New",
        "Nurturing",
        "Demo",
        "Opportunity",
        "Proposal",
        "Won",
        "Lost",
      ].map((stage) => ({ stage, total: 0 }))
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
