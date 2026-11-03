import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";

export default function EmailDraftAssistant({ target, settings, subject, message, sending, onApply, onBusyChange }) {
  const [instructions, setInstructions] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [backup, setBackup] = useState(null);
  const [undone, setUndone] = useState(false);
  const [open, setOpen] = useState(true);
  const [polishOpen, setPolishOpen] = useState(false);
  const polish = useRef(null);
  const polishButton = useRef(null);
  const reopenButton = useRef(null);
  const input = useRef(null);
  const request = useRef(null);
  const mounted = useRef(true);
  const sampleMode = settings?.draft_mode === "sample";
  const unavailable = settings?.ai_drafting_enabled === false;
  const canUndo = backup && !undone && subject === backup.generated.subject && message === backup.generated.body;
  const canRedo = backup && undone && subject === backup.previous.subject && message === backup.previous.body;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!polishOpen) return;
    const dismiss = event => { if (!polish.current?.contains(event.target)) setPolishOpen(false); };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [polishOpen]);

  const generate = async (action = "custom") => {
    const text = instructions.trim();
    if ((action === "custom" ? !text : !message.trim()) || busy || sending || !settings || unavailable || sampleMode) return;
    setPolishOpen(false);
    setError(""); setNotice(""); setBusy(true); onBusyChange(true);
    const previous = { subject, body: message };
    const controller = new AbortController();
    request.current = controller;
    try {
      const draft = await api.draftEmail({
        record_field: target.field,
        record_id: Number(target.id),
        action,
        instructions: action === "custom" ? text : "",
        current_subject: subject,
        current_body: message,
      }, AbortSignal.any([controller.signal, AbortSignal.timeout(50000)]));
      if (mounted.current && !controller.signal.aborted) {
        setBackup({ previous, generated: draft });
        setUndone(false);
        onApply(draft);
        setNotice(action === "custom" ? `Draft added${draft.stage ? ` for the ${draft.stage} stage` : ""}. Review and edit before sending.` : "Email updated. Review and edit before sending.");
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

  const blocked = busy || sending || !settings || unavailable || sampleMode;
  const close = () => {
    request.current?.abort();
    setPolishOpen(false); setOpen(false);
    requestAnimationFrame(() => reopenButton.current?.focus());
  };

  if (!open) return <div className="email-assistant-collapsed">
    <button ref={reopenButton} type="button" className="email-assistant-reopen" aria-label="Open email AI assistant" aria-expanded={false} disabled={busy || sending} onClick={() => {
      setOpen(true); requestAnimationFrame(() => input.current?.focus());
    }}><Wand /> Help me write</button>
  </div>;

  return (
    <div className="email-assistant-inline" aria-label="Email AI assistant" aria-busy={busy}>
      <div className="email-assistant-toolbar">
      <div className="email-assistant-input-row">
        <button type="button" className="email-assistant-generate" aria-label="Apply described change" title="Apply described change" onClick={() => generate()} disabled={blocked || !instructions.trim()}><Wand /></button>
        <input ref={input} aria-label="Describe your change" placeholder="Describe your change" value={instructions} maxLength={4000} disabled={busy || sending} onChange={e => setInstructions(e.target.value)} onKeyDown={e => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); e.stopPropagation(); generate(); }
        }} aria-describedby="email-assistant-help"/>
        <div className="email-assistant-polish" ref={polish} onKeyDown={event => {
          if (event.key === "Escape" && polishOpen) { event.preventDefault(); event.stopPropagation(); setPolishOpen(false); polishButton.current?.focus(); }
        }}>
          <button ref={polishButton} type="button" className="email-assistant-polish-trigger" aria-label="Polish email" aria-expanded={polishOpen} aria-controls="email-polish-options" disabled={blocked || !message.trim()} onClick={() => setPolishOpen(value => !value)}><Wand /><span className="email-assistant-polish-label">Polish</span><svg className="email-assistant-more" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="12" cy="19" r="1.7"/></svg></button>
          {polishOpen && <div id="email-polish-options" className="email-assistant-polish-options" role="group" aria-label="Email refinement options">
            <button type="button" disabled={blocked} onClick={() => { polishButton.current?.focus(); generate("formalize"); }}><RefinementIcon kind="formalize" />Formalize</button>
            <button type="button" disabled={blocked} onClick={() => { polishButton.current?.focus(); generate("friendly"); }}><RefinementIcon kind="friendly" />Friendly</button>
            <button type="button" disabled={blocked} onClick={() => { polishButton.current?.focus(); generate("shorten"); }}><RefinementIcon kind="shorten" />Shorten</button>
          </div>}
        </div>
      </div>
        <div className="email-assistant-history" role="group" aria-label="AI draft history">
          <button type="button" aria-label="Undo draft" title="Undo draft" disabled={busy || sending || !canUndo} onClick={() => { onApply(backup.previous); setUndone(true); setNotice("Previous subject and message restored."); }}><HistoryIcon /></button>
          <button type="button" aria-label="Redo draft" title="Redo draft" disabled={busy || sending || !canRedo} onClick={() => { onApply(backup.generated); setUndone(false); setNotice("AI draft restored. Review before sending."); }}><HistoryIcon redo /></button>
        </div>
        <button type="button" className="email-assistant-close" aria-label="Close email AI assistant" title="Close email AI assistant" onClick={close}>×</button>
      </div>
      <div id="email-assistant-help" className="email-assistant-inline-status">
        {busy ? <><span role="status">Writing your email using the current CRM stage…</span><button type="button" className="link" onClick={() => request.current?.abort()}>Cancel generation</button></> : notice ? <span role="status">{notice}</span> : <span>{sampleMode ? "Custom descriptions require AI mode. Sample mode does not interpret your instructions." : unavailable ? settings?.settings_error || "AI drafting is unavailable. You can still write your email manually." : "Describe a change, then press Enter or the wand. Use Polish for tone and length."}</span>}
      </div>
      {error && <p className="form-error" role="alert">{error} Your existing email has been kept.</p>}
    </div>
  );
}

function Wand() {
  return <svg className="email-assistant-wand" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m4 20 11-11 4 4L8 24m5-13 4 4M6 2v4M4 4h4m10-4v4m-2-2h4M3 10v4m-2-2h4"/></svg>;
}

function RefinementIcon({ kind }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === "formalize" ? <><rect x="3" y="7" width="18" height="14" rx="2" /><path d="M8 7V4h8v3M3 12h18M10 12v3h4v-3" /></> : kind === "friendly" ? <><circle cx="12" cy="12" r="9" /><path d="M8 14s1 3 4 3 4-3 4-3M8 8h.01M16 8h.01" /></> : <path d="m8 3 4 4 4-4M12 1v6m-4 14 4-4 4 4m-4-4v6M5 12h14" />}
  </svg>;
}

function HistoryIcon({ redo = false }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={redo ? { transform: "scaleX(-1)" } : undefined}><path d="m9 5-5 5 5 5M4 10h10a5 5 0 0 1 0 10h-3" /></svg>;
}
