# SalesTrack CRM

SalesTrack is a CRM for our sales team, built as a POC and modeled on Salesforce Sales Cloud.
It follows a customer from the first enquiry to a won or lost deal. At every step the system creates the
next follow-up task, notifies the owner and keeps the full history.

![Seller Home](frontend/docs/seller-home.png)

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 19, Vite 6, plain CSS (Salesforce Lightning style) |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic |
| Database | PostgreSQL 16 |
| Email | SMTP (Gmail / company mail server), Microsoft Graph for Outlook (optional), Mailpit as the local test inbox |
| Login | Signed login tokens, passwords stored as bcrypt hashes |
| Run | Docker Compose (database, API, app and test inbox together), nginx serves the app |
| Tests | Pytest (backend), Node test runner (frontend) |

## Sales flow

```
Lead:         New  ->  Nurturing  ->  Demo  ->  Convert
Opportunity:  Opportunity  ->  Proposal  ->  Won
Lost:         a lead or an opportunity can be marked Lost at any open stage (a reason is required)
```

1. **Lead.** A salesperson creates a lead (Last Name and Company are required). A "Make first contact" task is created.
2. **Nurturing and Demo.** Each stage closes the old follow-up and creates the next one. For a demo, the system adds
   "Prepare for demo" (9 AM the day before) and a reminder 1 hour before the demo.
3. **Convert.** One click creates the Account (company), the Contact (person) and the Opportunity (deal).
   Emails sent to the lead move to the opportunity.
4. **Proposal.** The probability goes up to 75% and a "Follow up on proposal" task is created.
   A "Close date coming up" reminder is kept 3 days before the expected close date.
5. **Won or Lost.** The deal is closed, open tasks are closed, and Home shows it under Close Deals.

## Roles

There is no public sign up. The Admin creates every account.

| Role | Access |
| --- | --- |
| Salesperson | Sees the whole team's records. Creates and changes only their own records. Can't change the owner. |
| Manager | Changes any record and reassigns owners. |
| Admin | Everything a Manager can do, plus the **Users** page: add users, change roles, edit name and email, reset passwords, deactivate users and transfer someone's open records to another user (for example when they leave). |

The same rules are checked in the API, not only on the screen.

## Features

**Home**
- Close Deals (open, won and lost this quarter), accounts, contacts, new leads, key deals, today's demos and tasks.
- **Whole team / My records** switch.

**Leads and opportunities**
- List views with an Owner column, search and sorting. Opportunities also have a Kanban board (drag a deal to change its stage).
- Record page with the stage path, tasks, emails, notes and stage history (who changed what and when).

**Notifications**
- **Updates** (lead created, stage changes, converted, Won, Lost, assigned to you) pop up in the corner and stay in the
  bell for 30 days. Unread ones are highlighted and counted on the bell. **Mark all read** clears the count.
- **Reminders** (task due, demo coming up, close date, overdue tasks) stay on the bell until the task is done.
- **My Profile → Email Notifications:** each user chooses what also comes by email.
  Stage changes are off by default; assignments and reminders are on.

**Email**
- **Send Email** from a lead, opportunity, contact or account, with attachments. Every email is saved on the record.
- **Send from:**
  - **CRM mailbox** - sent by SalesTrack from the company mailbox (`MAIL_FROM`). Replies go to the salesperson (Reply-To).
  - **My email** - opens the salesperson's own Outlook or Gmail with the message ready to send.
- A failed email can be sent again with **Resend**.

**Emails to the customer** (no-reply, from "Company Name (no-reply)")
- New lead: thank you for your interest, and who will contact them.
- Won: thank you for choosing us, and the next steps.
- Lost: a short, polite thank-you. The lost reason and notes are internal and are never sent.
- Each one has a tick box on the form, so the salesperson can skip it.

**Users and profile**
- Welcome email with the login details when the Admin creates a user, and an email when the Admin resets a password.
- **My Profile** (name and email settings) and **Change Password** for every user.

