// The Leads list: every list view (All Open Leads, My Open Leads, Uploaded Leads...) is loaded from the server
// page by page with search and sorting, so it stays fast with 100,000s of leads. Uploaded leads have Lead Source "Upload".
// The Kanban view uses the same query: one request per status column, each with its own total.
// Tick the checkboxes to transfer or delete several leads at once (the server checks each lead and skips the ones you can't change).
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, apiRequest } from "./api";
import { leadBoardColumns } from "./domain";
import LeadsKanban from "./LeadsKanban";
import { can } from "./permissions";
import { ActionMenu, DateCell, Icon, PhoneReveal, StageBadge } from "./ui";
import { dateTime } from "./format";
import { filterSummary, rangeBounds, Th } from "./Filters";

const PAGE = 15; // leads per page (Previous / Next for the rest)
const BOARD_CARDS = 100; // cards per Kanban column; the column says when there are more
// [heading, sort key, column width]
const COLUMNS = [
  ["Name", "name", 115],
  ["Company", "company", 125],
  ["Title", "title", 95],
  ["Email", "email", 130],
  ["Phone", "phone", 168],
  ["Status", "stage", 100],
  ["Source", "source", 90],
  ["Owner", "owner", 115],
  ["Created", "created", 100],
  ["Last Modified", "modified", 125],
];

// a cell that keeps to one line and shows the full text on hover
const Cell = ({ children, title, className = "" }) => (
  <td className={`cell ${className}`} title={title ?? (typeof children === "string" ? children : undefined)}>
    {children}
  </td>
);

const plural = (n, word = "lead") => `${n} ${word}${n === 1 ? "" : "s"}`;

// One line about the leads that were left out, e.g. "2 skipped: Ana Ruiz (converted), Lead 41 (not found)"
const skippedText = (skipped) =>
  skipped.length
    ? ` ${plural(skipped.length)} skipped: ${skipped
        .slice(0, 3)
        .map((s) => `${s.name} (${s.reason})`)
        .join("; ")}${skipped.length > 3 ? ` and ${skipped.length - 3} more` : ""}.`
    : "";

// A select-all checkbox that also shows the "some selected" dash
function Check({ checked, some = false, onChange, label }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some && !checked;
  }, [some, checked]);
  return <input ref={ref} type="checkbox" className="row-check" checked={checked} onChange={onChange} aria-label={label} />;
}

