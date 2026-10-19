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

- The first time, PostgreSQL loads `schema.sql`, `home-page-views.sql` and `seed-data.sql` automatically.
- To start again with fresh sample data: `docker compose down -v` and then `docker compose up --build`
- PostgreSQL is on port 5433 (user `crm_user`, password `crm_pass`, database `crm_db`) if you want to check the tables, e.g. in pgAdmin.
- The API is on port 8001 because 8000 was already used on my laptop.

Sample users (password for all is `Password@123`):

- priya@crm.test (Manager)
- ravi@crm.test (Salesperson)
- anita@crm.test (Salesperson)

## Running the tests

```
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest -v
```

The tests use a temporary database, so they don't touch the PostgreSQL data. Right now all 18 pass.

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

## APIs for each screen

All APIs start with `/api`.

| Screen | API |
| --- | --- |
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
| Search box | GET /search?q= |
| DB check | GET /health/db |

The responses already include names next to the ids (owner_name, account_name, primary_contact_name and so on), so the screens don't need extra calls just to show a name.

The Home API also returns the Seller Home sections like Salesforce: close deals, accounts, contacts, build pipeline and recent records.

## Folder structure

```
backend/
  app/
    main.py          starts the app
    database.py      PostgreSQL connection
    models.py        tables (same as database/schema.sql)
    constants.py     dropdown values and the auto tasks for each stage
    services.py      common logic (stage history, auto-close and auto-create tasks)
    schemas.py       request and response formats
    serializers.py   adds names to the responses
    routers/         the APIs (auth, home, leads, opportunities, tasks, accounts, activity)
  tests/             tests
  Dockerfile
  requirements.txt
```

## Not done yet

- Login only checks the email and password. There is no token yet.
- Phase 2 items are pending: Apollo.io import, bulk upload, email/SMS notifications and email templates.
