import { DownloadLeads, TransferHistory, UploadLeads } from "./LeadFiles";
import { can, canCreateSales } from "./permissions";
import LeadsTable from "./LeadsTable";
import { applyFilters, filterSummary, opts, ownerOptions, Th, useFilters } from "./Filters";
import { LEAD_SOURCES, LEAD_STAGES, OPPORTUNITY_STAGES, UPLOAD_SOURCE } from "./domain";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { amount, compact, shortDate, time } from "./format";
import { Icon, ObjectIcon, Pagination, StageBadge, usePaged } from "./ui";

const OPEN_LEAD = ["New", "Nurturing", "Demo"];
const OPEN_OPP = ["Opportunity", "Proposal"];
const KANBAN_STAGES = ["Opportunity", "Proposal", "Won", "Lost"];

const ownerName = (data, id) => data.users.find((u) => u.id === id)?.full_name || "";

// Leads list views and their server-side filter (the Leads list is loaded page by page, see LeadsTable.jsx)
const LEAD_VIEWS = {
  "All Open Leads": "all_open",
  "My Open Leads": "my_open",
  "All Leads": "all",
  "Converted Leads": "converted",
  "Lost Leads": "lost",
  "Uploaded Leads": "uploaded",
  "My Uploaded Leads": "my_uploaded",
};

// List views per object, like the Salesforce "list view" picker
function views(collection, user) {
  const mine = (r) => r.owner_id === user.id;
  return {
    leads: [
      ["All Open Leads", (r) => OPEN_LEAD.includes(r.stage)],
      ["My Open Leads", (r) => mine(r) && OPEN_LEAD.includes(r.stage)],
      ["All Leads", () => true],
      ["Converted Leads", (r) => r.stage === "Converted"],
      ["Lost Leads", (r) => r.stage === "Lost"],
      ["Uploaded Leads", () => true],
      ["My Uploaded Leads", () => true],
    ],
    opportunities: [
      ["All Opportunities", () => true],
      ["My Opportunities", mine],
      ["My Open Opportunities", (r) => mine(r) && OPEN_OPP.includes(r.stage)],
      ["My Won Opportunities", (r) => mine(r) && r.stage === "Won"],
      ["My Lost Opportunities", (r) => mine(r) && r.stage === "Lost"],
      ["Open Opportunities", (r) => OPEN_OPP.includes(r.stage)],
      ["Won Opportunities", (r) => r.stage === "Won"],
      ["Lost Opportunities", (r) => r.stage === "Lost"],
    ],
    accounts: [
      ["All Accounts", () => true],
      ["My Accounts", mine],
    ],
    contacts: [
      ["All Contacts", () => true],
      ["My Contacts", mine],
    ],
  }[collection];
}

// Date on the first line, time underneath (keeps the list narrow enough to fit the screen)
function DateCell({ value }) {
  if (!value) return null;
  return (
    <span className="date-cell">
      {shortDate(value)}
      <small>{time(value)}</small>
    </span>
  );
}

function columns(collection, data) {
  const link = (r, text) => <a href={`#/${collection}/${r.id}`}>{text}</a>;
  const account = (r) => (r.account_id ? <a href={`#/accounts/${r.account_id}`}>{r.account_name}</a> : "");
  return {
    leads: [
      ["Name", (r) => r.name, (r) => link(r, r.name)],
      ["Title", (r) => r.title || ""],
      ["Company", (r) => r.company || ""],
      ["Phone", (r) => r.phone || ""],
      ["Email", (r) => r.email || "", (r) => (r.email ? <a href={`mailto:${r.email}`}>{r.email}</a> : "")],
      ["Status", (r) => r.stage, (r) => <StageBadge stage={r.stage} />],
      ["Source", (r) => r.source || ""],
      ["Owner", (r) => r.owner || ""],
      ["Created", (r) => r.created_at || "", (r) => <DateCell value={r.created_at} />, "date"],
      ["Transferred", (r) => r.last_transferred_at || "", (r) => <DateCell value={r.last_transferred_at} />, "date"],
    ],
    opportunities: [
      ["Opportunity Name", (r) => r.name, (r) => link(r, r.name)],
      ["Account Name", (r) => r.account_name || "", account],
      ["Amount", (r) => Number(r.value ?? -1), (r) => amount(r.value), "num"],
      ["Close Date", (r) => r.expected_close_date || "", (r) => shortDate(r.expected_close_date)],
      ["Stage", (r) => r.stage, (r) => <StageBadge stage={r.stage} />],
      ["Owner", (r) => r.owner || ""],
      ["Created", (r) => r.created_at || "", (r) => <DateCell value={r.created_at} />, "date"],
      ["Last Modified", (r) => r.updated_at || "", (r) => <DateCell value={r.updated_at} />, "date"],
    ],
    accounts: [
      ["Account Name", (r) => r.name, (r) => link(r, r.name)],
      ["Industry", (r) => r.industry || ""],
      ["Phone", (r) => r.phone || ""],
      ["Website", (r) => r.website || ""],
      ["Owner", (r) => r.owner_name || ""],
      ["Created", (r) => r.created_at || "", (r) => <DateCell value={r.created_at} />, "date"],
      ["Last Modified", (r) => r.updated_at || "", (r) => <DateCell value={r.updated_at} />, "date"],
    ],
    contacts: [
      ["Name", (r) => r.full_name, (r) => link(r, r.full_name)],
      ["Account Name", (r) => r.account_name || "", account],
      ["Title", (r) => r.job_title || ""],
      ["Phone", (r) => r.phone || ""],
      ["Email", (r) => r.email || "", (r) => (r.email ? <a href={`mailto:${r.email}`}>{r.email}</a> : "")],
      ["Owner", (r) => ownerName(data, r.owner_id)],
      ["Created", (r) => r.created_at || "", (r) => <DateCell value={r.created_at} />, "date"],
      ["Last Modified", (r) => r.updated_at || "", (r) => <DateCell value={r.updated_at} />, "date"],
    ],
  }[collection];
}

