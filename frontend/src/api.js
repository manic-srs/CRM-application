// The React dev server proxies /api to the locally configured backend.
const BASE = (import.meta.env?.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

// Login token from POST /auth/login, sent on every request. A 401 means the login expired
// (or the user was deactivated): the app then goes back to the login page.
let token = "";
export const setToken = (value) => {
  token = value || "";
};
const authHeaders = () => (token ? { Authorization: `Bearer ${token}` } : {});
function checkLogin(response) {
  if (response.status === 401 && token) window.dispatchEvent(new Event("crm-logout"));
}

export async function apiRequest(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal || AbortSignal.timeout(15000),
    });
  } catch (error) {
    throw new Error(
      error.name === "TimeoutError"
        ? "The backend took too long to respond. Try again."
        : "Cannot reach the backend. Check that it is running and try again.",
    );
  }
  checkLogin(response);
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = result?.detail;
    const message = Array.isArray(detail)
      ? detail
          .map(
            (item) =>
              `${item.loc.filter((part) => part !== "body").join(".")}: ${item.msg}`,
          )
          .join("; ")
      : typeof detail === "string"
        ? detail
        : "The backend could not complete this request.";
    throw new Error(message);
  }
  if (result === null)
    throw new Error("The backend returned an unexpected response.");
  return result;
}

const optional = (value) =>
  value === "" || value === undefined ? null : value;
const numeric = (value) =>
  value === "" || value == null ? null : Number(value);
export function leadPayload(values, editing = false) {
  const payload = {
    salutation: optional(values.salutation),
    first_name: optional(values.first_name?.trim()),
    last_name: values.last_name.trim(),
    company: values.company.trim(),
    title: optional(values.title),
    industry: optional(values.industry),
    email: optional(values.email),
    phone: optional(values.phone),
    source: values.source || "Other",
    owner_id: numeric(values.owner_id),
  };
  if (editing) payload.demo_date = optional(values.demo_date);
  else payload.welcome_email = values.welcome_email === "on";
  if (!editing && values.confirm_duplicate) payload.confirm_duplicate = true; // returning customer
  return payload;
}
export function taskPayload(values, editing = false) {
  const payload = {
    title: values.title.trim(),
    description: optional(values.description),
    due_date: values.due_date,
    reminder_at: optional(values.reminder_at),
    priority: values.priority,
    owner_id: numeric(values.owner_id),
  };
  if (!editing) {
    payload.lead_id =
      values.relatedType === "leads" ? numeric(values.relatedId) : null;
    payload.opportunity_id =
      values.relatedType === "opportunities" ? numeric(values.relatedId) : null;
  }
  return payload;
}
export function opportunityPayload(values) {
  return {
    name: values.name.trim(),
    expected_value: numeric(values.expected_value),
    expected_close_date: optional(values.expected_close_date),
    primary_contact_id: numeric(values.primary_contact_id),
    owner_id: numeric(values.owner_id),
  };
}
const actor = (editing, actorId) =>
  actorId ? { [editing ? "changed_by_id" : "created_by_id"]: Number(actorId) } : {};

// Multipart upload (email with attachments); JSON errors are read like apiRequest does
async function upload(path, formData) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: "POST",
      body: formData,
      headers: authHeaders(),
      signal: AbortSignal.timeout(60000),
    });
  } catch {
    throw new Error("Cannot reach the backend. Check that it is running and try again.");
  }
  checkLogin(response);
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = result?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ")
          : response.status === 413
            ? "The attachments are too large."
            : "The email could not be sent.",
    );
  }
  return result;
}

