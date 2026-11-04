// AI writing in New Email. A pen button opens a compact instruction bar inside the composer:
// - a request writes a new email (when the message is only the greeting and signature) or changes the current draft;
// - Refine (Professional, Conversational, Concise) rewrites an existing draft.
// Only the subject and message are filled, after the server has validated the draft. It never sends, and never changes
// To, Cc, attachments or the record. An answer is applied only if nothing changed while it was being written.
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { api } from "./api";
import { draftContent, toRecordContact } from "./domain";
import { Icon } from "./ui";

const REFINE = [["formalize", "Professional"], ["friendly", "Conversational"], ["shorten", "Concise"]];
const DESCRIBE_FIRST = "Describe the email you need first. Professional, Conversational, and Concise refine an existing draft.";
// Server messages that already say the email was kept, or that ask for more, are shown as they are.
const keptMessage = (text) =>
  /unchanged|kept|helps with CRM|sales context|describe the email/i.test(text) ? text : `${text} Your email is unchanged.`;

export default function EmailDraftAssistant({ target, settings, user, subject, message, sending, recipients, onApply, onBusyChange }) {
  const [open, setOpen] = useState(false); // closed until the pen is clicked
  const [instructions, setInstructions] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [history, setHistory] = useState(null); // the last AI change: { previous, applied, undone }
  const id = useId();
  const toggle = useRef(null);
  const input = useRef(null);
  const refineButton = useRef(null);
  const refineBox = useRef(null);
  const menu = useRef(null);
  const request = useRef(null); // the request in progress: { id, controller }
  const requests = useRef(0);
  const mounted = useRef(true);
  const now = useRef(null); // what the composer holds now, for an answer that arrives later
  now.current = { subject, message, record: `${target.field}:${target.id}` };
  const sampleMode = settings?.draft_mode === "sample";
  const unavailable = !settings || settings.ai_drafting_enabled === false;
  const blocked = busy || sending || unavailable || sampleMode;
  const canUndo = !!history && !history.undone && subject === history.applied.subject && message === history.applied.body;
  const canRedo = !!history && history.undone && subject === history.previous.subject && message === history.previous.body;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      request.current?.controller.abort(); // the composer closed: the answer is never applied
    };
  }, []);

  // The instruction box grows with its text, up to four lines.
  useLayoutEffect(() => {
    const box = input.current;
    if (!box || !open) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 96)}px`;
  }, [instructions, open]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const dismiss = (event) => { if (!refineBox.current?.contains(event.target)) setMenuOpen(false); };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [menuOpen]);

  const stopWaiting = () => {
    request.current = null;
    setBusy(false);
    onBusyChange(false);
  };

  const run = async (action) => {
    if (busy || sending) return;
    setMenuOpen(false);
    setError("");
    if (unavailable || sampleMode) return;
    const refining = action !== "custom";
    const text = instructions.trim();
    if (!refining && !text) return input.current?.focus();
    if (refining && !draftContent(message, user.full_name, user.email)) return setNotice(DESCRIBE_FIRST);
    const before = { subject, message, to: recipients(), record: now.current.record };
    const mine = { id: ++requests.current, controller: new AbortController() };
    request.current = mine;
    setNotice("");
    setBusy(true);
    onBusyChange(true);
    try {
      const draft = await api.draftEmail(
        {
          record_field: target.field,
          record_id: Number(target.id),
          action,
          instructions: refining ? "" : text,
          current_subject: subject,
          current_body: message,
          recipient_is_record_contact: toRecordContact(before.to, target.email),
        },
        AbortSignal.any([mine.controller.signal, AbortSignal.timeout(50000)]),
      );
      if (!mounted.current || request.current !== mine) return; // cancelled, closed or replaced
      const latest = now.current;
      if (latest.subject !== before.subject || latest.message !== before.message)
        return setNotice("You changed the email while the draft was being written, so your version was kept.");
      if (latest.record !== before.record || recipients() !== before.to)
        return setNotice("The recipient changed while the draft was being written, so the draft wasn't applied.");
      const applied = { subject: draft.subject, body: draft.body };
      setHistory({ previous: { subject: before.subject, body: before.message }, applied, undone: false });
      onApply(applied);
      setNotice(draft.draft_type === "revision" ? "Draft updated. Review before sending." : "Draft generated. Review before sending.");
    } catch (err) {
      if (mounted.current && request.current === mine) setError(keptMessage(err.message));
    } finally {
      if (mounted.current && request.current === mine) stopWaiting();
    }
  };

  const cancel = () => {
    if (!request.current) return;
    request.current.controller.abort();
    stopWaiting();
    setNotice("Generation cancelled. Your email is unchanged.");
  };
  const openBar = () => {
    setOpen(true);
    requestAnimationFrame(() => input.current?.focus());
  };
  const closeBar = () => {
    cancel(); // a pending answer would otherwise land after the bar is closed
    setMenuOpen(false);
    setOpen(false);
    requestAnimationFrame(() => toggle.current?.focus());
  };
  const openMenu = (index) => {
    setMenuOpen(true);
    requestAnimationFrame(() => menu.current?.querySelectorAll("[role=menuitem]")[index]?.focus());
  };
  const undo = () => {
    onApply(history.previous);
    setHistory({ ...history, undone: true });
    setNotice("Previous subject and message restored.");
  };
  const redo = () => {
    onApply(history.applied);
    setHistory({ ...history, undone: false });
    setNotice("AI draft restored. Review before sending.");
  };

  const onBarKey = (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation(); // Escape closes the menu or the bar here, not the whole composer
    if (menuOpen) {
      setMenuOpen(false);
      refineButton.current?.focus();
    } else closeBar();
  };
  const onMenuKey = (event) => {
    const items = [...(menu.current?.querySelectorAll("[role=menuitem]") || [])];
    const at = items.indexOf(document.activeElement);
    const go = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[event.key];
    if (go !== undefined) {
      event.preventDefault();
      items[(go + items.length) % items.length]?.focus();
    } else if (event.key === "Tab") setMenuOpen(false);
  };

  let status = "";
  if (busy)
    status = (
      <>
        Writing draft…{" "}
        <button type="button" className="link" onClick={cancel}>
          Cancel
        </button>
      </>
    );
  else if (notice) status = notice;
  else if (open && sampleMode) status = "AI drafting needs AI mode on the server. You can still write the email yourself.";
  else if (open && settings && unavailable)
    status = settings.settings_error || "AI drafting isn't available. You can still write the email yourself.";
  else if (open) status = "Enter to generate · Shift+Enter for a new line";

  return (
    <div className="email-ai">
      <div id={`${id}-bar`} className="email-ai-bar" role="group" aria-label="Write with AI" hidden={!open} onKeyDown={onBarKey}>
        <textarea
          ref={input}
          className="email-ai-input"
          rows={1}
          value={instructions}
          maxLength={4000}
          aria-label="Describe the email or change you need"
          placeholder="Describe the email or change you need…"
          aria-describedby={`${id}-status`}
          onChange={(event) => setInstructions(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              run("custom");
            }
          }}
        />
        <div className="email-ai-refine" ref={refineBox}>
          <button
            ref={refineButton}
            type="button"
            className="email-ai-refine-button"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-controls={menuOpen ? `${id}-menu` : undefined}
            disabled={blocked}
            onClick={() => (menuOpen ? setMenuOpen(false) : openMenu(0))}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                openMenu(event.key === "ArrowDown" ? 0 : REFINE.length - 1);
              }
            }}
          >
            Refine <Chevron />
          </button>
          {menuOpen && (
            <div id={`${id}-menu`} ref={menu} className="email-ai-menu" role="menu" aria-label="Refine the current draft" onKeyDown={onMenuKey}>
              {REFINE.map(([action, label]) => (
                <button
                  key={action}
                  type="button"
                  role="menuitem"
                  tabIndex={-1}
                  onClick={() => {
                    input.current?.focus(); // Refine is disabled while the draft is written
                    run(action);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          type="button"
          className="email-ai-submit"
          aria-label="Generate draft"
          title="Generate draft (Enter)"
          disabled={blocked || !instructions.trim()}
          onClick={() => {
            input.current?.focus(); // this button is disabled while the draft is written
            run("custom");
          }}
        >
          <ArrowUp />
        </button>
        <button type="button" className="email-ai-close" aria-label="Close AI writing bar" title="Close" onClick={closeBar}>
          <Icon name="close" size={14} />
        </button>
      </div>
      <div className="email-ai-tools">
        <button
          ref={toggle}
          type="button"
          className="email-ai-toggle"
          aria-label="Write with AI"
          title="Write or refine this email with AI"
          aria-expanded={open}
          aria-controls={`${id}-bar`}
          disabled={sending}
          onClick={() => (open ? closeBar() : openBar())}
        >
          <Pen />
        </button>
        <span id={`${id}-status`} className="email-ai-status" role="status">
          {status}
        </span>
        {history && (
          <span className="email-ai-history" role="group" aria-label="AI changes">
            <button type="button" aria-label="Undo AI change" title="Undo AI change" disabled={busy || sending || !canUndo} onClick={undo}>
              <HistoryIcon />
            </button>
            <button type="button" aria-label="Redo AI change" title="Redo AI change" disabled={busy || sending || !canRedo} onClick={redo}>
              <HistoryIcon redo />
            </button>
          </span>
        )}
      </div>
      {error && (
        <p className="form-error email-ai-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function Pen() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 20l1.2-4.2L15.6 5.4a2 2 0 0 1 2.9 0l.1.1a2 2 0 0 1 0 2.9L8.2 18.8z" />
      <path d="M13.8 7.2l3 3M19 14.5v4M17 16.5h4" />
    </svg>
  );
}

function ArrowUp() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 19V5M6 11l6-6 6 6" />
    </svg>
  );
}

function Chevron() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function HistoryIcon({ redo = false }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={redo ? { transform: "scaleX(-1)" } : undefined}>
      <path d="m9 5-5 5 5 5M4 10h10a5 5 0 0 1 0 10h-3" />
    </svg>
  );
}
