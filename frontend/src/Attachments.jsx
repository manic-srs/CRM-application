// Attachments card on the opportunity page: upload PDF / Word (.docx) / JPG / PNG files, open, download, delete.
// Files are fetched with the login header and shown from a temporary blob: address (no file links with tokens).
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ATTACHMENT_EXTENSIONS, ATTACHMENT_STAGES, PREVIEW_TYPES, attachmentProblem } from "./domain";
import { size } from "./Email";
import { dateTime } from "./format";
import { Card, Icon, ObjectIcon, StageBadge } from "./ui";

const MAX_PER_PICK = 10; // files are uploaded one by one; this only bounds one selection
// Text after the file name in an upload result ("report.pdf is empty." already starts with the name)
const afterName = (r) =>
  r.text.startsWith(r.name) ? r.text.slice(r.name.length) : r.state === "error" ? `: ${r.text}` : ` ${r.text}`;
const KIND = {
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
  "image/jpeg": "JPEG",
  "image/png": "PNG",
};

// A preview tab keeps its blob: address until the tab is closed or goes to another page (checked every few
// seconds), so reloading the preview keeps working. Everything left is freed when the app itself is closed.
const previews = new Set();
function keepUntilClosed(tab, address) {
  previews.add(address);
  const timer = setInterval(() => {
    let gone;
    try {
      gone = tab.closed || ![address, "about:blank"].includes(tab.location.href);
    } catch {
      gone = true; // the tab went to another site
    }
    if (gone) {
      clearInterval(timer);
      URL.revokeObjectURL(address);
      previews.delete(address);
    }
  }, 3000);
}
if (typeof window !== "undefined")
  window.addEventListener("pagehide", () => previews.forEach((address) => URL.revokeObjectURL(address)));

