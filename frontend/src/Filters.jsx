// Column filters for the lists (Leads, Opportunities, Accounts, Contacts, Tasks): a dropdown arrow in the
// column header, like Salesforce/Excel. The chosen values are kept per list in this browser.
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "./ui";

// Date ranges. "past" fits created dates, "future" fits close and due dates.
const PAST = [
  ["today", "Today"],
  ["week", "This week"],
  ["last7", "Last 7 days"],
  ["last30", "Last 30 days"],
  ["month", "This month"],
  ["quarter", "This quarter"],
  ["year", "This year"],
];
const FUTURE = [
  ["overdue", "Before today"],
  ["today", "Today"],
  ["week", "This week"],
  ["next7", "Next 7 days"],
  ["next30", "Next 30 days"],
  ["month", "This month"],
  ["quarter", "This quarter"],
];

const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

// [start, end) in local time for a range key; custom uses the two date inputs (yyyy-mm-dd)
export function rangeBounds(range, from, to) {
  const today = startOfDay(new Date());
  const weekStart = addDays(today, -today.getDay());
  const q = Math.floor(today.getMonth() / 3) * 3;
  switch (range) {
    case "today":
      return [today, addDays(today, 1)];
    case "week":
      return [weekStart, addDays(weekStart, 7)];
    case "last7":
      return [addDays(today, -6), addDays(today, 1)];
    case "last30":
      return [addDays(today, -29), addDays(today, 1)];
    case "next7":
      return [today, addDays(today, 7)];
    case "next30":
      return [today, addDays(today, 30)];
    case "overdue":
      return [null, today];
    case "month":
      return [new Date(today.getFullYear(), today.getMonth(), 1), new Date(today.getFullYear(), today.getMonth() + 1, 1)];
    case "quarter":
      return [new Date(today.getFullYear(), q, 1), new Date(today.getFullYear(), q + 3, 1)];
    case "year":
      return [new Date(today.getFullYear(), 0, 1), new Date(today.getFullYear() + 1, 0, 1)];
    case "custom": {
      const day = (s) => (s ? new Date(`${s}T00:00:00`) : null);
      return [day(from), to ? addDays(day(to), 1) : null];
    }
    default:
      return [null, null];
  }
}

const toDate = (value) => (!value ? null : String(value).length === 10 ? new Date(`${value}T12:00:00`) : new Date(value));

// Client-side filtering for lists that are fully loaded (Opportunities, Accounts, Contacts, Tasks)
export function applyFilters(rows, defs, values) {
  const active = defs.filter((f) => values[f.key]);
  if (!active.length) return rows;
  const tests = active.map((f) => {
    if (f.type === "date") {
      const [start, end] = rangeBounds(values[f.key], values[`${f.key}_from`], values[`${f.key}_to`]);
      return (r) => {
        const d = toDate(f.get(r));
        return !!d && (!start || d >= start) && (!end || d < end);
      };
    }
    return (r) => String(f.get(r) ?? "") === values[f.key];
  });
  return rows.filter((r) => tests.every((t) => t(r)));
}

// Values kept per list ("leads", "tasks"...) so a filter stays when you come back
export function useFilters(name) {
  const storeKey = `salestrack.filters.${name}`;
  const read = () => {
    try {
      return JSON.parse(localStorage.getItem(storeKey)) || {};
    } catch {
      return {};
    }
  };
  const [values, setValues] = useState(read);
  useEffect(() => setValues(read()), [name]); // eslint-disable-line react-hooks/exhaustive-deps
  const update = (next) => {
    setValues(next);
    try {
      localStorage.setItem(storeKey, JSON.stringify(next));
    } catch {
      /* private window: filters just aren't remembered */
    }
  };
  return [values, update];
}

export const activeCount = (defs, values) => defs.filter((f) => values[f.key]).length;

// Owner choices for Admins/Managers (people who can see the team's records)
export const ownerOptions = (users, me) => [
  [String(me.id), "Me"],
  ...users
    .filter((u) => u.is_active !== false && u.id !== me.id && u.role !== "Admin")
    .sort((a, b) => a.full_name.localeCompare(b.full_name))
    .map((u) => [String(u.id), u.full_name]),
];

export const opts = (list) => list.map((x) => [x, x]);

