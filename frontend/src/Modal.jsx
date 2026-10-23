// Create / edit dialogs (lead, opportunity, task, account, contact) and the stage actions
// (lost, won, convert, stage change, note). Form logic by Samhit; Salesforce-style layout.
import React, { useEffect, useRef, useState } from "react";
import { LEAD_SOURCES, LOST_REASONS, PRIORITIES, SALUTATIONS, localInput } from "./domain";
import { Icon } from "./ui";

const go = (path) => {
  window.location.hash = path;
};

export default function Modal({ modal, close, data, run, notify, user }) {
  const ref = useRef(null),
    previousFocus = useRef(document.activeElement),
    lock = useRef(false);
  const [error, setError] = useState(""),
    [submitting, setSubmitting] = useState(false);
  const record = modal.record;
  const type = modal.type;
  const [relatedType, setRelatedType] = useState(
    record?.relatedType || modal.relatedType || "general",
  );
  const titles = {
    lead: record ? `Edit ${record.name}` : "New Lead",
    opportunity: `Edit ${record?.name}`,
    task: record ? `Edit Task` : "New Task",
    account: "New Account",
    contact: "New Contact",
    lost: `Mark as Lost: ${record?.name}`,
    won: `Mark as Won: ${record?.name}`,
    convert: `Convert Lead: ${record?.name}`,
    stage: `Change Stage to ${modal.stage}`,
    note: "New Note",
  };
  useEffect(() => {
    const first = ref.current.querySelector("input,select,textarea,button");
    first?.focus();
    const key = (event) => {
      if (event.key === "Escape" && !lock.current) close();
      if (event.key === "Tab") {
        const items = [
          ...ref.current.querySelectorAll("input,select,textarea,button"),
        ].filter((el) => !el.disabled);
        if (event.shiftKey && document.activeElement === items[0]) {
          event.preventDefault();
          items.at(-1).focus();
        } else if (!event.shiftKey && document.activeElement === items.at(-1)) {
          event.preventDefault();
          items[0].focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
      previousFocus.current?.focus();
    };
  }, []);
  const field = (
    label,
    name,
    inputType = "text",
    required = false,
    value = record?.[name] ?? "",
  ) => (
    <label className="field">
      <span>
        {label}
        {required && <i> *</i>}
      </span>
      <input
        name={name}
        type={inputType}
        required={required}
        defaultValue={value}
        min={inputType === "number" ? 0 : undefined}
        max={name === "probability" ? 100 : undefined}
        step={
          name === "probability"
            ? 1
            : inputType === "number"
              ? "any"
              : undefined
        }
        maxLength={
          ["first_name", "last_name"].includes(name)
            ? 50
            : name === "company"
              ? 200
              : undefined
        }
      />
    </label>
  );
  // Tick box for the no-reply email to the customer (ticked by default; the backend skips it if there is no email)
  const customerEmail =
    type === "won"
      ? data.contacts.find((c) => c.id === record?.primary_contact_id)?.email
      : record?.email;
  const customerCheck = (label, hint) => (
    <label className="check-field welcome-check">
      <input type="checkbox" name="notify_customer" defaultChecked={!!customerEmail} disabled={!customerEmail} />
      <span>
        {label}
        <small>{customerEmail ? `To ${customerEmail}. ${hint}` : "No email address on this record, so nothing is sent."}</small>
      </span>
    </label>
  );
  const textArea = (label, name, value = "") => (
    <label className="field">
      <span>{label}</span>
      <textarea name={name} rows={3} defaultValue={value} />
    </label>
  );
  const select = (
    label,
    name,
    options,
    value = record?.[name] ?? "",
    required = false,
  ) => (
    <label className="field">
      <span>
        {label}
        {required && <i> *</i>}
      </span>
      <select name={name} defaultValue={value} required={required}>
        <option value="">
          {required ? "Select an option" : "Default / not specified"}
        </option>
        {options.map((option) => {
          const [id, label] = Array.isArray(option) ? option : [option, option];
          return (
            <option key={id} value={id}>
              {label}
            </option>
          );
        })}
      </select>
    </label>
  );
  // Only Managers and Admins can give a record to someone else; a Salesperson sees the owner read-only
  const canAssign = ["Manager", "Admin"].includes(user?.role);
  const owner = () =>
    !canAssign ? (
      <label className="field">
        <span>Owner</span>
        <input readOnly value={record?.owner || user?.full_name || ""} aria-readonly="true" />
        <input type="hidden" name="owner_id" value={record?.owner_id ?? user?.id ?? ""} />
      </label>
    ) : select("Owner", "owner_id", [
      ...data.users.map((user) => [user.id, user.full_name]),
      ...(record?.owner_id &&
      !data.users.some((user) => user.id === record.owner_id)
        ? [[record.owner_id, record.owner || "Current owner"]]
        : []),
    ], record?.owner_id ?? user?.id ?? "");
  // The green message after saving says what happened (the customer email, if any, is mentioned too)
  const doneMessage = (v, saved) => {
    const name = record?.name;
    const mailed = v.notify_customer === "on" ? " The customer was emailed." : "";
    if (type === "convert") return "Lead converted. Account, contact, opportunity and follow-up task created.";
    if (type === "lead" && !record)
      return `Lead "${saved.name}" was created.${v.welcome_email === "on" && v.email ? " A welcome email was sent to the lead." : ""}`;
    if (type === "stage") return `"${name}" moved to ${modal.stage}. The next follow-up task was created.`;
    if (type === "won") return `"${name}" was marked as Won.${mailed}`;
    if (type === "lost") return `"${name}" was marked as Lost.${mailed}`;
    if (type === "task") return record ? "Task updated." : "Task created.";
    if (type === "note") return "Note added.";
    if (type === "account") return `Account "${saved.name}" was created.`;
    if (type === "contact") return `Contact "${saved.full_name || v.last_name}" was created.`;
    return "Your changes were saved.";
  };
  const submit = async (event) => {
    event.preventDefault();
    if (lock.current) return;
    lock.current = true;
    setSubmitting(true);
    setError("");
    const v = Object.fromEntries(new FormData(event.target));
    try {
      let saved;
      if (type === "lead") {
        if (!v.last_name.trim() || !v.company.trim())
          throw new Error("Last name and company are required.");
        saved = await run("saveLead", v, record?.id, user?.id);
      }
      if (type === "opportunity")
        saved = await run("saveOpportunity", v, record.id, user?.id);
      if (type === "task") {
        if (!v.title.trim()) throw new Error("Task title is required.");
        saved = await run("saveTask", v, record?.id, user?.id);
      }
      if (type === "account") {
        if (!v.name.trim()) throw new Error("Account name is required.");
        saved = await run("saveAccount", v);
      }
      if (type === "contact") {
        if (!v.last_name.trim()) throw new Error("Last name is required.");
        saved = await run("saveContact", v);
      }
      if (type === "lost")
        await run("lost", modal.collection, record.id, {
          lost_reason: v.lost_reason,
          lost_notes: v.lost_notes || null,
          notify_customer: v.notify_customer === "on",
        });
      if (type === "won")
        await run("won", record.id, {
          final_value: v.final_value === "" ? null : Number(v.final_value),
          note: v.note || null,
          notify_customer: v.notify_customer === "on",
        });
      if (type === "convert")
        saved = await run("convert", record.id, {
          opportunity_name: v.opportunity_name || null,
          expected_value:
            v.expected_value === "" ? null : Number(v.expected_value),
          expected_close_date: v.expected_close_date || null,
          account_id: v.account_id ? Number(v.account_id) : null,
        });
      if (type === "stage")
        await run("stage", modal.collection, record.id, {
          stage: modal.stage,
          note: v.note || null,
          ...(modal.collection === "leads" && modal.stage === "Demo"
            ? { demo_date: v.demo_date || null }
            : {}),
        });
      if (type === "note") {
        if (!v.body.trim()) throw new Error("Note cannot be blank.");
        await run("note", modal.collection, record.id, v.body.trim());
      }
      close();
      notify(doneMessage(v, saved));
      if (type === "lead") go(`/leads/${saved.id}`);
      if (type === "account") go(`/accounts/${saved.id}`);
      if (type === "contact") go(`/contacts/${saved.id}`);
      if (type === "convert") go(`/opportunities/${saved.opportunity.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      lock.current = false;
      setSubmitting(false);
    }
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !submitting) close();
      }}
    >
      <section
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <button
          className="modal-close"
          aria-label="Close dialog"
          onClick={close}
          disabled={submitting}
        >
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="modal-title">{titles[type]}</h2>
        </header>
        <form onSubmit={submit}>
          <div className="modal-body">
          <p className="modal-subtitle">
            {type === "convert"
              ? "Creates an account (or uses an existing one), a contact and an opportunity. Open lead tasks are closed automatically."
              : type === "stage"
                ? "Open follow-up tasks are closed automatically and the next follow-up task is created."
                : <><i className="req">*</i> = Required Information</>}
          </p>
          {type === "account" && (
            <div className="form-grid">
              {field("Account Name", "name", "text", true, "")}
              {field("Industry", "industry", "text", false, "")}
              {field("Phone", "phone", "tel", false, "")}
              {field("Website", "website", "text", false, "")}
              {field("Address", "address", "text", false, "")}
              {owner()}
            </div>
          )}
          {type === "contact" && (
            <div className="form-grid">
              {select("Salutation", "salutation", SALUTATIONS, "")}
              {field("First Name", "first_name", "text", false, "")}
              {field("Last Name", "last_name", "text", true, "")}
              {select(
                "Account Name",
                "account_id",
                data.accounts.map((a) => [a.id, a.name]),
                modal.defaults?.account_id ?? "",
                true,
              )}
              {field("Title", "job_title", "text", false, "")}
              {field("Email", "email", "email", false, "")}
              {field("Phone", "phone", "tel", false, "")}
              {owner()}
            </div>
          )}
          {type === "lead" && (
            <div className="form-grid">
              {select("Salutation", "salutation", SALUTATIONS)}
              {field("First Name", "first_name")}
              {field("Last Name", "last_name", "text", true)}
              {field("Company", "company", "text", true)}
              {field("Title", "title")}
              {field("Industry", "industry")}
              {field("Email", "email", "email")}
              {field("Phone", "phone", "tel")}
              {select(
                "Lead Source",
                "source",
                LEAD_SOURCES,
                record?.source || "Other",
                true,
              )}
              {owner()}
              {!record && (
                <label className="check-field welcome-check">
                  <input type="checkbox" name="welcome_email" defaultChecked />
                  <span>
                    Send the lead a welcome email
                    <small>An automatic (no-reply) email to the lead's email address saying their profile was created and who will contact them.</small>
                  </span>
                </label>
              )}
              {record &&
                field(
                  "Demo Date",
                  "demo_date",
                  "datetime-local",
                  false,
                  localInput(record.demo_date),
                )}
            </div>
          )}
          {type === "opportunity" && (
            <div className="form-grid">
              {field("Opportunity Name", "name", "text", true)}
              {field("Amount", "expected_value", "number")}
              {field("Close Date", "expected_close_date", "date")}
              {field("Probability (%)", "probability", "number", true)}
              {select(
                "Primary Contact",
                "primary_contact_id",
                data.contacts
                  .filter((contact) => contact.account_id === record.account_id)
                  .map((contact) => [contact.id, contact.full_name]),
              )}
              {owner()}
            </div>
          )}
          {type === "task" && (
            <>
              <div className="form-grid">
                {field("Subject", "title", "text", true)}
                {field(
                  "Due Date",
                  "due_date",
                  "datetime-local",
                  true,
                  localInput(record?.due_date),
                )}
                {select(
                  "Priority",
                  "priority",
                  PRIORITIES,
                  record?.priority || "Normal",
                  true,
                )}
                {owner()}
                {field(
                  "Reminder",
                  "reminder_at",
                  "datetime-local",
                  false,
                  localInput(record?.reminder_at),
                )}
                {!record ? (
                  <>
                    <label className="field">
                      <span>Related To</span>
                      <select
                        name="relatedType"
                        value={relatedType}
                        onChange={(event) => setRelatedType(event.target.value)}
                      >
                        <option value="general">General task</option>
                        <option value="leads">Lead</option>
                        <option value="opportunities">Opportunity</option>
                      </select>
                    </label>
                    {relatedType !== "general" && (
                      <label className="field">
                        <span>
                          Record <i>*</i>
                        </span>
                        <select
                          name="relatedId"
                          required
                          key={relatedType}
                          defaultValue={
                            modal.relatedType === relatedType
                              ? modal.relatedId
                              : ""
                          }
                        >
                          <option value="">Select a record</option>
                          {data[relatedType].map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </>
                ) : (
                  <label className="field">
                    <span>Related Record</span>
                    <input
                      readOnly
                      value={record.related_to || "General task"}
                    />
                  </label>
                )}
              </div>
              {textArea(
                "Description",
                "description",
                record?.description || "",
              )}
            </>
          )}
          {type === "lost" && (
            <>
              {select("Lost Reason", "lost_reason", LOST_REASONS, "", true)}
              {textArea("Lost Notes", "lost_notes")}
              {customerCheck(
                "Send the customer a polite closing email",
                "A short thank-you (no-reply). The lost reason and notes are internal and are never sent.",
              )}
            </>
          )}
          {type === "won" && (
            <>
              {field(
                "Final Amount",
                "final_value",
                "number",
                record.expected_value == null,
                record.expected_value ?? "",
              )}
              {textArea("Closing Note", "note")}
              {customerCheck(
                "Send the customer a thank-you email",
                "A no-reply email to the deal's contact: thank you for accepting the proposal, and who will contact them about next steps.",
              )}
            </>
          )}
          {type === "convert" && (
            <>
              <div className="form-grid">
                {field("Opportunity Name", "opportunity_name")}
                {field("Amount", "expected_value", "number")}
                {field("Close Date", "expected_close_date", "date")}
                <label className="field">
                  <span>Account</span>
                  <select name="account_id" defaultValue="">
                    <option value="">Create new account from company</option>
                    {data.accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </>
          )}
          {type === "stage" && (
            <>
              {modal.stage === "Demo" &&
                field(
                  "Demo Date",
                  "demo_date",
                  "datetime-local",
                  false,
                  localInput(record.demo_date),
                )}
              {textArea("Note", "note")}
            </>
          )}
          {type === "note" && (
            <label className="field">
              <span>
                Note <i>*</i>
              </span>
              <textarea name="body" required rows={5} />
            </label>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          </div>
          <div className="modal-footer">
            <button
              type="button"
              className="sf-button"
              onClick={close}
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="sf-button brand"
              disabled={submitting}
              aria-busy={submitting}
            >
              {submitting
                ? "Saving…"
                : type === "convert"
                  ? "Convert lead"
                  : type === "won"
                    ? "Mark as won"
                    : type === "lost"
                      ? "Mark as lost"
                      : "Save"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
