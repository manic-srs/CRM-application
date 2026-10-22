# CRM Application (SalesTrack)

A small CRM for a sales team, built to look and work like Salesforce.
It tracks a customer from the first enquiry to a won or lost deal, with follow-up tasks at every step.

```
Lead:         New -> Nurturing -> Demo -> Convert
Opportunity:  Opportunity -> Proposal -> Won
Lost:         a lead or an opportunity can be marked Lost at any open stage (a reason is required)
```

![Seller Home](frontend/docs/seller-home.png)

## What it does

- **Sign up and log in.** Pick your role (Salesperson, Manager or Admin) on the Sign Up form.
- **Seller Home.** Deals closing this quarter, accounts, contacts and new leads, key deals, today's demos, today's tasks and recent records.
- **One shared database.** Everyone who logs in works on the same records. Home has a **Whole team / My records** switch (Whole team is the default).
- **Leads.** Create, edit, move through the stages, convert or mark as lost.
- **Convert.** Turns a lead into an Account (the company), a Contact (the person) and an Opportunity (the deal) in one step.
- **Opportunities.** List view or Kanban board (drag a deal to change its stage), then Won or Lost.
- **Tasks.** The system creates the next follow-up at each stage and closes the old ones. You can add your own tasks with reminders.
- **Reminders for dates.** The task manager keeps reminder tasks in step with the important dates:
  - Demo: "Prepare for demo" at 9 AM the day before, and "Conduct demo" with a reminder 1 hour before it starts. Rescheduling the demo moves both and tells the owner.
  - Close date: "Close date coming up" at 9 AM, 3 days before the opportunity's expected close date. It moves when the close date changes and closes when the deal is won or lost.
  - When a record gets a new owner, its system tasks and reminders go to the new owner.
- **Email.** Send an email with attachments from a lead, opportunity, contact or account. It is saved on the record.
- **Notifications.** At every step (lead created, Nurturing, Demo, converted to an opportunity, Proposal, Won, Lost) the owner gets a bell notification and an email with the details and the next follow-up task. Task reminders appear on the bell and are emailed, overdue alerts are emailed, and the bell shows when someone assigns you a record.
- **History.** Every stage change is saved with who did it and when.

## Run it

You only need **Docker Desktop**. From this folder:

```
docker compose up --build
```

The first run takes a few minutes. Then open:

| What | Link |
| --- | --- |
| The app | http://localhost:5173 |
| API docs (try every API) | http://localhost:8001/docs |
| Test inbox (emails the app sends) | http://localhost:8026 |
| Database (pgAdmin or any client) | localhost:5433, user `crm_user`, password `crm_pass`, database `crm_db` |

The database starts **empty**. Click **Sign Up**, pick your role and create your account.
Everything you add is saved in PostgreSQL and kept when you stop and start the app.
To wipe everything and start empty again: `docker compose down -v`, then `docker compose up --build`.

Useful commands:

| Command | What it does |
| --- | --- |
| `docker compose up -d` | Start in the background |
| `docker compose down` | Stop (your data is kept) |
| `docker compose down -v` | Stop and delete all data (start fresh next time) |
| `docker compose logs api` | See the backend logs |

## Try the full flow (5 minutes)

1. **Sign up** at http://localhost:5173.
2. **Leads → New.** Last Name and Company are required. Save. A "Make first contact" task is created for you.
3. On the lead page, click **Mark Status as Complete** to move to Nurturing, then click **Demo** on the path and pick a date.
4. Click **Send Email**, attach a file and send. Open http://localhost:8026 to see it.
5. Click **Convert**, enter an amount, then **Convert lead**. You land on the new opportunity.
6. Click **Mark Stage as Complete** (Proposal), then **Mark as Won**. Or click **Mark as Lost** and pick a reason.
7. Open **Home** to see the numbers update.

## Real email (optional)

By default every email goes to the test inbox, so nothing reaches real people.
To send real emails:

1. Copy `.env.example` to `.env` (same folder as `docker-compose.yml`).
2. Fill in the mail server and **remove the `#`** at the start of each `SMTP_...` and `MAIL_FROM` line.
3. Run `docker compose up -d` (it restarts the API with the new settings).
4. Check it: http://localhost:8001/docs → **GET /api/health/email** should say `real email`, then
   **POST /api/health/email/test** with your address sends one email straight away and shows any error from the mail server.

`.env` is ignored by Git, so the password is never committed. Emails are sent in the background, so clicks stay fast.
Each user gets the notifications at the email address they signed up with.

## Folders

| Folder | What is inside | Read more |
| --- | --- | --- |
| `database/` | PostgreSQL tables (`schema.sql`), home page views, optional sample data (`seed-data.sql`, not loaded) and handy queries (`test-queries.sql`). | |
| `backend/` | Python FastAPI API, business rules, email and reminders, tests | [backend/README.md](backend/README.md) |
| `frontend/` | React app (Vite), Salesforce-style screens | [frontend/README.md](frontend/README.md) |
| `docker-compose.yml` | Starts the database, API, app and test inbox together | |

## Tech stack

React (Vite) · Python FastAPI · SQLAlchemy · PostgreSQL 16 · Docker Compose · Mailpit (test inbox) · Pytest

## Tests

```
cd backend && pytest -v        # backend tests (use a temporary database)
cd frontend && npm test        # frontend tests
```

## Branches

Each part is developed in its own branch and merged into `main` with a pull request:

| Branch | Contains |
| --- | --- |
| `database` | PostgreSQL schema, views and optional sample data |
| `backend` | FastAPI API (builds on `database`) |
| `frontend` | React app and the full `docker-compose.yml` (builds on `backend`) |

Merge order: `database` → `backend` → `frontend`.

## Not in this version

- Logins are checked, but the API does not issue tokens yet.
- Replies from leads are not read back into the CRM yet.
- Phase 2: Apollo.io import, bulk upload, SMS and email templates.

## Team

Naga Mani (backend), Sharanya (database), Samhit (frontend), Akhil (review).
