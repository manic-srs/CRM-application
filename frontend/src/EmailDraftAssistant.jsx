import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { LEAD_STAGES, OPPORTUNITY_STAGES } from "./domain";

const EMAIL_STAGES = [...new Set([...LEAD_STAGES.filter(stage => stage !== "Lost"), ...OPPORTUNITY_STAGES])];

export default function EmailDraftAssistant({ target, settings, subject, message, sending, onApply, onBusyChange }) {
  const [instructions, setInstructions] = useState("");
  const [emailStage, setEmailStage] = useState("");
  const [recordStage, setRecordStage] = useState(target.stage || null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [backup, setBackup] = useState(null);
  const request = useRef(null);
  const mounted = useRef(true);
  const sampleMode = settings?.draft_mode === "sample";
  const unavailable = settings?.ai_drafting_enabled === false;
  const canUndo = backup && subject === backup.generated.subject && message === backup.generated.body;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); };
  }, []);

  const generate = async () => {
    const text = instructions.trim();
    if ((!text && !emailStage) || busy || sending || !settings || unavailable || sampleMode) return;
    setError(""); setNotice(""); setBusy(true); onBusyChange(true);
    const previous = { subject, body: message };
    const controller = new AbortController();
    request.current = controller;
    try {
      const draft = await api.draftEmail({
        record_field: target.field,
        record_id: Number(target.id),
        action: "custom",
        email_stage: emailStage || null,
        instructions: text,
      }, AbortSignal.any([controller.signal, AbortSignal.timeout(50000)]));
      if (mounted.current && !controller.signal.aborted) {
        if (draft.record_stage !== undefined) setRecordStage(draft.record_stage);
        setBackup({ previous, generated: draft });
        onApply(draft);
        setNotice(`Draft added${draft.stage ? ` for the ${draft.stage} stage` : ""}. Review and edit before sending.`);
      }
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setError(err.message);
    } finally {
      if (mounted.current) {
        if (controller.signal.aborted) setNotice("Generation cancelled. Your email is unchanged.");
        setBusy(false); onBusyChange(false);
      }
      request.current = null;
    }
  };

  return (
    <div className="email-assistant-inline" aria-busy={busy}>
      <div className="email-assistant-stage-row">
        <label htmlFor="email-draft-stage">Email stage</label>
        <select id="email-draft-stage" value={emailStage} disabled={busy || sending} onChange={e => { setEmailStage(e.target.value); setNotice(""); setError(""); }} aria-describedby="email-stage-note">
          <option value="">Use current stage{recordStage ? ` (${recordStage})` : ""}</option>
          {EMAIL_STAGES.map(stage => <option key={stage} value={stage}>{stage}</option>)}
        </select>
        <span id="email-stage-note">For this draft only</span>
      </div>
      <div className="email-assistant-input-row">
        <svg className="email-assistant-wand" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m4 20 11-11 4 4L8 24m5-13 4 4M6 2v4M4 4h4m10-4v4m-2-2h4M3 10v4m-2-2h4"/></svg>
        <input aria-label="Describe your message" placeholder="Describe your message" value={instructions} maxLength={4000} disabled={busy || sending} onChange={e => setInstructions(e.target.value)} onKeyDown={e => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); e.stopPropagation(); generate(); }
        }} aria-describedby="email-assistant-help"/>
        <button type="button" className="email-assistant-generate" aria-label="Generate email draft" title="Generate email draft" onClick={generate} disabled={busy || sending || (!instructions.trim() && !emailStage) || !settings || unavailable || sampleMode}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>
        </button>
      </div>
      <div id="email-assistant-help" className="email-assistant-inline-status">
        {busy ? <><span role="status">Writing your email for the selected stage…</span><button type="button" className="link" onClick={() => request.current?.abort()}>Cancel generation</button></> : notice ? <span role="status">{notice}</span> : <span>{sampleMode ? "Custom descriptions require AI mode. Sample mode does not interpret your instructions." : unavailable ? settings?.settings_error || "AI drafting is unavailable. You can still write your email manually." : "Choose an email stage, describe your message, or both. Press Enter or the arrow to generate."}</span>}
        {!busy && canUndo && <button type="button" className="link" disabled={sending} onClick={() => { onApply(backup.previous); setBackup(null); setNotice("Previous subject and message restored."); }}>Undo draft</button>}
      </div>
      {error && <p className="form-error" role="alert">{error} Your existing email has been kept.</p>}
    </div>
  );
}
