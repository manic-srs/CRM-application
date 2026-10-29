import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";


function AssistantIcon({ wand = false }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{wand ? <><path d="m4 20 12-12 4 4L8 24m6-14 4 4M6 2v4M4 4h4m10-4v4m-2-2h4M3 10v4m-2-2h4"/></> : <><rect x="4" y="7" width="16" height="13" rx="3"/><path d="M12 3v4m-2-4h4M1 12v4m22-4v4M8 12v3m8-3v3m-7 2h6"/></>}</svg>;
}

export default function EmailDraftAssistant({ target, settings, sending, onApply, onBusyChange }) {
  const [open, setOpen] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(null);
  const [menu, setMenu] = useState(null);
  const [menuLoading, setMenuLoading] = useState(false);
  const [menuError, setMenuError] = useState("");
  const [menuRefresh, setMenuRefresh] = useState(0);
  const menuStage = useRef(undefined);
  const request = useRef(null);
  const mounted = useRef(true);
  const trigger = useRef(null);
  const input = useRef(null);
  const sampleMode = settings?.draft_mode === "sample";
  const unavailable = settings?.ai_drafting_enabled === false;
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); };
  }, []);
  useEffect(() => { if (open) input.current?.focus(); }, [open]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setMenuLoading(true); setMenuError("");
    api.emailDraftOptions(target.field, target.id, controller.signal).then(next => {
      if (controller.signal.aborted) return;
      if (menuStage.current !== undefined && menuStage.current !== next.stage) {
        setDraft(null); setSelected(null); setInstructions("");
        setNotice("The record stage changed. The email options have been updated.");
      }
      menuStage.current = next.stage;
      setMenu(next);
    }).catch(err => {
      if (!controller.signal.aborted) { setMenu(null); setMenuError(err.message); }
    }).finally(() => { if (!controller.signal.aborted) setMenuLoading(false); });
    return () => controller.abort();
  }, [open, target.field, target.id, menuRefresh]);

  const close = () => { setOpen(false); trigger.current?.focus(); };
  const reset = () => {
    setDraft(null); setSelected(null); setError(""); setInstructions(""); setNotice(""); setMenuRefresh(v => v + 1); input.current?.focus();
  };
  const generate = async (option, text = "") => {
    if (busy || sending || !settings || unavailable || menuLoading || !menu) return;
    setError(""); setNotice("");
    if (sampleMode && option.action === "custom") {
      setError("For local sample testing, choose one of the four options or type its number. Custom descriptions are available in AI mode.");
      return;
    }
    setSelected(option); setDraft(null); setBusy(true); onBusyChange(true);
    const controller = new AbortController(); request.current = controller;
    try {
      const next = await api.draftEmail({ record_field: target.field, record_id: Number(target.id), action: option.action || "stage", option_id: option.option_id, instructions: text }, AbortSignal.any([controller.signal, AbortSignal.timeout(50000)]));
      if (mounted.current && !controller.signal.aborted) setDraft(next);
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setError(err.message);
    } finally {
      if (mounted.current) { setBusy(false); onBusyChange(false); }
      request.current = null;
    }
  };
  const submitRequest = () => {
    const text = instructions.trim();
    if (!text) return;
    const number = /^[1-4]$/.test(text) ? Number(text) - 1 : -1;
    if (menuLoading || !menu) return;
    generate(number >= 0 ? menu.options[number] : { action: "custom", label: text }, number >= 0 ? "" : text);
  };

  return (
    <div className="email-assistant-dock">
      <button ref={trigger} type="button" className="email-assistant-trigger" onClick={() => setOpen(v => !v)} disabled={sending} aria-expanded={open} aria-controls="email-assistant-panel"><AssistantIcon wand/><span>{busy ? "Drafting your email…" : "Describe your message"}</span></button>
      {notice && <span className="email-assistant-applied" role="status">{notice}</span>}
      {open && <section id="email-assistant-panel" className="email-assistant-panel" aria-labelledby="email-assistant-title" onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); close(); } }}>
        <header className="email-assistant-header"><h3 id="email-assistant-title"><AssistantIcon/>Email assistant</h3><button type="button" onClick={reset} disabled={busy || sending} className="email-assistant-reset">Start over</button><button type="button" className="email-assistant-close" onClick={close} aria-label="Close email assistant">×</button></header>
        <div className="email-assistant-conversation" aria-busy={busy}>
          <p className="email-assistant-bubble">What would you like to write?</p>
          <p className="email-assistant-meta">{sampleMode ? "Local sample mode" : "AI drafting"}{menu?.stage ? ` · ${menu.stage} stage` : ""}</p>
          {menuLoading && <p className="email-assistant-note" role="status">Loading options for the current stage…</p>}
          {menuError && <div role="alert"><p className="form-error">{menuError}</p><button type="button" className="link" onClick={() => setMenuRefresh(v => v + 1)}>Retry loading options</button></div>}
          {!selected && menu && !menuLoading && <ol className="email-assistant-options">{menu.options.map((option, index) => <li key={option.option_id}><button type="button" disabled={busy || sending || !settings || unavailable || menuLoading} onClick={() => generate(option)}><span>{index + 1}</span>{option.label}</button></li>)}</ol>}
          {selected && <p className="email-assistant-user">{selected.label}</p>}
          {busy && <div className="email-assistant-progress" role="status"><span>Writing your {sampleMode ? "sample " : ""}draft…</span><button type="button" onClick={() => request.current?.abort()}>Cancel</button></div>}
          {draft && <div className="email-assistant-preview"><h4>{draft.mode === "sample" ? "Sample draft" : "Draft"}{draft.stage ? ` · ${draft.stage}` : ""}</h4><p><b>Subject:</b> {draft.subject}</p><div className="email-assistant-draft-body">{draft.body}</div><div className="email-assistant-actions"><button type="button" className="sf-button brand" disabled={busy || sending} onClick={() => { onApply(draft); reset(); setNotice("Draft added. Review before sending."); close(); }}>Use draft</button><button type="button" className="sf-button" disabled={busy || sending} onClick={reset}>Discard</button></div><small>Use draft replaces the current subject and message.</small></div>}
          {selected && !draft && !busy && <button type="button" className="link" onClick={reset}>Back to the four options</button>}
          {error && <p className="form-error" role="alert">{error}</p>}
          {unavailable && <p className="email-assistant-note" role="status">{settings?.settings_error || "Drafting is not configured. You can still write your email manually."}</p>}
        </div>
        <footer className="email-assistant-footer">
          <div className="email-assistant-prompt"><input ref={input} aria-label="Describe your email or type a menu number" value={instructions} maxLength={4000} placeholder="Describe your email, or type 1–4…" disabled={busy || sending} onChange={e => setInstructions(e.target.value)} onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); submitRequest(); } }}/><button type="button" aria-label="Submit email request" disabled={busy || sending || !instructions.trim() || !settings || unavailable || menuLoading || !menu} onClick={submitRequest}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m3 3 18 9-18 9 4-9-4-9Zm4 9h14"/></svg></button></div>
          <p className="email-assistant-note">{sampleMode ? "Sample mode uses fixed examples for each option and the current CRM stage. No AI calls." : "Your request and the record’s name and stage are sent to OpenAI. Review the draft before sending."}</p>
        </footer>
      </section>}
    </div>
  );
}
