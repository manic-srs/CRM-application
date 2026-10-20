import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { BrandMark } from "./Login";
import { Avatar, Icon, ObjectIcon } from "./ui";

export const TABS = [
  ["home", "Home", "/", "home"],
  ["opportunities", "Opportunities", "/opportunities", "opportunity"],
  ["leads", "Leads", "/leads", "lead"],
  ["tasks", "Tasks", "/tasks", "task"],
  ["accounts", "Accounts", "/accounts", "account"],
  ["contacts", "Contacts", "/contacts", "contact"],
];

// "App Launcher" (the 9 dots): every page of the app plus the tools that run next to it
const LAUNCHER_LINKS = [
  ["Test Inbox", "Emails the app has sent (local test mailbox)", "http://localhost:8026", "note"],
  ["API Docs", "Try the backend APIs", "http://localhost:8001/docs", "event"],
];

function AppLauncher({ onClose }) {
  const [q, setQ] = useState("");
  const match = (text) => text.toLowerCase().includes(q.trim().toLowerCase());
  return (
    <div className="launcher" role="dialog" aria-label="App Launcher">
      <div className="launcher-head">
        <h2>App Launcher</h2>
        <label className="list-search">
          <Icon name="search" size={14} />
          <input autoFocus placeholder="Search apps and items..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search apps and items" />
        </label>
      </div>
      <h3>Sales</h3>
      <div className="launcher-grid">
        {TABS.filter(([, label]) => match(label)).map(([key, label, path, icon]) => (
          <a key={key} href={`#${path}`} onClick={onClose}>
            <ObjectIcon type={icon} size={32} />
            <span>{label}</span>
          </a>
        ))}
      </div>
      <h3>Tools</h3>
      <div className="launcher-grid">
        {LAUNCHER_LINKS.filter(([label]) => match(label)).map(([label, text, url, icon]) => (
          <a key={label} href={url} target="_blank" rel="noreferrer" onClick={onClose}>
            <ObjectIcon type={icon} size={32} />
            <span>
              {label}
              <small>{text}</small>
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}

const routeFor = {
  Lead: "leads",
  Opportunity: "opportunities",
  Account: "accounts",
  Contact: "contacts",
  Task: "tasks",
};

// Closes a popover when clicking outside it or pressing Escape
function useDismiss(open, setOpen) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onClick = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, setOpen]);
  return ref;
}

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, setOpen);
  useEffect(() => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    const t = setTimeout(() => {
      api
        .search(q.trim())
        .then(setResults)
        .catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  const pick = (r) => {
    window.location.hash = r.type === "Task" ? `/tasks?task=${r.id}` : `/${routeFor[r.type]}/${r.id}`;
    setQ("");
    setOpen(false);
  };
  return (
    <div className="global-search" ref={ref}>
      <Icon name="search" size={16} />
      <input
        aria-label="Search"
        placeholder="Search..."
        value={q}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
      />
      {open && q.trim() && (
        <div className="search-drop" role="listbox">
          {results.length ? (
            results.map((r) => (
              <button key={r.type + r.id} role="option" onClick={() => pick(r)}>
                <ObjectIcon type={r.type} size={24} />
                <span>
                  <b>{r.name}</b>
                  <small>
                    {r.type}
                    {r.detail ? ` • ${r.detail}` : ""}
                  </small>
                </span>
              </button>
            ))
          ) : (
            <p>No results for "{q.trim()}"</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function Header({ section, user, data, onLogout, openNew, run, notify, toggleSidebar }) {
  const [menu, setMenu] = useState(null); // "apps" | "new" | "bell" | "user"
  const toggle = (name) => setMenu((m) => (m === name ? null : name));
  const ref = useDismiss(!!menu, () => setMenu(null));
  useEffect(() => setMenu(null), [section]);
  const unread = data.notifications.filter((n) => !n.is_read);

  const openNotification = async (n) => {
    setMenu(null);
    try {
      await run("readNotification", n.id);
    } catch (err) {
      notify(err.message);
    }
    window.location.hash = n.link || (n.task_id ? `/tasks?task=${n.task_id}` : "/tasks");
  };

  return (
    <header className="global-header" ref={ref}>
      <div className="header-top">
        <div className="header-left">
          <button className="plain-icon menu-toggle" aria-label="Show or hide the navigation" onClick={toggleSidebar}>
            <Icon name="list" size={20} />
          </button>
          <div className="pop-wrap">
            <button
              className={`launcher-button ${menu === "apps" ? "on" : ""}`}
              aria-label="App Launcher"
              title="App Launcher"
              aria-expanded={menu === "apps"}
              onClick={() => toggle("apps")}
            >
              <Icon name="apps" size={18} />
            </button>
            {menu === "apps" && <AppLauncher onClose={() => setMenu(null)} />}
          </div>
          <a className="header-brand" href="#/" aria-label="SalesTrack home">
            <BrandMark size={34} />
            <span>SalesTrack</span>
          </a>
        </div>
        <GlobalSearch />
        <div className="header-icons">
          <div className="pop-wrap">
            <button className="round-icon" aria-label="Global actions" title="New" onClick={() => toggle("new")}>
              <Icon name="plus" size={18} />
            </button>
            {menu === "new" && (
              <div className="menu-pop">
                <button onClick={() => (setMenu(null), openNew("lead"))}>
                  <ObjectIcon type="lead" size={20} /> New Lead
                </button>
                <button onClick={() => (setMenu(null), openNew("task"))}>
                  <ObjectIcon type="task" size={20} /> New Task
                </button>
                <button onClick={() => (setMenu(null), openNew("account"))}>
                  <ObjectIcon type="account" size={20} /> New Account
                </button>
                <button onClick={() => (setMenu(null), openNew("contact"))}>
                  <ObjectIcon type="contact" size={20} /> New Contact
                </button>
              </div>
            )}
          </div>
          <div className="pop-wrap">
            <button
              className="plain-icon"
              title="Notifications"
              aria-label={`Notifications${unread.length ? `, ${unread.length} unread` : ""}`}
              onClick={() => toggle("bell")}
            >
              <Icon name="bell" size={20} />
              {unread.length > 0 && <span className="bell-count">{unread.length}</span>}
            </button>
            {menu === "bell" && (
              <div className="menu-pop notifications-pop">
                <div className="notifications-head">
                  <h3>Notifications</h3>
                  {unread.length > 0 && (
                    <button
                      className="link"
                      onClick={async () => {
                        try {
                          await run("readAllNotifications", user.id);
                        } catch (err) {
                          notify(err.message);
                        }
                      }}
                    >
                      Mark all as read
                    </button>
                  )}
                </div>
                {unread.length ? (
                  unread.map((n) => (
                    <button key={n.id} className="notification" onClick={() => openNotification(n)}>
                      <ObjectIcon type={n.title.startsWith("Lead") ? "lead" : n.title.startsWith("Opportunity") ? "opportunity" : "task"} size={24} />
                      <span>
                        <b>{n.title}</b>
                        <small>{n.message}</small>
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="muted">You're all caught up.</p>
                )}
              </div>
            )}
          </div>
          <div className="pop-wrap">
            <button className="avatar-button" aria-label="View profile" title={user.full_name} onClick={() => toggle("user")}>
              <Avatar name={user.full_name} size={32} />
            </button>
            {menu === "user" && (
              <div className="menu-pop user-pop">
                <div className="user-card">
                  <Avatar name={user.full_name} size={44} />
                  <div>
                    <b>{user.full_name}</b>
                    <small>{user.email}</small>
                    <small>{user.role}</small>
                  </div>
                </div>
                <button onClick={onLogout}>
                  <Icon name="logout" size={16} /> Log Out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

// Left navigation panel (collapses to icons)
export function Sidebar({ section, data, user, collapsed }) {
  const openTasks = data.tasks.filter((t) => !t.completed && t.owner_id === user.id).length;
  return (
    <nav className={`sidebar ${collapsed ? "collapsed" : ""}`} aria-label="Main navigation">
      <div className="sidebar-app">
        <span className="app-dot">S</span>
        {!collapsed && <span>Sales</span>}
      </div>
      <ul>
        {TABS.map(([key, label, path, icon]) => (
          <li key={key}>
            <a
              href={`#${path}`}
              className={section === key ? "active" : ""}
              aria-current={section === key ? "page" : undefined}
              title={collapsed ? label : undefined}
            >
              <ObjectIcon type={icon} size={24} />
              {!collapsed && <span>{label}</span>}
              {!collapsed && key === "tasks" && openTasks > 0 && <span className="nav-count">{openTasks}</span>}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
