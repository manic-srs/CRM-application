import React, { useEffect, useState } from "react";
import { api } from "./api";
import { LEAD_OPEN_STAGES, OPPORTUNITY_OPEN_STAGES, dateKey } from "./domain";
import { compact, dateTime, greeting, shortDate, time } from "./format";
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
    .filter((o) => mine(o) && OPPORTUNITY_OPEN_STAGES.includes(o.stage) && o.expected_close_date && o.expected_close_date < today)
    .forEach((o) =>
      items.push({ key: `late${o.id}`, icon: "opportunity", text: `${o.name} is past its close date`, href: `#/opportunities/${o.id}` }),
    );
  const openTaskFor = new Set(data.tasks.filter((t) => !t.completed && t.relatedType === "leads").map((t) => t.relatedId));
  data.leads
    .filter((l) => mine(l) && LEAD_OPEN_STAGES.includes(l.stage) && !openTaskFor.has(l.id))
    .forEach((l) =>
      items.push({ key: `idle${l.id}`, icon: "lead", text: `${l.name} has no upcoming activity`, href: `#/leads/${l.id}` }),
    );
  return items.slice(0, 6);
}

// The line under the greeting: what this dashboard shows for this person and view
function homeSummary(user, team) {
  if (user.role === "Admin") return "Here's the sales overview across every team.";
  if (team) return user.role === "Manager" ? "Here's how your team's pipeline and activity are tracking." : "Here's the team's pipeline and activity.";
  return "Here's your pipeline and what needs your attention today.";
}

// ---------- Whole team graphs: leads by stage, pipeline by stage, won vs lost this month, per salesperson ----------
const money = (n) => `$${compact(n)}`;