export const api = {
  // actorId = the logged-in user, so the backend can tell an owner "assigned to you by ..."
  saveLead: (v, id, actorId) =>
    apiRequest(id ? `/leads/${id}` : "/leads", {
      method: id ? "PUT" : "POST",
      body: { ...leadPayload(v, !!id), ...actor(id, actorId) },
    }),
  saveOpportunity: (v, id, actorId) =>
    apiRequest(`/opportunities/${id}`, {
      method: "PUT",
      body: { ...opportunityPayload(v), ...actor(id, actorId) },
    }),
  saveTask: (v, id, actorId) =>
    apiRequest(id ? `/tasks/${id}` : "/tasks", {
      method: id ? "PUT" : "POST",
      body: { ...taskPayload(v, !!id), ...actor(id, actorId) },
    }),
  completeTask: (id) => apiRequest(`/tasks/${id}/complete`, { method: "PUT" }),
  stage: (collection, id, values) =>
    apiRequest(`/${collection}/${id}/stage`, { method: "PUT", body: values }),
  lost: (collection, id, values) =>
    apiRequest(`/${collection}/${id}/lost`, { method: "POST", body: values }),
  won: (id, values) =>
    apiRequest(`/opportunities/${id}/won`, { method: "POST", body: values }),
  convert: (id, values) =>
    apiRequest(`/leads/${id}/convert`, { method: "POST", body: values }),
  transferLead: (id, values) =>
    apiRequest(`/leads/${id}/transfer`, { method: "POST", body: values }),
  cancelDemo: (id, values) =>
    apiRequest(`/leads/${id}/cancel-demo`, { method: "POST", body: values }),
  note: (collection, id, body) =>
    apiRequest("/notes", {
      method: "POST",
      body: {
        body,
        [collection === "leads" ? "lead_id" : "opportunity_id"]: Number(id),
      },
    }),
  readNotification: (id) =>
    apiRequest(`/notifications/${id}/read`, { method: "PUT" }),
  notifications: () => apiRequest("/notifications"),
  readAllNotifications: () => apiRequest("/notifications/read-all", { method: "PUT" }),
  saveAccount: (v) =>
    apiRequest("/accounts", {
      method: "POST",
      body: {
        name: v.name.trim(),
        industry: optional(v.industry),
        phone: optional(v.phone),
        website: optional(v.website),
        address: optional(v.address),
        owner_id: numeric(v.owner_id),
      },
    }),
  saveContact: (v) =>
    apiRequest("/contacts", {
      method: "POST",
      body: {
        salutation: optional(v.salutation),
        first_name: optional(v.first_name?.trim()),
        last_name: v.last_name.trim(),
        job_title: optional(v.job_title),
        email: optional(v.email),
        phone: optional(v.phone),
        account_id: Number(v.account_id),
        owner_id: numeric(v.owner_id),
      },
    }),
  login: (email, password) =>
    apiRequest("/auth/login", {
      method: "POST",
      body: { email: email.trim(), password },
    }),
  search: (q) => apiRequest(`/search?q=${encodeURIComponent(q)}`),
  me: () => apiRequest("/auth/me"),
  // My Profile: name + which notifications also come by email
  updateProfile: (changes) => apiRequest("/auth/me", { method: "PUT", body: changes }),
  changePassword: (current_password, new_password) =>
    apiRequest("/auth/password", { method: "PUT", body: { current_password, new_password } }),
  // Admin: users
  allUsers: () => apiRequest("/users?include_inactive=true"),
  createUser: (v) =>
    apiRequest("/users", {
      method: "POST",
      body: { full_name: v.full_name.trim(), email: v.email.trim(), password: v.password, role: v.role },
    }),
  updateUser: (id, changes) => apiRequest(`/users/${id}`, { method: "PUT", body: changes }),
  resetPassword: (id, password) => apiRequest(`/users/${id}/password`, { method: "PUT", body: { password } }),
  transferRecords: (id, toUserId, deactivate) =>
    apiRequest(`/users/${id}/transfer`, { method: "POST", body: { to_user_id: Number(toUserId), deactivate } }),
  emailSettings: () => apiRequest("/emails/settings"),
  // Roles & Permissions (Admin) and team access (Manager)
  permissions: () => apiRequest("/permissions"),
  activityLog: () => apiRequest("/activity-log"),
  setPermission: (role, permission, allowed) =>
    apiRequest("/permissions", { method: "PUT", body: { role, permission, allowed } }),
  setTeamAccess: (userId, team_access) =>
    apiRequest(`/users/${userId}/team-access`, { method: "PUT", body: { team_access } }),
  // duplicate email check before creating a lead
  leadDuplicates: (email) => apiRequest(`/leads/duplicates?email=${encodeURIComponent(email)}`),
  sendEmail: (formData) => upload("/emails", formData),
  resendEmail: (id) => apiRequest(`/emails/${id}/resend`, { method: "POST", signal: AbortSignal.timeout(60000) }),
  emails: (field, id) => apiRequest(`/emails?${field}=${encodeURIComponent(id)}`),
  // plain links can't send headers, so the download passes the login token in the address
  attachmentUrl: (id) => `${BASE}/emails/attachments/${id}?token=${encodeURIComponent(token)}`,
};

const idText = (value) => (value == null ? "" : String(value));
const day = (value) => value?.slice(0, 10) || "";
export function normalizeTask(record) {
  return {
    ...record,
    id: idText(record.id),
    due: day(record.due_date),
    reminder: record.reminder_at || "",
    completed: record.status !== "Open",
    isOverdue: record.is_overdue,
    relatedType:
      record.lead_id != null
        ? "leads"
        : record.opportunity_id != null
          ? "opportunities"
          : "general",
    relatedId: idText(record.lead_id ?? record.opportunity_id),
    owner: record.owner_name || "",
  };
}
function normalizeRecord(record, collection, contacts) {
  const contact = contacts.find((c) => c.id === record.primary_contact_id);
  return {
    ...record,
    id: idText(record.id),
    leadId: idText(record.lead_id),
    company: record.company ?? record.account_name ?? "",
    email: record.email ?? contact?.email ?? "",
    phone: record.phone ?? contact?.phone ?? "",
    role: record.title ?? contact?.job_title ?? "",
    value: record.stage === "Won" ? record.final_value : record.expected_value,
    closeDate: record.expected_close_date || "",
    created: day(record.created_at),
    owner: record.owner_name || "",
    lossReason: record.lost_reason || "",
    source: record.source || "",
    color: "sage",
    notes: record.notes || [],
    activity: (record.history || [])
      .map((event) => ({
        text:
          event.from_stage && event.from_stage === event.to_stage && event.note
            ? event.note
            : `${event.from_stage ? `${event.from_stage} → ` : "Created at "}${event.to_stage}${event.note ? `: ${event.note}` : ""}`,
        date: event.changed_at,
        by: event.changed_by_name,
      }))
      .reverse(),
    collection,
  };
}
export function normalizeWorkspace(raw, detail) {
  const contacts = raw.contacts || [];
  const data = {
    ...raw,
    leads: raw.leads.map((record) =>
      normalizeRecord(record, "leads", contacts),
    ),
    opportunities: raw.opportunities.map((record) =>
      normalizeRecord(record, "opportunities", contacts),
    ),
    tasks: raw.tasks.map(normalizeTask),
  };
  if (detail) {
    data[detail.collection] = data[detail.collection].map((record) =>
      record.id === idText(detail.record.id)
        ? normalizeRecord(detail.record, detail.collection, contacts)
        : record,
    );
  }
  return data;
}
