import React, { useEffect, useState } from "react";
import { shortDate, shortDateTime } from "./format";
import { Icon, ObjectIcon, Pagination, usePaged } from "./ui";

const todayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// Task list views, like Salesforce: My Tasks, Today, Overdue, Completed...
function taskViews(user) {
  const mine = (t) => t.owner_id === user.id;
  const today = (t) => !t.completed && t.due === todayKey();
  return [
    ["My Open Tasks", (t) => mine(t) && !t.completed],
    ["Today", (t) => mine(t) && today(t)],
    ["Overdue", (t) => mine(t) && !t.completed && t.isOverdue],
    ["Completed", (t) => mine(t) && t.completed],
    ["All Open Tasks", (t) => !t.completed],
    ["All Tasks", () => true],
  ];
}

export default function TasksPage({ data, user, toggleTask, openTask, setModal, query }) {
  const views = taskViews(user);
  const params = new URLSearchParams(query);
  const initial = params.get("view") === "overdue" ? "Overdue" : params.get("task") ? "All Tasks" : "My Open Tasks";
  // ?task=ID (from a notification or search) opens that task
  useEffect(() => {
    const task = data.tasks.find((t) => t.id === params.get("task"));
    if (task) setModal({ type: "task", record: task });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [view, setView] = useState(initial);
  const [search, setSearch] = useState("");
  const filter = views.find(([name]) => name === view)[1];
  const rows = data.tasks
    .filter(filter)
    .filter((t) => !search.trim() || `${t.title} ${t.related_to || ""}`.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => Number(a.completed) - Number(b.completed) || a.due_date.localeCompare(b.due_date));
  const { pageRows, pager } = usePaged(rows, `${view}|${search}`);

  return (
    <div className="page">
      <section className="list-header card">
        <div className="list-title">
          <ObjectIcon type="task" size={36} />
          <div>
            <h1>{view}</h1>
          </div>
          <div className="list-buttons">
            <button className="sf-button" onClick={() => openTask()}>
              New Task
            </button>
          </div>
        </div>
        <div className="list-meta">
          <div className="view-tabs" role="tablist">
            {views.map(([name, fn]) => (
              <button key={name} role="tab" aria-selected={view === name} className={view === name ? "on" : ""} onClick={() => setView(name)}>
                {name} <span>{data.tasks.filter(fn).length}</span>
              </button>
            ))}
          </div>
          <label className="list-search">
            <Icon name="search" size={14} />
            <input placeholder="Search this list..." value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search tasks" />
          </label>
        </div>
      </section>
      <section className="card table-card">
        <div className="table-scroll">
          <table className="sf-table">
            <thead>
              <tr>
                <th className="rownum" aria-label="Complete" />
                <th>Subject</th>
                <th className="date">Due Date</th>
                <th>Related To</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Assigned To</th>
                <th className="date">Reminder</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((t) => (
                <tr key={t.id} className={t.completed ? "row-done" : ""}>
                  <td className="rownum">
                    <input
                      type="checkbox"
                      checked={t.completed}
                      disabled={t.completed}
                      onChange={() => toggleTask(t.id)}
                      aria-label={`Complete ${t.title}`}
                    />
                  </td>
                  <td>
                    <button className="link" onClick={() => setModal({ type: "task", record: t })}>
                      {t.title}
                    </button>
                    {t.is_auto && <span className="auto-tag">Automatic</span>}
                  </td>
                  <td className={`date ${!t.completed && t.isOverdue ? "overdue" : ""}`}>{shortDate(t.due_date)}</td>
                  <td>
                    {t.relatedType !== "general" ? (
                      <a href={`#/${t.relatedType}/${t.relatedId}`}>{t.related_to}</a>
                    ) : (
                      <span className="muted">General</span>
                    )}
                  </td>
                  <td className={t.priority === "High" ? "high" : ""}>{t.priority}</td>
                  <td>{t.status}</td>
                  <td>{t.owner}</td>
                  <td className="date">{shortDateTime(t.reminder_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <p className="table-empty">No tasks in this view.</p>}
        </div>
        <Pagination {...pager} />
      </section>
    </div>
  );
}
