// AI Assistant page (#/assistant): do CRM work by typing what you want, in any format.
// The backend (app/assistant.py) runs the same actions as the screens, as the logged-in user, and saves every chat
// (the history panel on the left: rename, delete, date and time). Closing actions (Lost, Unqualified, Won, transfer,
// cancel demo, delete) come back as a Confirm card first. Files (PDF, Word, Excel, images...) can be attached.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ASSISTANT_ATTACH_HELP, ASSISTANT_FILE_TYPES } from "./domain";
import { dateTime } from "./format";
import { Icon, ObjectIcon } from "./ui";

// Quick actions start the sentence; the details can then be typed or pasted in any format.
// Everything else (convert, new opportunity, reports, files...) is asked in the chat.
const QUICK = [
  { icon: "lead", label: "New lead", text: "Create a new lead: " },
  { icon: "event", label: "Book demo", text: "Book a demo with " },
  { icon: "task", label: "Follow-up task", text: "Create a follow-up task: " },
  { icon: "opportunity", label: "Convert lead", text: "Convert the lead " },
  { icon: "outcome", label: "Won / Lost", text: "Mark the deal as " },
];

// Example questions, grouped like the menu (click to ask)
const EXAMPLES = [
  ["Lead workflow", ["Which leads should I follow up today?", "Which leads have a demo this week?", "Show my leads waiting at Nurturing"]],
  ["Deals", ["Show my open opportunities by stage", "Which deals close this month?", "Which deals are at Proposal?"]],
  ["Tasks & demos", ["What is overdue?", "What do I have today?", "Show my upcoming demos"]],
  ["Stats", ["Give me a pipeline report for this month", "What is our win rate this quarter?", "How many leads did we convert last month?"]],
];

const ACCEPT = ASSISTANT_FILE_TYPES; // what the backend reads (backend/app/assistant_store.py)
const LAST_CHAT = (user) => `crm-assistant-chat-${user.id}`;
const remember = (user, id) => {
  try {
    if (id) sessionStorage.setItem(LAST_CHAT(user), String(id));
    else sessionStorage.removeItem(LAST_CHAT(user));
  } catch {
    /* storage unavailable: the page opens on a new chat */
  }
};
const remembered = (user) => {
  try {
    return Number(sessionStorage.getItem(LAST_CHAT(user))) || null;
  } catch {
    return null;
  }
};

const recordHref = (l) =>
  ({
    Lead: `#/leads/${l.id}`,
    Opportunity: `#/opportunities/${l.id}`,
    Account: `#/accounts/${l.id}`,
    Contact: `#/contacts/${l.id}`,
    Task: `#/tasks?task=${l.id}`,
  })[l.type] || "#/";

const size = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

// **bold**, `code`
function inline(line) {
  return line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <b key={i}>{part.slice(2, -2)}</b>
    ) : part.startsWith("`") && part.endsWith("`") ? (
      <code key={i}>{part.slice(1, -1)}</code>
    ) : (
      part
    ),
  );
}

