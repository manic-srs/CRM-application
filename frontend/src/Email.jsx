// Send Email (with attachments) from a lead, opportunity, contact or account, and the list of sent emails.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import EmailDraftAssistant from "./EmailDraftAssistant";
import { dateTime } from "./format";
import { Icon, ObjectIcon } from "./ui";

const MAX_FILE = 10 * 1024 * 1024;
const MAX_TOTAL = 25 * 1024 * 1024;
const MAX_FILES = 10;

export const size = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

// Loads the emails of one record; reload() after sending.
export function useEmails(field, id, version = 0) {
  const [emails, setEmails] = useState([]);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    if (!id) return Promise.resolve();
    return api
      .emails(field, id)
      .then((list) => {
        setEmails(list);
        setError("");
      })
      .catch((err) => setError(err.message));
  }, [field, id]);
  useEffect(() => {
    reload();
  }, [reload, version]);
  return { emails, error, reload };
}

// "My Outlook": opens a new message in the user's own Outlook; the CRM only keeps a copy on the record.
const composeUrl = (app, { to, cc, subject, body }) => {
  const q = (params) =>
    Object.entries(params)
      .filter(([, v]) => v)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join("&");
  return `https://outlook.office.com/mail/deeplink/compose?${q({ to, cc, subject, body })}`;
};
const APP_NAME = { outlook: "Outlook" };

