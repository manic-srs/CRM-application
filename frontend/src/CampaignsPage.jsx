// Email campaigns: one email to many people (leads, or typed-in addresses), sent a few at a time under the Outlook limits (backend/app/campaigns.py).
// - Campaigns page: every campaign with its progress; open one to see who got it, who was left out and why.
// - New Campaign: from this page (typed-in email addresses, also people not in the CRM) or from
//   Leads > select leads > Actions > Email Campaign.
// Unsubscribed leads and invalid emails are always left out, and every email ends with an unsubscribe link.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { companyFromEmail, LEAD_OPEN_STAGES, LEAD_STAGES, parseEmailList } from "./domain";
import { can } from "./permissions";
import { Icon, ObjectIcon } from "./ui";

const n = (x) => Number(x || 0).toLocaleString();
const when = (value) =>
  value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
const STATUS_TONE = { Scheduled: "info", Sending: "live", Paused: "warn", Completed: "ok", Cancelled: "off" };
const FIELDS = [
  ["first_name", "First name"],
  ["company", "Company"],
  ["full_name", "Full name"],
  ["sender_name", "Your name"],
];
const SAMPLE_BODY =
  "Hi {first_name},\n\nI wanted to share a quick update that may be useful for {company}.\n\n" +
  "Would you be open to a short call next week?\n\nBest regards,\n{sender_name}";

function duration(minutes, days) {
  if (days) return `about ${days} day${days === 1 ? "" : "s"}${minutes % 1440 ? " and more" : ""}`;
  if (minutes < 2) return "about a minute";
  if (minutes < 90) return `about ${minutes} minutes`;
  return `about ${Math.round(minutes / 60)} hours`;
}

// the {fields} for the preview, filled like the backend does (campaigns.fill): a missing company comes from the
// email's domain
function fill(text, lead, user) {
  const values = {
    first_name: lead?.first_name || lead?.name?.split(" ")[0] || "there",
    last_name: lead?.last_name || "",
    full_name: lead?.name || "",
    company: lead?.company || companyFromEmail(lead?.email) || "your team",
    sender_name: user.full_name,
  };
  return text.replace(/\{(\w+)\}/g, (all, key) => (key in values ? values[key] : all));
}

function Dialog({ title, onClose, busy, children, footer }) {
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="modal campaign-modal" role="dialog" aria-modal="true" aria-labelledby="campaign-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="campaign-title">{title}</h2>
        </header>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">{footer}</div>
      </section>
    </div>
  );
}

// ---------- New Campaign ----------

// Choosing recipients by lead stage (and owner) is switched OFF for now: New Campaign takes typed-in email addresses
// instead, so people who aren't in the CRM can be emailed too (requirement, Nov 2026). The stage picker below is kept
// and still works in the API (Audience.stages): set STAGE_PICKER to true to bring the checkboxes back.
const STAGE_PICKER = false;
const plural = (count, word) => `${n(count)} ${word}${count === 1 ? "" : "s"}`;

