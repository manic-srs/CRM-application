# CRM Backend

Backend for our CRM POC. It is written in Python (FastAPI) and uses the PostgreSQL database from the `database` folder.

The flow is the same as Salesforce:

Lead -> Nurturing -> Demo -> Convert -> Opportunity -> Proposal -> Won / Lost

A lead or opportunity can be marked Lost at any open stage.

## How to run

You need Docker Desktop running. From the main project folder (not inside backend):

```
docker compose up --build
```

Then open http://localhost:8001/docs. All the APIs are listed there and you can try them from the browser.

- The first time, PostgreSQL creates the tables from `schema.sql` and `home-page-views.sql`. There is no sample data: the database starts empty.
- Create a user with `POST /api/auth/signup` (or the Sign Up page in the app). The first user becomes the Manager, everyone after that is a Salesperson.
- To start again with an empty database: `docker compose down -v` and then `docker compose up --build`
- PostgreSQL is on port 5433 (user `crm_user`, password `crm_pass`, database `crm_db`) if you want to check the tables, e.g. in pgAdmin.
- The API is on port 8001 because 8000 was already used on my laptop.
- Emails go to a test inbox (Mailpit) at http://localhost:8026, so nothing reaches real people while we test.

If you want sample records to try things out, load `database/seed-data.sql` by hand (see the top of that file).

## Running the tests

```
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest -v
```

The tests use a temporary database and don't send real emails, so they don't touch the PostgreSQL data. Right now all 26 pass.

## Fields

We kept the fields close to the Salesforce forms.

Lead: salutation, first name, last name, company, title, industry, email, phone, lead source.
Last name and company are required. The full name (`name`) is filled automatically from first + last name.

Contact: salutation, first name, last name, job title, email, phone, account. Last name and account are required.

Opportunity: name, stage, probability, expected value, final value, expected close date, account, primary contact.

Probability changes with the stage: Opportunity 20%, Proposal 75%, Won 100%, Lost 0%. It can also be edited.

## What happens at each step

- New lead: stage is New and a "Make first contact" task is created for the owner (due next day).
- Moving the stage: the old open tasks are closed automatically ("Auto-closed") and a new follow-up task is added:
  - Nurturing: Follow-up call
  - Demo: Conduct demo (due on the demo date)
  - Opportunity: Send proposal
  - Proposal: Follow up on proposal
- Every automatic task also shows up as a notification (bell icon) for the owner.
- Lost: needs a reason (Price, Competitor, No response, No budget, Not interested, Other).
- Convert: creates the Account (from company and industry, or you can pick an existing account), the Contact and the Opportunity at 20%. The lead becomes Converted.
- Won: final value is optional. If it's empty, the expected value is used.
- Once a lead is Converted/Lost or an opportunity is Won/Lost, the stage can't be changed again.
- Every stage change is saved in stage history (who changed it, when, and a note).
- Tasks can belong to a lead, an opportunity, or nothing (general task). Status is Open, Done or Auto-closed.

## Emails and notifications

Send Email (lead, opportunity, contact or account page):

- To, Cc, subject, message and up to 10 attachments (10 MB each, 25 MB in total).
- The email is saved in the `emails` table and the files in `email_attachments`, so it shows on the record even later.
- The salesperson's name is shown as the sender and replies go to their own email address.
- If the mail server can't be reached, the email is still saved with status "Failed" and the reason.

The owner gets an email when:

- a follow-up task is created for them (new lead, stage change, convert)
- a task's reminder time is reached
- a task is overdue (once a day while it stays open)
- someone else assigns a lead, opportunity or task to them

Only assignments show on the bell. Task alerts don't, because the Tasks page and Home already show what is due
and overdue. When a lead is converted, its emails also show on the new opportunity, contact and account.

Reminders and overdue tasks are checked every minute in the background (`app/scheduler.py`).
Notification emails are sent only after the change is saved.

Mail settings (environment variables in `docker-compose.yml`; to use a real mail server, put them in a `.env` file,
see `.env.example` in the main folder):

| Setting | Meaning |
| --- | --- |
| `SMTP_HOST`, `SMTP_PORT` | Mail server. Docker uses Mailpit (`mailpit`, `1025`). Empty = no emails are sent |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS` | For a real company mail server later |
| `MAIL_FROM` | Sender address |
| `APP_URL` | Link to the app inside notification emails |
| `CHECK_INTERVAL_SECONDS` | How often reminders are checked (default 60, 0 = off) |

## APIs for each screen

All APIs start with `/api`.

| Screen | API |
| --- | --- |
| Sign up | POST /auth/signup |
| Login | POST /auth/login |
| Users (owner dropdown) | GET /users |
| Home | GET /home |
| Leads list | GET /leads (filters: stage, source, owner_id, search) |
| New lead | POST /leads |
| Lead page | GET /leads/{id} (details, tasks, notes and history together) |
| Edit lead | PUT /leads/{id} |
| Lead path bar | PUT /leads/{id}/stage |
| Mark lead lost | POST /leads/{id}/lost |
| Convert lead | POST /leads/{id}/convert |
| Opportunities list | GET /opportunities |
| Opportunity page | GET /opportunities/{id} |
| Edit opportunity | PUT /opportunities/{id} |
| Opportunity path bar | PUT /opportunities/{id}/stage |
| Won / Lost | POST /opportunities/{id}/won, POST /opportunities/{id}/lost |
| Tasks list | GET /tasks (filters: status, due=overdue/today/upcoming, owner_id) |
| Add / edit / complete task | POST /tasks, PUT /tasks/{id}, PUT /tasks/{id}/complete |
| Accounts | GET /accounts, POST /accounts, GET /accounts/{id} |
| Contacts | GET /contacts, POST /contacts, GET /contacts/{id} |
| Notes | GET /notes, POST /notes |
| Notifications (bell) | GET /notifications?user_id=, PUT /notifications/{id}/read |
| Send email | POST /emails (form data with files) |
| Emails of a record | GET /emails?lead_id= (or opportunity_id, contact_id, account_id) |
| Download attachment | GET /emails/attachments/{id} |
| Search box | GET /search?q= |
| DB check | GET /health/db |

The responses already include names next to the ids (owner_name, account_name, primary_contact_name and so on), so the screens don't need extra calls just to show a name.

`GET /home?owner_id=` returns the Seller Home cards for one user, like Salesforce:

- Close Deals: my opportunities closing this quarter (open, won and lost amounts)
- Plan My Accounts / Grow Relationships (contacts from the last 90 days) / Build Pipeline (leads from the last 30 days), each split into upcoming, past and no activity
- Key Deals: my biggest open opportunities
- Today's Events: demos booked for today
- Recent Records

## Folder structure

```
backend/
  app/
    main.py          starts the app
    database.py      PostgreSQL connection
    models.py        tables (same as database/schema.sql)
    constants.py     dropdown values and the auto tasks for each stage
    services.py      common logic (stage history, auto-close and auto-create tasks, notifications)
    mailer.py        sending email (SMTP)
    scheduler.py     reminder and overdue checks every minute
    schemas.py       request and response formats
    serializers.py   adds names to the responses
    routers/         the APIs (auth, home, leads, opportunities, tasks, accounts, activity, emails)
  tests/             tests
  Dockerfile
  requirements.txt
```

## Not done yet

- Login only checks the email and password. There is no token yet.
- Phase 2 items are pending: Apollo.io import, bulk upload, SMS notifications and email templates.
- Emails go to the Mailpit test inbox. To send real emails, set the company SMTP settings above.
