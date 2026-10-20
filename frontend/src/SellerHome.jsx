import React from "react";
import { dateKey } from "./domain";
import { compact, dateTime, firstName, greeting, shortDate, time } from "./format";
import { Card, EmptyState, Icon, ObjectIcon, Ring, StageBadge } from "./ui";

const COLORS = { open: "#06a59a", won: "#1b96ff", lost: "#ea001e", upcoming: "#06a59a", past: "#1b96ff", none: "#ea001e" };
const routeFor = { Lead: "leads", Opportunity: "opportunities", Account: "accounts", Contact: "contacts" };

// Each pill opens the matching list (items: [colorKey, text, href])
function Legend({ items }) {
  return (
    <ul className="legend">
      {items.map(([key, text, href]) => (
        <li key={key}>
          <i style={{ background: COLORS[key] }} />
          <a className={`pill pill-${key}`} href={href}>
            {text}
          </a>
        </li>
      ))}
    </ul>
  );
}

const list = (collection, view) => `#/${collection}?list=${encodeURIComponent(view)}`;

function ViewButton({ href, children }) {
  return (
    <a className="outline-button" href={href}>
      {children}
    </a>
  );
}

// "Upcoming / Past / No Activity" ring used by the Accounts, Contacts and Leads cards
function ActivityCard({ title, subtitle, stats, total, noun, href, button, listHref }) {
  return (
    <Card title={title} className="home-card" footer={<ViewButton href={href}>{button}</ViewButton>}>
      <p className="card-sub">{subtitle}</p>
      <div className="ring-row">
        <Ring
          label={`${total} ${noun}`}
          segments={[
            { value: stats.upcoming_activity, color: COLORS.upcoming },
            { value: stats.past_activity, color: COLORS.past },
            { value: stats.no_activity, color: COLORS.none },
          ]}
        >
          <strong>{total}</strong>
          <span>{noun}</span>
        </Ring>
        <Legend
          items={[
            ["upcoming", `${stats.upcoming_activity} Upcoming Activity`, listHref],
            ["past", `${stats.past_activity} Past Activity`, listHref],
            ["none", `${stats.no_activity} No Activity`, listHref],
          ]}
        />
      </div>
    </Card>
  );
}

function assistantItems(data, user) {
  const mine = (r) => r.owner_id === user.id;
  const items = [];
  const overdue = data.tasks.filter((t) => mine(t) && !t.completed && t.isOverdue);
  if (overdue.length)
    items.push({
      key: "overdue",
      icon: "task",
      text: `You have ${overdue.length} overdue task${overdue.length > 1 ? "s" : ""}`,
      href: "#/tasks?view=overdue",
    });
  const today = dateKey();
  data.opportunities
    .filter((o) => mine(o) && ["Opportunity", "Proposal"].includes(o.stage) && o.expected_close_date && o.expected_close_date < today)
    .forEach((o) =>
      items.push({ key: `late${o.id}`, icon: "opportunity", text: `${o.name} is past its close date`, href: `#/opportunities/${o.id}` }),
    );
  const openTaskFor = new Set(data.tasks.filter((t) => !t.completed && t.relatedType === "leads").map((t) => t.relatedId));
  data.leads
    .filter((l) => mine(l) && ["New", "Nurturing", "Demo"].includes(l.stage) && !openTaskFor.has(l.id))
    .forEach((l) =>
      items.push({ key: `idle${l.id}`, icon: "lead", text: `${l.name} has no upcoming activity`, href: `#/leads/${l.id}` }),
    );
  return items.slice(0, 6);
}

