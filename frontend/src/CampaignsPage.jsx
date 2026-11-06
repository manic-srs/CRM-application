// Email campaigns: one email to many people (leads, or typed-in addresses), sent a few at a time under the Outlook limits (backend/app/campaigns.py).
// - Campaigns page: the totals (Sent, Queued, Bounced, Failed, Unsubscribed, Not sent) and every campaign with its
//   progress; open one to see who got it, who wasn't sent it and why.
// - New Campaign: from this page (typed-in email addresses, also people not in the CRM) or from
//   Leads > select leads > Actions > Email Campaign.
// Unsubscribed and bounced addresses are never emailed again, and every email ends with an unsubscribe link.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { companyFromEmail, LEAD_OPEN_STAGES, LEAD_STAGES, parseRecipients } from "./domain";
import { can } from "./permissions";
import { Icon, ObjectIcon } from "./ui";

const n = (x) => Number(x || 0).toLocaleString();
const when = (value) =>
  value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
const STATUS_TONE = { Scheduled: "info", Sending: "live", Paused: "warn", Completed: "ok", Cancelled: "off" };
// one email's status, in the words email tools use (Invalid = the address doesn't work: a bounce)
const EMAIL_STATUS = { Queued: "Queued", Sent: "Sent", Invalid: "Bounced", Failed: "Failed", Skipped: "Not sent", Cancelled: "Cancelled" };
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

const EMAIL_OK = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/;

// The "To" field: type an address and press Enter (or comma / space), or paste a list; each becomes a chip.
// A pasted "Asha Rao <asha@acme.com>" keeps the name. Backspace in the empty box removes the last chip.
function RecipientInput({ value, onChange, id, placeholder }) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef(null);
  const add = (text) => {
    const seen = new Set(value.map((r) => r.email.toLowerCase()));
    const next = [...value];
    for (const r of parseRecipients(text)) {
      if (seen.has(r.email.toLowerCase())) continue; // already in the list
      seen.add(r.email.toLowerCase());
      next.push({ ...r, valid: EMAIL_OK.test(r.email) });
    }
    if (next.length !== value.length) onChange(next);
    setDraft("");
  };
  const remove = (i) => onChange(value.filter((_, j) => j !== i));
  return (
    <div className="recipient-box" onClick={() => inputRef.current?.focus()}>
      {value.map((r, i) => (
        <span key={`${r.email}-${i}`} className={`recipient-chip ${r.valid ? "" : "bad"}`} title={r.valid ? r.name || r.email : "Not an email address"}>
          {r.name ? `${r.name} <${r.email}>` : r.email}
          <button type="button" aria-label={`Remove ${r.email}`} onClick={(e) => (e.stopPropagation(), remove(i))}>
            <Icon name="close" size={12} />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        id={id}
        type="text"
        inputMode="email"
        autoComplete="off"
        value={draft}
        placeholder={value.length ? "" : placeholder}
        onChange={(e) => {
          const text = e.target.value;
          // a comma, semicolon or space after an address makes it a chip (not inside "Name <address")
          if (/[,;\s]$/.test(text) && text.includes("@") && !/<[^>]*$/.test(text)) add(text);
          else setDraft(text);
        }}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === "Tab") && draft.trim()) {
            e.preventDefault();
            add(draft);
          } else if (e.key === "Enter") {
            e.preventDefault();
          } else if (e.key === "Backspace" && !draft && value.length) {
            remove(value.length - 1);
          }
        }}
        onPaste={(e) => {
          e.preventDefault();
          add(draft + " " + e.clipboardData.getData("text"));
        }}
        onBlur={() => draft.trim() && add(draft)}
      />
    </div>
  );
}

// Choosing recipients by lead stage (and owner) is switched OFF for now: New Campaign takes typed-in email addresses
// instead, so people who aren't in the CRM can be emailed too (requirement, Nov 2026). The stage picker below is kept
// and still works in the API (Audience.stages): set STAGE_PICKER to true to bring the checkboxes back.
const STAGE_PICKER = false;
const plural = (count, word) => `${n(count)} ${word}${count === 1 ? "" : "s"}`;

// Draft with AI (the same AI as lead emails): describe the email, or refine the current one. The draft keeps the
// fields ({first_name}, {company}, {sender_name}) that are filled in for each recipient. Undo puts the old text back.
const CAMPAIGN_REFINE = [
  ["formalize", "Professional"],
  ["friendly", "Conversational"],
  ["shorten", "Concise"],
];

