# CRM API (Python FastAPI + MySQL)

Back end for the CRM POC. Built on the MySQL schema in `database/` (tables, home-page views, sample data).
The flow follows Salesforce: **Lead → Nurturing → Demo → Convert → Opportunity → Proposal → Won / Lost**.

## Run with Docker (recommended)

From the **repo root** (Docker Desktop must be running):

```bash
docker compose up --build
```

- API docs (try every API in the browser): **http://localhost:8001/docs**
- MySQL: `localhost:3307`, user `crm_user` / `crm_pass`, database `crm_db`
- On the first start MySQL loads `schema.sql`, `home-page-views.sql` and `seed-data.sql`.
- Reset to the sample data: `docker compose down -v && docker compose up --build`

Sample logins (from `seed-data.sql`), password **Password@123**:
`priya@crm.test` (Manager), `ravi@crm.test`, `anita@crm.test` (Salesperson)

## Run without Docker

Needs your own MySQL with the `database/` scripts loaded (`schema.sql`, then `home-page-views.sql`, then `seed-data.sql`).

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp example.env .env          # set DATABASE_URL if needed
uvicorn app.main:app --reload
```

Docs: http://localhost:8000/docs

## Tests

```bash
cd backend && pytest -v
```

The tests use a temporary in-memory database, so your MySQL data is never touched.

## Fields (like the Salesforce forms)

| Record | Fields |
| --- | --- |
| Lead | `salutation` (Mr., Ms., Mrs., Dr., Prof.), `first_name`, **`last_name`**, **`company`**, `title`, `industry`, `email`, `phone`, `source`; `name` = first + last name (automatic) |
| Contact | `salutation`, `first_name`, **`last_name`**, `job_title`, `email`, `phone`, **`account_id`**; `full_name` = automatic |
| Opportunity | `name`, `stage`, `probability` (%), `expected_value`, `final_value`, `expected_close_date`, account, primary contact |

**Bold** = required. Win probability is set by stage: Opportunity 20, Proposal 75, Won 100, Lost 0 (can be adjusted).

## How it behaves (business rules)

| Rule | What the API does |
| --- | --- |
| New lead | Starts at **New**; system task "Make first contact" (due in 1 day) |
| Stage change | Old open tasks become **Auto-closed**; the next system task is created (Nurturing: "Follow-up call", Demo: "Conduct demo" on the demo date, Opportunity: "Send proposal", Proposal: "Follow up on proposal") |
| Notification | Every system task adds a notification to the owner's bell |
| Lost | Allowed from any open stage; `lost_reason` required (Price, Competitor, No response, No budget, Not interested, Other) |
| Convert | Creates the **Account** (company + industry, or uses an existing one), the **Contact** (salutation, first/last name, title) and the **Opportunity** (20%); lead becomes Converted |
| Won | Allowed from any open stage; `final_value` defaults to `expected_value` |
| Closed records | Converted / Lost leads and Won / Lost opportunities can't change stage |
| History | Every stage change is saved in `stage_history` with who, when and an optional note |
| Tasks | Belong to a lead **or** an opportunity, or neither (general task); status Open / Done / Auto-closed |

## APIs

All paths start with `/api`.

| Screen | API | Purpose |
| --- | --- | --- |
| Login | `POST /auth/login` | Check email + password (placeholder, no tokens yet) |
| Dropdowns | `GET /users` | Owners / assignees |
| Home | `GET /home?owner_id=` | Summary cards, pipeline, today's tasks, won vs lost, and **seller_home** (Salesforce Seller Home cards: Close Deals, Accounts, Contacts, Build Pipeline, Recent Records) |
| Leads list | `GET /leads?stage=&source=&owner_id=&search=` | List leads |
| New lead | `POST /leads` | Create |
| Lead page | `GET /leads/{id}` | Details + tasks + notes + stage history |
| Edit lead | `PUT /leads/{id}` | Edit fields |
| Path bar | `PUT /leads/{id}/stage` | New / Nurturing / Demo (`demo_date`, `note` optional) |
| Lost button | `POST /leads/{id}/lost` | `lost_reason`, `lost_notes` |
| Convert button | `POST /leads/{id}/convert` | `opportunity_name`, `expected_value`, `expected_close_date`, `account_id` (all optional) |
| History | `GET /leads/{id}/history` | Stage changes |
| Opportunities list | `GET /opportunities?stage=&owner_id=&account_id=&search=` | List |
| Opportunity page | `GET /opportunities/{id}` | Details + tasks + notes + history |
| Edit opportunity | `PUT /opportunities/{id}` | Name, value, close date, contact, owner |
| Path bar | `PUT /opportunities/{id}/stage` | Opportunity / Proposal |
| Won / Lost | `POST /opportunities/{id}/won`, `POST /opportunities/{id}/lost` | Close the deal |
| Tasks | `GET /tasks?status=&due=overdue\|today\|upcoming&owner_id=&lead_id=&opportunity_id=` | To-do list |
| Tasks | `POST /tasks`, `PUT /tasks/{id}`, `PUT /tasks/{id}/complete` | Add, edit, mark done |
| Accounts | `GET/POST /accounts`, `GET /accounts/{id}` | Account page shows contacts + opportunities |
| Contacts | `GET/POST /contacts`, `GET /contacts/{id}` | People at accounts |
| Notes | `GET /notes`, `POST /notes` | Call / demo notes on a lead or opportunity |
| Bell | `GET /notifications?user_id=`, `PUT /notifications/{id}/read` | Notifications |
| Search box | `GET /search?q=` | Leads, opportunities, accounts, contacts, tasks |
| Health | `GET /health/db` | Database connection check |

Responses include readable names next to ids (`owner_name`, `account_name`, `primary_contact_name`,
`related_to`, `changed_by_name`) so screens don't need extra calls.

## Files

| Path | Purpose |
| --- | --- |
| `app/main.py` | Starts the API, CORS for the React app |
| `app/database.py` | MySQL connection (`DATABASE_URL`) |
| `app/models.py` | Tables (match `database/schema.sql`) |
| `app/constants.py` | Allowed values and the automatic follow-up tasks per stage |
| `app/services.py` | Shared rules: stage history, auto-close tasks, auto-create tasks + notifications |
| `app/schemas.py` | What each API accepts and returns |
| `app/serializers.py` | Adds readable names to responses |
| `app/routers/` | APIs: `auth`, `home`, `leads`, `opportunities`, `tasks`, `accounts`, `activity` (notes, bell, search) |
| `tests/` | Automatic tests |

## Not in this POC

Apollo.io import, bulk upload, email / SMS sending and real authentication (tokens) come later.