export default function SellerHome({ data, user, toggleTask, openTask }) {
  const home = data.home?.seller_home;
  if (!home) return null;
  const deals = home.close_deals;
  const myTasks = (data.home.todays_tasks || [])
    .map((t) => data.tasks.find((x) => x.id === String(t.id)))
    .filter(Boolean);
  const assistant = assistantItems(data, user);

  return (
    <div className="page seller-home">
      <div className="home-title">
        <h1>Seller Home</h1>
        <p>
          {greeting()}, {firstName(user.full_name)}. Let's get selling!
        </p>
      </div>

      <div className="home-grid">
        <Card
          title="Close Deals"
          className="home-card"
          footer={<ViewButton href="#/opportunities">View Opportunities</ViewButton>}
        >
          <p className="card-sub">Opportunities owned by me and closing this quarter</p>
          <div className="ring-row">
            <Ring
              label={`Total pipeline ${compact(deals.total_pipeline)}`}
              segments={[
                { value: deals.open, color: COLORS.open },
                { value: deals.won, color: COLORS.won },
                { value: deals.lost, color: COLORS.lost },
              ]}
            >
              <strong>{compact(deals.total_pipeline)}</strong>
              <span>Total Pipeline</span>
            </Ring>
            <Legend
              items={[
                ["open", `${compact(deals.open)} Open`, list("opportunities", "My Open Opportunities")],
                ["won", `${compact(deals.won)} Won`, list("opportunities", "My Won Opportunities")],
                ["lost", `${compact(deals.lost)} Lost`, list("opportunities", "My Lost Opportunities")],
              ]}
            />
          </div>
        </Card>

        <ActivityCard
          title="Plan My Accounts"
          subtitle="Accounts owned by me"
          stats={home.accounts}
          total={home.accounts.total}
          noun="Accounts"
          href="#/accounts"
          listHref={list("accounts", "My Accounts")}
          button="View Accounts"
        />
        <ActivityCard
          title="Grow Relationships"
          subtitle="Contacts owned by me and created in the last 90 days"
          stats={home.contacts}
          total={home.contacts.total}
          noun="Contacts"
          href="#/contacts"
          listHref={list("contacts", "My Contacts")}
          button="View Contacts"
        />
        <ActivityCard
          title="Build Pipeline"
          subtitle="Leads owned by me and created in the last 30 days"
          stats={home.build_pipeline}
          total={home.build_pipeline.leads_last_30_days}
          noun="Leads"
          href="#/leads"
          listHref={list("leads", "My Open Leads")}
          button="View Leads"
        />

        <Card title="Key Deals" className="home-card" footer={<ViewButton href="#/opportunities">View All</ViewButton>}>
          <p className="card-sub">My open opportunities, largest first</p>
          {home.key_deals.length ? (
            <ul className="deal-list">
              {home.key_deals.map((d) => (
                <li key={d.id}>
                  <ObjectIcon type="opportunity" size={28} />
                  <div>
                    <a href={`#/opportunities/${d.id}`}>{d.name}</a>
                    <small>
                      {d.account_name} • Close {shortDate(d.close_date)}
                    </small>
                  </div>
                  <div className="deal-amount">
                    <b>{compact(d.amount)}</b>
                    <StageBadge stage={d.stage} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="No open deals yet. Convert a lead to start one." small />
          )}
        </Card>

        <Card title="Today's Events" className="home-card" footer={<ViewButton href="#/leads?stage=Demo">View Demos</ViewButton>}>
          {home.todays_events.length ? (
            <ul className="event-list">
              {home.todays_events.map((e) => (
                <li key={e.lead_id}>
                  <span className="event-time">{time(e.start)}</span>
                  <ObjectIcon type="event" size={28} />
                  <div>
                    <a href={`#/leads/${e.lead_id}`}>Demo with {e.name}</a>
                    <small>{e.company}</small>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="Looks like you're free and clear the rest of the day." />
          )}
        </Card>

        <Card
          title="Today's Tasks"
          className="home-card"
          actions={
            <button className="icon-btn" aria-label="New task" title="New Task" onClick={() => openTask()}>
              <Icon name="plus" size={14} />
            </button>
          }
          footer={<ViewButton href="#/tasks">View All</ViewButton>}
        >
          {myTasks.length ? (
            <ul className="home-tasks">
              {myTasks.slice(0, 6).map((t) => (
                <li key={t.id}>
                  <input
                    type="checkbox"
                    aria-label={`Complete ${t.title}`}
                    checked={t.completed}
                    disabled={t.completed}
                    onChange={() => toggleTask(t.id)}
                  />
                  <div>
                    <a href={t.relatedType !== "general" ? `#/${t.relatedType}/${t.relatedId}` : `#/tasks?task=${t.id}`}>{t.title}</a>
                    {t.related_to && (
                      <small>
                        {t.related_type}: {t.related_to}
                      </small>
                    )}
                  </div>
                  <span className={t.isOverdue ? "due overdue" : "due"}>
                    {t.isOverdue ? shortDate(t.due_date) : time(t.due_date)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="Nothing due today. Be a go-getter, and check back soon." />
          )}
        </Card>

        <Card title="Recent Records" className="home-card">
          {home.recent_records.length ? (
            <ul className="recent-list">
              {home.recent_records.map((r) => (
                <li key={r.type + r.id}>
                  <ObjectIcon type={r.type} size={28} />
                  <a href={`#/${routeFor[r.type]}/${r.id}`} title={`${r.type} • updated ${dateTime(r.updated_at)}`}>
                    {r.name}
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="Records you work on will show up here." small />
          )}
        </Card>

        <Card title="Assistant" className="home-card">
          {assistant.length ? (
            <ul className="assistant-list">
              {assistant.map((a) => (
                <li key={a.key}>
                  <ObjectIcon type={a.icon} size={24} />
                  <a href={a.href}>{a.text}</a>
                  <Icon name="right" size={14} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="Nothing needs your attention right now. Nice work!" small />
          )}
        </Card>
      </div>
    </div>
  );
}
