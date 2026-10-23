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

// "App Launcher" (the 9 dots): every page of the app plus the test inbox (API docs are for developers, not shown here)
const LAUNCHER_LINKS = [
  ["Test Inbox", "Emails the app has sent (local test mailbox)", "http://localhost:8026", "note"],
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

const POLL_MS = 15000;
// "5 min ago", "3 h ago", "Yesterday", then the date
function when(value) {
  if (!value) return "";
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} h ago`;
  if (minutes < 48 * 60) return "Yesterday";
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
const iconFor = (n) =>
  n.kind === "reminder" ? "task" : n.title.startsWith("Lead") ? "lead" : n.title.startsWith("Opportunity") ? "opportunity" : "task";

// The bell. Two kinds of notifications:
//  - updates (stage changes, assignments): pop up in the corner when they arrive (the pop-up goes away by
//    itself) and stay in the bell list for 30 days; unread ones have a blue dot and count in the red badge
//  - reminders (tasks, demos, close dates, overdue): stay on the bell until the task is done
// Clicking a notification or "Mark all read" only clears the dot; nothing is removed from the list.
function Bell({ data, open, setOpen, notify }) {
  const [items, setItems] = useState(data.notifications);
  const [popups, setPopups] = useState([]);
  const known = useRef(null);

  const receive = (list) => {
    setItems(list);
    if (known.current === null) {
      known.current = new Set(list.map((n) => n.id)); // first load: no pop-ups for old items
      return;
    }
    const fresh = list.filter((n) => !n.is_read && !known.current.has(n.id));
    fresh.forEach((n) => known.current.add(n.id));
    if (fresh.length) setPopups((p) => [...fresh.slice(0, 3), ...p].slice(0, 3));
  };
  useEffect(() => receive(data.notifications), [data.notifications]);
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.hidden) return;
      api.notifications().then(receive).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!popups.length) return;
    const t = setTimeout(() => setPopups((p) => p.slice(0, -1)), 7000);
    return () => clearTimeout(t);
  }, [popups]);

  const unread = items.filter((n) => !n.is_read);
  const markAllRead = () => {
    setItems((list) => list.map((n) => ({ ...n, is_read: true })));
    api.readAllNotifications().catch((err) => notify(err.message));
  };
  useEffect(() => {
    if (open) setPopups([]); // the list shows them now
  }, [open]);

  const go = (n) => {
    setOpen(false);
    setPopups((p) => p.filter((x) => x.id !== n.id));
    if (!n.is_read) {
      setItems((list) => list.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)));
      api.readNotification(n.id).catch(() => {});
    }
    window.location.hash = n.link || (n.task_id ? `/tasks?task=${n.task_id}` : "/tasks");
  };
  const row = (n) => (
    <button
      key={n.id}
      className={`notification ${n.kind === "reminder" ? "reminder" : ""} ${n.is_read ? "read" : "unread"}`}
      onClick={() => go(n)}
    >
      <ObjectIcon type={iconFor(n)} size={24} />
      <span>
        <b>
          {n.title}
          {!n.is_read && <i className="new-dot" aria-label="new" />}
        </b>
        <small>{n.message}</small>
        <small className="when">{when(n.created_at)}</small>
      </span>
    </button>
  );
  const updates = items.filter((n) => n.kind !== "reminder");
  const reminders = items.filter((n) => n.kind === "reminder");

  return (
    <>
      <button
        className="plain-icon"
        title="Notifications"
        aria-label={`Notifications${unread.length ? `, ${unread.length} new` : ""}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Icon name="bell" size={20} />
        {unread.length > 0 && <span className="bell-count">{unread.length}</span>}
      </button>
      {open && (
        <div className="menu-pop notifications-pop">
          <div className="notifications-head">
            <h3>Notifications</h3>
            {unread.length > 0 && (
              <button className="link" onClick={markAllRead}>
                Mark all read
              </button>
            )}
          </div>
          {!updates.length && !reminders.length && <p className="muted">No notifications in the last 30 days.</p>}
          {reminders.length > 0 && (
            <>
              <h4 className="bell-section">Reminders</h4>
              {reminders.map(row)}
            </>
          )}
          {updates.length > 0 && (
            <>
              <h4 className="bell-section">Updates</h4>
              {updates.map(row)}
            </>
          )}
        </div>
      )}
      {popups.length > 0 && !open && (
        <div className="popups" role="status" aria-live="polite">
          {popups.map((n) => (
            <div key={n.id} className={`popup ${n.kind === "reminder" ? "reminder" : ""}`}>
              <button className="popup-body" onClick={() => go(n)}>
                <ObjectIcon type={iconFor(n)} size={28} />
                <span>
                  <small>{n.kind === "reminder" ? "Reminder" : "Update"}</small>
                  <b>{n.title}</b>
                  <span>{n.message?.split("\n")[0]}</span>
                </span>
              </button>
              <button className="popup-close" aria-label="Dismiss" onClick={() => setPopups((p) => p.filter((x) => x.id !== n.id))}>
                <Icon name="close" size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function Header({ section, user, data, onLogout, openNew, notify, openPassword, openProfile, toggleSidebar }) {
  const [menu, setMenu] = useState(null); // "apps" | "new" | "bell" | "user"
  const toggle = (name) => setMenu((m) => (m === name ? null : name));
  const ref = useDismiss(!!menu, () => setMenu(null));
  useEffect(() => setMenu(null), [section]);
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
            <Bell data={data} open={menu === "bell"} setOpen={(v) => setMenu(v ? "bell" : null)} notify={notify} />
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
                <button onClick={() => (setMenu(null), openProfile())}>
                  <Icon name="user" size={16} /> My Profile
                </button>
                {user.role === "Admin" && (
                  <a href="#/users" onClick={() => setMenu(null)}>
                    <Icon name="settings" size={16} /> Users
                  </a>
                )}
                <button onClick={() => (setMenu(null), openPassword())}>
                  <Icon name="lock" size={16} /> Change Password
                </button>
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
        {[...TABS, ...(user.role === "Admin" ? [["users", "Users", "/users", "contact"]] : [])].map(([key, label, path, icon]) => (
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
