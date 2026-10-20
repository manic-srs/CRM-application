import React, { useState } from "react";
import { EmailList, useEmails } from "./Email";
import { amount, dateTime, shortDate } from "./format";
import { Card, Icon, ObjectIcon, PathBar, StageBadge } from "./ui";

const LEAD_PATH = ["New", "Nurturing", "Demo", "Converted"];
const OPP_PATH = ["Opportunity", "Proposal", "Won"];

function Field({ label, children, onEdit }) {
  return (
    <div className="field-row">
      <span className="field-label">{label}</span>
      <span className="field-value">
        {children === "" || children == null ? <>&nbsp;</> : children}
        {onEdit && (
          <button className="inline-edit" onClick={onEdit} aria-label={`Edit ${label}`}>
            <Icon name="edit" size={12} />
          </button>
        )}
      </span>
    </div>
  );
}

function Section({ title, children }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="detail-section">
      <button className="section-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="down" size={12} className={open ? "" : "rot"} /> {title}
      </button>
      {open && <div className="field-grid">{children}</div>}
    </div>
  );
}

export function TaskLine({ task, toggleTask, setModal }) {
  return (
    <li className={`task-line ${task.completed ? "done" : ""}`}>
      <ObjectIcon type="task" size={24} />
      <input
        type="checkbox"
        checked={task.completed}
        disabled={task.completed}
        onChange={() => toggleTask(task.id)}
        aria-label={`Complete ${task.title}`}
      />
      <div>
        <button className="link" onClick={() => setModal({ type: "task", record: task })}>
          {task.title}
        </button>
        <small>
          {task.owner}
          {task.is_auto ? " • Automatic" : ""}
          {task.completed ? ` • ${task.status}` : ""}
          {task.priority === "High" ? " • High priority" : ""}
        </small>
      </div>
      <span
        className={`due ${!task.completed && task.isOverdue ? "overdue" : ""}`}
        title={task.completed ? `Completed ${shortDate(task.completed_at)} • Due ${shortDate(task.due_date)}` : "Due date"}
      >
        {task.completed ? shortDate(task.completed_at || task.due_date) : shortDate(task.due_date)}
      </span>
    </li>
  );
}

function ActivityTab({ item, tasks, toggleTask, setModal, openTask, collection, emails, sendEmail }) {
  const open = tasks.filter((t) => !t.completed).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const done = tasks.filter((t) => t.completed);
  const past = [
    ...done.map((t) => ({ key: `t${t.id}`, date: t.completed_at || t.due_date, task: t })),
    ...item.activity.map((a, i) => ({ key: `h${i}`, date: a.date, history: a })),
  ].sort((a, b) => String(b.date).localeCompare(String(a.date)));
  return (
    <div className="activity-tab">
      <div className="activity-actions">
        <button className="sf-button" onClick={() => openTask(item.id, collection)}>
          <ObjectIcon type="task" size={18} /> New Task
        </button>
        <button className="sf-button" onClick={sendEmail}>
          <ObjectIcon type="event" size={18} /> Email
        </button>
        <button className="sf-button" onClick={() => setModal({ type: "note", collection, record: item })}>
          <ObjectIcon type="note" size={18} /> New Note
        </button>
      </div>
      <h3 className="activity-heading">Upcoming &amp; Overdue</h3>
      {open.length ? (
        <ul className="task-lines">
          {open.map((t) => (
            <TaskLine key={t.id} task={t} toggleTask={toggleTask} setModal={setModal} />
          ))}
        </ul>
      ) : (
        <p className="muted pad">No next steps. To get things moving, add a task.</p>
      )}
      <h3 className="activity-heading">Emails ({emails.length})</h3>
      <EmailList emails={emails} empty="No emails yet. Use Email to send one with attachments." />
      <h3 className="activity-heading">Past Activity</h3>
      {past.length ? (
        <ul className="task-lines">
          {past.map((p) =>
            p.task ? (
              <TaskLine key={p.key} task={p.task} toggleTask={toggleTask} setModal={setModal} />
            ) : (
              <li key={p.key} className="task-line history">
                <ObjectIcon type="event" size={24} />
                <div>
                  <span>{p.history.text}</span>
                  <small>{p.history.by}</small>
                </div>
                <span className="due">{shortDate(p.history.date)}</span>
              </li>
            ),
          )}
        </ul>
      ) : (
        <p className="muted pad">No past activity.</p>
      )}
    </div>
  );
}

