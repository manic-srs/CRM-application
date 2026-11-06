import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { shortDate, shortDateTime } from "./format";
import { Icon, ObjectIcon, Pagination, usePaged } from "./ui";
import { applyFilters, filterSummary, opts, ownerOptions, TASK_DUE_RANGES, Th, useFilters } from "./Filters";
import { can } from "./permissions";
import { PRIORITIES } from "./domain";

const todayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// The list view picker under the page title ("All Tasks ▾"), like the other list pages
function taskViews(user, team) {
  const mine = (t) => t.owner_id === user.id;
  return [
    ["All Tasks", () => true],
    ["My Open Tasks", (t) => mine(t) && !t.completed],
    ["Today", (t) => mine(t) && !t.completed && t.due === todayKey()],
    ["Overdue", (t) => mine(t) && !t.completed && t.isOverdue],
    ["Completed", (t) => mine(t) && t.completed],
    ...(team ? [["All Open Tasks", (t) => !t.completed]] : []),
  ];
}

// A select-all checkbox that also shows the "some selected" dash
function Check({ checked, some = false, onChange, label }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some && !checked;
  }, [some, checked]);
  return <input ref={ref} type="checkbox" className="row-check" checked={checked} onChange={onChange} aria-label={label} />;
}

export default function TasksPage({ data, user, toggleTask, openTask, setModal, query, reload, notify }) {
  const params = new URLSearchParams(query);
  const team = can(user, "view_team_records");
  const fromLink = params.get("task") ? "task" : params.get("view") === "overdue" ? "overdue" : "";
  // ?task=ID (from a notification or search) opens that task
  useEffect(() => {
    const task = data.tasks.find((t) => t.id === params.get("task"));
    if (task) setModal({ type: "task", record: task });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const views = taskViews(user, team);
  const [view, setView] = useState(fromLink === "overdue" ? "Overdue" : "All Tasks");
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef(null);
  useEffect(() => {
    if (!pickerOpen) return undefined;
    const away = (e) => !pickerRef.current?.contains(e.target) && setPickerOpen(false);
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [pickerOpen]);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState(() => new Set());
  const [reassignTo, setReassignTo] = useState("");
  const [busy, setBusy] = useState(false);
  // One list; the column headers filter it: Status, Due Date, Priority, Type, Related To and (team) Assigned To
  const defs = [
    { key: "status", label: "Status", options: opts(["Open", "Done", "Auto-closed"]), get: (t) => t.status },
    { key: "due", label: "Due Date", type: "date", future: true, ranges: TASK_DUE_RANGES, get: (t) => t.due },
    { key: "priority", label: "Priority", options: opts(PRIORITIES), get: (t) => t.priority },
    { key: "kind", label: "Type", options: [["auto", "Automatic"], ["manual", "Manual"]], get: (t) => (t.is_auto ? "auto" : "manual") },
    { key: "related", label: "Related To", options: [["leads", "Lead"], ["opportunities", "Opportunity"], ["general", "General"]], get: (t) => t.relatedType },
    ...(team ? [{ key: "owner", label: "Assigned To", options: ownerOptions(data.users || [], user), get: (t) => String(t.owner_id) }] : []),
  ];
  const [stored, setStored] = useFilters("tasks");
  // a link to one task or an overdue reminder starts without leftover filters
  useEffect(() => {
    if (fromLink) setStored({});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const active = Object.fromEntries(
    Object.entries(stored).filter(([k, v]) => {
      const f = defs.find((d) => d.key === k.split("_")[0]);
      if (!f || !stored[f.key]) return false;
      if (f.type === "date") return k !== f.key || v === "custom" || f.ranges.some(([o]) => o === v);
      return !f.options || k !== f.key || f.options.some(([o]) => o === v);
    }),
  );
  const viewTest = views.find(([name]) => name === view)[1];
  const rows = applyFilters(data.tasks.filter(viewTest), defs, active)
    .filter((t) => !search.trim() || `${t.title} ${t.related_to || ""}`.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => Number(a.completed) - Number(b.completed) || a.due_date.localeCompare(b.due_date));
  const resetKey = `${view}|${search}|${JSON.stringify(active)}`;
  const { pageRows, pager } = usePaged(rows, resetKey);
  useEffect(() => setPicked(new Set()), [resetKey]);

  const selectable = (t) => !t.completed; // only open tasks are marked done or reassigned
  const pageIds = pageRows.filter(selectable).map((t) => t.id);
  const pageTicked = pageIds.filter((id) => picked.has(id)).length;
  const allOnPage = pageIds.length > 0 && pageTicked === pageIds.length;
  const togglePage = () =>
    setPicked((s) => {
      const next = new Set(s);
      pageIds.forEach((id) => (allOnPage ? next.delete(id) : next.add(id)));
      return next;
    });
  const toggleOne = (id) =>
    setPicked((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const openRows = rows.filter(selectable);
  const selectAllRows = () => setPicked(new Set(openRows.map((t) => t.id)));
  const canReassign = can(user, "reassign_owner");
  const people = (data.users || []).filter((u) => u.is_active !== false && u.role !== "Admin");

  const runBulk = async (action) => {
    setBusy(true);
    try {
      const result = await api.bulkTasks({
        ids: [...picked].map(Number),
        action,
        ...(action === "reassign" ? { owner_id: Number(reassignTo) } : {}),
      });
      const n = result.done.length;
      const who = action === "reassign" ? people.find((u) => String(u.id) === reassignTo)?.full_name : "";
      const doneText =
        action === "complete" ? `${n} task${n === 1 ? "" : "s"} marked as done.` : `${n} task${n === 1 ? "" : "s"} reassigned to ${who}.`;
      const skipped = result.skipped.length
        ? ` ${result.skipped.length} skipped: ${result.skipped
            .slice(0, 3)
            .map((s) => `${s.title} (${s.reason})`)
            .join(", ")}${result.skipped.length > 3 ? "…" : ""}`
        : "";
      notify?.(doneText + skipped);
      setPicked(new Set());
      setReassignTo("");
      await reload?.();
    } catch (err) {
      notify?.(err.message);
    } finally {
      setBusy(false);
    }
  };

  const count = picked.size;

  return (
    <div className="page">
      <section className="list-header card">
        <div className="list-title">
          <ObjectIcon type="task" size={36} />
          <div>
            <h1>Tasks</h1>
          </div>
          <div className="list-buttons task-actions">
            {count > 0 && (
              <>
                <span className="task-picked">
                  {count} selected
                  {count < openRows.length && allOnPage && (
                    <button className="link" onClick={selectAllRows}>
                      Select all {openRows.length}
                    </button>
                  )}
                  <button className="link" onClick={() => setPicked(new Set())}>
                    Clear
                  </button>
                </span>
                {canReassign && (
                  <select value={reassignTo} onChange={(e) => setReassignTo(e.target.value)} aria-label="Reassign to" className="task-reassign">
                    <option value="">Reassign to…</option>
                    {people.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.id === user.id ? `${u.full_name} (me)` : u.full_name}
                      </option>
                    ))}
                  </select>
                )}
                {canReassign && reassignTo && (
                  <button className="sf-button" disabled={busy} onClick={() => runBulk("reassign")}>
                    Reassign
                  </button>
                )}
              </>
            )}
            <button
              className="sf-button brand"
              disabled={busy || !count}
              onClick={() => runBulk("complete")}
              title={count ? `Mark the ${count} selected task${count === 1 ? "" : "s"} as done` : "Tick tasks in the list first"}
            >
              Mark as Done
            </button>
            <button className="sf-button" onClick={() => openTask()}>
              New Task
            </button>
          </div>
        </div>
        <div className="list-meta">
          <div className="task-view-row">
            <div className="view-picker task-view-picker" ref={pickerRef}>
              <button
                className="task-view-button"
                onClick={() => setPickerOpen((o) => !o)}
                aria-haspopup="listbox"
                aria-expanded={pickerOpen}
                title="Choose a list view"
              >
                {view}
                <Icon name="down" size={13} />
              </button>
              {pickerOpen && (
                <ul className="menu-pop" role="listbox">
                  <li className="menu-label">LIST VIEWS</li>
                  {views.map(([name]) => (
                    <li key={name}>
                      <button
                        role="option"
                        aria-selected={name === view}
                        onClick={() => {
                          setView(name);
                          setPickerOpen(false);
                        }}
                      >
                        {name === view && <Icon name="check" size={13} />} {name}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          {filterSummary(defs, active) && (
            <p className="filter-line">
              Filtered by <b className="filter-note">{filterSummary(defs, active)}</b>{" "}
              <button className="link filter-clear" onClick={() => setStored({})}>
                Clear filters
              </button>
            </p>
          )}
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
                <th className="rownum">
                  <Check checked={allOnPage} some={pageTicked > 0} onChange={togglePage} label="Select all open tasks on this page" />
                </th>
                {[
                  ["Subject"],
                  ["Type", "kind"],
                  ["Due Date", "due", "date"],
                  ["Related To", "related"],
                  ["Priority", "priority"],
                  ["Status", "status"],
                  ["Assigned To", "owner"],
                  ["Reminder", null, "date"],
                ].map(([label, key, className]) => (
                  <Th key={label} label={label} className={className} filter={key && defs.find((f) => f.key === key)} values={active} onChange={setStored} />
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((t) => (
                <tr key={t.id} className={`${t.completed ? "row-done" : ""} ${picked.has(t.id) ? "row-selected" : ""}`}>
                  <td className="rownum">
                    <input
                      type="checkbox"
                      className="row-check"
                      checked={t.completed || picked.has(t.id)}
                      disabled={t.completed}
                      onChange={() => toggleOne(t.id)}
                      aria-label={t.completed ? `${t.title}: ${t.status}` : `Select ${t.title}`}
                      title={t.completed ? t.status : "Select (then Mark as Done or Reassign)"}
                    />
                  </td>
                  <td>
                    <button className="link" onClick={() => setModal({ type: "task", record: t })}>
                      {t.title}
                    </button>
                  </td>
                  <td className="muted">{t.is_auto ? "Automatic" : "Manual"}</td>
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
          {!rows.length && <p className="table-empty">No tasks match these filters.</p>}
        </div>
        <Pagination {...pager} />
      </section>
    </div>
  );
}
