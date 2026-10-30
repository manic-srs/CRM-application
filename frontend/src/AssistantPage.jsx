// AI Assistant page (#/assistant): do CRM work by typing one sentence.
// The backend (app/assistant.py) runs the same actions as the screens, as the logged-in user.
// Closing actions (Lost, Won, transfer, cancel demo, delete) come back as a Confirm card first.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Icon, ObjectIcon } from "./ui";

// Quick actions put a ready-to-finish sentence in the box
const QUICK = [
  ["lead", "New lead", "Create a lead: name , title , company , email , phone , source "],
  ["event", "Book a demo", "Book a demo with  on  at "],
  ["opportunity", "Convert", "Convert the lead  with an amount of  closing on "],
  ["opportunity", "Mark won", "Mark the  opportunity as won"],
  ["task", "Follow-up", "Create a follow-up task for  due "],
];

// Example questions, grouped like the menu (click to ask)
const EXAMPLES = [
  ["Leads", ["Show my new leads", "Which leads have a demo this week?", "Move the newest lead to Nurturing"]],
  ["Opportunities", ["Show my open opportunities", "Which deals close this month?", "Move the biggest open deal to Proposal"]],
  ["Tasks & demos", ["What is overdue?", "What do I have today?", "Reschedule my next demo to Friday 3 PM"]],
  ["Team & pipeline", ["Give me a pipeline summary", "How many deals did we win and lose?", "Who owns the most open leads?"]],
];

const STORE = (user) => `crm-assistant-${user.id}`;
const load = (user) => {
  try {
    return JSON.parse(sessionStorage.getItem(STORE(user))) || null;
  } catch {
    return null;
  }
};
const save = (user, state) => {
  try {
    sessionStorage.setItem(STORE(user), JSON.stringify(state));
  } catch {
    /* storage unavailable: the chat lasts until the page is left */
  }
};

const recordHref = (l) =>
  ({ Lead: `#/leads/${l.id}`, Opportunity: `#/opportunities/${l.id}`, Task: `#/tasks?task=${l.id}` })[l.type] || "#/";

// Plain text with **bold**, "- " bullet lines and line breaks
function Formatted({ text }) {
  const bold = (line) =>
    line.split(/(\*\*[^*]+\*\*)/g).map((part, i) => (part.startsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : part));
  const lines = (text || "").split("\n");
  const out = [];
  let list = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`l${out.length}`}>{list}</ul>);
    list = [];
  };
  lines.forEach((line, i) => {
    const m = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)/);
    if (m) list.push(<li key={i}>{bold(m[1])}</li>);
    else {
      flush();
      if (line.trim()) out.push(<p key={i}>{bold(line)}</p>);
    }
  });
  flush();
  return <div className="ai-text">{out}</div>;
}

