// The React dev server proxies /api to the locally configured backend.
const BASE = (import.meta.env?.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export async function apiRequest(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
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
    probability: Number(values.probability),
    primary_contact_id: numeric(values.primary_contact_id),
    owner_id: numeric(values.owner_id),
  };
}
export const api = {
  saveLead: (v, id) =>
    apiRequest(id ? `/leads/${id}` : "/leads", {
      method: id ? "PUT" : "POST",
      body: leadPayload(v, !!id),
    }),
  saveOpportunity: (v, id) =>
    apiRequest(`/opportunities/${id}`, {
      method: "PUT",
      body: opportunityPayload(v),
    }),
  saveTask: (v, id) =>
    apiRequest(id ? `/tasks/${id}` : "/tasks", {
      method: id ? "PUT" : "POST",
      body: taskPayload(v, !!id),
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
        text: `${event.from_stage ? `${event.from_stage} → ` : "Created at "}${event.to_stage}${event.note ? `: ${event.note}` : ""}`,
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
