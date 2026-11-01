// Leads and Opportunities lists: Upload (many records at once from Excel / CSV),
// Download (to Excel / CSV, a reason is required) and History (who uploaded / downloaded what, when and why).
// Uploads and downloads are recorded in the Activity Log.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { LEAD_STAGES, OPPORTUNITY_STAGES } from "./domain";
import { can } from "./permissions";
import { Icon } from "./ui";

const SAMPLE_LEADS = [
  "First Name,Last Name,Title,Company,Email,Phone,Person Linkedin Url,Website,Company Linkedin Url,Annual Revenue,# Employees,City,State,Country,Lead Source,Lead Owner",
  "Priya,Menon,Head of Operations,Brightline Logistics,priya.menon@brightline.example,+1 512 555 0100,https://www.linkedin.com/in/priya-menon,https://brightline.example,https://www.linkedin.com/company/brightline,12500000,250,Austin,Texas,United States,Website,",
].join("\n");
const SAMPLE_OPPS = [
  "Opportunity Name,Company,Amount,Close Date,Stage,Contact Name,Contact Email,Lost Reason",
  "Brightline CRM rollout,Brightline Logistics,45000,2026-12-15,Proposal,Priya Menon,priya.menon@brightline.example,",
  "Kestrel renewal,Kestrel Foods,12000,2026-11-30,Won,Rahul Varma,rahul@kestrel.example,",
].join("\n");
const OBJECTS = {
  leads: {
    label: "Leads",
    one: "lead",
    sample: SAMPLE_LEADS,
    intro: "Import leads from an Excel (.xlsx) or CSV file.",
    rules: ["Required: Last Name, Company", "Email must match the company website", "Emails already in the CRM are skipped", "Leads start at Unqualified"],
    columns: [
      ["Name", (l) => [l.first_name, l.last_name].filter(Boolean).join(" ")],
      ["Title", (l) => l.title],
      ["Company", (l) => l.company],
      ["Email", (l) => l.email],
      ["Location", (l) => l.location],
      ["LinkedIn", (l) => (l.linkedin_url ? "Yes" : "")],
      ["Owner", (l) => l.owner_name || ""],
    ],
    stages: [["all", "All leads I can see"], ["open", "Open leads"], ...LEAD_STAGES.map((s) => [s.toLowerCase(), s])],
  },
  opportunities: {
    label: "Opportunities",
    one: "opportunity",
    sample: SAMPLE_OPPS,
    intro: "Import opportunities from an Excel (.xlsx) or CSV file.",
    rules: ["Required: Opportunity Name or Company", "Stage: Opportunity, Discovery, Proposal, Won or Lost", "Won requires an Amount", "Existing deals are skipped"],
    columns: [
      ["Opportunity", (o) => o.name],
      ["Company", (o) => o.company],
      ["Stage", (o) => o.stage],
      ["Amount", (o) => (o.amount != null ? `$${Number(o.amount).toLocaleString()}` : "")],
      ["Close Date", (o) => o.close_date],
      ["Contact", (o) => o.contact],
    ],
    stages: [["all", "All opportunities I can see"], ["open", "Open opportunities"], ...OPPORTUNITY_STAGES.map((s) => [s.toLowerCase(), s])],
  },
};

function saveText(name, text) {
  const url = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Dialog({ title, onClose, busy, children, footer, wide }) {
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className={`modal ${wide ? "" : "small-modal"}`} role="dialog" aria-modal="true" aria-labelledby="files-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="files-title">{title}</h2>
        </header>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">{footer}</div>
      </section>
    </div>
  );
}

const n = (x) => Number(x || 0).toLocaleString();

