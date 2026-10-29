import { canCreateSales } from "./permissions";
import React, { useMemo, useState } from "react";
import { amount, compact, shortDate, time } from "./format";
import { Icon, ObjectIcon, Pagination, StageBadge, usePaged } from "./ui";

const OPEN_LEAD = ["New", "Nurturing", "Demo"];
const OPEN_OPP = ["Opportunity", "Proposal"];
const KANBAN_STAGES = ["Opportunity", "Proposal", "Won", "Lost"];

const ownerName = (data, id) => data.users.find((u) => u.id === id)?.full_name || "";

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

export default function ListView({ collection, data, user, openNew, setModal, query }) {
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
  const [mode, setMode] = useState(params.get("view") === "kanban" ? "kanban" : "table");
  const [search, setSearch] = useState("");
  const cols = columns(collection, data);
  const [sort, setSort] = useState({ col: 0, dir: 1 });

  const filter = stageFilter && viewName === `${stageFilter} ${LABEL[collection]}`
    ? (r) => r.stage === stageFilter
    : allViews.find(([name]) => name === viewName)?.[1] || (() => true);

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    const list = data[collection].filter(filter).filter((r) => !term || cols.some(([, get]) => String(get(r)).toLowerCase().includes(term)));
    const get = cols[sort.col][1];
    return [...list].sort((a, b) => {
      const x = get(a), y = get(b);
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sort.dir;
    });
  }, [data, collection, search, sort, viewName]); // eslint-disable-line react-hooks/exhaustive-deps
  const { pageRows, start, pager } = usePaged(rows, `${collection}|${viewName}|${search}`);

  const pickerViews = stageFilter ? [[`${stageFilter} ${LABEL[collection]}`], ...allViews] : allViews;

  return (
    <div className="page">
      <section className="list-header card">
        <div className="list-title">
          <ObjectIcon type={collection} size={36} />
          <div>
            <div className="view-picker">
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
        <div className="list-meta">
          <span>
            {rows.length} item{rows.length === 1 ? "" : "s"} • Sorted by {cols[sort.col][0]}
            {search.trim() ? " • Filtered by search" : ""}
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
      </section>

      {mode === "kanban" && collection === "opportunities" ? (
        <Kanban records={rows} setModal={setModal} />
      ) : (
        <section className="card table-card">
          <div className="table-scroll">
            <table className="sf-table">
              <thead>
                <tr>
                  <th className="rownum" aria-label="Row number" />
                  {cols.map(([label, , , kind], i) => (
                    <th key={label} className={kind || ""}>
                      <button onClick={() => setSort((s) => ({ col: i, dir: s.col === i ? -s.dir : 1 }))}>
                        {label}
                        {sort.col === i && <Icon name="down" size={12} className={sort.dir < 0 ? "flip" : ""} />}
                      </button>
                    </th>
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
    </div>
  );
}