## Getting started

**You need:** Docker Desktop and Git.

**1. Clone the repo**
```
git clone https://github.com/manic-srs/CRM-application.git
cd CRM-application
```

**2. Settings (optional for a first try)**
```
cp .env.example .env
```
Fill in the mail server, company name, Admin login and `SECRET_KEY` (see [Configuration](#configuration)).
Without a `.env` file, every email goes to the local test inbox, so nothing reaches real people.

**3. Start**
```
docker compose up -d --build
```
The first run takes a few minutes.

**4. Open**

| What | Link |
| --- | --- |
| App | http://localhost:5173 |
| Test inbox (emails the app sends) | http://localhost:8026 |
| API docs | http://localhost:8001/docs |
| Database (pgAdmin or any client) | `localhost:5433`, user `crm_user`, password `crm_pass`, database `crm_db` |

**5. First login**
- Log in as the default Admin: `admin@salestrack.local` / `Admin@2026` (or the `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`).
- Change the password: profile picture (top right) → **Change Password**.
- Open **Users** → **New User** and add your Managers and Salespeople. Each user gets a welcome email.

The database starts empty. Everything is saved in PostgreSQL and stays when you stop or rebuild the app.

**Useful commands**

| Command | What it does |
| --- | --- |
| `docker compose up -d --build` | Start (or restart after code changes) |
| `docker compose down` | Stop. The data is kept. |
| `docker compose down -v` | Stop and **delete all data** |
| `docker compose logs api --tail 50` | Backend logs (for example email errors) |

## Configuration

All settings go in `.env` (next to `docker-compose.yml`). `.env` is ignored by Git, so passwords are never committed.

| Setting | Purpose |
| --- | --- |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS` | Mail server, for example `smtp.gmail.com`, `587`, `true` |
| `SMTP_USER`, `SMTP_PASSWORD` | Mailbox login (for Gmail, a 16-letter App Password) |
| `MAIL_FROM` | Address every email is sent from (for Gmail, the same as `SMTP_USER`) |
| `COMPANY_NAME` | Shown to customers, for example `SRS Consulting` |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Default Admin, created on the first start |
| `SECRET_KEY` | Signs the login tokens. Set your own long random text. |
| `MAIL_PROVIDER=graph`, `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` | Send through Outlook / Microsoft 365 (needs an Azure app from IT with the Mail.Send permission) |
| `APP_URL` | Link used in emails (default `http://localhost:5173`) |

After changing `.env`, run `docker compose up -d`.

## Tests

```
docker compose exec api pip install -q pytest httpx
docker compose exec -e MAIL_ASYNC=false api pytest -q    # backend
cd frontend && npm test                                   # frontend
```
The backend tests use a temporary database and never send real emails.

## Project structure

| Folder | Contents |
| --- | --- |
| `database/` | PostgreSQL tables (`schema.sql`), Home views, optional sample data (`seed-data.sql`, not loaded) |
| `backend/` | FastAPI API: routers, business rules, login and roles (`app/security.py`), email (`app/mailer.py`), reminders (`app/scheduler.py`), tests. See [backend/README.md](backend/README.md) |
| `frontend/` | React app: Home, list views, record pages, Users page, email composer. See [frontend/README.md](frontend/README.md) |
| `docker-compose.yml` | Database, API, app and test inbox |

## Current limits and next steps

- The app runs on one machine. To share data across the team, it needs a shared database or a hosted server.
- Real emails use a test Gmail account. For production we need a company mailbox (Outlook via Microsoft Graph is supported).
- Customer replies are not read back into the CRM yet.
- No "Forgot password" on the login page yet. The Admin resets passwords.
- Next: Apollo.io lead enrichment from a LinkedIn URL (needs an API key), bulk lead import, email templates.

## Team

Naga Mani Chappidi (backend and integration), Sharanya Utkuri (database), Samhit Eppanapally (frontend), Akhil Arroju (review).