// Plain text with headings, **bold**, "- " / "1." lists, markdown tables and line breaks
export function Formatted({ text }) {
  const lines = (text || "").split("\n");
  const out = [];
  let list = [];
  let table = [];
  const flushList = () => {
    if (list.length) out.push(<ul key={`l${out.length}`}>{list}</ul>);
    list = [];
  };
  const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const flushTable = () => {
    if (table.length) {
      const rows = table.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
      const [head, ...body] = rows.map(cells);
      out.push(
        <div className="ai-table-wrap" key={`t${out.length}`}>
          <table className="ai-table">
            <thead>
              <tr>{head.map((c, i) => <th key={i}>{inline(c)}</th>)}</tr>
            </thead>
            <tbody>
              {body.map((r, i) => (
                <tr key={i}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
    }
    table = [];
  };
  lines.forEach((line, i) => {
    if (/^\s*\|.*\|\s*$/.test(line)) {
      flushList();
      table.push(line);
      return;
    }
    flushTable();
    const heading = line.match(/^\s*#{1,4}\s+(.*)/);
    const item = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)/);
    if (heading) {
      flushList();
      out.push(<h3 key={i}>{inline(heading[1])}</h3>);
    } else if (item) list.push(<li key={i}>{inline(item[1])}</li>);
    else {
      flushList();
      if (line.trim()) out.push(<p key={i}>{inline(line)}</p>);
    }
  });
  flushList();
  flushTable();
  return <div className="ai-text">{out}</div>;
}

// The history panel: every saved chat with its date and time; rename and delete in place
function ChatList({ items, current, busy, onOpen, onNew, onRename, onDelete, onClose }) {
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(null); // { id, title }
  const [deleting, setDeleting] = useState(null);
  const [menu, setMenu] = useState(null); // the chat whose small arrow menu (Rename / Delete) is open
  useEffect(() => {
    if (menu === null) return undefined;
    const close = (e) => !e.target.closest?.(".ai-history-actions") && setMenu(null);
    const key = (e) => e.key === "Escape" && setMenu(null);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key);
    };
  }, [menu]);
  const shown = items.filter((c) => c.title.toLowerCase().includes(filter.trim().toLowerCase()));
  const save = async () => {
    if (!editing) return;
    const { id, title } = editing;
    setEditing(null);
    if (title.trim()) await onRename(id, title.trim());
  };
  return (
    <aside className="ai-history" aria-label="Chat history">
      <div className="ai-history-head">
        <p className="ai-history-label">Chat history</p>
        <button className="icon-button ai-history-hide" onClick={onClose} aria-label="Hide chat history" title="Hide chat history">
          <Icon name="panel" size={17} />
        </button>
      </div>
      <button className="sf-button brand ai-new" onClick={onNew} disabled={busy}>
        <Icon name="plus" size={15} /> New chat
      </button>
      {items.length > 4 && (
        <label className="list-search ai-history-search">
          <Icon name="search" size={14} />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search chats" aria-label="Search chats" />
        </label>
      )}
      <ul className="ai-history-list">
        {shown.map((c) => (
          <li key={c.id} className={c.id === current ? "on" : ""}>
            {editing?.id === c.id ? (
              <form
                className="ai-rename"
                onSubmit={(e) => {
                  e.preventDefault();
                  save();
                }}
              >
                <input
                  autoFocus
                  value={editing.title}
                  maxLength={120}
                  aria-label="Chat name"
                  onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                  onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                  onBlur={save}
                />
              </form>
            ) : deleting === c.id ? (
              <div className="ai-delete">
                <span>Delete this chat?</span>
                <button className="sf-button small danger" onClick={() => (onDelete(c.id), setDeleting(null))}>
                  Delete
                </button>
                <button className="sf-button small" onClick={() => setDeleting(null)}>
                  Keep
                </button>
              </div>
            ) : (
              <>
                <button className="ai-history-item" onClick={() => onOpen(c.id)} disabled={busy} title={c.title}>
                  <span className="ai-history-title">{c.title}</span>
                  <span className="ai-history-time">{dateTime(c.updated_at || c.created_at)}</span>
                </button>
                <span className="ai-history-actions">
                  <button
                    className="icon-button ai-row-arrow"
                    onClick={() => setMenu(menu === c.id ? null : c.id)}
                    aria-haspopup="menu"
                    aria-expanded={menu === c.id}
                    aria-label={`Options for ${c.title}`}
                    title="Rename or delete"
                  >
                    <Icon name="down" size={14} />
                  </button>
                  {menu === c.id && (
                    <span className="ai-row-menu" role="menu">
                      <button role="menuitem" onClick={() => (setMenu(null), setEditing({ id: c.id, title: c.title }))}>
                        <Icon name="edit" size={14} /> Rename
                      </button>
                      <button role="menuitem" className="danger" onClick={() => (setMenu(null), setDeleting(c.id))}>
                        <Icon name="trash" size={14} /> Delete
                      </button>
                    </span>
                  )}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}

export default function AssistantPage({ user, reload }) {
  const [status, setStatus] = useState(null);
  const [chats, setChats] = useState([]);
  const [current, setCurrent] = useState(null); // saved chat id (null = new chat)
  const [chat, setChat] = useState([]); // what the page shows: { from, text, links, pending, files }
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState([]); // attached to the next message: { key, id?, filename, kind, size_bytes, error? }
  const [historyOpen, setHistoryOpen] = useState(false); // small screens: the panel slides in
  const [historyShown, setHistoryShown] = useState(() => {
    try {
      return localStorage.getItem("crm-assistant-history") !== "hidden";
    } catch {
      return true;
    }
  }); // wide screens: the panel can be hidden
  const toggleHistory = () => {
    if (window.matchMedia("(max-width: 960px)").matches) return setHistoryOpen(true);
    setHistoryShown((shown) => {
      try {
        localStorage.setItem("crm-assistant-history", shown ? "hidden" : "shown");
      } catch {
        /* not remembered */
      }
      return !shown;
    });
  };
  const [dragging, setDragging] = useState(false);
  const endRef = useRef(null);
  const boxRef = useRef(null);
  const fileRef = useRef(null);

  const off = status && !status.enabled;
  const last = chat.length ? chat[chat.length - 1] : null;
  const pending = last?.pending || null;
  const uploading = files.some((f) => !f.id && !f.error);
  const ready = files.filter((f) => f.id);

  const open = async (id) => {
    try {
      const conv = await api.assistantConversation(id);
      setCurrent(conv.id);
      setChat(conv.chat || []);
      remember(user, conv.id);
    } catch {
      setCurrent(null);
      setChat([]);
      remember(user, null);
    }
    setHistoryOpen(false);
  };
  useEffect(() => {
    api.assistantStatus().then(setStatus).catch(() => setStatus({ enabled: false }));
    api.assistantConversations().then(setChats).catch(() => {});
    const id = remembered(user);
    if (id) open(id);
  }, [user.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat, busy]);

  const newChat = () => {
    setCurrent(null);
    setChat([]);
    setInput("");
    setFiles([]);
    remember(user, null);
    setHistoryOpen(false);
    setTimeout(() => boxRef.current?.focus());
  };

  const apply = (res) => {
    setChat(res.chat);
    setCurrent(res.conversation.id);
    remember(user, res.conversation.id);
    setChats((list) => [res.conversation, ...list.filter((c) => c.id !== res.conversation.id)]);
    if ((res.links || []).length || (res.done || []).length) reload().catch(() => {}); // lists and Home show the change
  };
  const fail = (err) => setChat((c) => [...c, { from: "ai", text: err.message, error: true }]);

  const send = async (text) => {
    const message = (text ?? input).trim();
    if (!message || busy || uploading) return;
    const attached = ready;
    setInput("");
    setFiles([]);
    setChat((c) => [...c.map((m) => ({ ...m, pending: null })), { from: "me", text: message, files: attached }]);
    setBusy(true);
    try {
      apply(await api.assistantChat(current, message, attached.map((f) => f.id)));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
      boxRef.current?.focus();
    }
  };

  const answer = async (confirmed) => {
    if (!pending || busy || !current) return;
    setChat((c) => [...c.map((m) => ({ ...m, pending: null })), { from: "me", text: confirmed ? "Confirm" : "Cancel", small: true }]);
    setBusy(true);
    try {
      apply(await api.assistantConfirm(current, confirmed));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const attach = (list) => {
    const room = Math.max(0, 5 - files.length);
    const picked = [...list].slice(0, room);
    if (list.length > picked.length) fail(new Error("Attach up to 5 files per message."));
    picked.forEach((file) => {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      setFiles((f) => [...f, { key, filename: file.name, size_bytes: file.size, kind: file.type.startsWith("image/") ? "image" : "text" }]);
      api
        .assistantUpload(file, current)
        .then((saved) => setFiles((f) => f.map((x) => (x.key === key ? { ...x, ...saved } : x))))
        .catch((err) => setFiles((f) => f.map((x) => (x.key === key ? { ...x, error: err.message } : x))));
    });
  };

  const quick = (q) => {
    setInput(q.text);
    setTimeout(() => {
      const box = boxRef.current;
      if (!box) return;
      box.focus();
      box.setSelectionRange(q.text.length, q.text.length);
    });
  };

  const rename = async (id, title) => {
    try {
      const saved = await api.renameAssistantConversation(id, title);
      setChats((list) => list.map((c) => (c.id === id ? { ...c, ...saved } : c)));
    } catch (err) {
      fail(err);
    }
  };
  const remove = async (id) => {
    try {
      await api.deleteAssistantConversation(id);
      setChats((list) => list.filter((c) => c.id !== id));
      if (id === current) newChat();
    } catch (err) {
      fail(err);
    }
  };

  const title = chats.find((c) => c.id === current)?.title;

  return (
    <div className="page ai-page">
      <div className="ai-head">
        <div>
          <h1>AI Assistant</h1>
          <p>
            Ask in your own words or attach the details. It works on your CRM data with your permissions &amp; closing actions
            wait for your confirmation.
          </p>
        </div>

      </div>

      <div className={`ai-layout ${historyShown ? "" : "history-hidden"}`}>
        <div className={`ai-history-wrap ${historyOpen ? "open" : ""}`}>
          <ChatList
            items={chats}
            current={current}
            busy={busy}
            onOpen={open}
            onNew={newChat}
            onRename={rename}
            onDelete={remove}
            onClose={() => (historyOpen ? setHistoryOpen(false) : toggleHistory())}
          />
        </div>

        <section
          className={`card ai-card ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => {
            if (off || ![...e.dataTransfer.types].includes("Files")) return;
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget) && setDragging(false)}
          onDrop={(e) => {
            if (off || !e.dataTransfer.files.length) return;
            e.preventDefault();
            setDragging(false);
            attach(e.dataTransfer.files);
          }}
        >
          <div className="ai-quick" role="toolbar" aria-label="Quick actions">
            <button
              className={`ai-history-show ${historyShown ? "" : "visible"}`}
              onClick={toggleHistory}
              aria-label="Show chat history"
              title="Show chat history"
            >
              <Icon name="panel" size={17} />
            </button>
            <span className="ai-quick-label">
              <Icon name="flash" size={14} /> Quick actions
            </span>
            {QUICK.map((q) => (
              <button key={q.label} onClick={() => quick(q)} disabled={off || busy}>
                <ObjectIcon type={q.icon} size={20} />
                {q.label}
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
            {title && <h2 className="ai-chat-title" title={title}>{title}</h2>}
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
                      {m.from === "me" ? <p className="ai-mine">{m.text}</p> : <Formatted text={m.text} />}
                      {m.files?.length > 0 && (
                        <div className="ai-files sent">
                          {m.files.map((f, j) => (
                            <span key={j} className="ai-file">
                              <Icon name={f.kind === "image" ? "image" : "file"} size={13} /> {f.filename}
                            </span>
                          ))}
                        </div>
                      )}
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
                      {m.pending && i === chat.length - 1 && (
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
            {dragging && <div className="ai-drop">Drop files to attach them</div>}
          </div>

          <form
            className="ai-input"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            {files.length > 0 && (
              <div className="ai-files">
                {files.map((f) => (
                  <span key={f.key} className={`ai-file ${f.error ? "bad" : f.id ? "" : "loading"}`} title={f.error || f.filename}>
                    <Icon name={f.error ? "warn" : f.kind === "image" ? "image" : "file"} size={13} />
                    {f.filename}
                    <small>{f.error || (f.id ? size(f.size_bytes) : "Uploading…")}</small>
                    <button type="button" onClick={() => setFiles((list) => list.filter((x) => x.key !== f.key))} aria-label={`Remove ${f.filename}`}>
                      <Icon name="close" size={12} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="ai-input-row">
              <button
                type="button"
                className="ai-tool"
                onClick={() => fileRef.current?.click()}
                aria-label="Attach files"
                aria-describedby="ai-attach-help"
                title="Attach files: PDF, Word, Excel, PowerPoint, CSV, text or images (up to 10 MB)"
                disabled={off || files.length >= 5}
              >
                <Icon name="clip" size={18} />
              </button>
              <input
                ref={fileRef}
                type="file"
                multiple
                accept={ACCEPT}
                hidden
                onChange={(e) => {
                  attach(e.target.files);
                  e.target.value = "";
                }}
              />
              <textarea
                ref={boxRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                }}
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
                    : "Ask or describe something…"
                }
                aria-label="Message the AI Assistant"
                disabled={off}
              />
              <button type="submit" className="ai-send" disabled={off || busy || uploading || !input.trim()} aria-label="Send">
                <Icon name="up" size={18} />
              </button>
            </div>
            <small id="ai-attach-help" className="ai-attach-help">
              {ASSISTANT_ATTACH_HELP}
            </small>
          </form>
        </section>
      </div>
      {historyOpen && <div className="ai-history-backdrop" onClick={() => setHistoryOpen(false)} />}
    </div>
  );
}