const RANGE_LABEL = Object.fromEntries([...PAST, ...FUTURE, ["custom", "Custom range"]]);

// short text for the active filter, shown under the list title ("Priority: High")
export function filterSummary(defs, values) {
  return defs
    .filter((f) => values[f.key])
    .map((f) => {
      const v = values[f.key];
      const text = f.type === "date" ? RANGE_LABEL[v] : f.options.find(([o]) => o === v)?.[1] || v;
      return `${f.label}: ${text}`;
    })
    .join(" • ");
}

// The dropdown arrow inside a column header and its menu
function HeaderFilter({ def, values, onChange }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const [custom, setCustom] = useState({ from: "", to: "" });
  const button = useRef(null);
  const menu = useRef(null);
  const value = values[def.key] || "";

  useLayoutEffect(() => {
    if (!open) return;
    const r = button.current.getBoundingClientRect();
    const left = Math.min(r.right - 220, window.innerWidth - 240);
    setPos({ top: r.bottom + 4, left: Math.max(8, left), maxHeight: Math.max(220, window.innerHeight - r.bottom - 16) });
    setCustom({ from: values[`${def.key}_from`] || "", to: values[`${def.key}_to`] || "" });
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const away = (e) => !menu.current?.contains(e.target) && !button.current?.contains(e.target) && setOpen(false);
    const key = (e) => e.key === "Escape" && setOpen(false);
    const close = (e) => !menu.current?.contains(e.target) && setOpen(false); // page scroll, not the menu's own
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const choose = (v, extra = {}) => {
    const next = { ...values };
    delete next[def.key];
    delete next[`${def.key}_from`];
    delete next[`${def.key}_to`];
    if (v) Object.assign(next, { [def.key]: v }, extra);
    onChange(next);
    setOpen(false);
  };
  const choices = def.type === "date" ? (def.future ? FUTURE : PAST) : def.options;

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`th-filter ${value ? "on" : ""} ${open ? "open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-label={`Filter ${def.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={value ? `Filtered: ${filterSummary([def], values)}` : `Filter by ${def.label}`}
      >
        <Icon name="down" size={14} />
      </button>
      {open && pos && (
        <div ref={menu} className="th-menu" role="menu" style={pos}>
          <p className="th-menu-label">Filter by {def.label}</p>
          <button role="menuitemradio" aria-checked={!value} className={!value ? "on" : ""} onClick={() => choose("")}>
            <Icon name="check" size={13} /> {def.type === "date" ? "Any time" : "All"}
          </button>
          {choices.map(([v, text]) => (
            <button key={v} role="menuitemradio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => choose(v)}>
              <Icon name="check" size={13} /> {text}
            </button>
          ))}
          {def.type === "date" && (
            <div className="th-custom">
              <p className="th-menu-label">Custom range</p>
              <label>
                From
                <input type="date" value={custom.from} max={custom.to || undefined} onChange={(e) => setCustom({ ...custom, from: e.target.value })} />
              </label>
              <label>
                To
                <input type="date" value={custom.to} min={custom.from || undefined} onChange={(e) => setCustom({ ...custom, to: e.target.value })} />
              </label>
              <button
                className="sf-button brand"
                disabled={!custom.from && !custom.to}
                onClick={() => choose("custom", { [`${def.key}_from`]: custom.from, [`${def.key}_to`]: custom.to })}
              >
                Apply
              </button>
            </div>
          )}
          {!choices.length && <p className="th-menu-empty">Nothing to filter yet</p>}
        </div>
      )}
    </>
  );
}

// A column header: click the name to sort, the arrow to filter
export function Th({ label, sorted, flip, onSort, filter, values, onChange, className = "" }) {
  const active = filter && values[filter.key];
  return (
    <th className={`${className} ${active ? "filtered" : ""}`}>
      <div className="th-cell">
        {onSort ? (
          <button type="button" className="th-sort" onClick={onSort}>
            {label}
            {sorted && <span className="th-dir" aria-label={flip ? "sorted ascending" : "sorted descending"}>{flip ? "↑" : "↓"}</span>}
          </button>
        ) : (
          <span className="th-sort">{label}</span>
        )}
        {filter && <HeaderFilter def={filter} values={values} onChange={onChange} />}
      </div>
    </th>
  );
}
