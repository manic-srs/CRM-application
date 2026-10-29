# SalesTrack CRM

SalesTrack is a web-based Customer Relationship Management (CRM) application for managing the sales cycle from first
enquiry to a won or lost deal. It is modeled on Salesforce Sales Cloud: leads, opportunities, accounts, contacts and
tasks, with role-based access, automated follow-ups, notifications and email.

![Seller Home](frontend/docs/seller-home.png)

## Demo

[Watch the SalesTrack demo video (17 min)](https://srsconsultinc-my.sharepoint.com/personal/nagamani_ch_srsconsultinginc_com/_layouts/15/stream.aspx?id=%2fpersonal%2fnagamani_ch_srsconsultinginc_com%2fDocuments%2fSalesTrack_CRM+application.mov&share=cQqXZCWENaJQT63KiSb3KpnnEgUBgmKLffuHpxHn7NkSH7kzgg) (SRS Consulting sign-in required)

Walkthrough of the Admin, Salesperson and Manager roles: user management and permissions, lead creation, stage flow,
email, tasks and reminders, notifications, lead conversion, closing a deal, and the manager's team view.

## Contents

- [Demo](#demo)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Sales process](#sales-process)
- [Roles and permissions](#roles-and-permissions)
- [Running tests](#running-tests)
- [Project structure](#project-structure)
- [Known limitations and roadmap](#known-limitations-and-roadmap)

## Features

**Sales pipeline**
- Leads and opportunities with list views, search, sorting and an opportunity Kanban board.
- Stage path on every record, with enforced stage order and a full stage history.
- One-step lead conversion into an Account, a Contact and an Opportunity.
- Automatic follow-up tasks and reminders at each stage.
- Duplicate email detection when creating a lead.
- Opportunity attachments: PDF, Word (.docx), JPG and PNG files (20 MB each) added at the Opportunity and Proposal
  stages, kept with their stage, and viewable after the deal closes.

**Access control**
- Role-based access (Salesperson, Manager, Admin) with a configurable **Roles & Permissions** matrix.
- Record-level visibility: salespeople see only their own records unless a Manager grants team access.
- All rules are enforced in the API, not only in the UI.

**Notifications and email**
- In-app notifications (bell and pop-ups) with a 30-day history, plus due-date reminders.
- Per-user email notification preferences.
- Send emails with attachments from any record, through the CRM mailbox or the user's own Outlook. Every email is logged on the record.
- Automatic no-reply emails to customers when a lead is created, won or lost (optional per action).

**Administration**
- User management: create users, assign roles, reset passwords, deactivate users and transfer their records.
- Welcome email with login details for new users; self-service profile and password change.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 19, Vite 6, CSS |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic |
| Database | PostgreSQL 16 |
| Authentication | Token-based login, bcrypt password hashing |
| Email | Microsoft 365 / Outlook (Microsoft Graph) or SMTP; Mailpit for local testing |
| Deployment | Docker Compose, nginx |
| Testing | Pytest (backend), Node test runner (frontend) |

## Getting started

### Prerequisites

- Docker Desktop
- Git

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/manic-srs/CRM-application.git
   cd CRM-application
   ```
2. (Optional) Create the environment file and update the values (see [Configuration](#configuration)):
   ```
   cp .env.example .env
   ```
   Without a `.env` file, all outgoing email is captured by the local test inbox.
3. Build and start the services:
   ```
   docker compose up -d --build
   ```

### Services

| Service | URL |
| --- | --- |
| Application | http://localhost:5173 |
| API documentation (Swagger) | http://localhost:8001/docs |
| Test mail inbox (Mailpit) | http://localhost:8026 |
| PostgreSQL | `localhost:5433` (database `crm_db`) |

### First login

1. Sign in with the default Admin account defined by `ADMIN_EMAIL` / `ADMIN_PASSWORD`
   (default `admin@salestrack.local` / `Admin@2026`).
2. Change the default password from the profile menu → **Change Password**.
3. Go to **Users** → **New User** to add Managers and Salespeople.

The database starts empty and is upgraded automatically on startup. Data is persisted in a Docker volume.

### Common commands

| Command | Description |
| --- | --- |
| `docker compose up -d --build` | Build and start (or restart after code changes) |
| `docker compose down` | Stop the services (data is kept) |
| `docker compose down -v` | Stop the services and delete all data |
| `docker compose logs api --tail 50` | View backend logs |

## Configuration

Settings are read from `.env` in the project root. This file is excluded from version control.

| Variable | Description |
| --- | --- |
| `MAIL_PROVIDER`, `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` | Send email through Microsoft 365 / Outlook using Microsoft Graph (`MAIL_PROVIDER=graph`; requires an Azure app registration with `Mail.Send`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USER`, `SMTP_PASSWORD` | SMTP server settings (used when Graph is not configured) |
| `MAIL_FROM` | Sender address for all outgoing email |
| `COMPANY_NAME` | Company name shown in customer emails |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Default Admin account created on first start |
| `SECRET_KEY` | Secret used to sign login tokens (use a long random value) |
| `APP_URL` | Base URL used in email links (default `http://localhost:5173`) |

Apply changes with `docker compose up -d`.

## Sales process

```
Lead:         New -> Nurturing -> Demo -> Convert
Opportunity:  Opportunity -> Proposal -> Won
Lost:         available from any open stage (reason required)
```

| Stage | System behavior |
| --- | --- |
| New | Creates a "Make first contact" task |
| Nurturing / Demo | Closes the previous follow-up and creates the next; demo preparation task and a 1-hour reminder |
| Convert | Creates the Account, Contact and Opportunity; moves lead emails to the opportunity |
| Proposal | Sets probability to 75%, creates a proposal follow-up and a close-date reminder |
| Won / Lost | Closes the deal and its open tasks; optional customer email |

**Stage order.** Stages cannot be skipped. Moving forward past a stage requires the user to confirm that stage as
completed, with an optional note recorded in the stage history. Moving back and marking Lost are always allowed.
Implemented in `backend/app/services.py` (`confirm_skipped`).

**Duplicate email.** A lead cannot be created with an email that belongs to an open lead. If the email belongs to a
closed lead or a contact, the user can create a new lead for the returning customer or use a different email.

## Roles and permissions

| Role | Default access |
| --- | --- |
| Salesperson | Views and edits own leads, opportunities, accounts, contacts, tasks and emails |
| Manager | Views and edits all records, reassigns owners, grants team access to salespeople |
| Admin | Full access, including user management and the permissions matrix |

- **Roles & Permissions** (Admin): enable or disable each permission for the Salesperson and Manager roles. Admin permissions are fixed.
- **Team access** (Users page): grants a salesperson read-only access to all team records.
- Records outside a user's access are hidden from lists, search, dashboards and direct links.

Access rules are implemented in `backend/app/security.py`.

## Running tests

```
docker compose exec api pip install -q pytest httpx
docker compose exec -e MAIL_ASYNC=false api pytest -q   # backend
cd frontend && npm test                                  # frontend
```

Backend tests run against a temporary database and do not send real email.

## Project structure

```
CRM-application/
├── backend/              FastAPI application (routers, models, security, email, scheduler, tests)
├── frontend/             React application (pages, components, styles)
├── database/             PostgreSQL schema, views and optional seed data
├── docker-compose.yml    Database, API, frontend and mail inbox services
└── .env.example          Environment variable template
```

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md) for module details.

## Known limitations and roadmap

**Limitations**
- Runs as a single local deployment; a shared database or hosted environment is required for multi-user access across machines.
- Production email requires a Microsoft 365 mailbox and Azure app registration.
- Customer replies are not synced back into the CRM.
- Self-service password reset is not available; passwords are reset by an Admin.

**Roadmap**
- Lead enrichment (Apollo.io)
- Bulk lead import
- Email templates
- Inbound email sync