export function UploadLeads({ object = "leads", user, data, onClose, onDone, notify }) {
  const info = OBJECTS[object];
  const admin = user.role === "Admin";
  const canAssign = admin || can(user, "reassign_owner");
  const owners = (data.users || []).filter((u) => u.is_active !== false && u.role !== "Admin");
  const [file, setFile] = useState(null);
  const [owner, setOwner] = useState(admin ? "" : String(user.id));
  // Leads only: who owns them, as in Salesforce's Data Import Wizard
  const [assign, setAssign] = useState("one");
  const [team, setTeam] = useState([]); // "even": the people to share between
  const leads = object === "leads";
  const changed = (fn) => (...args) => (fn(...args), setCheck(null));
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const input = useRef(null);

  const pick = (f) => {
    setFile(f || null);
    setCheck(null);
    setError("");
  };
  const send = async (dryRun) => {
    if (!file) return setError("Choose an Excel (.xlsx) or CSV file.");
    if (assign === "even" && team.length < 1) return setError("Choose the people to share the leads between.");
    if (assign !== "even" && admin && !owner)
      return setError(assign === "column"
        ? "Choose who gets the rows without a Lead Owner."
        : `Choose who will own the uploaded ${info.label.toLowerCase()}.`);
    setBusy(dryRun ? "check" : "upload");
    setError("");
    try {
      const result = await api.importData(object, file, {
        ownerId: assign === "even" ? "" : owner,
        dryRun,
        ...(leads ? { assign, ownerIds: assign === "even" ? team : [] } : {}),
      });
      if (dryRun) setCheck(result);
      else {
        const word = result.created === 1 ? info.one : info.label.toLowerCase();
        notify(`${n(result.created)} ${word} uploaded and assigned to ${result.owner}.`);
        onDone();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };
  const errorFile = () =>
    saveText(
      `${(check.file || "upload").replace(/\.[^.]+$/, "")}-skipped-rows.csv`,
      ["Row,Reason", ...check.errors.map((e) => `${e.row},"${e.reason.replace(/"/g, '""')}"`)].join("\n"),
    );

  return (
    <Dialog
      title={`Upload ${info.label}`}
      wide={!!check}
      busy={!!busy}
      onClose={onClose}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={!!busy}>
            Cancel
          </button>
          {check?.ready > 0 ? (
            <button className="sf-button brand" onClick={() => send(false)} disabled={!!busy} aria-busy={busy === "upload"}>
              {busy === "upload" ? "Uploading…" : `Upload ${n(check.ready)} ${check.ready === 1 ? info.one : info.label.toLowerCase()}`}
            </button>
          ) : (
            <button className="sf-button brand" onClick={() => send(true)} disabled={!!busy || !file} aria-busy={busy === "check"}>
              {busy === "check" ? "Checking…" : "Check file"}
            </button>
          )}
        </>
      }
    >
      <p className="upload-intro">{info.intro}</p>
      <ul className="upload-rules">
        {info.rules.map((rule) => (
          <li key={rule}>{rule}</li>
        ))}
      </ul>
      <div
        className={`dropzone upload-zone ${file ? "has-file" : ""}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          pick(e.dataTransfer.files[0]);
        }}
      >
        <button type="button" className="sf-button small" onClick={() => input.current.click()} disabled={!!busy}>
          {file ? "Change file" : "Choose file"}
        </button>
        <span className={file ? "" : "muted"}>{file ? `${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)` : "or drag it here · .xlsx or .csv, up to 100,000 rows (50 MB)"}</span>
        <input ref={input} type="file" hidden accept=".xlsx,.csv" onChange={(e) => (pick(e.target.files[0]), (e.target.value = ""))} />
      </div>
      <button type="button" className="link sample-link" onClick={() => saveText(`SalesTrack-${object}-upload-sample.csv`, info.sample)}>
        Download sample file
      </button>
      {canAssign && !leads && (
        <label className="field">
          <span>
            Owner <i>*</i>
          </span>
          <select value={owner} onChange={(e) => (setOwner(e.target.value), setCheck(null))} disabled={!!busy}>
            {admin && <option value="">Choose a Manager or Salesperson</option>}
            {owners.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name} ({u.role})
              </option>
            ))}
          </select>
        </label>
      )}
      {canAssign && leads && (
        <fieldset className="assign-box" disabled={!!busy}>
          <legend>Assign leads</legend>
          {[
            ["one", "Assign all to one person"],
            ["column", "Use the Lead Owner column in the file", "The owner's email or full name. Rows without one go to:"],
            ["even", "Share evenly between people (round-robin)"],
          ].map(([value, label, hint]) => (
            <div key={value} className={`assign-option ${assign === value ? "on" : ""}`}>
              <label className="assign-choice">
                <input type="radio" name="assign" value={value} checked={assign === value} onChange={changed(() => setAssign(value))} />
                <span>{label}</span>
              </label>
              {assign === value && value !== "even" && (
                <div className="assign-detail">
                  {hint && <small>{hint}</small>}
                  <select value={owner} onChange={changed((e) => setOwner(e.target.value))} aria-label={value === "one" ? "Owner" : "Default owner"}>
                    {admin && <option value="">Choose a Manager or Salesperson</option>}
                    {owners.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name} ({u.role})
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {assign === value && value === "even" && (
                <div className="assign-detail assign-people">
                  {owners.map((u) => (
                    <label key={u.id} className={`person-chip ${team.includes(String(u.id)) ? "on" : ""}`}>
                      <input
                        type="checkbox"
                        checked={team.includes(String(u.id))}
                        onChange={changed((e) =>
                          setTeam((t) => (e.target.checked ? [...t, String(u.id)] : t.filter((id) => id !== String(u.id)))),
                        )}
                      />
                      {u.full_name}
                    </label>
                  ))}
                  <small>{team.length ? `${team.length} selected · leads are shared in turn` : "Pick two or more people"}</small>
                </div>
              )}
            </div>
          ))}
        </fieldset>
      )}
      {!canAssign && leads && <p className="field-hint">The uploaded leads will be assigned to you.</p>}
      {check && (
        <div className="upload-check">
          <div className="upload-counts">
            <span>
              <b>{n(check.rows)}</b> rows
            </span>
            <span className="ok">
              <b>{n(check.ready)}</b> ready to upload
            </span>
            <span className="warn">
              <b>{n(check.duplicates)}</b> duplicates
            </span>
            <span className="bad">
              <b>{n(check.invalid)}</b> invalid
            </span>
            {check.with_blanks > 0 && (
              <span className="warn">
                <b>{n(check.with_blanks)}</b> with blank fields
              </span>
            )}
          </div>
          {check.owners?.length > 0 && (
            <div className="owner-split" aria-label="Owners">
              <span>Assigned to</span>
              {check.owners.map((o) => (
                <span key={o.id} className="owner-pill">
                  {o.name} <b>{n(o.count)}</b>
                </span>
              ))}
            </div>
          )}
          <p className="field-hint">
            {!check.owners?.length && <>Owner: <b>{check.owner}</b> • </>}Matched columns: {check.columns_used.join(", ")}
            {check.columns_ignored.length > 0 && <> • Ignored: {check.columns_ignored.join(", ")}</>}
          </p>
          {check.preview.length > 0 && (
            <div className="table-scroll">
              <table className="sf-table upload-preview">
                <thead>
                  <tr>
                    {info.columns.map(([label]) => (
                      <th key={label}>{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {check.preview.map((row, i) => (
                    <tr key={i}>
                      {info.columns.map(([label, get]) => (
                        <td key={label}>{get(row)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {check.errors.length > 0 && (
            <details className="upload-errors">
              <summary>
                {n(check.duplicates + check.invalid)} row{check.duplicates + check.invalid === 1 ? "" : "s"} skipped
              </summary>
              <ul>
                {check.errors.slice(0, 20).map((e) => (
                  <li key={e.row}>
                    Row {e.row}: {e.reason}
                  </li>
                ))}
              </ul>
              <button type="button" className="link" onClick={errorFile}>
                Download skipped rows
              </button>
            </details>
          )}
          {check.warnings?.length > 0 && (
            <details className="upload-errors">
              <summary>
                {n(check.with_blanks)} row{check.with_blanks === 1 ? "" : "s"} with invalid values (imported with those fields blank)
              </summary>
              <ul>
                {check.warnings.slice(0, 20).map((w) => (
                  <li key={w.row}>
                    Row {w.row}: {w.reason.replace("Uploaded; left blank: ", "")}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {check.ready === 0 && <p className="form-error">No new records to import.</p>}
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}

export function DownloadLeads({ object = "leads", onClose, notify }) {
  const info = OBJECTS[object];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    if ((form.reason || "").trim().length < 5) return setError("Enter a reason (at least 5 characters).");
    setBusy(true);
    setError("");
    try {
      const name = await api.exportData(object, {
        reason: form.reason.trim(),
        format: form.format,
        stage: form.stage,
        mine: form.mine === "on" ? "true" : "false",
      });
      notify(`${name} was downloaded.`);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`Download ${info.label}`}
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="sf-button brand" type="submit" form="download-form" disabled={busy} aria-busy={busy}>
            {busy ? "Preparing…" : "Download"}
          </button>
        </>
      }
    >
      <form id="download-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>{info.label}</span>
            <select name="stage" defaultValue="all">
              {info.stages.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Format</span>
            <select name="format" defaultValue="xlsx">
              <option value="xlsx">Excel (.xlsx)</option>
              <option value="csv">CSV (.csv)</option>
            </select>
          </label>
        </div>
        <label className="check-field">
          <input type="checkbox" name="mine" /> Only my {info.label.toLowerCase()}
        </label>
        <label className="field">
          <span>
            Reason <i>*</i>
          </span>
          <textarea name="reason" rows={3} maxLength={300} required placeholder="e.g. Monthly pipeline review" />
        </label>
        <p className="field-hint">Every download is logged with your name, time, filter and reason.</p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// Who uploaded or downloaded leads / opportunities, when, what and why
export function TransferHistory({ object = "leads", onClose }) {
  const info = OBJECTS[object];
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.transferHistory(object).then(setRows).catch((err) => setError(err.message));
  }, [object]);
  return (
    <Dialog
      title={`Upload & Download History: ${info.label}`}
      wide
      onClose={onClose}
      footer={
        <button className="sf-button" onClick={onClose}>
          Close
        </button>
      }
    >
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="table-scroll">
        <table className="sf-table history-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Done By</th>
              <th>Action</th>
              <th>What</th>
              <th>Reason / Details</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{new Date(r.at).toLocaleString()}</td>
                <td>{r.by}</td>
                <td>
                  <span className={`pill ${r.action === "Download" ? "pill-upcoming" : "pill-ok"}`}>{r.action}</span>
                </td>
                <td>{r.what}</td>
                <td className="muted">{r.details}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows && !rows.length && <p className="table-empty">No uploads or downloads yet.</p>}
        {rows === null && !error && <p className="table-empty">Loading…</p>}
      </div>
    </Dialog>
  );
}

// Manage Access > People (Admin): add many users at once. Same rules as Add User; each gets the welcome email.
const SAMPLE_USERS = "Full Name,Email,Role\nPriya Menon,priya.menon@srsconsultinginc.com,Salesperson\nArjun Rao,arjun.rao@srsconsultinginc.com,Manager\n";
export function UploadUsers({ onClose, onDone, notify }) {
  const [file, setFile] = useState(null);
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const input = useRef(null);
  const pick = (f) => (setFile(f || null), setCheck(null), setError(""));
  const send = async (dryRun) => {
    if (!file) return setError("Choose an Excel (.xlsx) or CSV file.");
    setBusy(dryRun ? "check" : "upload");
    setError("");
    try {
      const result = await api.importUsers(file, dryRun);
      if (dryRun) setCheck(result);
      else {
        notify(`${n(result.created)} user${result.created === 1 ? "" : "s"} added. Each one was emailed their login details.`);
        onDone();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };
  return (
    <Dialog
      title="Upload Users"
      wide={!!check}
      busy={!!busy}
      onClose={onClose}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={!!busy}>
            Cancel
          </button>
          {check?.ready > 0 ? (
            <button className="sf-button brand" onClick={() => send(false)} disabled={!!busy} aria-busy={busy === "upload"}>
              {busy === "upload" ? "Adding…" : `Add ${n(check.ready)} user${check.ready === 1 ? "" : "s"}`}
            </button>
          ) : (
            <button className="sf-button brand" onClick={() => send(true)} disabled={!!busy || !file} aria-busy={busy === "check"}>
              {busy === "check" ? "Checking…" : "Check file"}
            </button>
          )}
        </>
      }
    >
      <p className="upload-intro">Add many users from an Excel (.xlsx) or CSV file.</p>
      <ul className="upload-rules">
        {["Required: Full Name, Email", "Role: Salesperson (default), Manager or Admin", "Company emails only", "Each user gets a welcome email"].map((rule) => (
          <li key={rule}>{rule}</li>
        ))}
      </ul>
      <div
        className={`dropzone upload-zone ${file ? "has-file" : ""}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => (e.preventDefault(), pick(e.dataTransfer.files[0]))}
      >
        <button type="button" className="sf-button small" onClick={() => input.current.click()} disabled={!!busy}>
          {file ? "Change file" : "Choose file"}
        </button>
        <span className={file ? "" : "muted"}>{file ? file.name : "or drag it here · .xlsx or .csv, up to 500 users"}</span>
        <input ref={input} type="file" hidden accept=".xlsx,.csv" onChange={(e) => (pick(e.target.files[0]), (e.target.value = ""))} />
      </div>
      <button type="button" className="link sample-link" onClick={() => saveText("SalesTrack-users-upload-sample.csv", SAMPLE_USERS)}>
        Download sample file
      </button>
      {check && (
        <div className="upload-check">
          <div className="upload-counts">
            <span>
              <b>{n(check.rows)}</b> rows
            </span>
            <span className="ok">
              <b>{n(check.ready)}</b> ready to add
            </span>
            <span className="warn">
              <b>{n(check.duplicates)}</b> already have an account
            </span>
            <span className="bad">
              <b>{n(check.invalid)}</b> invalid
            </span>
          </div>
          {check.ready > 0 && (
            <p className="field-hint">
              {Object.entries(check.roles).filter(([, count]) => count).map(([role, count]) => `${count} ${role}${count === 1 ? "" : "s"}`).join(" • ")}
              {" "}• A temporary password is created for anyone without one in the file.
            </p>
          )}
          {check.preview.length > 0 && (
            <div className="table-scroll">
              <table className="sf-table upload-preview">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Role</th>
                  </tr>
                </thead>
                <tbody>
                  {check.preview.map((u) => (
                    <tr key={u.email}>
                      <td>{u.full_name}</td>
                      <td>{u.email}</td>
                      <td>{u.role}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {check.errors.length > 0 && (
            <details className="upload-errors" open={check.ready === 0}>
              <summary>
                {n(check.errors.length)} row{check.errors.length === 1 ? "" : "s"} skipped
              </summary>
              <ul>
                {check.errors.map((e) => (
                  <li key={e.row}>
                    Row {e.row}: {e.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {check.ready === 0 && <p className="form-error">No new users to add.</p>}
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