// Filters per object. Status choices follow the list view (open views offer only open statuses);
// Owner is offered to people who see the team's records, except on "My ..." views.
function filterDefs(collection, data, user, viewName, fixedStage) {
  const team = can(user, "view_team_records") && !viewName.startsWith("My ");
  const owner = team ? [{ key: "owner", column: "Owner", label: "Owner", options: ownerOptions(data.users || [], user), get: (r) => String(r.owner_id) }] : [];
  const created = { key: "created", column: "Created", label: "Created", type: "date", get: (r) => r.created_at };
  const stages = (all, open) => {
    if (fixedStage) return null;
    if (/Open/.test(viewName)) return open;
    if (/Converted|Won|Lost/.test(viewName)) return null;
    return all;
  };
  const distinct = (list) => [...new Set(list.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  if (collection === "leads") {
    const st = stages(LEAD_STAGES, OPEN_LEAD);
    return [
      ...(st ? [{ key: "stage", label: "Lead Status", options: opts(st) }] : []),
      { key: "source", label: "Lead Source", options: opts([...LEAD_SOURCES, UPLOAD_SOURCE]) },
      ...owner,
      created,
    ];
  }
  if (collection === "opportunities") {
    const st = stages(OPPORTUNITY_STAGES, OPEN_OPP);
    return [
      ...(st ? [{ key: "stage", column: "Stage", label: "Stage", options: opts(st), get: (r) => r.stage }] : []),
      ...owner,
      { key: "close", column: "Close Date", label: "Close Date", type: "date", future: true, get: (r) => r.expected_close_date },
      created,
    ];
  }
  if (collection === "accounts")
    return [{ key: "industry", column: "Industry", label: "Industry", options: opts(distinct(data.accounts.map((a) => a.industry))), get: (r) => r.industry }, ...owner, created];
  return [{ key: "account", column: "Account Name", label: "Account", options: opts(distinct(data.contacts.map((c) => c.account_name))), get: (r) => r.account_name }, ...owner, created];
}

// keep only filter values the current view offers (e.g. a "Lost" status left over from All Leads)
function validFilters(defs, values) {
  const out = {};
  for (const f of defs) {
    const v = values[f.key];
    if (!v || (f.options && !f.options.some(([o]) => o === v))) continue;
    out[f.key] = v;
    if (f.type === "date") for (const k of ["from", "to"]) if (values[`${f.key}_${k}`]) out[`${f.key}_${k}`] = values[`${f.key}_${k}`];
  }
  return out;
}

const LABEL = { leads: "Leads", opportunities: "Opportunities", accounts: "Accounts", contacts: "Contacts" };
const NEW_TYPE = { leads: "lead", accounts: "account", contacts: "contact" };

function Kanban({ records, setModal }) {
  const [over, setOver] = useState(null);
  const drop = (stage, id) => {
    setOver(null);
    const record = records.find((r) => r.id === id);
    if (!record || record.stage === stage || !OPEN_OPP.includes(record.stage)) return;
    if (stage === "Won") setModal({ type: "won", record });
    else if (stage === "Lost") setModal({ type: "lost", collection: "opportunities", record });
    else setModal({ type: "stage", collection: "opportunities", record, stage });
  };
  return (
    <div className="kanban">
      {KANBAN_STAGES.map((stage) => {
        const items = records.filter((r) => r.stage === stage);
        const sum = items.reduce((s, r) => s + Number(r.value || 0), 0);
        return (
          <section
            key={stage}
            className={`kanban-col ${over === stage ? "drag-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(stage);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => drop(stage, e.dataTransfer.getData("text/plain"))}
          >
            <header>
              <h3 className={`kanban-stage k-${stage.toLowerCase()}`}>
                {stage} ({items.length})
              </h3>
              <p>{compact(sum)}</p>
            </header>
            <div className="kanban-cards">
              {items.map((r) => (
                <article
                  key={r.id}
                  className="kanban-card"
                  draggable={OPEN_OPP.includes(r.stage)}
                  onDragStart={(e) => e.dataTransfer.setData("text/plain", r.id)}
                >
                  <a href={`#/opportunities/${r.id}`}>{r.name}</a>
                  <dl>
                    <dt>Account Name</dt>
                    <dd>{r.account_name}</dd>
                    <dt>Close Date</dt>
                    <dd>{shortDate(r.expected_close_date)}</dd>
                    <dt>Amount</dt>
                    <dd>{amount(r.value) || "—"}</dd>
                  </dl>
                  <small>{r.owner}</small>
                </article>
              ))}
              {!items.length && <p className="kanban-empty">No opportunities</p>}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export default function ListView({ collection, data, user, openNew, setModal, query, notify, reload }) {
  const [files, setFiles] = useState(null); // "upload" | "download" | "history" (Leads and Opportunities)
  const dataList = collection === "leads" || collection === "opportunities";
  const [uploads, setUploads] = useState(0); // reloads the Leads list after an upload
  const params = new URLSearchParams(query);
  const stageFilter = params.get("stage");
  const allViews = views(collection, user);
  const listParam = params.get("list");
  const [viewName, setViewName] = useState(
    stageFilter
      ? `${stageFilter} ${LABEL[collection]}`
      : allViews.some(([name]) => name === listParam)
        ? listParam
        : collection === "leads"
          ? "All Open Leads"
          : allViews[0][0],
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef(null);
  useEffect(() => {
    // the list-view menu closes on a click anywhere else or on Esc
    if (!pickerOpen) return;
    const away = (e) => pickerRef.current && !pickerRef.current.contains(e.target) && setPickerOpen(false);
    const key = (e) => e.key === "Escape" && setPickerOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [pickerOpen]);
  const [mode, setMode] = useState(params.get("view") === "kanban" ? "kanban" : "table");
  const [search, setSearch] = useState("");
  const cols = columns(collection, data);
  const [sort, setSort] = useState({ col: 0, dir: 1 });

  const fixedStage = stageFilter && viewName === `${stageFilter} ${LABEL[collection]}` ? stageFilter : null;
  const defs = filterDefs(collection, data, user, viewName, fixedStage);
  const [filterValues, setFilterValues] = useFilters(collection);
  const active = validFilters(defs, filterValues);

  const filter = stageFilter && viewName === `${stageFilter} ${LABEL[collection]}`
    ? (r) => r.stage === stageFilter
    : allViews.find(([name]) => name === viewName)?.[1] || (() => true);

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    const list = (collection === "leads" ? data.leads : applyFilters(data[collection].filter(filter), defs, active)).filter((r) => !term || cols.some(([, get]) => String(get(r)).toLowerCase().includes(term)));
    const get = cols[sort.col][1];
    return [...list].sort((a, b) => {
      const x = get(a), y = get(b);
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sort.dir;
    });
  }, [data, collection, search, sort, viewName, JSON.stringify(active)]); // eslint-disable-line react-hooks/exhaustive-deps
  const { pageRows, start, pager } = usePaged(rows, `${collection}|${viewName}|${search}|${JSON.stringify(active)}`);

  const pickerViews = stageFilter ? [[`${stageFilter} ${LABEL[collection]}`], ...allViews] : allViews;

  return (
    <div className="page">
      <section className="list-header card">
        <div className="list-title">
          <ObjectIcon type={collection} size={36} />
          <div>
            <div className="view-picker" ref={pickerRef}>
              <button onClick={() => setPickerOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={pickerOpen}>
                <h1>{viewName}</h1>
                <Icon name="down" size={14} />
              </button>
              {pickerOpen && (
                <ul className="menu-pop" role="listbox">
                  <li className="menu-label">LIST VIEWS</li>
                  {pickerViews.map(([name]) => (
                    <li key={name}>
                      <button
                        role="option"
                        aria-selected={name === viewName}
                        onClick={() => {
                          setViewName(name);
                          setPickerOpen(false);
                        }}
                      >
                        {name === viewName && <Icon name="check" size={13} />} {name}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          <div className="list-buttons">
            {dataList && can(user, "import_leads") && (
              <button className="sf-button" onClick={() => setFiles("upload")}>
                Upload
              </button>
            )}
            {dataList && can(user, "export_data") && (
              <button className="sf-button" onClick={() => setFiles("download")}>
                Download
              </button>
            )}
            {dataList && (
              <button className="sf-button" onClick={() => setFiles("history")} title="Who uploaded or downloaded, when and why">
                History
              </button>
            )}
            {collection === "opportunities" && !canCreateSales(user) ? null : NEW_TYPE[collection] ? (
              <button className="sf-button" onClick={() => openNew(NEW_TYPE[collection])}>
                New
              </button>
            ) : (
              <a className="sf-button" href="#/leads" title="Opportunities are created by converting a lead">
                Convert a Lead
              </a>
            )}
          </div>
        </div>
        {collection !== "leads" && (
        <div className="list-meta">
          <span>
            {rows.length} item{rows.length === 1 ? "" : "s"} • Sorted by {cols[sort.col][0]}
            {search.trim() ? " • Filtered by search" : ""}
            {filterSummary(defs, active) && (
              <>
                {" • "}
                <b className="filter-note">{filterSummary(defs, active)}</b>{" "}
                <button className="link filter-clear" onClick={() => setFilterValues({})}>
                  Clear filters
                </button>
              </>
            )}
          </span>
          <div className="list-tools">
            <label className="list-search">
              <Icon name="search" size={14} />
              <input placeholder="Search this list..." value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search this list" />
            </label>
            {collection === "opportunities" && (
              <div className="toggle-group" role="group" aria-label="Display as">
                <button className={mode === "table" ? "on" : ""} onClick={() => setMode("table")} aria-label="Table" title="Table">
                  <Icon name="list" size={15} />
                </button>
                <button className={mode === "kanban" ? "on" : ""} onClick={() => setMode("kanban")} aria-label="Kanban" title="Kanban">
                  <Icon name="kanban" size={15} />
                </button>
              </div>
            )}
          </div>
        </div>
        )}
      </section>

      {collection === "leads" ? (
        <LeadsTable
          view={LEAD_VIEWS[viewName] || "all"}
          stage={fixedStage}
          filters={active}
          defs={defs}
          onFilter={setFilterValues}
          refresh={uploads}
        />
      ) : mode === "kanban" && collection === "opportunities" ? (
        <Kanban records={rows} setModal={setModal} />
      ) : (
        <section className="card table-card">
          <div className="table-scroll">
            <table className="sf-table">
              <thead>
                <tr>
                  <th className="rownum" aria-label="Row number" />
                  {cols.map(([label, , , kind], i) => (
                    <Th
                      key={label}
                      label={label}
                      className={kind || ""}
                      sorted={sort.col === i}
                      flip={sort.dir > 0}
                      onSort={() => setSort((s) => ({ col: i, dir: s.col === i ? -s.dir : 1 }))}
                      filter={defs.find((f) => f.column === label)}
                      values={active}
                      onChange={setFilterValues}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((r, i) => (
                  <tr key={r.id}>
                    <td className="rownum">{start + i + 1}</td>
                    {cols.map(([label, get, render, kind]) => {
                      const text = get(r);
                      return (
                        <td key={label} className={kind || ""} title={typeof text === "string" && text.length > 24 ? text : undefined}>
                          {render ? render(r) : text}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <p className="table-empty">No items to display.</p>}
          </div>
          <Pagination {...pager} />
        </section>
      )}
      {files === "upload" && (
        <UploadLeads
          object={collection}
          user={user}
          data={data}
          notify={notify}
          onClose={() => setFiles(null)}
          onDone={() => {
            setFiles(null);
            if (collection === "leads") {
              setViewName("My Open Leads");
              setUploads((n) => n + 1);
            }
            reload?.().catch(() => {});
          }}
        />
      )}
      {files === "download" && <DownloadLeads object={collection} notify={notify} onClose={() => setFiles(null)} />}
      {files === "history" && <TransferHistory object={collection} onClose={() => setFiles(null)} />}
    </div>
  );
}