export default function OpportunityAttachments({ opportunity, user, canEdit }) {
  const [files, setFiles] = useState(null); // null = loading
  const [loadError, setLoadError] = useState("");
  const [results, setResults] = useState([]); // one line per file of the last upload
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(null); // id of the file being opened / downloaded / deleted
  const [confirming, setConfirming] = useState(null);
  const [message, setMessage] = useState({ text: "", error: false });
  const input = useRef(null);

  const id = opportunity.id;
  const canUpload = canEdit && ATTACHMENT_STAGES.includes(opportunity.stage);
  const canDelete = (file) =>
    canUpload && (file.uploaded_by_id === user?.id || ["Manager", "Admin"].includes(user?.role));

  const load = useCallback(() => {
    setLoadError("");
    return api
      .attachments(id)
      .then(setFiles)
      .catch((err) => setLoadError(err.message));
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  const say = (text, error = false) => setMessage({ text, error });

  const uploadFiles = async (list) => {
    const chosen = [...list];
    if (!chosen.length || uploading) return;
    say("");
    if (chosen.length > MAX_PER_PICK) return say(`Choose up to ${MAX_PER_PICK} files at a time.`, true);
    const lines = chosen.map((f, i) => ({ key: `${i}-${f.name}`, name: f.name, state: "waiting", text: "Waiting…" }));
    const update = (i, change) => {
      lines[i] = { ...lines[i], ...change };
      setResults([...lines]);
    };
    setResults([...lines]);
    setUploading(true);
    for (const [i, file] of chosen.entries()) {
      const problem = attachmentProblem(file);
      if (problem) {
        update(i, { state: "error", text: problem });
        continue;
      }
      update(i, { state: "uploading", text: "Uploading…" });
      try {
        await api.uploadAttachment(id, file);
        update(i, { state: "done", text: "Uploaded" });
        await load();
      } catch (err) {
        update(i, { state: "error", text: err.message });
      }
    }
    setUploading(false);
  };

  // Fetches the file with the login header. download=true: always save it.
  const fetchFile = async (file, download) => {
    const blob = await api.attachmentFile(id, file.id, download);
    return URL.createObjectURL(new Blob([blob], { type: file.content_type }));
  };

  const save = async (file) => {
    setBusy(file.id);
    say("");
    try {
      const address = await fetchFile(file, true);
      const link = document.createElement("a");
      link.href = address;
      link.download = file.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(address), 60000); // the browser has the file by then
    } catch (err) {
      say(`${file.filename} could not be downloaded: ${err.message}`, true);
    } finally {
      setBusy(null);
    }
  };

  // PDF and images open in a new tab; Word files are downloaded (the computer opens them with Word).
  const open = async (file) => {
    if (!PREVIEW_TYPES.includes(file.content_type)) return save(file);
    say("");
    const tab = window.open("", "_blank"); // inside the click, so the browser doesn't block it
    if (!tab) return say("Your browser blocked the new tab. Allow pop-ups for this site, or use Download.", true);
    tab.opener = null;
    try {
      tab.document.title = file.filename;
      tab.document.body.textContent = "Loading preview…";
    } catch {
      // the blank tab can't always be written to; the preview still loads
    }
    setBusy(file.id);
    try {
      const address = await fetchFile(file, false);
      tab.location.replace(address);
      keepUntilClosed(tab, address);
    } catch (err) {
      tab.close();
      say(`${file.filename} could not be opened: ${err.message}`, true);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (file) => {
    setBusy(file.id);
    say("");
    try {
      await api.deleteAttachment(id, file.id);
      setConfirming(null);
      say(`${file.filename} was deleted.`);
      await load();
    } catch (err) {
      say(`${file.filename} could not be deleted: ${err.message}`, true);
    } finally {
      setBusy(null);
    }
  };

  const closed = !ATTACHMENT_STAGES.includes(opportunity.stage);
  return (
    <Card title={`Attachments (${files ? files.length : 0})`} icon="note" className="attachments-card">
      <div className="attachments">
        {canUpload ? (
          <div
            className={`dropzone attach-drop ${dragging ? "dragging" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              uploadFiles(e.dataTransfer.files);
            }}
          >
            <button
              type="button"
              className="sf-button small"
              onClick={() => input.current.click()}
              disabled={uploading}
              aria-busy={uploading}
            >
              {uploading ? "Uploading…" : "Upload Files"}
            </button>
            <span className="muted">or drop files here. PDF, Word (.docx), JPG or PNG • 20 MB per file</span>
            <input
              ref={input}
              type="file"
              multiple
              hidden
              accept={ATTACHMENT_EXTENSIONS.join(",")}
              onChange={(e) => {
                uploadFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
        ) : (
          <p className="attach-note">
            <Icon name="lock" size={14} />
            {closed
              ? `This opportunity is ${opportunity.stage}. Files can be opened and downloaded, but not added or deleted.`
              : "Only the owner or a Manager can add files."}
          </p>
        )}

        {results.length > 0 && (
          <div className="upload-results" aria-live="polite">
            <ul>
              {results.map((r) => (
                <li key={r.key} className={r.state}>
                  <Icon name={r.state === "done" ? "check" : r.state === "error" ? "warn" : "clock"} size={14} />
                  <span>
                    <b>{r.name}</b>
                    {afterName(r)}
                  </span>
                </li>
              ))}
            </ul>
            {!uploading && (
              <button type="button" className="link" onClick={() => setResults([])}>
                Clear
              </button>
            )}
          </div>
        )}
        {message.text && (
          <p className={message.error ? "form-error" : "attach-success"} role={message.error ? "alert" : "status"}>
            {message.text}
          </p>
        )}

        {loadError ? (
          <p className="form-error" role="alert">
            The files could not be loaded: {loadError}{" "}
            <button type="button" className="link" onClick={load}>
              Try again
            </button>
          </p>
        ) : files === null ? (
          <p className="muted attach-state">Loading files…</p>
        ) : files.length === 0 ? (
          <p className="muted attach-state">No files yet.</p>
        ) : (
          <ul className="attachment-list">
            {files.map((f) => (
              <li key={f.id}>
                <ObjectIcon type="note" size={24} />
                <div className="attachment-info">
                  <button
                    type="button"
                    className="link attachment-name"
                    onClick={() => open(f)}
                    disabled={busy === f.id}
                    title={PREVIEW_TYPES.includes(f.content_type) ? `Open ${f.filename} in a new tab` : `Download ${f.filename}`}
                  >
                    {f.filename}
                  </button>
                  <small>
                    {KIND[f.content_type] || "File"} • {size(f.size_bytes)} • Uploaded at{" "}
                    <StageBadge stage={f.stage} />
                  </small>
                  <small>
                    {f.uploaded_by_name} • {dateTime(f.uploaded_at)}
                  </small>
                </div>
                <div className="attachment-actions">
                  <button
                    type="button"
                    className="sf-button small"
                    onClick={() => save(f)}
                    disabled={busy === f.id}
                    aria-label={`Download ${f.filename}`}
                  >
                    Download
                  </button>
                  {canDelete(f) && (
                    <button
                      type="button"
                      className="sf-button small"
                      onClick={() => setConfirming(f.id)}
                      disabled={busy === f.id}
                      aria-label={`Delete ${f.filename}`}
                    >
                      Delete
                    </button>
                  )}
                </div>
                {confirming === f.id && canDelete(f) && (
                  <div className="attachment-confirm" role="alert">
                    <span>
                      Delete <b>{f.filename}</b>? It will no longer be listed or downloadable.
                    </span>
                    <button
                      type="button"
                      className="sf-button small danger"
                      onClick={() => remove(f)}
                      disabled={busy === f.id}
                    >
                      {busy === f.id ? "Deleting…" : "Delete"}
                    </button>
                    <button type="button" className="sf-button small" onClick={() => setConfirming(null)}>
                      Cancel
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