export default function RecordPage({ collection, item, data, openLead, openTask, toggleTask, convert, setModal, openEmail, emailVersion }) {
  const lead = collection === "leads";
  const [tab, setTab] = useState("activity");
  const { emails } = useEmails(lead ? "lead_id" : "opportunity_id", item?.id, emailVersion);
  if (!item)
    return (
      <div className="page">
        <Card title="Record not found">
          <p className="pad">
            This record may have been deleted. <a href={`#/${collection}`}>Back to list</a>
          </p>
        </Card>
      </div>
    );

  const closed = ["Won", "Lost", "Converted"].includes(item.stage);
  const tasks = data.tasks.filter((t) => t.relatedId === item.id && t.relatedType === collection);
  const edit = () => (lead ? openLead(item) : setModal({ type: "opportunity", record: item }));
  const convertedTo = lead && data.opportunities.find((o) => o.leadId === item.id);
  const sourceLead = !lead && item.leadId && data.leads.find((l) => l.id === item.leadId);
  const contact = !lead && data.contacts.find((c) => c.id === item.primary_contact_id);
  const sendEmail = () =>
    openEmail(
      lead
        ? { type: "lead", field: "lead_id", id: item.id, name: item.name, email: item.email, firstName: item.first_name }
        : { type: "opportunity", field: "opportunity_id", id: item.id, name: item.name, email: contact?.email, firstName: contact?.first_name },
    );

  const path = lead ? LEAD_PATH : OPP_PATH;
  const pathStages = item.stage === "Lost" ? [...path.slice(0, -1), "Lost"] : path;
  const nextStage = path[path.indexOf(item.stage) + 1];
  const selectStage = (stage) => {
    if (stage === "Converted") return convert(item.id);
    if (stage === "Won") return setModal({ type: "won", record: item });
    if (stage !== item.stage) setModal({ type: "stage", collection, record: item, stage });
  };

  const highlights = lead
    ? [
        ["Title", item.title],
        ["Company", item.company],
        ["Phone", item.phone],
        ["Email", item.email && <a href={`mailto:${item.email}`}>{item.email}</a>],
      ]
    : [
        ["Account Name", item.account_id && <a href={`#/accounts/${item.account_id}`}>{item.account_name}</a>],
        ["Close Date", shortDate(item.expected_close_date)],
        ["Amount", amount(item.value)],
        ["Opportunity Owner", item.owner],
      ];

  return (
    <div className="page record-page">
      <section className="card highlights">
        <div className="highlights-top">
          <ObjectIcon type={collection} size={36} />
          <div className="highlights-name">
            <small>{lead ? "Lead" : "Opportunity"}</small>
            <h1>
              {lead && item.salutation ? `${item.salutation} ` : ""}
              {item.name}
            </h1>
          </div>
          <div className="button-group">
            <button className="sf-button" onClick={sendEmail}>
              Send Email
            </button>
            <button className="sf-button" onClick={() => openTask(item.id, collection)}>
              New Task
            </button>
            <button className="sf-button" onClick={edit}>
              Edit
            </button>
            {lead && !closed && (
              <button className="sf-button" onClick={() => convert(item.id)}>
                Convert
              </button>
            )}
            {!closed && (
              <button className="sf-button" onClick={() => setModal({ type: "lost", collection, record: item })}>
                Mark as Lost
              </button>
            )}
          </div>
        </div>
        <dl className="highlights-fields">
          {highlights.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value || " "}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card path-card">
        <PathBar
          stages={pathStages}
          current={item.stage}
          closed={closed}
          onSelect={selectStage}
          lostLabel={item.stage === "Lost" ? (lead ? "Lost" : "Closed Lost") : null}
        />
        {!closed && nextStage && (
          <button className="sf-button brand" onClick={() => selectStage(nextStage)}>
            <Icon name="check" size={14} />
            {nextStage === "Converted" ? "Convert" : nextStage === "Won" ? "Mark as Won" : `Mark ${lead ? "Status" : "Stage"} as Complete`}
          </button>
        )}
        {closed && (
          <span className={`path-result ${item.stage === "Lost" ? "lost" : "won"}`}>
            {item.stage === "Lost"
              ? `Lost: ${item.lost_reason || ""}`
              : item.stage === "Won"
                ? `Closed Won • ${amount(item.final_value)}`
                : "Converted"}
          </span>
        )}
      </section>

      <div className="record-columns">
        <section className="card record-main">
          <div className="tabs" role="tablist">
            {["activity", "details"].map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {t === "details" ? "Details" : "Activity"}
              </button>
            ))}
          </div>
          {tab === "activity" ? (
            <ActivityTab
              item={item}
              tasks={tasks}
              toggleTask={toggleTask}
              setModal={setModal}
              openTask={openTask}
              collection={collection}
              emails={emails}
              sendEmail={sendEmail}
            />
          ) : lead ? (
            <>
              <Section title="Lead Information">
                <Field label="Lead Owner" onEdit={edit}>{item.owner}</Field>
                <Field label="Lead Status"><StageBadge stage={item.stage} /></Field>
                <Field label="Name" onEdit={edit}>
                  {[item.salutation, item.first_name, item.last_name].filter(Boolean).join(" ")}
                </Field>
                <Field label="Company" onEdit={edit}>{item.company}</Field>
                <Field label="Title" onEdit={edit}>{item.title}</Field>
                <Field label="Industry" onEdit={edit}>{item.industry}</Field>
                <Field label="Email" onEdit={edit}>{item.email && <a href={`mailto:${item.email}`}>{item.email}</a>}</Field>
                <Field label="Phone" onEdit={edit}>{item.phone}</Field>
                <Field label="Lead Source" onEdit={edit}>{item.source}</Field>
                <Field label="Demo Date">{dateTime(item.demo_date)}</Field>
              </Section>
              {item.stage === "Lost" && (
                <Section title="Lost Details">
                  <Field label="Lost Reason">{item.lost_reason}</Field>
                  <Field label="Lost Notes">{item.lost_notes}</Field>
                </Section>
              )}
              <Section title="System Information">
                <Field label="Created">{dateTime(item.created_at)}</Field>
                <Field label="Last Modified">{dateTime(item.updated_at)}</Field>
                <Field label="Converted Date">{dateTime(item.converted_at)}</Field>
                <Field label="Closed Date">{dateTime(item.closed_at)}</Field>
              </Section>
            </>
          ) : (
            <>
              <Section title="Opportunity Information">
                <Field label="Opportunity Owner" onEdit={edit}>{item.owner}</Field>
                <Field label="Opportunity Name" onEdit={edit}>{item.name}</Field>
                <Field label="Account Name">
                  {item.account_id && <a href={`#/accounts/${item.account_id}`}>{item.account_name}</a>}
                </Field>
                <Field label="Primary Contact" onEdit={edit}>
                  {contact && <a href={`#/contacts/${contact.id}`}>{contact.full_name}</a>}
                </Field>
                <Field label="Close Date" onEdit={edit}>{shortDate(item.expected_close_date)}</Field>
                <Field label="Amount" onEdit={edit}>{amount(item.expected_value)}</Field>
                <Field label="Stage"><StageBadge stage={item.stage} /></Field>
                <Field label="Probability (%)" onEdit={edit}>{`${item.probability}%`}</Field>
                {item.stage === "Won" && <Field label="Final Amount">{amount(item.final_value)}</Field>}
                <Field label="Converted From">
                  {sourceLead && <a href={`#/leads/${sourceLead.id}`}>{sourceLead.name}</a>}
                </Field>
              </Section>
              {item.stage === "Lost" && (
                <Section title="Lost Details">
                  <Field label="Lost Reason">{item.lost_reason}</Field>
                  <Field label="Lost Notes">{item.lost_notes}</Field>
                </Section>
              )}
              <Section title="System Information">
                <Field label="Created">{dateTime(item.created_at)}</Field>
                <Field label="Last Modified">{dateTime(item.updated_at)}</Field>
                <Field label="Closed Date">{dateTime(item.closed_at)}</Field>
              </Section>
            </>
          )}
        </section>

        <aside className="record-side">
          {convertedTo && (
            <Card title="Converted To" icon="opportunity">
              <ul className="related-links">
                <li>
                  <ObjectIcon type="opportunity" size={22} /> <a href={`#/opportunities/${convertedTo.id}`}>{convertedTo.name}</a>
                </li>
                <li>
                  <ObjectIcon type="account" size={22} /> <a href={`#/accounts/${convertedTo.account_id}`}>{convertedTo.account_name}</a>
                </li>
                {convertedTo.primary_contact_id && (
                  <li>
                    <ObjectIcon type="contact" size={22} />{" "}
                    <a href={`#/contacts/${convertedTo.primary_contact_id}`}>{convertedTo.primary_contact_name}</a>
                  </li>
                )}
              </ul>
            </Card>
          )}
          <Card
            title={`Notes (${item.notes.length})`}
            icon="note"
            actions={
              <button className="sf-button small" onClick={() => setModal({ type: "note", collection, record: item })}>
                New
              </button>
            }
          >
            {item.notes.length ? (
              <ul className="note-list">
                {item.notes.map((n) => (
                  <li key={n.id}>
                    <p>{n.body}</p>
                    <small>
                      {n.created_by_name} • {dateTime(n.created_at)}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted pad">No notes yet.</p>
            )}
          </Card>
          <Card title={`Stage History (${item.activity.length})`} icon="event">
            <ul className="history-list">
              {item.activity.map((a, i) => (
                <li key={i}>
                  <b>{a.text}</b>
                  <small>
                    {a.by} • {dateTime(a.date)}
                  </small>
                </li>
              ))}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  );
}
