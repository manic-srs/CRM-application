import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  dateKey,
  salesOverview,
  money,
  LEAD_STAGES,
  OPPORTUNITY_STAGES,
  LEAD_SOURCES,
  LOST_REASONS,
  SALUTATIONS,
  PRIORITIES,
  localInput,
} from "./domain";
import "./styles.css";
import { useWorkspace } from "./useWorkspace";

const paths = {
  menu: "M4 6h16M4 12h16M4 18h16",
  panel: "M3 4h18v16H3ZM9 4v16m7-12-3 4 3 4",
  home: "M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z",
  users:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8m8-7.87a4 4 0 0 1 0 7.75",
  briefcase:
    "M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M3 7h18v13H3Zm0 6a24 24 0 0 0 18 0M12 11v4",
  tasks: "M9 5h12M9 12h12M9 19h12M2 5l1 1 2-3m-3 9 1 1 2-3m-3 9 1 1 2-3",
  search: "m21 21-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  chevron: "m9 5 7 7-7 7",
  down: "m6 9 6 6 6-6",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4",
  calendar: "M8 2v4m8-4v4M3 10h18M3 5h18v17H3Z",
  trend: "m3 17 6-6 4 4 8-11m-6 0h6v6",
  check: "m5 12 4 4L19 6",
  close: "m6 6 12 12M6 18 18 6",
  clock: "M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  filter: "M4 7h16M7 12h10m-7 5h4",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  mail: "M3 5h18v14H3Zm0 1 9 7 9-7",
  phone: "M7 3H3c-1 10 8 19 18 18v-4l-5-2-2 2a15 15 0 0 1-7-7l2-2Z",
  building: "M4 21V3h12v18m0-12h4v12M8 7h4m-4 4h4m-4 4h4m-4 6v-3h4v3",
  edit: "m15 5 4 4M4 20l4-1L21 6l-4-4L4 15Z",
  logout: "M9 3H3v18h6m5-14 5 5-5 5m-7-5h14",
  target: "M21 12a9 9 0 1 1-9-9m0 9 9-9m-5 0h5v5M16 12a4 4 0 1 1-4-4",
  help: "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2-3 4m0 3h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  leaf: "M20 3C8 1 1 9 6 15s15 0 14-12ZM5 21l10-12",
  download: "M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4",
  flag: "M5 21V3m0 1c5-4 9 4 15 0v10c-6 4-10-4-15 0",
  spark: "m12 3 2 6 6 3-6 2-2 7-2-7-6-2 6-3Z",
};
function Icon({ name, size = 18, ...props }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d={paths[name] || paths.target} />
    </svg>
  );
}
const go = (path) => {
  window.location.hash = path;
};
const fmtDate = (value) =>
  value
    ? new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : "—";
