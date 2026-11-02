import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";

export default function EmailDraftAssistant({ target, settings, subject, message, sending, onApply, onBusyChange }) {
  const [instructions, setInstructions] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [backup, setBackup] = useState(null);
  const [suggestions, setSuggestions] = useState(null);
  const [suggestionsError, setSuggestionsError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const input = useRef(null);
  const request = useRef(null);
  const mounted = useRef(true);
  const sampleMode = settings?.draft_mode === "sample";
  const unavailable = settings?.ai_drafting_enabled === false;
  const canUndo = backup && subject === backup.generated.subject && message === backup.generated.body;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setSuggestionsError(false);
    api.emailDraftOptions(target.field, Number(target.id), controller.signal).then(result => {
      if (!controller.signal.aborted) setSuggestions(result);
    }).catch(() => {
      if (!controller.signal.aborted) { setSuggestions(null); setSuggestionsError(true); }
    });
    return () => controller.abort();
  }, [target.field, target.id, refresh]);

  useEffect(() => {
    const refreshSuggestions = () => setRefresh(value => value + 1);
    window.addEventListener("focus", refreshSuggestions);
    return () => window.removeEventListener("focus", refreshSuggestions);
  }, []);

  const generate = async () => {
    const text = instructions.trim();
    if (!text || busy || sending || !settings || unavailable || sampleMode) return;
    setError(""); setNotice(""); setBusy(true); onBusyChange(true);
    const previous = { subject, body: message };
    const controller = new AbortController();
    request.current = controller;
    try {
      const draft = await api.draftEmail({
        record_field: target.field,
        record_id: Number(target.id),
        action: "custom",
        instructions: text,
      }, AbortSignal.any([controller.signal, AbortSignal.timeout(50000)]));
      if (mounted.current && !controller.signal.aborted) {
        setBackup({ previous, generated: draft });
        onApply(draft);
        setRefresh(value => value + 1);
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
      <div className="email-assistant-input-row">
        <svg className="email-assistant-wand" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m4 20 11-11 4 4L8 24m5-13 4 4M6 2v4M4 4h4m10-4v4m-2-2h4M3 10v4m-2-2h4"/></svg>
        <input ref={input} aria-label="Describe your message" placeholder="Describe your message" value={instructions} maxLength={4000} disabled={busy || sending} onFocus={() => setRefresh(value => value + 1)} onChange={e => setInstructions(e.target.value)} onKeyDown={e => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); e.stopPropagation(); generate(); }
        }} aria-describedby="email-assistant-help"/>
        <button type="button" className="email-assistant-generate" aria-label="Generate email draft" title="Generate email draft" onClick={generate} disabled={busy || sending || !instructions.trim() || !settings || unavailable || sampleMode}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>
        </button>
      </div>
      {suggestions && <div className="email-assistant-suggestions" role="group" aria-label="Suggested email prompts">
        <span className="email-assistant-suggestions-label">{suggestions.stage ? `Suggestions for ${suggestions.stage}` : "Suggested messages"}</span>
        <div className="email-assistant-suggestion-list">
          {suggestions.options.map(option => <button key={option.option_id} type="button" disabled={busy || sending} onClick={() => {
            setInstructions(option.prompt); setNotice(""); setError(""); input.current?.focus();
          }}>{option.label}</button>)}
        </div>
      </div>}
      {suggestionsError && <p className="email-assistant-suggestions-label" role="status">Suggestions could not be loaded. You can still describe your message; generation checks the saved stage.</p>}
      <div id="email-assistant-help" className="email-assistant-inline-status">
        {busy ? <><span role="status">Writing your email using the current CRM stage…</span><button type="button" className="link" onClick={() => request.current?.abort()}>Cancel generation</button></> : notice ? <span role="status">{notice}</span> : <span>{sampleMode ? "Custom descriptions require AI mode. Sample mode does not interpret your instructions." : unavailable ? settings?.settings_error || "AI drafting is unavailable. You can still write your email manually." : "Describe what to write, then press Enter or the arrow. Uses the current CRM stage."}</span>}
        {!busy && canUndo && <button type="button" className="link" disabled={sending} onClick={() => { onApply(backup.previous); setBackup(null); setNotice("Previous subject and message restored."); }}>Undo draft</button>}
      </div>
      {error && <p className="form-error" role="alert">{error} Your existing email has been kept.</p>}
    </div>
  );
}