// One series of horizontal bars (one hue; the label on each row names it, the value sits at the bar's end)
function BarList({ rows, format = (v) => v, label }) {
  const max = Math.max(...rows.map((r) => r.value), 0);
  return (
    <ul className="team-bars" aria-label={label}>
      {rows.map((r) => (
        <li key={r.label} title={`${r.label}: ${format(r.value)}${r.note ? ` (${r.note})` : ""}`}>
          <span className="team-bar-label">{r.label}</span>
          <span className="team-bar-track">
            <span className={`team-bar ${r.tone || ""}`} style={{ width: max ? `${Math.max((r.value / max) * 100, r.value ? 2 : 0)}%` : 0 }} />
          </span>
          <span className="team-bar-value">
            {format(r.value)}
            {r.note && <small>{r.note}</small>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function TeamCharts() {
  const [charts, setCharts] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.teamCharts().then(setCharts).catch((err) => setError(err.message));
  }, []);
  if (error) return <p className="table-empty">{error}</p>;
  if (!charts) return <p className="table-empty">Loading team charts…</p>;
  const { won, lost } = charts.won_lost_month;
  const winRate = won.count + lost.count ? Math.round((won.count / (won.count + lost.count)) * 100) : null;
  const people = [...charts.people].sort((a, b) => b.open_pipeline - a.open_pipeline || a.name.localeCompare(b.name));
  return (
    <section className="team-charts" aria-label="Team performance">
      <div className="team-charts-head">
        <h2>Team Performance</h2>
        <p>{charts.scope === "team" ? "You and the Salespeople in your team" : "Everyone's records"}</p>
      </div>
      <div className="team-charts-grid">
        <Card title="Leads by Stage" className="home-card">
          <BarList label="Leads by stage" rows={charts.leads_by_stage.map((r) => ({ label: r.stage, value: r.count }))} />
        </Card>
        <Card title="Open Pipeline by Stage" className="home-card">
          <BarList
            label="Open pipeline value by stage"
            format={money}
            rows={charts.pipeline_by_stage.map((r) => ({ label: r.stage, value: r.value, note: `${r.count} deal${r.count === 1 ? "" : "s"}` }))}
          />
        </Card>
        <Card title={`Won vs Lost · ${charts.month}`} className="home-card">
          <div className="team-winrate">
            <b>{winRate === null ? "–" : `${winRate}%`}</b>
            <span>win rate this month</span>
          </div>
          <BarList
            label="Won and lost deals this month"
            rows={[
              { label: "Won", value: won.count, note: money(won.value), tone: "won" },
              { label: "Lost", value: lost.count, note: money(lost.value), tone: "lost" },
            ]}
          />
        </Card>
      </div>
      <Card title="Performance per Salesperson" className="home-card team-people">
        <div className="table-scroll">
          <table className="sf-table">
            <thead>
              <tr>
                <th>Name</th>
                <th className="num">Open Leads</th>
                <th className="num">Converted ({charts.month})</th>
                <th>Open Pipeline</th>
                <th className="num">Won ({charts.month})</th>
              </tr>
            </thead>
            <tbody>
              {people.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.name} {p.role === "Manager" && <small className="muted">(Manager)</small>}
                  </td>
                  <td className="num">{p.open_leads}</td>
                  <td className="num">{p.converted_this_month}</td>
                  <td>
                    <span className="team-inline-bar">
                      <span style={{ width: `${people[0].open_pipeline ? (p.open_pipeline / people[0].open_pipeline) * 100 : 0}%` }} />
                      <b>{money(p.open_pipeline)}</b>
                    </span>
                  </td>
                  <td className="num">{money(p.won_this_month)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!people.length && <p className="table-empty">No salespeople yet.</p>}
        </div>
      </Card>
    </section>
  );
}

export default function SellerHome({ data, user, toggleTask, openTask, scope = "team", setScope = () => {}, teamDashboard = true }) {
  const home = data.home?.seller_home;
  if (!home) return null;
  const team = scope === "team";
  const who = team ? "owned by the team" : "owned by me";
  const myList = (collection, mineView, teamView) => list(collection, team ? teamView : mineView);
  const deals = home.close_deals;
  const myTasks = (data.home.todays_tasks || [])
    .map((t) => data.tasks.find((x) => x.id === String(t.id)))
    .filter(Boolean);
  const assistant = assistantItems(data, user);

  return (
    <div className="page seller-home">
      <div className="home-title">
        <div className="home-greeting">
          {/* Title Case on the page title: "Good Evening" */}
          <h1>{greeting().replace(/\b\w/g, (c) => c.toUpperCase())}!</h1>
          <p>{homeSummary(user, team)}</p>
        </div>
        {teamDashboard && (
        <div className="toggle-group scope-toggle" role="group" aria-label="Show records">
          <button className={team ? "on" : ""} aria-pressed={team} onClick={() => setScope("team")}>
            Whole team
          </button>
          <button className={team ? "" : "on"} aria-pressed={!team} onClick={() => setScope("mine")}>
            My records
          </button>
        </div>
        )}
      </div>

      <div className="home-grid">
        <Card
          title="Close Deals"
          className="home-card"
          footer={<ViewButton href="#/opportunities">View Opportunities</ViewButton>}
        >
          <p className="card-sub">Opportunities {who} and closing this quarter</p>
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
                ["open", `${compact(deals.open)} Open`, myList("opportunities", "My Open Opportunities", "Open Opportunities")],
                ["won", `${compact(deals.won)} Won`, myList("opportunities", "My Won Opportunities", "Won Opportunities")],
                ["lost", `${compact(deals.lost)} Lost`, myList("opportunities", "My Lost Opportunities", "Lost Opportunities")],
              ]}
            />
          </div>
        </Card>

        <ActivityCard
          title={team ? "Plan Accounts" : "Plan My Accounts"}
          subtitle={`Accounts ${who}`}
          stats={home.accounts}
          total={home.accounts.total}
          noun="Accounts"
          href="#/accounts"
          listHref={myList("accounts", "My Accounts", "All Accounts")}
          button="View Accounts"
        />
        <ActivityCard
          title="Grow Relationships"
          subtitle={`Contacts ${who} and created in the last 90 days`}
          stats={home.contacts}
          total={home.contacts.total}
          noun="Contacts"
          href="#/contacts"
          listHref={myList("contacts", "My Contacts", "All Contacts")}
          button="View Contacts"
        />
        <ActivityCard
          title="Build Pipeline"
          subtitle={`Leads ${who} and created in the last 30 days`}
          stats={home.build_pipeline}
          total={home.build_pipeline.leads_last_30_days}
          noun="Leads"
          href="#/leads"
          listHref={myList("leads", "My Open Leads", "All Open Leads")}
          button="View Leads"
        />

        <Card title="Key Deals" className="home-card" footer={<ViewButton href="#/opportunities">View All</ViewButton>}>
          <p className="card-sub">{team ? "Open opportunities" : "My open opportunities"}, largest first</p>
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
      {team && teamDashboard && <TeamCharts />}
    </div>
  );
}
