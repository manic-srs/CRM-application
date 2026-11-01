// The Leads list: every list view (All Open Leads, My Open Leads, Uploaded Leads...) is loaded from the server
// page by page with search and sorting, so it stays fast with 100,000s of leads. Uploaded leads have Lead Source "Upload".
// The Kanban view uses the same query: one request per status column, each with its own total.
import React, { useEffect, useState } from "react";
import { apiRequest } from "./api";
import { leadBoardColumns } from "./domain";
import LeadsKanban from "./LeadsKanban";
import { DateCell, Icon, StageBadge } from "./ui";
import { dateTime, maskPhone } from "./format";
import { filterSummary, rangeBounds, Th } from "./Filters";

const PAGE = 100;
const BOARD_CARDS = 100; // cards per Kanban column; the column says when there are more
// [heading, sort key, column width]
const COLUMNS = [
  ["Name", "name", 115],
  ["Company", "company", 125],
  ["Title", "title", 95],
  ["Email", "email", 130],
  ["Phone", "phone", 134],
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

export default function LeadsTable({ view, stage, filters = {}, defs = [], onFilter, refresh = 0, mode = "table", onMode,
                                     user, setModal }) {
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [sort, setSort] = useState({ col: "created", dir: "desc" });
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [board, setBoard] = useState(null); // Kanban: { stage: { total, items } } for the columns this list can have
  const [error, setError] = useState("");
  const kanban = mode === "kanban";
  const columns = leadBoardColumns(view, stage || filters.stage);

  useEffect(() => {
    const t = setTimeout(() => (setTerm(search.trim()), setPage(0)), 350); // search after typing stops
    return () => clearTimeout(t);
  }, [search]);
  const filterKey = JSON.stringify(filters);
  useEffect(() => setPage(0), [view, stage, filterKey]);

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
  }, [kanban, view, stage, filterKey, term, sort, page, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

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

  return (
    <>
      <section className="card table-card leads-card">
        <div className="list-meta leads-meta">
          <span>
            {loaded ? `${total.toLocaleString()} item${total === 1 ? "" : "s"}` : "Loading…"} • Sorted by {sortLabel}
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
              <col style={{ width: 52 }} />
              {COLUMNS.map(([, col, width]) => (
                <col key={col} style={{ width }} />
              ))}
            </colgroup>
            <thead>
              <tr>
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
              {(result?.items || []).map((l, i) => (
                <tr key={l.id}>
                  <td className="rownum">{page * PAGE + i + 1}</td>
                  <Cell title={l.name}>
                    <a href={`#/leads/${l.id}`}>{l.name}</a>
                  </Cell>
                  <Cell>{l.company || ""}</Cell>
                  <Cell>{l.title || ""}</Cell>
                  <Cell title={l.email || ""}>{l.email && <a href={`mailto:${l.email}`}>{l.email}</a>}</Cell>
                  <Cell className="phone">{maskPhone(l.phone)}</Cell>
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
    </>
  );
}