// Transfer / delete dialog for the selected leads
function BulkDialog({ action, count, users, me, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const transfer = action.type === "transfer";
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);
  const submit = async (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    setError("");
    try {
      const res = transfer
        ? await api.bulkTransferLeads(action.ids, Number(v.to_user_id), v.note)
        : await api.bulkDeleteLeads(action.ids);
      onDone(res);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="modal small-modal" role="dialog" aria-modal="true" aria-labelledby="bulk-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="bulk-title">{transfer ? `Transfer ${plural(count)}` : `Delete ${plural(count)}`}</h2>
        </header>
        <form onSubmit={submit}>
          <div className="modal-body bulk-form">
            {transfer ? (
              <>
                <p className="field-hint">
                  Only the owner changes. Details, stage, tasks and emails stay with each lead, and every transfer is saved in the lead's
                  history. Converted or closed leads, and leads you can't transfer, are skipped.
                </p>
                <label className="field">
                  <span>
                    <abbr title="required">*</abbr> Transfer to
                  </span>
                  <select name="to_user_id" required defaultValue="">
                    <option value="" disabled>
                      Select a user…
                    </option>
                    {users
                      .filter((u) => u.is_active !== false)
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.full_name} ({u.role}){u.id === me?.id ? " - me" : ""}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="field">
                  <span>Note</span>
                  <textarea name="note" rows={3} maxLength={300} />
                </label>
              </>
            ) : (
              <p className="modal-subtitle">
                Delete {plural(count)} with their tasks, notes and history? This can't be undone. Converted leads, and leads you can't
                change, are skipped.
              </p>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="sf-button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className={`sf-button ${transfer ? "brand" : "danger"}`} disabled={busy} aria-busy={busy}>
              {busy ? "Working…" : transfer ? "Transfer" : "Delete"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function LeadsTable({
  view,
  stage,
  filters = {},
  defs = [],
  onFilter,
  refresh = 0,
  mode = "table",
  onMode,
  user,
  setModal,
  users = [],
  notify = () => {},
  reload = () => Promise.resolve(),
}) {
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [sort, setSort] = useState({ col: "created", dir: "desc" });
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [board, setBoard] = useState(null); // Kanban: { stage: { total, items } } for the columns this list can have
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [bulk, setBulk] = useState(null); // { type: "transfer" | "delete", ids }
  // the Actions menu sits with Upload / Download / History / New in the list header (a slot ListView renders)
  const [actionsSlot, setActionsSlot] = useState(null);
  useEffect(() => setActionsSlot(document.getElementById("lead-bulk-actions")), []);
  const [again, setAgain] = useState(0); // reloads the list after a bulk action
  const kanban = mode === "kanban";
  const columns = leadBoardColumns(view, stage || filters.stage);

  useEffect(() => {
    const t = setTimeout(() => (setTerm(search.trim()), setPage(0)), 350); // search after typing stops
    return () => clearTimeout(t);
  }, [search]);
  const filterKey = JSON.stringify(filters);
  useEffect(() => setPage(0), [view, stage, filterKey]);
  useEffect(() => setSelected(new Set()), [view, stage, filterKey, term, kanban]); // a new list starts with nothing ticked

  useEffect(() => {
    const params = new URLSearchParams({ view, sort: sort.col, direction: sort.dir });
    if (filters.source) params.set("source", filters.source);
    if (filters.owner) params.set("owner", filters.owner);
    for (const key of ["created", "modified"]) {
      if (!filters[key]) continue;
      const [from, to] = rangeBounds(filters[key], filters[`${key}_from`], filters[`${key}_to`]);
      if (from) params.set(`${key}_from`, from.toISOString());
      if (to) params.set(`${key}_to`, to.toISOString());
    }
    if (term) params.set("search", term);
    const load = (extra) => apiRequest(`/leads/page?${new URLSearchParams([...params, ...Object.entries(extra)])}`);
    let current = true;
    if (kanban) {
      const shown = columns.filter((c) => !c.excluded);
      Promise.all(shown.map((c) => load({ stage: c.stage, offset: 0, limit: BOARD_CARDS })))
        .then((pages) => current && (setBoard(Object.fromEntries(shown.map((c, i) => [c.stage, pages[i]]))), setError("")))
        .catch((err) => current && setError(err.message));
    } else {
      load({ ...(stage || filters.stage ? { stage: stage || filters.stage } : {}), offset: page * PAGE, limit: PAGE })
        .then((r) => current && (setResult(r), setError("")))
        .catch((err) => current && setError(err.message));
    }
    return () => {
      current = false;
    };
  }, [kanban, view, stage, filterKey, term, sort, page, refresh, again]); // eslint-disable-line react-hooks/exhaustive-deps

  const loaded = kanban ? board : result;
  const total = kanban
    ? columns.reduce((sum, c) => sum + (c.excluded ? 0 : board?.[c.stage]?.total || 0), 0)
    : result?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const sortBy = (col) => {
    setSort((s) => ({ col, dir: s.col === col && s.dir === "asc" ? "desc" : "asc" }));
    setPage(0);
  };
  const sortLabel = COLUMNS.find(([, c]) => c === sort.col)?.[0];

  // Selection: ticks stay when you change pages, so you can pick leads from several pages
  const items = result?.items || [];
  const canTransferAny = !!user && (user.role === "Admin" || can(user, "reassign_owner") || can(user, "transfer_leads"));
  const pageIds = items.map((l) => l.id);
  const pageTicked = pageIds.filter((id) => selected.has(id)).length;
  const allOnPage = pageIds.length > 0 && pageTicked === pageIds.length;
  const toggle = (id) =>
    setSelected((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const togglePage = () =>
    setSelected((s) => {
      const next = new Set(s);
      pageIds.forEach((id) => (allOnPage ? next.delete(id) : next.add(id)));
      return next;
    });
  const finish = (res) => {
    const transfer = bulk.type === "transfer";
    const done = transfer ? res.transferred : res.deleted;
    notify(
      (done
        ? transfer
          ? `${plural(done)} transferred to ${res.to}.`
          : `${plural(done)} deleted.`
        : transfer
          ? "No leads were transferred."
          : "No leads were deleted.") + skippedText(res.skipped || []),
    );
    setBulk(null);
    setSelected(new Set());
    setAgain((n) => n + 1);
    reload().catch(() => {});
  };


  return (
    <>
      {actionsSlot &&
        !kanban &&
        createPortal(
          <ActionMenu
            label="Actions"
            badge={selected.size ? selected.size.toLocaleString() : null}
            items={
              selected.size
                ? [
                    canTransferAny && {
                      label: `Transfer ${selected.size === 1 ? "Lead" : "Leads"}`,
                      disabled: selected.size > 500,
                      title: selected.size > 500 ? "Up to 500 leads at a time" : undefined,
                      onClick: () => setBulk({ type: "transfer", ids: [...selected] }),
                    },
                    "-",
                    {
                      label: `Delete ${selected.size === 1 ? "Lead" : "Leads"}`,
                      danger: true,
                      disabled: selected.size > 500,
                      title: selected.size > 500 ? "Up to 500 leads at a time" : undefined,
                      onClick: () => setBulk({ type: "delete", ids: [...selected] }),
                    },
                  ]
                : [{ label: "Tick leads in the list first", disabled: true }]
            }
          />,
          actionsSlot,
        )}
      <section className="card table-card leads-card">
        <div className="list-meta leads-meta">
          <span>
            {loaded ? `${total.toLocaleString()} item${total === 1 ? "" : "s"}` : "Loading…"}
            {!kanban && selected.size > 0 && (
              <>
                {" • "}
                <b>{selected.size.toLocaleString()} selected</b>{" "}
                <button className="link filter-clear" onClick={() => setSelected(new Set())}>
                  Clear selection
                </button>
              </>
            )}
            {" • "}Sorted by {sortLabel}
            {term ? " • Filtered by search" : ""}
            {filterSummary(defs, filters) && (
              <>
                {" • "}
                <b className="filter-note">{filterSummary(defs, filters)}</b>{" "}
                <button className="link filter-clear" onClick={() => onFilter({})}>
                  Clear filters
                </button>
              </>
            )}
          </span>
          <div className="list-tools">
            <label className="list-search">
              <Icon name="search" size={14} />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search this list..." aria-label="Search this list" />
            </label>
            {onMode && (
              <div className="toggle-group" role="group" aria-label="Display as">
                <button className={kanban ? "" : "on"} onClick={() => onMode("table")} aria-label="Table" title="Table" aria-pressed={!kanban}>
                  <Icon name="list" size={15} />
                </button>
                <button className={kanban ? "on" : ""} onClick={() => onMode("kanban")} aria-label="Kanban" title="Kanban" aria-pressed={kanban}>
                  <Icon name="kanban" size={15} />
                </button>
              </div>
            )}
          </div>
        </div>
        {error && (
          <div className="alert" role="alert">
            <Icon name="warn" size={16} />
            <span>{error}</span>
          </div>
        )}
        {kanban ? (
          <LeadsKanban columns={columns} board={board} user={user} setModal={setModal} />
        ) : (
        <>
        <div className="table-scroll">
          <table className="sf-table leads-table">
            <colgroup>
              <col style={{ width: 38 }} />
              <col style={{ width: 52 }} />
              {COLUMNS.map(([, col, width]) => (
                <col key={col} style={{ width }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th className="select-col">
                  <Check checked={allOnPage} some={pageTicked > 0} onChange={togglePage} label="Select all leads on this page" />
                </th>
                <th className="rownum" aria-label="Row number" />
                {COLUMNS.map(([label, col]) => (
                  <Th
                    key={col}
                    label={label}
                    sorted={sort.col === col}
                    flip={sort.dir === "asc"}
                    onSort={() => sortBy(col)}
                    filter={defs.find((f) => f.key === col)}
                    values={filters}
                    onChange={onFilter}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((l, i) => (
                <tr key={l.id} className={selected.has(l.id) ? "row-selected" : ""}>
                  <td className="select-col">
                    <input
                      type="checkbox"
                      className="row-check"
                      checked={selected.has(l.id)}
                      onChange={() => toggle(l.id)}
                      aria-label={`Select ${l.name}`}
                    />
                  </td>
                  <td className="rownum">{page * PAGE + i + 1}</td>
                  <Cell title={l.name}>
                    <a href={`#/leads/${l.id}`}>{l.name}</a>
                  </Cell>
                  <Cell>{l.company || ""}</Cell>
                  <Cell>{l.title || ""}</Cell>
                  <Cell title={l.email || ""}>{l.email && <a href={`mailto:${l.email}`}>{l.email}</a>}</Cell>
                  <Cell className="phone">
                    <PhoneReveal value={l.phone} />
                  </Cell>
                  <td className="cell">
                    <StageBadge stage={l.stage} />
                  </td>
                  <Cell title={l.uploaded_from ? `Uploaded from ${l.uploaded_from}` : l.source}>{l.source}</Cell>
                  <Cell>{l.owner_name || ""}</Cell>
                  <Cell className="date" title={dateTime(l.created_at)}>
                    <DateCell value={l.created_at} />
                  </Cell>
                  <Cell className="date" title={dateTime(l.updated_at)}>
                    <DateCell value={l.updated_at} />
                  </Cell>
                </tr>
              ))}
            </tbody>
          </table>
          {result && !result.items.length && <p className="table-empty">No items to display.</p>}
        </div>
        {total > PAGE && (
          <div className="pager">
            <span>
              {(page * PAGE + 1).toLocaleString()}–{Math.min(total, (page + 1) * PAGE).toLocaleString()} of {total.toLocaleString()}
            </span>
            <button className="sf-button small" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span>
              Page {page + 1} of {pages.toLocaleString()}
            </span>
            <button className="sf-button small" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
              Next
            </button>
          </div>
        )}
        </>
        )}
      </section>
      {bulk && (
        <BulkDialog
          action={bulk}
          count={bulk.ids.length}
          users={users}
          me={user}
          onClose={() => setBulk(null)}
          onDone={finish}
        />
      )}
    </>
  );
}
