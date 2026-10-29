// The Leads list: every list view (All Open Leads, My Open Leads, Uploaded Leads...) is loaded from the server
// page by page with search and sorting, so it stays fast with 100,000s of leads. Uploaded leads have Lead Source "Upload".
import React, { useEffect, useState } from "react";
import { apiRequest } from "./api";
import { Icon, StageBadge } from "./ui";
import { filterSummary, rangeBounds, Th } from "./Filters";

const PAGE = 100;
// [heading, sort key, column width]
const COLUMNS = [
  ["Name", "name", 130],
  ["Company", "company", 140],
  ["Title", "title", 110],
  ["Email", "email", 140],
  ["Phone", "phone", 160],
  ["Lead Status", "stage", 115],
  ["Lead Source", "source", 118],
  ["Owner", "owner", 125],
  ["Created", "created", 100],
];

// "+91 98200 00110", "+1 416-555-0114", "4165550114" -> one consistent style with single spaces
export function formatPhone(value) {
  if (!value) return "";
  const text = String(value).trim();
  const digits = text.replace(/\D/g, "");
  if (!text.startsWith("+") && digits.length === 10) return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  if (text.startsWith("+1") && digits.length === 11) return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  if (text.startsWith("+91") && digits.length === 12) return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  return text.replace(/[\s\-.()]+/g, " ").replace(/\s+/g, " ");
}

// a cell that keeps to one line and shows the full text on hover
const Cell = ({ children, title, className = "" }) => (
  <td className={`cell ${className}`} title={title ?? (typeof children === "string" ? children : undefined)}>
    {children}
  </td>
);

export default function LeadsTable({ view, stage, filters = {}, defs = [], onFilter, refresh = 0 }) {
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [sort, setSort] = useState({ col: "created", dir: "desc" });
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const t = setTimeout(() => (setTerm(search.trim()), setPage(0)), 350); // search after typing stops
    return () => clearTimeout(t);
  }, [search]);
  const filterKey = JSON.stringify(filters);
  useEffect(() => setPage(0), [view, stage, filterKey]);

  useEffect(() => {
    const params = new URLSearchParams({ view, sort: sort.col, direction: sort.dir, offset: page * PAGE, limit: PAGE });
    if (stage || filters.stage) params.set("stage", stage || filters.stage);
    if (filters.source) params.set("source", filters.source);
    if (filters.owner) params.set("owner", filters.owner);
    if (filters.created) {
      const [from, to] = rangeBounds(filters.created, filters.created_from, filters.created_to);
      if (from) params.set("created_from", from.toISOString());
      if (to) params.set("created_to", to.toISOString());
    }
    if (term) params.set("search", term);
    let current = true;
    apiRequest(`/leads/page?${params}`)
      .then((r) => current && (setResult(r), setError("")))
      .catch((err) => current && setError(err.message));
    return () => {
      current = false;
    };
  }, [view, stage, filterKey, term, sort, page, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  const total = result?.total ?? 0;
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
            {result ? `${total.toLocaleString()} item${total === 1 ? "" : "s"}` : "Loading…"} • Sorted by {sortLabel}
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
          </div>
        </div>
        {error && (
          <div className="alert" role="alert">
            <Icon name="warn" size={16} />
            <span>{error}</span>
          </div>
        )}
        <div className="table-scroll">
          <table className="sf-table leads-table">
            <colgroup>
              <col style={{ width: 40 }} />
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
                  <Cell className="phone">{formatPhone(l.phone)}</Cell>
                  <td className="cell">
                    <StageBadge stage={l.stage} />
                  </td>
                  <Cell title={l.uploaded_from ? `Uploaded from ${l.uploaded_from}` : l.source}>{l.source}</Cell>
                  <Cell>{l.owner_name || ""}</Cell>
                  <Cell className="date">{l.created_at ? new Date(l.created_at).toLocaleDateString("en-US", { month: "2-digit", day: "2-digit", year: "2-digit" }) : ""}</Cell>
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
      </section>
    </>
  );
}
