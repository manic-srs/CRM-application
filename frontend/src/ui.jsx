// Small building blocks used by every screen: icons, object icons, ring charts, path bar, empty states.
import { shortDate, time } from "./format";
import React, { useEffect, useState } from "react";

const paths = {
  flash: "M13 2 4 14h7l-1 8 9-12h-7Z",
  up: "M12 19V5m-6 6 6-6 6 6",
  search: "m21 21-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0",
  plus: "M12 5v14M5 12h14",
  close: "m6 6 12 12M6 18 18 6",
  check: "m5 12 4 4L19 6",
  down: "m6 9 6 6 6-6",
  right: "m9 6 6 6-6 6",
  left: "m15 6-6 6 6 6",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4",
  help: "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2-3 4m0 3h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  edit: "m15 5 4 4M4 20l4-1L21 6l-4-4L4 15Z",
  trash: "M4 7h16M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3",
  transfer: "M4 8h14l-4-4M20 16H6l4 4",
  logout: "M9 3H3v18h6m5-14 5 5-5 5m-7-5h14",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  kanban: "M3 3h5v18H3ZM10 3h5v12h-5ZM17 3h4v8h-4Z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  calendar: "M8 2v4m8-4v4M3 10h18M3 5h18v17H3Z",
  clock: "M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  warn: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  star: "m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3l-5.5 2.9 1-6.2L3 9.6l6.2-.9Z",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
  filter: "M3 5h18l-7 8v6l-4 2v-8Z",
  lock: "M6 11h12v10H6ZM8 11V7a4 4 0 0 1 8 0v4",
  settings: "M16 19v-1a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v1M9.5 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M21 19v-1a3 3 0 0 0-2.2-2.9M16 5.1a3 3 0 0 1 0 5.8",
  mail: "M3 5h18v14H3ZM3 6l9 7 9-7",
};

export function Icon({ name, size = 16, className = "", ...props }) {
  if (name === "apps")
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" className={className} {...props}>
        {[4, 12, 20].flatMap((x) =>
          [4, 12, 20].map((y) => <circle key={`${x}${y}`} cx={x} cy={y} r="2.2" fill="currentColor" />),
        )}
      </svg>
    );
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...props}
    >
      <path d={paths[name] || paths.star} />
    </svg>
  );
}

// Colored square icons per record type (white glyph on a colored tile)
const glyphs = {
  lead: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8c0-3.3 3.1-5.5 7-5.5s7 2.2 7 5.5Zm12.5-11 1.5 1.5 3-3",
  opportunity: "M12 3 4 7v2h16V7Zm-6 8v6m4-6v6m4-6v6m4-6v6M4 20h16",
  account: "M5 21V5h9v16m0-10h5v10M8 8h3m-3 4h3m-3 4h3",
  contact: "M4 5h16v14H4Zm5 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm-3 7c.5-1.5 1.6-2 3-2s2.5.5 3 2m3-6h3m-3 3h3",
  task: "m4 7 2 2 3-3m3 1h8M4 15l2 2 3-3m3 1h8",
  event: "M5 5h14v15H5Zm3-3v4m8-4v4M5 10h14",
  note: "M6 3h9l4 4v14H6Zm3 7h7m-7 4h7",
  home: "M4 11 12 4l8 7v9h-5v-6H9v6H4Z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8c0-3.3 3.1-5.5 7-5.5s7 2.2 7 5.5Z",
  assistant: "M10 3 11.8 8.2 17 10l-5.2 1.8L10 17l-1.8-5.2L3 10l5.2-1.8Zm8 10 .9 2.1 2.1.9-2.1.9L18 21l-.9-2.1L15 18l2.1-.9Z",
};
const tileColor = {
  lead: "#f88962",
  opportunity: "#ff5d2d",
  account: "#5867e8",
  contact: "#a094ed",
  task: "#3ba755",
  event: "#cb65ff",
  note: "#e6d478",
  home: "#ef7ead",
  user: "#1b96ff",
  assistant: "#7f56d9",
};
const typeKey = {
  Lead: "lead",
  leads: "lead",
  Opportunity: "opportunity",
  opportunities: "opportunity",
  Account: "account",
  accounts: "account",
  Contact: "contact",
  contacts: "contact",
  Task: "task",
  tasks: "task",
};