function CampaignAiDraft({ subject, body, onApply }) {
  const [open, setOpen] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [undo, setUndo] = useState(null);
  const run = async (action) => {
    if (busy) return;
    if (action === "custom" && !instructions.trim()) return setError("Describe the email you want first.");
    setBusy(action);
    setError("");
    try {
      const draft = await api.draftCampaign({ action, instructions: instructions.trim(), current_subject: subject, current_body: body });
      setUndo({ subject, body });
      onApply(draft);
    } catch (err) {
      setError(`${err.message} Your email is unchanged.`);
    } finally {
      setBusy("");
    }
  };
  if (!open)
    return (
      <button type="button" className="sf-button small ai-draft-toggle" onClick={() => setOpen(true)}>
        <Icon name="edit" size={14} /> Draft with AI
      </button>
    );
  return (
    <div className="ai-draft-box" aria-busy={!!busy}>
      <label className="field">
        <span>Describe the email</span>
        <textarea
          rows={2}
          value={instructions}
          maxLength={2000}
          onChange={(e) => setInstructions(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.ctrlKey || e.metaKey) && run("custom")}
          placeholder="e.g. Invite them to a 20-minute demo of our reporting dashboards next week"
          disabled={!!busy}
        />
      </label>
      <div className="ai-draft-actions">
        <button type="button" className="sf-button small brand" onClick={() => run("custom")} disabled={!!busy}>
          {busy === "custom" ? "Writing…" : "Write email"}
        </button>
        <span className="muted">Refine:</span>
        {CAMPAIGN_REFINE.map(([action, label]) => (
          <button key={action} type="button" className="sf-button small" onClick={() => run(action)} disabled={!!busy}>
            {busy === action ? "Working…" : label}
          </button>
        ))}
        {undo && (
          <button type="button" className="link" onClick={() => (onApply(undo), setUndo(null))} disabled={!!busy}>
            Undo
          </button>
        )}
        <button type="button" className="link ai-draft-close" onClick={() => setOpen(false)}>
          Close
        </button>
      </div>
      {error && (
        <p className="field-error-text" role="alert">
          {error}
        </p>
      )}
      <small className="field-hint">Review the draft before sending. Fields like {"{first_name}"} are filled in for each recipient.</small>
    </div>
  );
}