function Avatar({ item, small = false }) {
  return (
    <span className={`avatar ${item.color || "sage"} ${small ? "small" : ""}`}>
      {item.initials ||
        item.name
          ?.split(" ")
          .map((x) => x[0])
          .slice(0, 2)
          .join("")}
    </span>
  );
}
function Badge({ stage }) {
  return (
    <span className={`badge ${stage.toLowerCase()}`}>
      <i />
      {stage}
    </span>
  );
}
function App() {
  const [route, setRoute] = useState(location.hash.slice(1) || "/");
  const section = route.split("?")[0].split("/")[1] || "home";
  const id = route.split("?")[0].split("/")[2];
  const {
    data,
    run,
    error: apiError,
    loading,
    saving,
    reload,
    hasLoaded,
    notificationOwner,
    setNotificationOwner,
  } = useWorkspace(section, id);
  const reminded = useRef(new Set());
  const [mobileSidebar, setMobileSidebar] = useState(
    () => window.matchMedia("(max-width: 900px)").matches,
  );
  const [sidebarOpen, setSidebarOpen] = useState(
    () => !window.matchMedia("(max-width: 900px)").matches,
  );
  const sidebarRef = useRef(null);
  const sidebarToggleRef = useRef(null);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const resize = () => {
      setMobileSidebar(media.matches);
      setSidebarOpen(!media.matches);
    };
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);
  useEffect(() => {
    if (!mobileSidebar || !sidebarOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => [
      ...sidebarRef.current.querySelectorAll("a[href], button"),
    ];
    focusable()[0]?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setSidebarOpen(false);
      }
      if (event.key === "Tab") {
        const items = focusable(),
          first = items[0],
          last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
      sidebarToggleRef.current?.focus();
    };
  }, [mobileSidebar, sidebarOpen]);
  const [modal, setModal] = useState(null);
  const [toast, setToast] = useState("");
  const [query, setQuery] = useState("");
  const [notifications, setNotifications] = useState(false);
  useEffect(() => {
    const onHash = () => {
      setRoute(location.hash.slice(1) || "/");
      setQuery("");
      setNotifications(false);
      window.scrollTo(0, 0);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 4000);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    const check = () => {
      const now = Date.now();
      for (const task of data.tasks) {
        if (!task.completed && task.reminder) {
          const at = new Date(task.reminder).getTime();
          const key = task.id + task.reminder;
          if (at <= now && !reminded.current.has(key)) {
            reminded.current.add(key);
            setToast(`Reminder: ${task.title}`);
            break;
          }
        }
      }
    };
    check();
    const interval = setInterval(check, 15000);
    return () => clearInterval(interval);
  }, [data.tasks]);
  const notify = (message) => setToast(message);
  const openLead = (record = null) => setModal({ type: "lead", record });
  const openTask = (relatedId = "", relatedType = "leads") =>
    setModal({ type: "task", relatedId, relatedType });
  const toggleTask = async (taskId) => {
    try {
      await run("completeTask", taskId);
    } catch (err) {
      notify(err.message);
    }
  };
  const convert = (leadId) =>
    setModal({
      type: "convert",
      record: data.leads.find((lead) => lead.id === leadId),
    });
  const searchResults = query.trim()
    ? ["leads", "opportunities"]
        .flatMap((type) =>
          data[type]
            .filter((x) =>
              `${x.name} ${x.company} ${x.email}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((x) => ({ ...x, type })),
        )
        .slice(0, 6)
    : [];
  return (
    <div
      className={`app-shell ${sidebarOpen ? "sidebar-expanded" : "sidebar-collapsed"}`}
    >
      {mobileSidebar && sidebarOpen && (
        <button
          className="sidebar-backdrop"
          aria-label="Close sidebar"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        id="crm-sidebar"
        ref={sidebarRef}
        className="sidebar"
        aria-label="Main navigation"
        inert={mobileSidebar && !sidebarOpen ? true : undefined}
        role={mobileSidebar && sidebarOpen ? "dialog" : undefined}
        aria-modal={mobileSidebar && sidebarOpen ? true : undefined}
      >
        <div className="sidebar-header">
          <a
            className="brand"
            href="#/"
            aria-label="SalesTrack home"
            onClick={() => {
              if (mobileSidebar) setSidebarOpen(false);
            }}
          >
            <span className="brand-mark">
              <Icon name="leaf" size={22} />
            </span>
            <span className="brand-name sidebar-label">SalesTrack</span>
          </a>
          {mobileSidebar && (
            <button
              className="icon-button sidebar-close"
              aria-label="Close sidebar"
              onClick={() => setSidebarOpen(false)}
            >
              <Icon name="close" />
            </button>
          )}
        </div>
        <span className="sidebar-section-label">WORKSPACE</span>
        <nav aria-label="Primary">
          {[
            ["home", "Home", "home", "/"],
            ["leads", "Leads", "users", "/leads"],
            ["opportunities", "Opportunities", "briefcase", "/opportunities"],
            ["tasks", "Tasks", "tasks", "/tasks"],
          ].map(([key, label, icon, path]) => (
            <a
              href={`#${path}`}
              key={key}
              className={section === key ? "active" : ""}
              aria-current={section === key ? "page" : undefined}
              aria-label={label}
              title={!sidebarOpen && !mobileSidebar ? label : undefined}
              onClick={() => {
                if (mobileSidebar) setSidebarOpen(false);
              }}
            >
              <Icon name={icon} />
              <span className="sidebar-label">{label}</span>
              {key === "tasks" &&
                data.tasks.some((task) => !task.completed) && (
                  <span className="nav-count">
                    {data.tasks.filter((t) => !t.completed).length}
                  </span>
                )}
            </a>
          ))}
        </nav>
      </aside>
      <div className="app-content">
        <header className="topbar">
          <button
            ref={sidebarToggleRef}
            className="icon-button sidebar-toggle"
            aria-controls="crm-sidebar"
            aria-expanded={sidebarOpen}
            aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            onClick={() => setSidebarOpen((open) => !open)}
          >
            <Icon
              name={sidebarOpen && !mobileSidebar ? "panel" : "menu"}
              size={21}
            />
          </button>
          <div className="top-actions">
            <div className="global-search">
              <Icon name="search" size={17} />
              <input
                aria-label="Search workspace"
                placeholder="Search anything…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <kbd>⌕</kbd>
              {query && (
                <div className="search-results">
                  {searchResults.length ? (
                    searchResults.map((r) => (
                      <button
                        key={r.type + r.id}
                        onClick={() => {
                          go(`/${r.type}/${r.id}`);
                          setQuery("");
                        }}
                      >
                        <Avatar item={r} small />
                        <span>
                          <b>{r.name}</b>
                          <small>
                            {r.company} ·{" "}
                            {r.type === "leads" ? "Lead" : "Opportunity"}
                          </small>
                        </span>
                        <Icon name="arrow" size={16} />
                      </button>
                    ))
                  ) : (
                    <p>No matching contacts found.</p>
                  )}
                </div>
              )}
            </div>
            <div className="popover-wrap">
              <button
                className={`icon-button bell ${data.notifications.length ? "has-dot" : ""}`}
                aria-label="Notifications"
                onClick={() => {
                  setNotifications(!notifications);
                }}
              >
                <Icon name="bell" size={20} />
              </button>
              {notifications && (
                <div className="popover notifications">
                  <h3>Your reminders</h3>
                  <label className="field">
                    <span>Notification owner</span>
                    <select
                      aria-label="Notification owner"
                      value={notificationOwner}
                      onChange={(event) =>
                        setNotificationOwner(event.target.value)
                      }
                    >
                      <option value="">Select owner</option>
                      {data.users.map((user) => (
                        <option key={user.id} value={user.id}>
                          {user.full_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {data.notifications.map((item) => (
                    <button
                      key={item.id}
                      onClick={async () => {
                        try {
                          await run("readNotification", item.id);
                          go("/tasks");
                        } catch (err) {
                          notify(err.message);
                        }
                      }}
                    >
                      <Icon name="bell" />
                      <span>
                        <b>{item.title}</b>
                        <small>{item.message}</small>
                      </span>
                    </button>
                  ))}
                  {notificationOwner && !data.notifications.length && (
                    <p>No unread notifications.</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </header>
        <main>
          {apiError && (
            <div className="warning" role="alert">
              {apiError}{" "}
              <button
                className="button"
                onClick={() => reload().catch(() => {})}
              >
                Reload data
              </button>
            </div>
          )}
          {saving && (
            <div className="save-indicator" role="status">
              Saving…
            </div>
          )}
          {loading && !hasLoaded ? (
            <div className="empty" role="status">
              Loading workspace…
            </div>
          ) : !hasLoaded ? (
            <div className="empty">
              <h2>Workspace unavailable</h2>
              <p>Start the backend, then select Reload data.</p>
            </div>
          ) : (
            <>
              {section === "home" ? (
                <Dashboard
                  data={data}
                  openLead={openLead}
                  openTask={openTask}
                  toggleTask={toggleTask}
                />
              ) : ["leads", "opportunities"].includes(section) ? (
                id ? (
                  <Detail
                    key={section + id}
                    collection={section}
                    item={data[section].find((x) => x.id === id)}
                    data={data}
                    openLead={openLead}
                    openTask={openTask}
                    toggleTask={toggleTask}

                    convert={convert}
                    setModal={setModal}
                  />
                ) : (
                  <RecordList
                    key={section}
                    collection={section}
                    data={data}
                    openLead={openLead}
                    setModal={setModal}
                  />
                )
              ) : section === "tasks" ? (
                <TasksPage
                  data={data}
                  toggleTask={toggleTask}
                  openTask={openTask}
                  setModal={setModal}
                />
              ) : (
                <div className="empty">
                  <Icon name="search" size={32} />
                  <h2>Page not found</h2>
                  <a href="#/">Back to Home</a>
                </div>
              )}
            </>
          )}
        </main>
        {section !== "home" && (
          <footer>
            <span>
              <span className="footer-dot" /> A little clarity. A lot of
              possibility.
            </span>
            <span>
              SalesTrack <span className="footer-separator">/</span> Phase 1
              workspace
            </span>
          </footer>
        )}
      </div>
      {modal && (
        <Modal
          modal={modal}
          close={() => setModal(null)}
          data={data}
          run={run}
          notify={notify}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          <span>
            <Icon name="check" size={17} />
          </span>
          {toast}
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
function PageHeading({ eyebrow, title, subtitle, children }) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
function Dashboard({ data, openLead, openTask, toggleTask }) {
  const overview = salesOverview(data);
  const closedCount = overview.wonCount + overview.lostCount;
  const stats = [
    {
      label: "Total leads",
      value: overview.totalLeads,
      icon: "users",
      note: "Every lead in your workspace",
      href: "/leads",
    },
    {
      label: "Open opportunities",
      value: overview.openOpportunities,
      icon: "briefcase",
      note: "Deals currently in progress",
      href: "/opportunities",
    },
    {
      label: "Won deals",
      value: overview.wonCount,
      icon: "trend",
      note: "Opportunities closed as Won",
      href: null,
    },
    {
      label: "Tasks due today",
      value: overview.dueToday,
      icon: "tasks",
      note: "Follow-ups waiting for you",
      href: "/tasks",
    },
  ];
  return (
    <div className="sales-overview">
      <PageHeading
        eyebrow="SALESTRACK"
        title="Sales Overview"
        subtitle="Track your pipeline, plan your follow-ups, and keep every deal moving."
      >
        <button className="button" onClick={() => openTask()}>
          <Icon name="plus" size={16} />
          Add task
        </button>
        <button className="button primary" onClick={() => openLead()}>
          <Icon name="plus" size={16} />
          New lead
        </button>
      </PageHeading>
      <div className="overview-label">
        <span className="live-dot" />
        Your sales at a glance
        <span className="date-label">
          {new Date().toLocaleDateString("en-US", {
            timeZone: "America/Los_Angeles",
            weekday: "long",
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </span>
      </div>
      <div className="stats-grid">
        {stats.map((stat) => (
          <section className="card stat-card" key={stat.label}>
            <div className="stat-top">
              <span>{stat.label}</span>
              <span className="stat-icon">
                <Icon name={stat.icon} size={18} />
              </span>
            </div>
            <strong>{stat.value || ""}</strong>
            <div className="stat-foot">
              {stat.note}
              {stat.href && (
                <a
                  className="stat-open"
                  href={`#${stat.href}`}
                  aria-label={`View ${stat.label.toLowerCase()}`}
                >
                  <Icon name="arrow" size={14} />
                </a>
              )}
            </div>
          </section>
        ))}
      </div>
      <section className="card sales-pipeline">
        <div className="card-heading">
          <div>
            <h2>Sales pipeline</h2>
            <p>From first contact to a closed deal.</p>
          </div>
          {overview.activeCount > 0 && (
            <span className="pipeline-active">
              {overview.activeCount} active
            </span>
          )}
        </div>
        <div className="sales-stage-grid">
          {overview.stages.map(({ stage, count }, index) => {
            const content = (
              <>
                <span
                  className={`sales-stage-label stage-label-${stage.toLowerCase()}`}
                >
                  <i />
                  {stage}
                </span>
                <strong>{count || ""}</strong>
                <span className="sales-stage-unit">
                  {index < 3
                    ? "leads"
                    : index < 5
                      ? "opportunities"
                      : "closed deals"}
                </span>
              </>
            );
            return index < 5 ? (
              <a
                className="sales-stage"
                key={stage}
                href={`#/${index < 3 ? "leads" : "opportunities"}?stage=${stage}`}
                aria-label={
                  count
                    ? `${stage}: ${count}. View records.`
                    : `${stage}. View records.`
                }
              >
                {content}
              </a>
            ) : (
              <div className="sales-stage" key={stage}>
                {content}
              </div>
            );
          })}
        </div>
        <div className="pipeline-note">
          <Icon name={overview.activeCount ? "trend" : "users"} size={16} />
          <span>
            {overview.activeCount
              ? "Select an open stage to view its leads or opportunities."
              : "No active relationships. Add a lead to grow your pipeline."}
          </span>
          {!data.leads.length && (
            <button className="text-link" onClick={() => openLead()}>
              Add your first lead
              <Icon name="arrow" size={14} />
            </button>
          )}
        </div>
      </section>
      <div className="sales-details-grid">
        <section className="card sales-tasks">
          <div className="card-heading">
            <div>
              <h2>
                Today’s tasks{" "}
                {overview.todayTasks.length > 0 && (
                  <span className="count-pill">
                    {overview.todayTasks.length}
                  </span>
                )}
              </h2>
              <p>Open tasks due today and overdue follow-ups.</p>
            </div>
            <a className="text-link" href="#/tasks">
              View all tasks
              <Icon name="arrow" size={15} />
            </a>
          </div>
          {overview.todayTasks.length ? (
            <>
              <div className="today-task-list">
                {overview.todayTasks.slice(0, 5).map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    data={data}
                    toggleTask={toggleTask}
                    compact
                  />
                ))}
              </div>
              <div className="sales-card-foot">
                <Icon name="check" size={15} />
                {overview.todayTasks.length} open follow-ups due today or
                overdue
              </div>
            </>
          ) : (
            <div className="sales-empty">
              <span className="sales-empty-icon">
                <Icon name="calendar" size={25} />
              </span>
              <h3>No tasks due today</h3>
              <p>Plan your next follow-up or set a reminder.</p>
              <button className="button" onClick={() => openTask()}>
                <Icon name="plus" size={15} />
                Add task
              </button>
            </div>
          )}
        </section>
        <section className="card sales-results">
          <div className="card-heading">
            <div>
              <h2>Won vs Lost</h2>
              <p>A clear picture of your closed deals.</p>
            </div>
            <span className="stat-icon">
              <Icon name="target" size={18} />
            </span>
          </div>
          {closedCount ? (
            <>
              <div className="outcomes-body">
                <div
                  className="donut"
                  role="img"
                  aria-label={`${overview.wonCount} won, ${overview.lostCount} lost; ${overview.winRate}% win rate`}
                  style={{
                    background: `conic-gradient(#35775b 0 ${overview.winRate}%, #dfc7ac ${overview.winRate}% 100%)`,
                  }}
                >
                  <div>
                    <strong>{overview.winRate}%</strong>
                    <span>win rate</span>
                  </div>
                </div>
                <div className="outcome-details">
                  {[
                    ["Won", overview.wonCount, overview.wonValue, "green"],
                    ["Lost", overview.lostCount, overview.lostValue, "tan"],
                  ].map(([label, count, value, color]) => (
                    <div key={label}>
                      <span>
                        <i className={`tiny-dot ${color}`} />
                        {label}
                      </span>
                      <b>
                        {count || ""}
                        <small>{count ? money(value) : ""}</small>
                      </b>
                    </div>
                  ))}
                </div>
              </div>
              <div className="sales-card-foot">
                <Icon name="briefcase" size={15} />
                {closedCount} closed {closedCount === 1 ? "deal" : "deals"}{" "}
                across your workspace
              </div>
            </>
          ) : (
            <div className="sales-empty">
              <span className="sales-empty-icon">
                <Icon name="trend" size={25} />
              </span>
              <h3>Your results will appear here</h3>
              <p>
                Close an opportunity or mark a lead as Lost
                <br />
                to see how your sales are progressing.
              </p>
              <div className="sales-results-key">
                <span>
                  <i className="tiny-dot green" />
                  Won
                </span>
                <span>
                  <i className="tiny-dot tan" />
                  Lost
                </span>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function RecordTable({ records, collection, compact = false }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{collection === "leads" ? "Name" : "Opportunity / account"}</th>
            {!compact && <th>Email</th>}
            <th>Stage</th>
            <th>{collection === "leads" ? "Source" : "Deal value"}</th>
            {!compact && (
              <th>{collection === "leads" ? "Owner" : "Close date"}</th>
            )}
            <th>
              <span className="sr-only">Open record</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={r.id}>
              <td>
                <a className="contact-cell" href={`#/${collection}/${r.id}`}>
                  <Avatar item={r} />
                  <span>
                    <b>{r.name}</b>
                    <small>{r.company}</small>
                  </span>
                </a>
              </td>
              {!compact && (
                <td>
                  <span className="muted">{r.email}</span>
                </td>
              )}
              <td>
                <Badge stage={r.stage} />
              </td>
              <td>
                {collection === "leads" ? (
                  <span className="muted">{r.source}</span>
                ) : (
                  money(r.value)
                )}
              </td>
              {!compact && (
                <td>
                  {collection === "leads"
                    ? r.owner || "Unassigned"
                    : fmtDate(r.closeDate)}
                </td>
              )}
              <td>
                <a
                  className="row-arrow"
                  href={`#/${collection}/${r.id}`}
                  aria-label={`View ${r.name}`}
                >
                  <Icon name="arrow" size={16} />
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!records.length && (
        <div className="empty">
          <Icon name="users" size={30} />
          <h3>No records to show</h3>
          <p>Try a different filter or add your first lead.</p>
        </div>
      )}
    </div>
  );
}
function RecordList({ collection, data, openLead, setModal }) {
  const initial =
    new URLSearchParams(location.hash.split("?")[1]).get("stage") || "All";
  const [stage, setStage] = useState(initial),
    [search, setSearch] = useState(""),
    [source, setSource] = useState("All"),
    [sort, setSort] = useState("recent");
  const lead = collection === "leads";
  const records = data[collection]
    .filter(
      (x) =>
        (stage === "All" || x.stage === stage) &&
        (source === "All" || x.source === source) &&
        `${x.name} ${x.company} ${x.email}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : sort === "value"
          ? (b.value ?? 0) - (a.value ?? 0)
          : b.created.localeCompare(a.created),
    );
  const stages = lead ? LEAD_STAGES : OPPORTUNITY_STAGES;
  const download = () => {
    const quote = (x) => '"' + String(x ?? "").replaceAll('"', '""') + '"';
    const columns = lead
      ? [
          ["Name", "name"],
          ["Company", "company"],
          ["Email", "email"],
          ["Stage", "stage"],
          ["Source", "source"],
          ["Owner", "owner"],
        ]
      : [
          ["Opportunity", "name"],
          ["Account", "company"],
          ["Stage", "stage"],
          ["Expected value", "expected_value"],
          ["Final value", "final_value"],
          ["Probability", "probability"],
          ["Expected close", "expected_close_date"],
          ["Owner", "owner"],
        ];
    const csv = [
      columns.map(([label]) => label),
      ...records.map((record) => columns.map(([, key]) => record[key])),
    ]
      .map((row) => row.map(quote).join(","))
      .join("\r\n");
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8;" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `crm-${collection}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <>
      <PageHeading
        eyebrow="MAKE EVERY CONNECTION COUNT"
        title={
          lead
            ? "Your next great relationships."
            : "Possibility, in the pipeline."
        }
        subtitle={
          lead
            ? "A home for every hello. Nurture your leads into something more."
            : "Keep your deals moving, from opportunity to a well-earned win."
        }
      >
        <button className="button" onClick={download}>
          <Icon name="download" size={17} />
          Export
        </button>
        <button
          className="button primary"
          onClick={() => (lead ? openLead() : go("/leads"))}
        >
          <Icon name="plus" size={17} />
          {lead ? "New lead" : "Convert a lead"}
        </button>
      </PageHeading>
      <div className="list-summary">
        <span>
          <Icon name={lead ? "users" : "briefcase"} size={18} />
          <b>{data[collection].length}</b> total {collection}
        </span>
        <span>
          <span className="live-dot" />
          {
            data[collection].filter(
              (r) => !["Won", "Lost", "Converted"].includes(r.stage),
            ).length
          }{" "}
          active
        </span>
      </div>
      <section className="card list-card">
        <div className="stage-tabs">
          <button
            className={stage === "All" ? "selected" : ""}
            onClick={() => setStage("All")}
          >
            All {collection}
            <span>{data[collection].length}</span>
          </button>
          {stages.map((s) => (
            <button
              key={s}
              className={stage === s ? "selected" : ""}
              onClick={() => setStage(s)}
            >
              {s}
              <span>
                {data[collection].filter((x) => x.stage === s).length}
              </span>
            </button>
          ))}
        </div>
        <div className="list-toolbar">
          <div className="input-search">
            <Icon name="search" size={17} />
            <input
              aria-label={`Search ${collection}`}
              placeholder={`Search ${collection}…`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="toolbar-filters">
            {lead && (
              <label className="select-control">
                <Icon name="filter" size={16} />
                <select
                  aria-label="Filter by source"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="All">All sources</option>
                  {LEAD_SOURCES.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
            )}
            <select
              className="sort-select"
              aria-label="Sort records"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="recent">Recently added</option>
              <option value="name">Name A–Z</option>
              {!lead && <option value="value">Highest expected value</option>}
            </select>
          </div>
        </div>
        <RecordTable records={records} collection={collection} />
        <div className="table-footer">
          <span>
            Showing {records.length} of {data[collection].length} {collection}
          </span>
          <span>Every relationship has a story.</span>
        </div>
      </section>
    </>
  );
}
function TaskRow({ task, data, toggleTask, compact = false, setModal }) {
  const related = data[task.relatedType]?.find((x) => x.id === task.relatedId);
  return (
    <div className={`task-row ${task.completed ? "completed" : ""}`}>
      <button
        className="task-check"
        aria-label={
          task.completed
            ? `${task.status}: ${task.title}`
            : `Mark complete: ${task.title}`
        }
        aria-pressed={task.completed}
        disabled={task.completed}
        onClick={() => toggleTask(task.id)}
      >
        {task.completed && <Icon name="check" size={13} />}
      </button>
      <div className="task-content">
        <b>{task.title}</b>
        {!compact && task.description && <p>{task.description}</p>}
        <div className="task-meta">
          {related && (
            <a href={`#/${task.relatedType}/${related.id}`}>
              {related.company}
            </a>
          )}
          {task.reminder && (
            <span>
              <Icon name="bell" size={12} />
              {new Date(task.reminder).toLocaleString("en-US", {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              })}
            </span>
          )}
          {task.is_auto && <span className="subtle-pill">Automatic</span>}
          {compact && task.completed && <span>{task.status}</span>}
          {compact && (
            <span className={`priority-dot ${task.priority.toLowerCase()}`}>
              {task.priority}
            </span>
          )}
        </div>
      </div>
      {!compact && (
        <>
          <span className={`priority-label ${task.priority.toLowerCase()}`}>
            <i />
            {task.priority}
          </span>
          <span
            className={`due-label ${!task.completed && task.isOverdue ? "overdue" : ""}`}
          >
            <Icon name="calendar" size={14} />
            {task.due === dateKey() ? "Today" : fmtDate(task.due)}
            {!task.completed && task.isOverdue && <small>Overdue</small>}
          </span>
          <span className={`status-label ${task.completed ? "done" : ""}`}>
            {task.status}
          </span>
          <button
            className="icon-button"
            onClick={() => setModal({ type: "task", record: task })}
            aria-label={`Edit ${task.title}`}
          >
            <Icon name="edit" size={16} />
          </button>
        </>
      )}
      {compact && (
        <span
          className={`task-time ${!task.completed && task.isOverdue ? "overdue" : ""}`}
        >
          {task.due === dateKey() ? "Today" : fmtDate(task.due)}
        </span>
      )}
    </div>
  );
}
function TasksPage({ data, toggleTask, openTask, setModal }) {
  const [filter, setFilter] = useState("All"),
    [search, setSearch] = useState("");
  const tasks = data.tasks
    .filter(
      (t) =>
        (filter === "All" ||
          (filter === "Today" &&
            data.home?.todays_tasks?.some(
              (task) => String(task.id) === t.id && !task.is_overdue,
            )) ||
          (filter === "Overdue" && !t.completed && t.isOverdue) ||
          (filter === "Upcoming" &&
            !t.completed &&
            !t.isOverdue &&
            !data.home?.todays_tasks?.some(
              (task) => String(task.id) === t.id,
            )) ||
          (filter === "Done" && t.status === "Done") ||
          (filter === "Auto-closed" && t.status === "Auto-closed")) &&
        t.title.toLowerCase().includes(search.toLowerCase()),
    )
    .sort(
      (a, b) =>
        Number(a.completed) - Number(b.completed) || a.due.localeCompare(b.due),
    );
  return (
    <>
      <PageHeading
        eyebrow="A LITTLE FOLLOW-THROUGH GOES A LONG WAY"
        title="Good relationships take care."
        subtitle="Your follow-ups, reminders, and next little steps. All in one place."
      >
        <button className="button primary" onClick={() => openTask()}>
          <Icon name="plus" size={17} />
          New task
        </button>
      </PageHeading>
      <div className="task-stats">
        {[
          ["To do", data.tasks.filter((t) => !t.completed).length, "tasks"],
          [
            "Due today",
            data.tasks.filter(
              (t) =>
                !t.completed &&
                data.home?.todays_tasks?.some(
                  (task) => String(task.id) === t.id && !task.is_overdue,
                ),
            ).length,
            "calendar",
          ],
          [
            "Overdue",
            data.tasks.filter((t) => !t.completed && t.isOverdue).length,
            "clock",
          ],
          [
            "Done",
            data.tasks.filter((t) => t.status === "Done").length,
            "check",
          ],
        ].map(([label, count, icon]) => (
          <div className="card" key={label}>
            <span className="stat-icon">
              <Icon name={icon} />
            </span>
            <div>
              <b>{count || ""}</b>
              <span>{label}</span>
            </div>
          </div>
        ))}
      </div>
      <section className="card list-card">
        <div className="stage-tabs">
          {["All", "Today", "Overdue", "Upcoming", "Done", "Auto-closed"].map(
            (f) => (
              <button
                key={f}
                className={filter === f ? "selected" : ""}
                onClick={() => setFilter(f)}
              >
                {f === "All" ? "All tasks" : f}
              </button>
            ),
          )}
        </div>
        <div className="list-toolbar">
          <div className="input-search">
            <Icon name="search" size={17} />
            <input
              placeholder="Find a task…"
              aria-label="Search tasks"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <span className="muted">
            {tasks.length ? `${tasks.length} tasks · ` : ""}Due date order
          </span>
        </div>
        <div className="full-tasks">
          {tasks.map((t) => (
            <TaskRow
              key={t.id}
              task={t}
              data={data}
              toggleTask={toggleTask}
              setModal={setModal}
            />
          ))}
          {!tasks.length && (
            <div className="empty">
              <Icon name="check" size={32} />
              <h3>A little breathing room.</h3>
              <p>No tasks match this view.</p>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
function Detail({
  collection,
  item,
  data,
  openLead,
  openTask,
  toggleTask,
  convert,
  setModal,
}) {
  if (!item)
    return (
      <div className="empty">
        <h2>We couldn’t find that record.</h2>
        <a href={`#/${collection}`}>Back to {collection}</a>
      </div>
    );
  const lead = collection === "leads",
    closed = ["Won", "Lost", "Converted"].includes(item.stage);
  const stages = lead
    ? ["New", "Nurturing", "Demo", "Converted"]
    : ["Opportunity", "Proposal", "Won"];
  const tasks = data.tasks.filter(
    (t) => t.relatedId === item.id && t.relatedType === collection,
  );
  const convertedTo =
    lead && data.opportunities.find((o) => o.leadId === item.id);
  return (
    <>
      <a className="breadcrumb" href={`#/${collection}`}>
        <Icon name="arrow" size={15} />
        Back to {collection}
      </a>
      <div className="detail-heading">
        <div className="detail-person">
          <Avatar item={item} />
          <div>
            <div className="detail-name">
              <h1>{item.name}</h1>
              <Badge stage={item.stage} />
            </div>
            <p>
              {item.role} <span>at</span> {item.company}
            </p>
          </div>
        </div>
        <div className="heading-actions">
          <button
            className="button"
            onClick={() =>
              lead
                ? openLead(item)
                : setModal({ type: "opportunity", record: item })
            }
          >
            <Icon name="edit" size={16} />
            Edit {lead ? "lead" : "opportunity"}
          </button>
          {!closed && (
            <>
              <button
                className="button danger-outline"
                onClick={() =>
                  setModal({ type: "lost", collection, record: item })
                }
              >
                Mark as lost
              </button>
              {!lead && (
                <button
                  className="button"
                  onClick={() => setModal({ type: "won", record: item })}
                >
                  <Icon name="check" size={16} />
                  Mark as won
                </button>
              )}
              {lead && (
                <button
                  className="button primary"
                  onClick={() => convert(item.id)}
                >
                  Convert lead
                  <Icon name="arrow" size={16} />
                </button>
              )}
            </>
          )}
          {convertedTo && (
            <a
              className="button primary"
              href={`#/opportunities/${convertedTo.id}`}
            >
              View opportunity
              <Icon name="arrow" size={16} />
            </a>
          )}
        </div>
      </div>
      <section className="card stage-card">
        <div className="stage-card-top">
          <h2>{lead ? "Lead journey" : "Opportunity journey"}</h2>
          <span>
            {closed
              ? "Journey complete"
              : "Select a stage to update this relationship"}
          </span>
        </div>
        <div className="journey">
          {stages.map((s, i) => (
            <button
              key={s}
              disabled={closed || item.stage === s}
              className={`${item.stage === s ? "current" : ""} ${stages.indexOf(item.stage) > i ? "past" : ""}`}
              onClick={() =>
                s === "Converted"
                  ? convert(item.id)
                  : setModal({
                      type: s === "Won" ? "won" : "stage",
                      collection,
                      record: item,
                      stage: s,
                    })
              }
            >
              <span>
                {stages.indexOf(item.stage) > i ? (
                  <Icon name="check" size={14} />
                ) : (
                  i + 1
                )}
              </span>
              {s}
              {i < stages.length - 1 && <Icon name="chevron" size={16} />}
            </button>
          ))}
          {["Won", "Lost"].includes(item.stage) &&
            !stages.includes(item.stage) && (
              <div className="lost-journey">
                <Badge stage={item.stage} />
              </div>
            )}
        </div>
        {item.stage === "Lost" && (
          <div className="loss-reason">
            <b>Lost reason:</b> {item.lossReason}
            {item.lost_notes && <p>{item.lost_notes}</p>}
          </div>
        )}
      </section>
      <div className="detail-grid">
        <div className="detail-main">
          <section className="card">
            <div className="card-heading">
              <div>
                <h2>Relationship details</h2>
                <p>The person behind the possibility.</p>
              </div>
              <Icon name="users" />
            </div>
            <div className="detail-fields">
              {[
                ["mail", "Email", item.email || "Not provided"],
                ["phone", "Phone", item.phone || "Not provided"],
                ["building", lead ? "Company" : "Account", item.company],
                ...(lead
                  ? [
                      ["flag", "Lead source", item.source],
                      ...(item.demo_date
                        ? [
                            [
                              "calendar",
                              "Demo date",
                              new Date(item.demo_date).toLocaleString(),
                            ],
                          ]
                        : []),
                    ]
                  : []),
                ...(lead
                  ? [["building", "Industry", item.industry || "Not provided"]]
                  : [
                      [
                        "briefcase",
                        "Expected value",
                        money(item.expected_value),
                      ],
                      ["target", "Probability", `${item.probability}%`],
                      [
                        "users",
                        "Primary contact",
                        item.primary_contact_name || "Not provided",
                      ],
                      ...(item.stage === "Won"
                        ? [
                            [
                              "briefcase",
                              "Final value",
                              money(item.final_value),
                            ],
                          ]
                        : []),
                    ]),
                [
                  "calendar",
                  lead ? "Added on" : "Expected close",
                  fmtDate(lead ? item.created : item.closeDate),
                ],
              ].map(([icon, label, value]) => (
                <div key={label}>
                  <Icon name={icon} size={17} />
                  <div>
                    <span>{label}</span>
                    <b>{value}</b>
                  </div>
                </div>
              ))}
            </div>
            <div className="notes-section">
              <div className="notes-heading">
                <h3>Notes</h3>
                <button
                  className="button"
                  onClick={() =>
                    setModal({ type: "note", collection, record: item })
                  }
                >
                  <Icon name="plus" size={14} />
                  Add note
                </button>
              </div>
              {item.notes.length ? (
                item.notes.map((note) => (
                  <div className="record-note" key={note.id}>
                    <p>{note.body}</p>
                    <small>
                      {note.created_by_name} ·{" "}
                      {new Date(note.created_at).toLocaleString()}
                    </small>
                  </div>
                ))
              ) : (
                <p>No notes yet.</p>
              )}
            </div>
          </section>
          <section className="card linked-tasks">
            <div className="card-heading">
              <div>
                <h2>
                  Follow-ups & tasks{" "}
                  {tasks.length > 0 && (
                    <span className="count-pill">{tasks.length}</span>
                  )}
                </h2>
                <p>A thoughtful next step makes all the difference.</p>
              </div>
              <button
                className="button"
                onClick={() => openTask(item.id, collection)}
              >
                <Icon name="plus" size={16} />
                Add task
              </button>
            </div>
            {tasks.map((t) => (
              <TaskRow
                key={t.id}
                task={t}
                data={data}
                toggleTask={toggleTask}
                compact
              />
            ))}
            {!tasks.length && (
              <div className="empty small-empty">
                <Icon name="tasks" size={24} />
                <p>No tasks yet. Plan your next follow-up.</p>
              </div>
            )}
          </section>
        </div>
        <aside>
          <section className="card owner-card">
            <div className="card-heading">
              <h2>Relationship owner</h2>
            </div>
            <div className="owner">
              <span className="stat-icon">
                <Icon name="users" size={18} />
              </span>
              <div>
                <b>{item.owner || "Unassigned"}</b>
              </div>
            </div>
          </section>
          <section className="card activity-card">
            <div className="card-heading">
              <h2>Activity timeline</h2>
              <Icon name="clock" size={17} />
            </div>
            <div className="timeline">
              {item.activity.map((a, i) => (
                <div className="timeline-item" key={i}>
                  <span className="timeline-dot">
                    <Icon name={i === 0 ? "check" : "plus"} size={12} />
                  </span>
                  <div>
                    <p>{a.text}</p>
                    <small>
                      {a.by && `${a.by} · `}
                      {new Date(a.date).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}
function Modal({ modal, close, data, run, notify }) {
  const ref = useRef(null),
    previousFocus = useRef(document.activeElement),
    lock = useRef(false);
  const [error, setError] = useState(""),
    [submitting, setSubmitting] = useState(false);
  const record = modal.record;
  const type = modal.type;
  const [relatedType, setRelatedType] = useState(
    record?.relatedType || modal.relatedType || "general",
  );
  const titles = {
    lead: record ? "Edit lead" : "New lead",
    opportunity: "Edit opportunity",
    task: record ? "Edit task" : "New task",
    lost: "Mark as lost",
    won: "Mark as won",
    convert: "Convert lead",
    stage: `Move to ${modal.stage}`,
    note: "Add note",
  };
  useEffect(() => {
    const first = ref.current.querySelector("input,select,textarea,button");
    first?.focus();
    const key = (event) => {
      if (event.key === "Escape" && !lock.current) close();
      if (event.key === "Tab") {
        const items = [
          ...ref.current.querySelectorAll("input,select,textarea,button"),
        ].filter((el) => !el.disabled);
        if (event.shiftKey && document.activeElement === items[0]) {
          event.preventDefault();
          items.at(-1).focus();
        } else if (!event.shiftKey && document.activeElement === items.at(-1)) {
          event.preventDefault();
          items[0].focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
      previousFocus.current?.focus();
    };
  }, []);
  const field = (
    label,
    name,
    inputType = "text",
    required = false,
    value = record?.[name] ?? "",
  ) => (
    <label className="field">
      <span>
        {label}
        {required && <i> *</i>}
      </span>
      <input
        name={name}
        type={inputType}
        required={required}
        defaultValue={value}
        min={inputType === "number" ? 0 : undefined}
        max={name === "probability" ? 100 : undefined}
        step={
          name === "probability"
            ? 1
            : inputType === "number"
              ? "any"
              : undefined
        }
        maxLength={
          ["first_name", "last_name"].includes(name)
            ? 50
            : name === "company"
              ? 200
              : undefined
        }
      />
    </label>
  );
  const textArea = (label, name, value = "") => (
    <label className="field">
      <span>{label}</span>
      <textarea name={name} rows={3} defaultValue={value} />
    </label>
  );
  const select = (
    label,
    name,
    options,
    value = record?.[name] ?? "",
    required = false,
  ) => (
    <label className="field">
      <span>
        {label}
        {required && <i> *</i>}
      </span>
      <select name={name} defaultValue={value} required={required}>
        <option value="">
          {required ? "Select an option" : "Default / not specified"}
        </option>
        {options.map((option) => {
          const [id, label] = Array.isArray(option) ? option : [option, option];
          return (
            <option key={id} value={id}>
              {label}
            </option>
          );
        })}
      </select>
    </label>
  );
  const owner = () =>
    select("Owner", "owner_id", [
      ...data.users.map((user) => [user.id, user.full_name]),
      ...(record?.owner_id &&
      !data.users.some((user) => user.id === record.owner_id)
        ? [[record.owner_id, record.owner || "Current owner"]]
        : []),
    ]);
  const submit = async (event) => {
    event.preventDefault();
    if (lock.current) return;
    lock.current = true;
    setSubmitting(true);
    setError("");
    const v = Object.fromEntries(new FormData(event.target));
    try {
      let saved;
      if (type === "lead") {
        if (!v.last_name.trim() || !v.company.trim())
          throw new Error("Last name and company are required.");
        saved = await run("saveLead", v, record?.id);
      }
      if (type === "opportunity")
        saved = await run("saveOpportunity", v, record.id);
      if (type === "task") {
        if (!v.title.trim()) throw new Error("Task title is required.");
        saved = await run("saveTask", v, record?.id);
      }
      if (type === "lost")
        await run("lost", modal.collection, record.id, {
          lost_reason: v.lost_reason,
          lost_notes: v.lost_notes || null,
        });
      if (type === "won")
        await run("won", record.id, {
          final_value: v.final_value === "" ? null : Number(v.final_value),
          note: v.note || null,
        });
      if (type === "convert")
        saved = await run("convert", record.id, {
          opportunity_name: v.opportunity_name || null,
          expected_value:
            v.expected_value === "" ? null : Number(v.expected_value),
          expected_close_date: v.expected_close_date || null,
          account_id: v.account_id ? Number(v.account_id) : null,
        });
      if (type === "stage")
        await run("stage", modal.collection, record.id, {
          stage: modal.stage,
          note: v.note || null,
          ...(modal.collection === "leads" && modal.stage === "Demo"
            ? { demo_date: v.demo_date || null }
            : {}),
        });
      if (type === "note") {
        if (!v.body.trim()) throw new Error("Note cannot be blank.");
        await run("note", modal.collection, record.id, v.body.trim());
      }
      close();
      notify(
        type === "convert"
          ? "Lead converted. Account, contact, opportunity, and follow-up created."
          : "Saved successfully",
      );
      if (type === "lead") go(`/leads/${saved.id}`);
      if (type === "convert") go(`/opportunities/${saved.opportunity.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      lock.current = false;
      setSubmitting(false);
    }
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !submitting) close();
      }}
    >
      <section
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="modal-heading">
          <span className="modal-symbol">
            <Icon name={type === "task" ? "tasks" : "edit"} size={22} />
          </span>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={close}
            disabled={submitting}
          >
            <Icon name="close" />
          </button>
        </div>
        <h2 id="modal-title">{titles[type]}</h2>
        <p className="modal-subtitle">
          {type === "convert"
            ? "Create an opportunity and contact. Existing lead follow-ups will be auto-closed."
            : type === "stage"
              ? "Open follow-ups will be auto-closed and the next follow-up will be created."
              : "Fields marked with * are required."}
        </p>
        <form onSubmit={submit}>
          {type === "lead" && (
            <div className="form-grid">
              {select("Salutation", "salutation", SALUTATIONS)}
              {field("First name", "first_name")}
              {field("Last name", "last_name", "text", true)}
              {field("Company", "company", "text", true)}
              {field("Job title", "title")}
              {field("Industry", "industry")}
              {field("Email", "email", "email")}
              {field("Phone", "phone", "tel")}
              {select(
                "Lead source",
                "source",
                LEAD_SOURCES,
                record?.source || "Other",
                true,
              )}
              {owner()}
              {record &&
                field(
                  "Demo date",
                  "demo_date",
                  "datetime-local",
                  false,
                  localInput(record.demo_date),
                )}
            </div>
          )}
          {type === "opportunity" && (
            <div className="form-grid">
              {field("Opportunity name", "name", "text", true)}
              {field("Expected value", "expected_value", "number")}
              {field("Expected close date", "expected_close_date", "date")}
              {field("Probability (%)", "probability", "number", true)}
              {select(
                "Primary contact",
                "primary_contact_id",
                data.contacts
                  .filter((contact) => contact.account_id === record.account_id)
                  .map((contact) => [contact.id, contact.full_name]),
              )}
              {owner()}
            </div>
          )}
          {type === "task" && (
            <>
              <div className="form-grid">
                {field("Task title", "title", "text", true)}
                {field(
                  "Due date and time",
                  "due_date",
                  "datetime-local",
                  true,
                  localInput(record?.due_date),
                )}
                {select(
                  "Priority",
                  "priority",
                  PRIORITIES,
                  record?.priority || "Normal",
                  true,
                )}
                {owner()}
                {field(
                  "Reminder",
                  "reminder_at",
                  "datetime-local",
                  false,
                  localInput(record?.reminder_at),
                )}
                {!record ? (
                  <>
                    <label className="field">
                      <span>Related to</span>
                      <select
                        name="relatedType"
                        value={relatedType}
                        onChange={(event) => setRelatedType(event.target.value)}
                      >
                        <option value="general">General task</option>
                        <option value="leads">Lead</option>
                        <option value="opportunities">Opportunity</option>
                      </select>
                    </label>
                    {relatedType !== "general" && (
                      <label className="field">
                        <span>
                          Record <i>*</i>
                        </span>
                        <select
                          name="relatedId"
                          required
                          key={relatedType}
                          defaultValue={
                            modal.relatedType === relatedType
                              ? modal.relatedId
                              : ""
                          }
                        >
                          <option value="">Select a record</option>
                          {data[relatedType].map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </>
                ) : (
                  <label className="field">
                    <span>Related record</span>
                    <input
                      readOnly
                      value={record.related_to || "General task"}
                    />
                  </label>
                )}
              </div>
              {textArea(
                "Description",
                "description",
                record?.description || "",
              )}
            </>
          )}
          {type === "lost" && (
            <>
              {select("Lost reason", "lost_reason", LOST_REASONS, "", true)}
              {textArea("Additional details", "lost_notes")}
            </>
          )}
          {type === "won" && (
            <>
              {field(
                "Final value",
                "final_value",
                "number",
                record.expected_value == null,
                record.expected_value ?? "",
              )}
              {textArea("Closing note", "note")}
            </>
          )}
          {type === "convert" && (
            <>
              <div className="form-grid">
                {field("Opportunity name", "opportunity_name")}
                {field("Expected value", "expected_value", "number")}
                {field("Expected close date", "expected_close_date", "date")}
                <label className="field">
                  <span>Account</span>
                  <select name="account_id" defaultValue="">
                    <option value="">Create account from company</option>
                    {data.accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </>
          )}
          {type === "stage" && (
            <>
              {modal.stage === "Demo" &&
                field(
                  "Demo date and time",
                  "demo_date",
                  "datetime-local",
                  false,
                  localInput(record.demo_date),
                )}
              {textArea("Stage change note", "note")}
            </>
          )}
          {type === "note" && (
            <label className="field">
              <span>
                Note <i>*</i>
              </span>
              <textarea name="body" required rows={5} />
            </label>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-footer">
            <button
              type="button"
              className="button"
              onClick={close}
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button primary"
              disabled={submitting}
              aria-busy={submitting}
            >
              {submitting
                ? "Saving…"
                : type === "convert"
                  ? "Convert lead"
                  : type === "won"
                    ? "Mark as won"
                    : type === "lost"
                      ? "Mark as lost"
                      : "Save"}
              <Icon name="check" size={16} />
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