export function NewCampaign({ user, users = [], leadIds = null, onClose, onCreated }) {
  const team = user.role === "Admin" || can(user, "view_team_records");
  const [stages, setStages] = useState(LEAD_OPEN_STAGES);
  const [emailText, setEmailText] = useState(""); // typed-in addresses, one per line (name, company optional)
  const typed = useMemo(() => parseEmailList(emailText), [emailText]);
  const [owner, setOwner] = useState(team ? "" : String(user.id));
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("Quick question for {company}");
  const [body, setBody] = useState(SAMPLE_BODY);
  const [timing, setTiming] = useState("now");
  const [sendAt, setSendAt] = useState("");
  const [preview, setPreview] = useState(null);
  const [settings, setSettings] = useState(null);
  const [showLeftOut, setShowLeftOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bodyRef = useRef(null);
  const audience = useMemo(() => {
    const emails = typed.items;
    if (leadIds) return { lead_ids: leadIds, emails };
    if (STAGE_PICKER) return { stages, owner_id: owner ? Number(owner) : null, emails };
    return { emails };
  }, [leadIds, stages, owner, typed]);
  const nobody = !leadIds && (STAGE_PICKER ? !stages.length && !typed.items.length : !typed.items.length);

  useEffect(() => {
    api.campaignSettings().then(setSettings).catch(() => {});
  }, []);
  useEffect(() => {
    if (nobody) return setPreview(null);
    let stale = false;
    setPreview((p) => (p ? { ...p, loading: true } : p));
    const timer = setTimeout(() => {
      api
        .campaignPreview(audience)
        .then((p) => !stale && (setPreview(p), setError("")))
        .catch((err) => !stale && setError(err.message));
    }, 250);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [audience, nobody]);

  const insert = (field) => {
    const box = bodyRef.current;
    const token = `{${field}}`;
    if (!box) return setBody((b) => b + token);
    const start = box.selectionStart ?? body.length;
    const end = box.selectionEnd ?? body.length;
    setBody(body.slice(0, start) + token + body.slice(end));
    requestAnimationFrame(() => {
      box.focus();
      box.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (name.trim().length < 2) return setError("Give the campaign a name.");
    if (subject.trim().length < 2) return setError("Write a subject.");
    if (body.trim().length < 10) return setError("Write the email.");
    if (timing === "later" && !sendAt) return setError("Choose when to send it.");
    if (timing === "later" && new Date(sendAt) < new Date()) return setError("Choose a time in the future.");
    if (nobody) return setError("Add the email addresses to send to.");
    if (!preview?.eligible) return setError("Nobody here can get the email (see who is left out).");
    setBusy(true);
    setError("");
    try {
      const created = await api.createCampaign({
        ...audience,
        name: name.trim(),
        subject: subject.trim(),
        body: body.trim(),
        send_at: timing === "later" ? new Date(sendAt).toISOString() : null,
      });
      onCreated(created);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  const limits = settings?.limits;
  const sample = preview?.sample?.[0];
  const reasons = preview?.reasons || {};
  const leftOutParts = [
    [reasons.unsubscribed, "unsubscribed"],
    [reasons.invalid, "invalid email"],
    [reasons.no_email, "no email"],
    [reasons.other, "same email twice"],
  ].filter(([count]) => count);
  return (
    <Dialog
      title={leadIds ? `Email Campaign: ${n(leadIds.length)} Selected Lead${leadIds.length === 1 ? "" : "s"}` : "New Campaign"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button type="button" className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form="campaign-form" className="sf-button brand" disabled={busy || !preview?.eligible} aria-busy={busy}>
            {busy
              ? "Saving…"
              : timing === "later"
                ? `Schedule for ${plural(preview?.eligible || 0, "person").replace("persons", "people")}`
                : `Send to ${plural(preview?.eligible || 0, "person").replace("persons", "people")}`}
          </button>
        </>
      }
    >
      <form id="campaign-form" className="campaign-form" onSubmit={submit}>
        <label className="field">
          <span>
            Campaign name <i>*</i>
          </span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={150} placeholder="e.g. November follow-up" />
        </label>

        <fieldset className="campaign-section">
          <legend>Recipients</legend>
          {leadIds && <p className="field-hint">The {plural(leadIds.length, "lead")} you selected in the Leads list.</p>}
          {STAGE_PICKER && !leadIds && (
            <>
              <div className="stage-chips" role="group" aria-label="Lead Status">
                {LEAD_STAGES.map((stage) => (
                  <label key={stage} className={`person-chip ${stages.includes(stage) ? "on" : ""}`}>
                    <input
                      type="checkbox"
                      checked={stages.includes(stage)}
                      onChange={(e) => setStages((s) => (e.target.checked ? [...s, stage] : s.filter((x) => x !== stage)))}
                    />
                    {stage}
                  </label>
                ))}
              </div>
              {team && (
                <label className="field compact">
                  <span>Lead Owner</span>
                  <select value={owner} onChange={(e) => setOwner(e.target.value)}>
                    <option value="">Anyone</option>
                    {users
                      .filter((u) => u.is_active !== false && u.role !== "Admin")
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.full_name}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              {!team && <p className="field-hint">Your own leads.</p>}
            </>
          )}
          <label className="field">
            <span>
              {leadIds ? "Add more email addresses (optional)" : "Email addresses"} {!leadIds && <i>*</i>}
            </span>
            <textarea
              className="email-list"
              rows={leadIds ? 3 : 6}
              value={emailText}
              onChange={(e) => setEmailText(e.target.value)}
              placeholder={"asha.rao@acme-retail.com, Asha Rao, Acme Retail\nravi@bluebird.io\nmeera@lumenhealth.com, Meera Iyer"}
              aria-describedby="email-list-hint"
            />
            <small id="email-list-hint" className="field-hint">
              One per line, or paste a list. People don't need to be in the CRM. After a comma, add their name and company to fill
              First name and Company; without them, the company comes from the email's domain.
            </small>
          </label>
          {typed.bad.length > 0 && (
            <p className="form-error" role="status">
              {plural(typed.bad.length, "line")} without an email address will be ignored: {typed.bad.slice(0, 3).join(" • ")}
              {typed.bad.length > 3 ? " …" : ""}
            </p>
          )}
          {preview?.too_many > 0 && (
            <p className="form-error" role="status">
              {n(preview.too_many)} people. A campaign can go to up to {n(preview.max)}: choose fewer.
            </p>
          )}
          {preview && !preview.too_many && (
            <div className={`audience-summary ${preview.loading ? "loading" : ""}`} aria-live="polite">
              <span className="audience-count ok">
                <b>{n(preview.eligible)}</b> will get it
              </span>
              {preview.left_out > 0 && (
                <button type="button" className="audience-count off" onClick={() => setShowLeftOut((v) => !v)} aria-expanded={showLeftOut}>
                  <b>{n(preview.left_out)}</b> left out
                  <small>{leftOutParts.map(([count, label]) => `${n(count)} ${label}`).join(" • ")}</small>
                  <span className="link">{showLeftOut ? "Hide" : "View"}</span>
                </button>
              )}
            </div>
          )}
          {showLeftOut && preview?.left_out_sample?.length > 0 && (
            <div className="table-scroll issue-scroll">
              <table className="sf-table issue-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Why it's left out</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.left_out_sample.map((l, i) => (
                    <tr key={l.id ?? `typed-${i}`}>
                      <td>
                        {l.id ? (
                          <a href={`#/leads/${l.id}`} target="_blank" rel="noreferrer">
                            {l.name}
                          </a>
                        ) : (
                          l.name
                        )}
                      </td>
                      <td>{l.email || <span className="muted">—</span>}</td>
                      <td className="issue-reason">{l.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.left_out > preview.left_out_sample.length && (
                <p className="field-hint pad-x">The first {preview.left_out_sample.length} are shown.</p>
              )}
            </div>
          )}
        </fieldset>

        <fieldset className="campaign-section">
          <legend>Email</legend>
          <label className="field">
            <span>
              Subject <i>*</i>
            </span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} />
          </label>
          <div className="merge-row">
            <span>Insert:</span>
            {FIELDS.map(([key, label]) => (
              <button key={key} type="button" className="merge-chip" onClick={() => insert(key)}>
                {label}
              </button>
            ))}
          </div>
          <label className="field">
            <span>
              Message <i>*</i>
            </span>
            <textarea ref={bodyRef} rows={9} value={body} onChange={(e) => setBody(e.target.value)} maxLength={20000} />
          </label>
          <div className="email-sample" aria-label="Preview">
            <small>Preview{sample ? ` for ${sample.name}` : ""}</small>
            <b>{fill(subject, sample, user)}</b>
            <pre>{fill(body, sample, user)}</pre>
            <pre className="email-footer">
              {"--\n"}You are receiving this email from your company.{"\n"}Unsubscribe: <u>link added automatically</u>{"\n"}Subscribe:{" "}
              <u>link added automatically</u> <span className="muted">(first email to each person only)</span>
            </pre>
          </div>
        </fieldset>

        <fieldset className="campaign-section">
          <legend>When</legend>
          <div className="timing-row">
            <label className="assign-choice">
              <input type="radio" name="timing" checked={timing === "now"} onChange={() => setTiming("now")} /> Send now
            </label>
            <label className="assign-choice">
              <input type="radio" name="timing" checked={timing === "later"} onChange={() => setTiming("later")} /> Schedule
            </label>
            {timing === "later" && (
              <input type="datetime-local" value={sendAt} onChange={(e) => setSendAt(e.target.value)} aria-label="Send at" />
            )}
          </div>
          {limits && preview?.eligible > 0 && (
            <p className="field-hint">
              Sent gradually to stay inside Outlook's limits: {limits.per_minute} a minute and up to {n(limits.per_day)} in 24 hours
              (all campaigns together). This one takes {duration(preview.eta.minutes, preview.eta.days)}.
            </p>
          )}
        </fieldset>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// ---------- Campaigns list and one campaign ----------

function StatusPill({ status }) {
  return <span className={`campaign-status ${STATUS_TONE[status] || ""}`}>{status}</span>;
}

function Progress({ counts }) {
  const total = counts.total - counts.Skipped || 0;
  const done = counts.Sent + counts.Invalid + counts.Failed;
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="campaign-progress" title={`${n(done)} of ${n(total)} done`}>
      <div className="bar">
        <span style={{ width: `${pct}%` }} />
      </div>
      <small>
        {n(counts.Sent)} sent of {n(total)}
      </small>
    </div>
  );
}

const RECIPIENT_GROUPS = [
  ["Queued", "Waiting to send", "info"],
  ["Sent", "Sent", "note"],
  ["Invalid", "Invalid emails", "bad"],
  ["Failed", "Failed", "bad"],
  ["Skipped", "Left out", "warn"],
  ["Cancelled", "Cancelled", "warn"],
];

function CampaignDetail({ id, user, notify }) {
  const [campaign, setCampaign] = useState(null);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let stale = false;
    api
      .campaign(id, { status, offset: page * 100, limit: 100 })
      .then((c) => !stale && (setCampaign(c), setError("")))
      .catch((err) => !stale && setError(err.message));
    return () => {
      stale = true;
    };
  }, [id, status, page, tick]);
  // refresh while it's sending
  useEffect(() => {
    if (!["Sending", "Scheduled"].includes(campaign?.status)) return;
    const timer = setInterval(() => setTick((t) => t + 1), 10000);
    return () => clearInterval(timer);
  }, [campaign?.status]);
  if (error && !campaign)
    return (
      <div className="page">
        <section className="card pad">
          <p className="form-error">{error}</p>
          <a href="#/campaigns">Back to Campaigns</a>
        </section>
      </div>
    );
  if (!campaign) return <div className="page"><section className="card pad">Loading…</section></div>;
  const c = campaign;
  const manage = c.created_by_id === user.id || ["Manager", "Admin"].includes(user.role);
  const act = async (action) => {
    setBusy(action);
    try {
      const res = await api.campaignAction(c.id, action);
      notify(`Campaign ${action === "pause" ? "paused" : action === "resume" ? "resumed" : "cancelled"}.`);
      setCampaign((old) => ({ ...old, ...res }));
      setTick((t) => t + 1);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };
  const rows = c.recipients.items;
  const pages = Math.ceil(c.recipients.total / 100);
  return (
    <div className="page campaign-page">
      <section className="card highlights">
        <div className="highlights-top">
          <ObjectIcon type="campaign" size={36} />
          <div className="highlights-name">
            <small>
              <a href="#/campaigns">Campaigns</a>
            </small>
            <h1>
              {c.name} <StatusPill status={c.status} />
            </h1>
          </div>
          <div className="button-group">
            {manage && ["Scheduled", "Sending"].includes(c.status) && (
              <button className="sf-button" onClick={() => act("pause")} disabled={!!busy}>
                Pause
              </button>
            )}
            {manage && c.status === "Paused" && (
              <button className="sf-button brand" onClick={() => act("resume")} disabled={!!busy}>
                Resume
              </button>
            )}
            {manage && ["Scheduled", "Sending", "Paused"].includes(c.status) && (
              <button className="sf-button danger" onClick={() => act("cancel")} disabled={!!busy}>
                Cancel campaign
              </button>
            )}
          </div>
        </div>
        <dl className="highlights-fields">
          <div>
            <dt>Created by</dt>
            <dd>{c.created_by}</dd>
          </div>
          <div>
            <dt>{c.status === "Scheduled" ? "Sends at" : "Started"}</dt>
            <dd>{when(c.status === "Scheduled" ? c.send_at : c.started_at || c.send_at)}</dd>
          </div>
          <div>
            <dt>{c.finished_at ? "Finished" : "Expected to finish"}</dt>
            <dd>{c.finished_at ? when(c.finished_at) : c.counts.Queued ? when(c.eta.finish_by) : "—"}</dd>
          </div>
          <div>
            <dt>Progress</dt>
            <dd>
              <Progress counts={c.counts} />
            </dd>
          </div>
        </dl>
        {c.status_note && (
          <p className={`campaign-note ${c.status === "Paused" ? "warn" : ""}`}>
            <Icon name="warn" size={14} /> {c.status_note}
          </p>
        )}
      </section>

      <div className="campaign-columns">
        <section className="card">
          <header className="card-header">
            <h2>Recipients</h2>
          </header>
          <div className="issue-cards pad-cards">
            {RECIPIENT_GROUPS.filter(([key]) => c.counts[key]).map(([key, label, tone]) => (
              <button
                key={key}
                type="button"
                className={`issue-card ${tone} ${status === key ? "on" : ""}`}
                aria-pressed={status === key}
                onClick={() => (setStatus(status === key ? "" : key), setPage(0))}
              >
                <b>{n(c.counts[key])}</b>
                <span>{label}</span>
                <small>{status === key ? "Show all" : "View"}</small>
              </button>
            ))}
          </div>
          <div className="table-scroll">
            <table className="sf-table campaign-recipients">
              <thead>
                <tr>
                  <th>Lead</th>
                  <th>Email</th>
                  <th>Status</th>
                  <th>Sent</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td title={r.name}>{r.lead_id ? <a href={`#/leads/${r.lead_id}`}>{r.name}</a> : r.name}</td>
                    <td title={r.email}>{r.email || <span className="muted">—</span>}</td>
                    <td>
                      <span className={`recipient-status s-${r.status.toLowerCase()}`}>{r.status}</span>
                    </td>
                    <td className="nowrap">{when(r.sent_at)}</td>
                    <td className="issue-reason">
                      {r.error || (r.status === "Queued" && r.next_attempt_at ? `Next try ${when(r.next_attempt_at)}` : "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <p className="table-empty">Nobody here.</p>}
          </div>
          {pages > 1 && (
            <div className="pager">
              <button className="sf-button small" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <span>
                Page {page + 1} of {pages}
              </span>
              <button className="sf-button small" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                Next
              </button>
            </div>
          )}
        </section>
        <section className="card campaign-email">
          <header className="card-header">
            <h2>Email</h2>
          </header>
          <div className="pad">
            <b>{c.subject}</b>
            <pre>{c.body}</pre>
            <p className="field-hint">
              Every email ends with an Unsubscribe link; the first email to each person also has a Subscribe link.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

// Email dashboard: what was sent and what wasn't, and which leads can still be emailed (Invalid / Unsubscribed open
// the matching Leads list)
// One dashboard number opened as a list: every email with that status, across the campaigns this user can see
function RecipientsDialog({ status, label, onClose }) {
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let stale = false;
    api
      .campaignRecipients(status, page * 100)
      .then((r) => !stale && (setResult(r), setError("")))
      .catch((err) => !stale && setError(err.message));
    return () => {
      stale = true;
    };
  }, [status, page]);
  const pages = result ? Math.ceil(result.total / 100) : 0;
  return (
    <Dialog
      title={`${label}${result ? ` (${n(result.total)})` : ""}`}
      onClose={onClose}
      footer={
        <button className="sf-button" onClick={onClose}>
          Close
        </button>
      }
    >
      {error && <p className="form-error">{error}</p>}
      {!result && !error && <p>Loading…</p>}
      {result && (
        <>
          <div className="table-scroll">
            <table className="sf-table campaign-recipients">
              <thead>
                <tr>
                  <th>Lead</th>
                  <th>Email</th>
                  <th>Campaign</th>
                  <th>{status === "Sent" ? "Sent" : "Note"}</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((r) => (
                  <tr key={r.id}>
                    <td title={r.name}>{r.lead_id ? <a href={`#/leads/${r.lead_id}`}>{r.name}</a> : r.name}</td>
                    <td title={r.email}>{r.email || <span className="muted">—</span>}</td>
                    <td title={r.campaign}>
                      <a href={`#/campaigns/${r.campaign_id}`}>{r.campaign}</a>
                    </td>
                    <td className={status === "Sent" ? "nowrap" : "issue-reason"}>
                      {status === "Sent"
                        ? when(r.sent_at)
                        : r.error || (r.next_attempt_at ? `Next try ${when(r.next_attempt_at)}` : "Waiting to send")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!result.items.length && <p className="table-empty">Nothing here.</p>}
          </div>
          {pages > 1 && (
            <div className="pager">
              <button className="sf-button small" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <span>
                Page {page + 1} of {pages}
              </span>
              <button className="sf-button small" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                Next
              </button>
            </div>
          )}
        </>
      )}
    </Dialog>
  );
}

// Email dashboard: every number opens its list. Email numbers open the emails (across campaigns); lead numbers open
// the matching Leads list view.
function EmailDashboard({ totals }) {
  const [open, setOpen] = useState(null); // [status, label] of the email list being shown
  const e = totals.emails;
  const l = totals.leads;
  const lists = (name) => `#/leads?list=${encodeURIComponent(name)}`;
  const groups = [
    [
      "Emails",
      `${n(totals.campaigns)} campaign${totals.campaigns === 1 ? "" : "s"}`,
      [
        ["Sent", e.sent, "ok", "Sent"],
        ["Failed", e.failed, "bad", "Failed"],
        ["Not working", e.invalid, "bad", "Invalid", "Bounced: the address doesn't exist"],
        ["Waiting", e.queued, "info", "Queued"],
        ["Left out", e.left_out, "warn", "Skipped", "Unsubscribed, invalid or no email when sending"],
      ],
    ],
    [
      "Lead emails",
      "who can be emailed",
      [
        ["Working", l.working, "ok", lists("Working Emails")],
        ["Invalid", l.invalid, "bad", lists("Invalid Emails")],
        ["Unsubscribed", l.unsubscribed, "warn", lists("Unsubscribed Leads")],
        ["No email", l.no_email, "muted", lists("No Email")],
      ],
    ],
  ];
  return (
    <>
      <section className="email-kpis" aria-label="Email dashboard">
        {groups.map(([title, note, items]) => (
          <div key={title} className="kpi-group">
            <div className="kpi-title">
              {title} <span>{note}</span>
            </div>
            <div className="kpi-row">
              {items.map(([label, value, tone, target, hint]) => {
                const inner = (
                  <>
                    <b>{n(value)}</b>
                    <span>
                      <i className={`kpi-dot ${tone}`} />
                      {label}
                    </span>
                  </>
                );
                return target.startsWith("#") ? (
                  <a key={label} className="kpi link" href={target} title={hint || `Open ${label.toLowerCase()} leads`}>
                    {inner}
                  </a>
                ) : (
                  <button
                    key={label}
                    type="button"
                    className="kpi link"
                    title={hint || `Show ${label.toLowerCase()} emails`}
                    onClick={() => setOpen([target, `${label} emails`])}
                  >
                    {inner}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </section>
      {open && <RecipientsDialog status={open[0]} label={open[1]} onClose={() => setOpen(null)} />}
    </>
  );
}

export default function CampaignsPage({ id, user, data, notify }) {
  const [list, setList] = useState(null);
  const [totals, setTotals] = useState(null); // the email dashboard
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (id) return;
    api
      .campaigns()
      .then(setList)
      .catch((err) => setError(err.message));
    api
      .campaignSummary()
      .then(setTotals)
      .catch(() => {});
  }, [id, tick]);
  useEffect(() => {
    if (id || !list?.items.some((c) => ["Sending", "Scheduled"].includes(c.status))) return;
    const timer = setInterval(() => setTick((t) => t + 1), 15000);
    return () => clearInterval(timer);
  }, [id, list]);
  if (id) return <CampaignDetail key={id} id={id} user={user} notify={notify} />;
  const canSend = can(user, "send_campaigns");
  return (
    <div className="page">
      <section className="card list-card">
        <header className="list-header campaign-list-header">
          <div className="list-title">
            <ObjectIcon type="campaign" size={32} />
            <div>
              <h1>Email Campaigns</h1>
              {list && (
                <small className="muted">
                  {n(list.sent_last_24h)} of {n(list.limits.per_day)} emails sent in the last 24 hours • {list.limits.per_minute} a minute
                </small>
              )}
            </div>
          </div>
          {canSend && (
            <button className="sf-button brand" onClick={() => setCreating(true)}>
              New Campaign
            </button>
          )}
        </header>
        {totals && <EmailDashboard totals={totals} />}
        <p className="campaign-rules">
          <Icon name="mail" size={14} /> Unsubscribed and invalid emails are always left out. Every email ends with an Unsubscribe link;
          the first one to each person also has a Subscribe link.
        </p>
        {error && <p className="form-error pad">{error}</p>}
        <div className="table-scroll">
          {list?.items.length > 0 && (
          <table className="sf-table campaign-table">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Invalid</th>
                <th>Failed</th>
                <th>Left out</th>
                <th>Send at</th>
                <th>Created by</th>
              </tr>
            </thead>
            <tbody>
              {list?.items.map((c) => (
                <tr key={c.id}>
                  <td title={c.name}>
                    <a href={`#/campaigns/${c.id}`}>{c.name}</a>
                  </td>
                  <td>
                    <StatusPill status={c.status} />
                  </td>
                  <td>
                    <Progress counts={c.counts} />
                  </td>
                  <td>{n(c.counts.Invalid)}</td>
                  <td>{n(c.counts.Failed)}</td>
                  <td>{n(c.counts.Skipped)}</td>
                  <td className="nowrap">{when(c.send_at)}</td>
                  <td>{c.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
          {list && !list.items.length && (
            <div className="campaign-empty">
              <span className="campaign-empty-icon">
                <Icon name="mail" size={22} />
              </span>
              <b>No campaigns yet</b>
              <p>
                Email many people at once: start a new campaign and paste their email addresses, or tick leads in{" "}
                <a href="#/leads">Leads</a> and choose Actions → Email Campaign.
              </p>
              {canSend && (
                <button className="sf-button brand" onClick={() => setCreating(true)}>
                  New Campaign
                </button>
              )}
            </div>
          )}
          {!list && !error && <p className="table-empty">Loading…</p>}
        </div>
      </section>
      {creating && (
        <NewCampaign
          user={user}
          users={data.users || []}
          onClose={() => setCreating(false)}
          onCreated={(c) => {
            setCreating(false);
            notify(`Campaign "${c.name}" saved: ${n(c.counts.Queued)} leads.`);
            window.location.hash = `#/campaigns/${c.id}`;
          }}
        />
      )}
    </div>
  );
}