export function NewCampaign({ user, users = [], leadIds = null, onClose, onCreated }) {
  const team = user.role === "Admin" || can(user, "view_team_records");
  const [stages, setStages] = useState(LEAD_OPEN_STAGES);
  const [recipients, setRecipients] = useState([]); // the "To" chips: { email, name?, company?, valid }
  const valid = useMemo(() => recipients.filter((r) => r.valid), [recipients]);
  const wrong = recipients.length - valid.length;
  const [owner, setOwner] = useState(team ? "" : String(user.id));
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("Quick question for {company}");
  const [body, setBody] = useState(SAMPLE_BODY);
  const [preview, setPreview] = useState(null);
  const [settings, setSettings] = useState(null);
  const [showLeftOut, setShowLeftOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bodyRef = useRef(null);
  const subjectRef = useRef(null);
  // where the Insert buttons put a field: the box (subject or message) and cursor the user was last in
  const caret = useRef({ field: "body", at: null });
  const remember = (field) => (e) => (caret.current = { field, at: e.target.selectionStart });
  const audience = useMemo(() => {
    const emails = valid.map(({ email, name, company }) => ({ email, name: name || null, company: company || null }));
    if (leadIds) return { lead_ids: leadIds }; // from Leads: only the ticked leads
    if (STAGE_PICKER) return { stages, owner_id: owner ? Number(owner) : null, emails };
    return { emails };
  }, [leadIds, stages, owner, valid]);
  const nobody = !leadIds && (STAGE_PICKER ? !stages.length && !valid.length : !valid.length);

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
    const token = `{${field}}`;
    const inSubject = caret.current.field === "subject";
    const text = inSubject ? subject : body;
    const at = Math.min(caret.current.at ?? text.length, text.length); // never clicked in: at the end
    const next = text.slice(0, at) + token + text.slice(at);
    (inSubject ? setSubject : setBody)(next);
    caret.current = { field: caret.current.field, at: at + token.length };
    const box = inSubject ? subjectRef.current : bodyRef.current;
    requestAnimationFrame(() => {
      box?.focus();
      box?.setSelectionRange(at + token.length, at + token.length);
    });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (name.trim().length < 2) return setError("Give the campaign a name.");
    if (subject.trim().length < 2) return setError("Write a subject.");
    if (body.trim().length < 10) return setError("Write the email.");
    if (nobody) return setError(wrong ? "Fix or remove the addresses marked in red." : "Add at least one recipient.");
    if (!preview?.eligible) return setError("None of these recipients can be emailed (see Excluded).");
    setBusy(true);
    setError("");
    try {
      const created = await api.createCampaign({
        ...audience,
        name: name.trim(),
        subject: subject.trim(),
        body: body.trim(),
        send_at: null, // sent straight away, paced automatically within the Outlook limits
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
    [reasons.invalid, "bounced before"],
    [reasons.no_email, "no email"],
    [reasons.other, "duplicate"],
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
            {busy ? "Saving…" : `Send to ${plural(preview?.eligible || 0, "recipient")}`}
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
          {!leadIds && (
            // the "To" field is only on Email Campaigns > New Campaign; from Leads the recipients are the ticked leads
            <div className="field">
              <label htmlFor="campaign-to">
                <span>
                  To <i>*</i>
                </span>
              </label>
              <RecipientInput
                id="campaign-to"
                value={recipients}
                onChange={setRecipients}
                placeholder="Type an email and press Enter, or paste a list"
              />
              <small className="field-hint">
                Recipients don't need to be in the CRM. First name and company are filled in from the address
                (asha.rao@acme-retail.com → Asha, Acme Retail).
              </small>
              {wrong > 0 && (
                <small className="field-error-text" role="status">
                  {`${n(wrong)} ${wrong === 1 ? "address" : "addresses"}`} in red {wrong === 1 ? "isn't" : "aren't"} valid and won't be
                  sent to.
                </small>
              )}
            </div>
          )}
          {preview?.too_many > 0 && (
            <p className="form-error" role="status">
              {n(preview.too_many)} recipients. A campaign can go to up to {n(preview.max)}: choose fewer.
            </p>
          )}
          {preview && !preview.too_many && (
            <div className={`audience-summary ${preview.loading ? "loading" : ""}`} aria-live="polite">
              <span className="audience-count ok">
                <b>{n(preview.eligible)}</b> {preview.eligible === 1 ? "recipient" : "recipients"}
              </span>
              {preview.left_out > 0 && (
                <button type="button" className="audience-count off" onClick={() => setShowLeftOut((v) => !v)} aria-expanded={showLeftOut}>
                  <b>{n(preview.left_out)}</b> excluded
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
                    <th>Reason</th>
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
          <CampaignAiDraft subject={subject} body={body} onApply={(d) => (setSubject(d.subject), setBody(d.body))} />
          <label className="field">
            <span>
              Subject <i>*</i>
            </span>
            <input
              ref={subjectRef}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              onSelect={remember("subject")}
              maxLength={200}
            />
          </label>
          <div className="merge-row">
            <span>Insert field:</span>
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
            <textarea
              ref={bodyRef}
              rows={9}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              onSelect={remember("body")}
              maxLength={20000}
            />
          </label>
          <div className="email-sample" aria-label="Preview">
            <small>Preview{sample ? ` for ${sample.name || sample.email}` : ""}</small>
            <b>{fill(subject, sample, user)}</b>
            <pre>{fill(body, sample, user)}</pre>
            <pre className="email-footer">
              {"--\n"}You are receiving this email from your company.{"\n"}Unsubscribe: <u>link added automatically</u>{"\n"}Subscribe:{" "}
              <u>link added automatically</u> <span className="muted">(until the recipient subscribes)</span>
            </pre>
          </div>
        </fieldset>

        <fieldset className="campaign-section">
          <legend>Sending</legend>
          <p className="field-hint sending-note">
            <Icon name="mail" size={14} /> Click Send and SalesTrack does the rest: the emails are queued and sent automatically
            {limits ? ` within Outlook's limits (${limits.per_minute} per minute, ${n(limits.per_day)} per day across all campaigns)` : ""}
            , whether it's 10 or 1,000 emails.
            {preview?.eligible > 0 && preview.eta && (
              <>
                {" "}
                This campaign takes {duration(preview.eta.minutes, preview.eta.days)}.
              </>
            )}
          </p>
          {settings && settings.links_reachable === false && (
            <p className="field-hint field-error-text" role="status">
              The Unsubscribe links point to {settings.unsubscribe_base.replace(/\/api\/public\/unsubscribe$/, "")}, which recipients
              can't open. Ask your administrator to set PUBLIC_URL to the app's public address.
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
  ["Queued", "Queued", "info"],
  ["Sent", "Sent", "note"],
  ["Invalid", "Bounced", "bad"],
  ["Failed", "Failed", "bad"],
  ["Skipped", "Not sent", "warn"],
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
                  <th>Recipient</th>
                  <th>Email</th>
                  <th>Status</th>
                  <th>Sent</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td title={r.name}>{r.lead_id ? <a href={`#/leads/${r.lead_id}`}>{r.name}</a> : r.name}</td>
                    <td title={r.email}>{r.email || <span className="muted">—</span>}</td>
                    <td>
                      <span className={`recipient-status s-${r.status.toLowerCase()}`}>{EMAIL_STATUS[r.status] || r.status}</span>
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
              Every email has an Unsubscribe link, and a Subscribe link until the recipient subscribes.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

// One dashboard number opened as a tab on the page: every email with that status, across the campaigns this user can
// see, with search and pages (works for any number of emails)
function RecipientsList({ status, label }) {
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => setPage(0), [search, status]);
  useEffect(() => {
    let stale = false;
    api
      .campaignRecipients(status, page * 50, 50, search)
      .then((r) => !stale && (setResult(r), setError("")))
      .catch((err) => !stale && setError(err.message));
    return () => {
      stale = true;
    };
  }, [status, page, search]);
  const pages = result ? Math.max(1, Math.ceil(result.total / 50)) : 0;
  const dated = status === "Sent" || status === "Unsubscribed"; // show when the (last) email went
  return (
    <div className="campaign-tab-panel" role="tabpanel" aria-label={label}>
      <div className="campaign-tab-toolbar">
        <b>
          {label}
          {result ? ` (${n(result.total)})` : ""}
        </b>
        <label className="list-search">
          <Icon name="search" size={14} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name, email or campaign" aria-label={`Search ${label}`} />
        </label>
      </div>
      {error && <p className="form-error pad">{error}</p>}
      {!result && !error && <p className="table-empty">Loading…</p>}
      {result && (
        <>
          <div className="table-scroll">
            <table className="sf-table campaign-recipients">
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Email</th>
                  <th>Campaign</th>
                  <th>{dated ? "Sent" : "Reason"}</th>
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
                    <td className={dated ? "nowrap" : "issue-reason"}>
                      {dated
                        ? when(r.sent_at)
                        : r.error || (r.next_attempt_at ? `Next try ${when(r.next_attempt_at)}` : "Waiting to send")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!result.items.length && <p className="table-empty">{search ? "No emails match." : "Nothing here."}</p>}
          </div>
          {pages > 1 && (
            <div className="pager">
              <button className="sf-button small" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <span>
                Page {page + 1} of {n(pages)}
              </span>
              <button className="sf-button small" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Email dashboard: the standard campaign numbers, across the campaigns this user can see. Each is a tab on the page
// (Campaigns is the first tab) that lists those emails with search and pages.
//   Sent          delivered to the mail server
//   Queued        waiting to be sent
//   Bounced       the address doesn't work (no mail server, or the server rejected it): never emailed again
//   Failed        not delivered after 3 tries (temporary problems)
//   Unsubscribed  people who got a campaign and then unsubscribed
//   Not sent      excluded when it was their turn: unsubscribed, bounced before, or no email
const pct = (part, whole) => (whole ? `${((part / whole) * 100).toFixed(part && part / whole < 0.1 ? 1 : 0)}%` : "0%");

function dashboardTiles(totals) {
  const e = totals.emails;
  const attempted = e.sent + e.invalid; // emails that reached a mail server, or bounced
  return [
    ["Sent", e.sent, "Sent", "ok", `to ${plural(e.people || 0, "recipient")}`],
    ["Queued", e.queued, "Queued", "info", e.queued ? "waiting to send" : "nothing waiting"],
    ["Bounced", e.invalid, "Invalid", "bad", `${pct(e.invalid, attempted)} bounce rate`],
    ["Failed", e.failed, "Failed", "bad", "after 3 tries"],
    ["Unsubscribed", e.unsubscribed || 0, "Unsubscribed", "warn", `${pct(e.unsubscribed || 0, e.people)} of recipients`],
    ["Not sent", e.left_out, "Skipped", "muted", "excluded at send time"],
  ];
}

function EmailDashboard({ totals, tab, setTab }) {
  return (
    <section className="campaign-metrics" role="tablist" aria-label={`Email campaign totals, ${plural(totals.campaigns, "campaign")}`}>
      {dashboardTiles(totals).map(([label, value, status, tone, note]) => (
        <button
          key={label}
          type="button"
          role="tab"
          aria-selected={tab === status}
          className={`metric ${tone} ${tab === status ? "on" : ""}`}
          onClick={() => setTab(tab === status ? "campaigns" : status)}
          title={tab === status ? "Back to the campaigns" : `Show ${label.toLowerCase()} emails`}
        >
          <span className="metric-label">{label}</span>
          <b>{n(value)}</b>
          <small>{note}</small>
        </button>
      ))}
    </section>
  );
}

// After New Campaign: how many emails were queued and when sending finishes (the backend paces them)
export function queuedMessage(c) {
  const count = c.counts?.Queued ?? 0;
  const finish = c.eta?.finish_by ? new Date(c.eta.finish_by) : null;
  const sameDay = finish && finish.toDateString() === new Date().toDateString();
  const by = finish
    ? ` - sending will finish by ${finish.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}${
        sameDay ? "" : ` on ${finish.toLocaleDateString([], { day: "numeric", month: "short" })}`
      }`
    : "";
  return `Campaign "${c.name}": ${plural(count, "email")} queued${by}.`;
}

export default function CampaignsPage({ id, user, data, notify }) {
  const [list, setList] = useState(null);
  const [totals, setTotals] = useState(null); // the email dashboard
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [tick, setTick] = useState(0);
  const [tab, setTab] = useState("campaigns"); // "campaigns" or an email status (Sent, Queued, Invalid...)
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
                  Sending limit: {n(list.sent_last_24h)} of {n(list.limits.per_day)} emails used in the last 24 hours ·{" "}
                  {list.limits.per_minute} per minute
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
        {totals && <EmailDashboard totals={totals} tab={tab} setTab={setTab} />}
        <nav className="campaign-tabs" role="tablist" aria-label="Email Campaigns">
          <button role="tab" aria-selected={tab === "campaigns"} className={tab === "campaigns" ? "on" : ""} onClick={() => setTab("campaigns")}>
            Campaigns{list ? ` (${n(list.items.length)})` : ""}
          </button>
          {totals &&
            dashboardTiles(totals).map(([label, value, status]) => (
              <button key={status} role="tab" aria-selected={tab === status} className={tab === status ? "on" : ""} onClick={() => setTab(status)}>
                {label} ({n(value)})
              </button>
            ))}
        </nav>
        {tab !== "campaigns" && totals && (
          <RecipientsList
            key={tab}
            status={tab}
            label={(dashboardTiles(totals).find((t) => t[2] === tab) || [tab])[0] + (tab === "Unsubscribed" ? "" : " emails")}
          />
        )}
        {error && <p className="form-error pad">{error}</p>}
        <div className="table-scroll" hidden={tab !== "campaigns"}>
          {list?.items.length > 0 && (
          <table className="sf-table campaign-table">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Bounced</th>
                <th>Failed</th>
                <th>Not sent</th>
                <th>Send time</th>
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
        <p className="campaign-rules">
          <Icon name="mail" size={14} /> Unsubscribed and bounced addresses are never emailed again. Every email has an Unsubscribe link,
          and a Subscribe link until the recipient subscribes.
        </p>
      </section>
      {creating && (
        <NewCampaign
          user={user}
          users={data.users || []}
          onClose={() => setCreating(false)}
          onCreated={(c) => {
            setCreating(false);
            notify(queuedMessage(c));
            window.location.hash = `#/campaigns/${c.id}`;
          }}
        />
      )}
    </div>
  );
}
