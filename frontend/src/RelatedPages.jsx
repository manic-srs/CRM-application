import React from "react";
import { EmailList, useEmails } from "./Email";
import { amount, dateTime, shortDate } from "./format";
import { Card, Icon, ObjectIcon, StageBadge } from "./ui";

function NotFound({ collection }) {
  return (
    <div className="page">
      <Card title="Record not found">
        <p className="pad">
          This record may have been deleted. <a href={`#/${collection}`}>Back to list</a>
        </p>
      </Card>
    </div>
  );
}

function Highlights({ type, label, name, fields, children }) {
  return (
    <section className="card highlights">
      <div className="highlights-top">
        <ObjectIcon type={type} size={36} />
        <div className="highlights-name">
          <small>{label}</small>
          <h1>{name}</h1>
        </div>
        <div className="button-group">{children}</div>
      </div>
      <dl className="highlights-fields">
        {fields.map(([l, v]) => (
          <div key={l}>
            <dt>{l}</dt>
            <dd>{v || " "}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function FieldGrid({ rows }) {
  return (
    <div className="field-grid">
      {rows.map(([label, value]) => (
        <div className="field-row" key={label}>
          <span className="field-label">{label}</span>
          <span className="field-value">{value || " "}</span>
        </div>
      ))}
    </div>
  );
}

const owner = (data, id) => data.users.find((u) => u.id === id)?.full_name || "";
const site = (url) => (url ? <a href={/^https?:/.test(url) ? url : `https://${url}`} target="_blank" rel="noreferrer">{url}</a> : "");

export function AccountPage({ id, data, openNew, openEmail, emailVersion }) {
  const account = data.accounts.find((a) => String(a.id) === id);
  const { emails } = useEmails("account_id", account?.id, emailVersion);
  if (!account) return <NotFound collection="accounts" />;
  const contacts = data.contacts.filter((c) => c.account_id === account.id);
  const opps = data.opportunities.filter((o) => o.account_id === account.id);
  return (
    <div className="page record-page">
      <Highlights
        type="account"
        label="Account"
        name={account.name}
        fields={[
          ["Industry", account.industry],
          ["Phone", account.phone],
          ["Website", site(account.website)],
          ["Account Owner", account.owner_name],
        ]}
      >
        <button
          className="sf-button"
          onClick={() =>
            openEmail({
              type: "account",
              field: "account_id",
              id: account.id,
              name: account.name,
              email: contacts[0]?.email,
              firstName: contacts[0]?.first_name,
            })
          }
        >
          Send Email
        </button>
        <button className="sf-button" onClick={() => openNew("contact", { account_id: account.id })}>
          New Contact
        </button>
      </Highlights>
      <div className="record-columns">
        <section className="card record-main">
          <div className="tabs">
            <button className="on">Details</button>
          </div>
          <div className="detail-section">
            <span className="section-toggle static">
              <Icon name="down" size={12} /> Account Information
            </span>
            <FieldGrid
              rows={[
                ["Account Name", account.name],
                ["Account Owner", account.owner_name],
                ["Industry", account.industry],
                ["Phone", account.phone],
                ["Website", site(account.website)],
                ["Address", account.address],
                ["Created", dateTime(account.created_at)],
              ]}
            />
          </div>
        </section>
        <aside className="record-side">
          <Card title={`Emails (${emails.length})`} icon="event">
            <EmailList emails={emails} />
          </Card>
          <Card
            title={`Contacts (${contacts.length})`}
            icon="contact"
            actions={
              <button className="sf-button small" onClick={() => openNew("contact", { account_id: account.id })}>
                New
              </button>
            }
          >
            <ul className="related-records">
              {contacts.map((c) => (
                <li key={c.id}>
                  <a href={`#/contacts/${c.id}`}>{c.full_name}</a>
                  <dl>
                    <dt>Title:</dt>
                    <dd>{c.job_title}</dd>
                    <dt>Email:</dt>
                    <dd>{c.email}</dd>
                    <dt>Phone:</dt>
                    <dd>{c.phone}</dd>
                  </dl>
                </li>
              ))}
              {!contacts.length && <p className="muted pad">No contacts yet.</p>}
            </ul>
          </Card>
          <Card title={`Opportunities (${opps.length})`} icon="opportunity">
            <ul className="related-records">
              {opps.map((o) => (
                <li key={o.id}>
                  <a href={`#/opportunities/${o.id}`}>{o.name}</a>
                  <dl>
                    <dt>Stage:</dt>
                    <dd>
                      <StageBadge stage={o.stage} />
                    </dd>
                    <dt>Amount:</dt>
                    <dd>{amount(o.value)}</dd>
                    <dt>Close Date:</dt>
                    <dd>{shortDate(o.expected_close_date)}</dd>
                  </dl>
                </li>
              ))}
              {!opps.length && <p className="muted pad">No opportunities yet.</p>}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  );
}

export function ContactPage({ id, data, openEmail, emailVersion }) {
  const contact = data.contacts.find((c) => String(c.id) === id);
  const { emails } = useEmails("contact_id", contact?.id, emailVersion);
  if (!contact) return <NotFound collection="contacts" />;
  const opps = data.opportunities.filter((o) => o.primary_contact_id === contact.id);
  const name = [contact.salutation, contact.full_name].filter(Boolean).join(" ");
  return (
    <div className="page record-page">
      <Highlights
        type="contact"
        label="Contact"
        name={name}
        fields={[
          ["Title", contact.job_title],
          ["Account Name", <a href={`#/accounts/${contact.account_id}`}>{contact.account_name}</a>],
          ["Phone", contact.phone],
          ["Email", contact.email],
        ]}
      >
        <button
          className="sf-button"
          onClick={() =>
            openEmail({
              type: "contact",
              field: "contact_id",
              id: contact.id,
              name: contact.full_name,
              email: contact.email,
              firstName: contact.first_name,
            })
          }
        >
          Send Email
        </button>
      </Highlights>
      <div className="record-columns">
        <section className="card record-main">
          <div className="tabs">
            <button className="on">Details</button>
          </div>
          <div className="detail-section">
            <span className="section-toggle static">
              <Icon name="down" size={12} /> Contact Information
            </span>
            <FieldGrid
              rows={[
                ["Contact Owner", owner(data, contact.owner_id)],
                ["Name", name],
                ["Account Name", <a href={`#/accounts/${contact.account_id}`}>{contact.account_name}</a>],
                ["Title", contact.job_title],
                ["Email", contact.email],
                ["Phone", contact.phone],
                ["Created", dateTime(contact.created_at)],
              ]}
            />
          </div>
        </section>
        <aside className="record-side">
          <Card title={`Emails (${emails.length})`} icon="event">
            <EmailList emails={emails} />
          </Card>
          <Card title={`Opportunities (${opps.length})`} icon="opportunity">
            <ul className="related-records">
              {opps.map((o) => (
                <li key={o.id}>
                  <a href={`#/opportunities/${o.id}`}>{o.name}</a>
                  <dl>
                    <dt>Stage:</dt>
                    <dd>
                      <StageBadge stage={o.stage} />
                    </dd>
                    <dt>Amount:</dt>
                    <dd>{amount(o.value)}</dd>
                  </dl>
                </li>
              ))}
              {!opps.length && <p className="muted pad">No opportunities with this contact.</p>}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  );
}
