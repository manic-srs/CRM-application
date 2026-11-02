// Opportunities list: Actions for the deals ticked in the list (Salesforce mass actions):
// Change Owner (follow-ups and reminders go with the deal) and Mark as Lost (one reason and note for all).
// Closed deals and deals the user can't change are skipped; the result says which and why.
import React, { useEffect, useState } from "react";
import { api } from "./api";
import { LOST_REASONS } from "./domain";
import { Icon } from "./ui";

const plural = (n) => `${n.toLocaleString()} ${n === 1 ? "Opportunity" : "Opportunities"}`;

export function OpportunityBulkDialog({ action, users, me, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const owner = action.type === "owner";
  const count = action.ids.length;
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);
  const submit = async (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.currentTarget));
    if (!owner && (v.lost_notes || "").trim().length < 1) return setError("Enter the lost notes.");
    setBusy(true);
    setError("");
    try {
      const res = owner
        ? await api.bulkTransferOpportunities(action.ids.map(Number), Number(v.to_user_id), v.note)
        : await api.bulkLostOpportunities(action.ids.map(Number), v.lost_reason, v.lost_notes.trim());
      onDone(res);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="modal small-modal" role="dialog" aria-modal="true" aria-labelledby="opp-bulk-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="opp-bulk-title">{owner ? `Change Owner: ${plural(count)}` : `Mark as Lost: ${plural(count)}`}</h2>
        </header>
        <form onSubmit={submit}>
          <div className="modal-body bulk-form">
            {owner ? (
              <>
                <p className="field-hint">
                  Each deal continues at its stage; its open follow-ups and reminders go to the new owner. Closed deals, and deals you can't transfer, are
                  skipped.
                </p>
                <label className="field">
                  <span>
                    <abbr title="required">*</abbr> New owner
                  </span>
                  <select name="to_user_id" required defaultValue="">
                    <option value="" disabled>
                      Select a user…
                    </option>
                    {users
                      .filter((u) => u.is_active !== false && u.role !== "Admin")
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.full_name} ({u.role}){u.id === me?.id ? " - me" : ""}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="field">
                  <span>Note</span>
                  <textarea name="note" rows={3} maxLength={300} />
                </label>
              </>
            ) : (
              <>
                <p className="field-hint">
                  Closes each deal as Lost with this reason and note (for example, deals that went quiet). Their open tasks are closed.
                  Deals you can't change are skipped.
                </p>
                <label className="field">
                  <span>
                    <abbr title="required">*</abbr> Lost Reason
                  </span>
                  <select name="lost_reason" required defaultValue="">
                    <option value="" disabled>
                      Select a reason…
                    </option>
                    {LOST_REASONS.map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>
                    <abbr title="required">*</abbr> Lost Notes
                  </span>
                  <textarea name="lost_notes" rows={3} required />
                </label>
              </>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="sf-button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className={`sf-button ${owner ? "brand" : "danger"}`} disabled={busy} aria-busy={busy}>
              {busy ? "Working…" : owner ? "Change Owner" : "Mark as Lost"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function bulkResultMessage(res, done) {
  const skipped = res.skipped || [];
  const first = skipped[0];
  return `${done}${skipped.length ? ` ${skipped.length} skipped${first ? ` (${first.name}: ${first.reason}${skipped.length > 1 ? ", …" : ""})` : ""}.` : ""}`;
}