export function EmailComposer({ target, user, onClose, onSent }) {
  const [files, setFiles] = useState([]);
  const [sender, setSender] = useState(null);
  // "crm": the app sends it from the CRM mailbox (SMTP). "mine": opens the user's own Gmail / Outlook.
  const [via, setVia] = useState("crm");
  const app = "outlook"; // "My email" always opens Outlook (company mail)
  useEffect(() => {
    api.emailSettings().then(setSender).catch(err => setSender({ ai_drafting_enabled: false, settings_error: err.message }));
  }, []);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [subject, setSubject] = useState(target.subject || "");
  const [message, setMessage] = useState(target.greeting || "");
  const fileInput = useRef(null);
  const ref = useRef(null);
  const formRef = useRef(null);

  useEffect(() => {
    ref.current?.querySelector("input[name=to]")?.focus();
    const onKey = (e) => e.key === "Escape" && !sending && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, sending]);

  const addFiles = (list) => {
    setError("");
    const next = [...files];
    for (const f of list) {
      if (f.size > MAX_FILE) {
        setError(`${f.name} is larger than 10 MB.`);
        continue;
      }
      if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f);
    }
    if (next.length > MAX_FILES) return setError(`You can attach up to ${MAX_FILES} files.`);
    if (next.reduce((s, f) => s + f.size, 0) > MAX_TOTAL) return setError("Attachments can be up to 25 MB in total.");
    setFiles(next);
  };

  const submit = async (event) => {
    event.preventDefault();
    if (sending || aiBusy) return;
    setError("");
    const form = new FormData(event.target);
    if (!String(form.get("to")).trim()) return setError("Enter at least one recipient.");
    form.delete("files");
    if (via === "mine") {
      // open the user's own mailbox right away (inside the click, so the browser doesn't block it)
      window.open(
        composeUrl(app, {
          to: form.get("to"),
          cc: form.get("cc"),
          subject: form.get("subject"),
          body: form.get("body"),
        }),
        "_blank",
        "noopener",
      );
      form.append("open_in", app);
    } else {
      files.forEach((f) => form.append("files", f, f.name));
    }
    form.append(target.field, target.id);
    setSending(true);
    try {
      const email = await api.sendEmail(form);
      onSent(email);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !sending && onClose()}>
      <section ref={ref} className="modal email-modal" role="dialog" aria-modal="true" aria-labelledby="email-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={sending}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="email-title">New Email</h2>
        </header>
        <form ref={formRef} onSubmit={submit} autoComplete="off">
          <div className="modal-body">
            <div className="email-related">
              <ObjectIcon type={target.type} size={20} />
              <span>
                Related to <b>{target.name}</b>
              </span>
            </div>
            <fieldset className="send-from">
              <legend>Send from</legend>
              <label className={`send-option ${via === "crm" ? "on" : ""}`}>
                <input type="radio" name="via" checked={via === "crm"} onChange={() => setVia("crm")} />
                <span>
                  <b>CRM mailbox</b>
                  <small>
                    Sent by SalesTrack. Replies come to you.
                  </small>
                </span>
              </label>
              <label className={`send-option ${via === "mine" ? "on" : ""}`}>
                <input type="radio" name="via" checked={via === "mine"} onChange={() => setVia("mine")} />
                <span>
                  <b>My Outlook</b>
                  <small>Sent from your own Outlook.</small>
                </span>
              </label>
            </fieldset>
            {via === "crm" ? (
              <label className="field">
                <span>Reply-To</span>
                <input name="reply_to" type="email" defaultValue={user.email} autoComplete="off" />
                <small className="field-hint">Replies from the customer go to this address.</small>
              </label>
            ) : (
              <p className="field-hint send-note">
                Opens {APP_NAME[app]} in a new tab. Add attachments there.
              </p>
            )}
            <label className="field">
              <span>
                To <i>*</i>
              </span>
              <input name="to" defaultValue={target.email || ""} placeholder="name@company.com" required />
            </label>
            <label className="field">
              <span>Cc</span>
              <input name="cc" placeholder="Separate addresses with commas" autoComplete="off" />
            </label>
            <label className="field">
              <span>
                Subject <i>*</i>
              </span>
              <input name="subject" required maxLength={255} value={subject} onChange={e => setSubject(e.target.value)} autoComplete="off" disabled={sending || aiBusy} />
            </label>
            <div className="field">
              <label htmlFor="email-message">Message <i>*</i></label>
              <div className="email-editor">
                <textarea id="email-message" name="body" rows={9} required value={message} onChange={e => setMessage(e.target.value)} disabled={sending || aiBusy} />
                <EmailDraftAssistant target={target} settings={sender} subject={subject} message={message} sending={sending} onBusyChange={setAiBusy} onApply={draft => { setSubject(draft.subject); setMessage(draft.body); }} />
              </div>
            </div>
            {via === "crm" && (
            <div
              className="dropzone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                addFiles(e.dataTransfer.files);
              }}
            >
              <button type="button" className="sf-button small" onClick={() => fileInput.current.click()}>
                Attach Files
              </button>
              <span className="muted">or drop files here (up to 10 MB each, 25 MB total)</span>
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
            )}
            {via === "crm" && files.length > 0 && (
              <ul className="file-list">
                {files.map((f) => (
                  <li key={f.name + f.size}>
                    <ObjectIcon type="note" size={20} />
                    <span>{f.name}</span>
                    <small>{size(f.size)}</small>
                    <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x !== f))}>
                      <Icon name="close" size={12} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="sf-button" onClick={onClose} disabled={sending}>
              Cancel
            </button>
            <button type="submit" className="sf-button brand" disabled={sending || aiBusy} aria-busy={sending}>
              {sending ? "Sending…" : via === "mine" ? `Open in ${APP_NAME[app]}` : "Send"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function EmailItem({ email: initial }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState(initial);
  const [resending, setResending] = useState(false);
  const [resendError, setResendError] = useState("");
  useEffect(() => setEmail(initial), [initial]);
  // A failed email can be sent again (same text and attachments), e.g. after the mail server is fixed
  const resend = async () => {
    setResending(true);
    setResendError("");
    try {
      const updated = await api.resendEmail(email.id);
      setEmail(updated);
      if (updated.status === "Failed") setResendError(`Still not sent: ${updated.error}`);
    } catch (err) {
      setResendError(err.message);
    } finally {
      setResending(false);
    }
  };
  return (
    <li className={`email-item ${email.status === "Failed" ? "failed" : ""}`}>
      <ObjectIcon type="note" size={24} />
      <div>
        <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {email.subject}
        </button>
        <small>
          {email.sent_by_name} to {email.to_address}
          {email.attachments.length ? ` • ${email.attachments.length} attachment${email.attachments.length > 1 ? "s" : ""}` : ""}
          {email.status === "Failed" ? " • Not sent" : ""}
          {["Gmail", "Outlook"].includes(email.status) ? ` • Opened in ${email.status}` : ""}
        </small>
        {open && (
          <div className="email-open">
            {email.cc_address && <p className="muted">Cc: {email.cc_address}</p>}
            <p className="email-body">{email.body}</p>
            {email.status === "Failed" && <p className="form-error">Not sent: {email.error}</p>}
            {email.attachments.length > 0 && (
              <ul className="file-list">
                {email.attachments.map((a) => (
                  <li key={a.id}>
                    <ObjectIcon type="note" size={20} />
                    <a href={api.attachmentUrl(a.id)} download={a.filename}>
                      {a.filename}
                    </a>
                    <small>{size(a.size_bytes)}</small>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <span className="email-side">
        <span className="due">{dateTime(email.sent_at)}</span>
        {email.status === "Failed" && (
          <button className="sf-button small" onClick={resend} disabled={resending} aria-busy={resending}>
            {resending ? "Sending…" : "Resend"}
          </button>
        )}
        {resendError && (
          <small className="form-error" role="alert">
            {resendError}
          </small>
        )}
      </span>
    </li>
  );
}

export function EmailList({ emails, empty = "No emails yet." }) {
  return emails.length ? (
    <ul className="task-lines">
      {emails.map((e) => (
        <EmailItem key={e.id} email={e} />
      ))}
    </ul>
  ) : (
    <p className="muted pad">{empty}</p>
  );
}