export default function AssistantPage({ user, reload }) {
  const saved = load(user);
  const [history, setHistory] = useState(saved?.history || []); // what the backend needs (OpenAI format)
  const [chat, setChat] = useState(saved?.chat || []); // what the page shows: { from, text, links, pending }
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const endRef = useRef(null);
  const boxRef = useRef(null);

  useEffect(() => {
    api.assistantStatus().then(setStatus).catch(() => setStatus({ enabled: false }));
  }, []);
  useEffect(() => {
    save(user, { history, chat });
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history, chat, user]);

  const pending = chat.length ? chat[chat.length - 1].pending : null;

  const apply = (res) => {
    setHistory(res.messages);
    setChat((c) => [...c, { from: "ai", text: res.reply, links: res.links || [], pending: res.pending || null }]);
    if ((res.links || []).length || (res.done || []).length) reload().catch(() => {}); // lists and Home show the change
  };
  const fail = (err) => setChat((c) => [...c, { from: "ai", text: err.message, error: true }]);

  const send = async (text) => {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setChat((c) => [...c.map((m) => ({ ...m, pending: null })), { from: "me", text: message }]);
    setBusy(true);
    try {
      apply(await api.assistantChat(history, message));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
      boxRef.current?.focus();
    }
  };

  const answer = async (confirmed) => {
    if (!pending || busy) return;
    setChat((c) => [
      ...c.map((m) => ({ ...m, pending: null })),
      { from: "me", text: confirmed ? "Confirm" : "Cancel", small: true },
    ]);
    setBusy(true);
    try {
      apply(await api.assistantConfirm(history, pending, confirmed));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const quick = (template) => {
    setInput(template);
    setTimeout(() => {
      const box = boxRef.current;
      if (!box) return;
      box.focus();
      const at = template.indexOf("  ") >= 0 ? template.indexOf("  ") + 1 : template.length;
      box.setSelectionRange(at, at);
    });
  };

  const clear = () => {
    setHistory([]);
    setChat([]);
  };

  const off = status && !status.enabled;

  return (
    <div className="page ai-page">
      <div className="ai-head">
        <div>
          <h1>AI Assistant</h1>
          <p>
            Ask in your own words. The assistant works on your data with your permissions, closing actions wait for your confirmation.
          </p>
        </div>
        {chat.length > 0 && (
          <button className="sf-button" onClick={clear} disabled={busy}>
            New chat
          </button>
        )}
      </div>

      <section className="card ai-card">
        <div className="ai-quick" role="toolbar" aria-label="Quick actions">
          <span className="ai-quick-label">
            <Icon name="flash" size={15} /> Quick actions
          </span>
          {QUICK.map(([icon, label, template]) => (
            <button key={label} onClick={() => quick(template)} disabled={off}>
              <ObjectIcon type={icon} size={20} />
              {label}
            </button>
          ))}
        </div>

        <div className="ai-body">
          {off && (
            <div className="alert ai-off" role="status">
              <Icon name="warn" size={16} />
              <span>
                The AI Assistant isn't set up yet. Add <code>OPENAI_API_KEY</code> to the <code>.env</code> file and restart the app.
              </span>
            </div>
          )}
          {!chat.length ? (
            <div className="ai-examples">
              {EXAMPLES.map(([group, items]) => (
                <div key={group} className="ai-example-group">
                  <h2>{group}</h2>
                  {items.map((q) => (
                    <button key={q} onClick={() => send(q)} disabled={off || busy}>
                      {q}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          ) : (
            <ol className="ai-chat" aria-live="polite">
              {chat.map((m, i) => (
                <li key={i} className={`ai-msg ${m.from === "me" ? "me" : "ai"} ${m.error ? "error" : ""} ${m.small ? "small" : ""}`}>
                  {m.from === "ai" && <ObjectIcon type="assistant" size={28} />}
                  <div className="ai-bubble">
                    {m.from === "me" ? <p>{m.text}</p> : <Formatted text={m.text} />}
                    {m.links?.length > 0 && (
                      <div className="ai-links">
                        {m.links.map((l, j) => (
                          <a key={j} href={recordHref(l)} className="ai-link">
                            <ObjectIcon type={l.type} size={18} />
                            {l.name}
                          </a>
                        ))}
                      </div>
                    )}
                    {m.pending && (
                      <div className="ai-confirm">
                        <p>
                          <Icon name="warn" size={15} /> {m.pending.summary}
                        </p>
                        <div>
                          <button className="sf-button" onClick={() => answer(false)} disabled={busy}>
                            Cancel
                          </button>
                          <button className="sf-button brand" onClick={() => answer(true)} disabled={busy}>
                            Confirm
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </li>
              ))}
              {busy && (
                <li className="ai-msg ai">
                  <ObjectIcon type="assistant" size={28} />
                  <div className="ai-bubble ai-typing" role="status">
                    <span />
                    <span />
                    <span />
                    Working…
                  </div>
                </li>
              )}
              <li ref={endRef} aria-hidden="true" />
            </ol>
          )}
        </div>

        <form
          className="ai-input"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <textarea
            ref={boxRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            placeholder={
              pending
                ? "Press Confirm or Cancel above, or type something else…"
                : "Ask a question or describe what you want to do… (Enter to send, Shift+Enter for a new line)"
            }
            aria-label="Message the AI Assistant"
            disabled={off}
          />
          <button type="submit" className="ai-send" disabled={off || busy || !input.trim()} aria-label="Send">
            <Icon name="up" size={18} />
          </button>
        </form>
      </section>
    </div>
  );
}