export function ObjectIcon({ type, size = 32 }) {
  const key = typeKey[type] || type;
  return (
    <span
      className="object-icon"
      style={{ background: tileColor[key], width: size, height: size }}
      aria-hidden="true"
    >
      <svg
        width={size * 0.62}
        height={size * 0.62}
        viewBox="0 0 24 24"
        fill="none"
        stroke="#fff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d={glyphs[key] || glyphs.note} />
      </svg>
    </span>
  );
}

// Donut chart. segments: [{ value, color }]. Empty rings are drawn grey.
export function Ring({ segments, size = 150, stroke = 9, children, label }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((sum, s) => sum + (s.value || 0), 0);
  let offset = 0;
  const gap = total && segments.filter((s) => s.value > 0).length > 1 ? 3 : 0;
  return (
    <div className="ring" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e5e5e5" strokeWidth={stroke} />
        {total > 0 &&
          segments.map((s, i) => {
            if (!s.value) return null;
            const len = (s.value / total) * c;
            const el = (
              <circle
                key={i}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={s.color}
                strokeWidth={stroke}
                strokeDasharray={`${Math.max(len - gap, 0.1)} ${c}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              />
            );
            offset += len;
            return el;
          })}
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  );
}

// Salesforce-style path: chevrons, completed steps get a check
export function PathBar({ stages, current, closed, onSelect, lostLabel }) {
  const index = stages.indexOf(current);
  return (
    <ol className="path">
      {stages.map((stage, i) => {
        const state =
          lostLabel && i === stages.length - 1
            ? "lost"
            : i < index || (closed && i <= index)
              ? "complete"
              : i === index
                ? "current"
                : "incomplete";
        return (
          <li key={stage} className={`path-step ${state}`}>
            <button
              type="button"
              disabled={closed || !onSelect}
              onClick={() => onSelect?.(stage)}
              title={stage}
            >
              {state === "complete" && <Icon name="check" size={14} className="path-check" />}
              <span className="path-label">{lostLabel && i === stages.length - 1 ? lostLabel : stage}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function StageBadge({ stage }) {
  return <span className={`stage-badge s-${String(stage).toLowerCase().replace(/\s/g, "-")}`}>{stage}</span>;
}

export function Card({ title, icon, actions, footer, className = "", children }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          {icon && <ObjectIcon type={icon} size={24} />}
          <h2>{title}</h2>
          <div className="card-actions">{actions}</div>
        </header>
      )}
      <div className="card-body">{children}</div>
      {footer && <footer className="card-footer">{footer}</footer>}
    </section>
  );
}

// Simple outdoor illustration for empty states (like the Lightning empty cards)
export function EmptyState({ text, small = false }) {
  return (
    <div className={`empty-state ${small ? "small" : ""}`}>
      <svg viewBox="0 0 240 90" width={small ? 160 : 230} aria-hidden="true">
        <g fill="none" stroke="#9bc7f0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="182" cy="26" r="11" />
          <circle cx="182" cy="26" r="17" opacity=".5" />
          <path d="M10 80h220" />
          <path d="M30 80 62 40l18 22 14-16 30 34" />
          <path d="M120 80l28-34 28 34" />
          <path d="M196 80V58m-8 8 8-8 8 8m-8 4-10 10m10-10 10 10" />
          <path d="M40 22c6 0 6-6 12-6s6 6 12 6" opacity=".6" />
        </g>
      </svg>
      <p>{text}</p>
    </div>
  );
}

export function Avatar({ name, size = 32 }) {
  const letters = (name || "?")
    .split(" ")
    .filter(Boolean)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.4 }}>
      {letters}
    </span>
  );
}

// ---------- paging for long tables ----------
// const { pageRows, pager } = usePaged(rows, resetKey);  ...  <Pagination {...pager} />
// resetKey: anything that changes the list (view, search), so the table goes back to page 1.
export const PAGE_SIZES = [10, 25, 50, 100];

export function usePaged(rows, resetKey = "", initialSize = 25) {
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(initialSize);
  useEffect(() => setPage(1), [resetKey, size]);
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const current = Math.min(page, pages);
  const start = (current - 1) * size;
  return {
    pageRows: rows.slice(start, start + size),
    start,
    pager: { page: current, pages, size, total: rows.length, start, setPage, setSize },
  };
}

export function Pagination({ page, pages, size, total, start, setPage, setSize }) {
  if (total <= PAGE_SIZES[0]) return null; // short lists fit on one page: no paging bar
  const go = (p) => setPage(Math.min(Math.max(1, p), pages));
  return (
    <nav className="pagination" aria-label="Pages">
      <span className="pagination-count">
        {start + 1}–{Math.min(start + size, total)} of {total}
      </span>
      <label className="pagination-size">
        Rows per page
        <select value={size} onChange={(e) => setSize(Number(e.target.value))}>
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <div className="pagination-buttons">
        <button type="button" onClick={() => go(1)} disabled={page === 1} aria-label="First page">
          «
        </button>
        <button type="button" onClick={() => go(page - 1)} disabled={page === 1} aria-label="Previous page">
          <Icon name="left" size={14} />
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button type="button" onClick={() => go(page + 1)} disabled={page === pages} aria-label="Next page">
          <Icon name="right" size={14} />
        </button>
        <button type="button" onClick={() => go(pages)} disabled={page === pages} aria-label="Last page">
          »
        </button>
      </div>
    </nav>
  );
}

// "Actions ▾" button at the end of a record's buttons (Edit, Transfer, Delete...), like HubSpot / Zoho.
// items: [{ label, onClick, danger }] or "-" for a divider. Opens under the button, right-aligned;
// arrow keys move between items, Esc or a click outside closes it.
export function ActionMenu({ items, label = "Actions" }) {
  const [open, setOpen] = React.useState(null);
  const ref = React.useRef(null);
  const list = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    list.current?.querySelector("button")?.focus();
    const away = (e) => ref.current && !ref.current.contains(e.target) && setOpen(null);
    const key = (e) => {
      if (e.key === "Escape") return setOpen(null);
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const buttons = [...(list.current?.querySelectorAll("button") || [])];
      const at = buttons.indexOf(document.activeElement);
      const next = (at + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    };
    const close = () => setOpen(null);
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
  // drop dividers at the start/end or next to each other
  const shown = items.filter(Boolean).filter((item, i, all) => item !== "-" || (i > 0 && i < all.length - 1 && all[i - 1] !== "-"));
  if (!shown.length) return null;
  return (
    <div className="action-menu" ref={ref}>
      <button
        type="button"
        className={`sf-button action-menu-button ${open ? "open" : ""}`}
        aria-haspopup="menu"
        aria-expanded={!!open}
        onClick={(e) => {
          if (open) return setOpen(null);
          const r = e.currentTarget.getBoundingClientRect();
          setOpen({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) });
        }}
      >
        {label}
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="action-menu-list" role="menu" aria-label={label} style={open} ref={list}>
          {shown.map((item, i) =>
            item === "-" ? (
              <hr key={i} />
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                className={item.danger ? "danger" : ""}
                onClick={() => {
                  setOpen(null);
                  item.onClick();
                }}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

// Date on the first line, time underneath (lists: Created, Last Modified)
export function DateCell({ value }) {
  if (!value) return null;
  return (
    <span className="date-cell">
      {shortDate(value)}
      <small>{time(value)}</small>
    </span>
  );
}
