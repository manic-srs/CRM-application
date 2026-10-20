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

- **Sign up and log in.** The first account becomes the Manager, everyone after that is a Salesperson.
- **Seller Home.** My deals closing this quarter, my accounts, contacts and new leads, key deals, today's demos, today's tasks and recent records.
- **Leads.** Create, edit, move through the stages, convert or mark as lost.
- **Convert.** Turns a lead into an Account (the company), a Contact (the person) and an Opportunity (the deal) in one step.
- **Opportunities.** List view or Kanban board (drag a deal to change its stage), then Won or Lost.
- **Tasks.** The system creates the next follow-up at each stage and closes the old ones. You can add your own tasks with reminders.
- **Email.** Send an email with attachments from a lead, opportunity, contact or account. It is saved on the record.
- **Notifications.** An email to the owner for new follow-ups, reminders and overdue tasks. The bell shows when someone assigns you a record.
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

The database starts **empty**. Click **Sign Up** and create your account.

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
To send real emails, copy `.env.example` to `.env`, fill in the mail server, then run `docker compose up -d`.
`.env` is ignored by Git, so the password is never committed.

## Folders

| Folder | What is inside | Read more |
| --- | --- | --- |
| `database/` | PostgreSQL tables (`schema.sql`) and home page views. `seed-data.sql` is optional sample data and is not loaded. | |
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
