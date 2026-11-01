// Leads Kanban: the same list view, filters and search as the Leads table (LeadsTable.jsx loads one page per column).
// Dropping a card on a column, or choosing it in the card's Change Status menu, opens the popup the lead page uses
// (Change Stage with its required note, Convert, Mark as Lost). Nothing moves until that popup is saved; the board
// is then loaded again. Converted and Lost are closed: their cards don't move.
import React, { useState } from "react";
import { leadStageAction } from "./domain";
import { can, canCreateSales } from "./permissions";
import { ActionMenu } from "./ui";

const MENU_LABEL = { Converted: "Convert", Lost: "Mark as Lost" };

export default function LeadsKanban({ columns, board, user, setModal }) {
  const [over, setOver] = useState(null);
  // Salespeople change only their own leads, Managers and Admins any; Admins don't convert (as on the lead page)
  const rights = (lead) => {
    const canEdit = lead.owner_id === user?.id || can(user, "edit_team_records");
    return { canEdit, canConvert: canEdit && canCreateSales(user) };
  };
  const moves = (lead) =>
    columns
      .map(({ stage }) => ({ stage, action: leadStageAction(lead, stage, rights(lead)) }))
      .filter(({ action }) => action);
  const drop = (stage, id) => {
    setOver(null);
    const lead = columns.flatMap((c) => board?.[c.stage]?.items || []).find((l) => String(l.id) === id);
    const action = lead && leadStageAction(lead, stage, rights(lead));
    if (action) setModal(action);
  };
  return (
    <div className="kanban lead-board">
      {columns.map(({ stage, closed, excluded }) => {
        const column = excluded ? { total: 0, items: [] } : board?.[stage];
        const items = column?.items || [];
        return (
          <section
            key={stage}
            className={`kanban-col ${closed ? "closed" : ""} ${over === stage ? "drag-over" : ""}`}
            aria-label={`${stage}: ${column ? column.total : "loading"} lead${column?.total === 1 ? "" : "s"}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(stage);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              drop(stage, e.dataTransfer.getData("text/plain"));
            }}
          >
            <header>
              <h3 className={`kanban-stage k-${stage.toLowerCase()}`}>
                {stage} ({column ? column.total.toLocaleString() : "…"})
              </h3>
              <p>{closed ? "Closed" : "Open"}</p>
            </header>
            <div className="kanban-cards">
              {items.map((lead) => {
                const options = moves(lead);
                return (
                  <article
                    key={lead.id}
                    className="kanban-card"
                    aria-labelledby={`lead-card-${lead.id}`}
                    draggable={options.length > 0}
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", String(lead.id));
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onDragEnd={() => setOver(null)}
                  >
                    <a id={`lead-card-${lead.id}`} href={`#/leads/${lead.id}`}>
                      {lead.name}
                    </a>
                    <dl>
                      <dt>Company</dt>
                      <dd>{lead.company || "—"}</dd>
                      {lead.title && (
                        <>
                          <dt>Title</dt>
                          <dd>{lead.title}</dd>
                        </>
                      )}
                    </dl>
                    <div className="lead-card-foot">
                      <small>{lead.owner_name}</small>
                      {options.length > 0 && (
                        <ActionMenu
                          label="Change Status"
                          items={options.map(({ stage: to, action }) => ({
                            label: MENU_LABEL[to] || `Move to ${to}`,
                            onClick: () => setModal(action),
                          }))}
                        />
                      )}
                    </div>
                  </article>
                );
              })}
              {column && column.total > items.length && (
                <p className="kanban-more">
                  Showing {items.length.toLocaleString()} of {column.total.toLocaleString()}. Search or filter to narrow
                  the list, or use the List view.
                </p>
              )}
              {!items.length && <p className="kanban-empty">{excluded || (column ? "No leads" : "Loading…")}</p>}
            </div>
          </section>
        );
      })}
    </div>
  );
}
