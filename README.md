# CRM-application

CRM application - lead lifecycle, opportunities and task manager.

Lead -> Nurturing -> Demo -> Opportunity -> Proposal -> Won / Lost, with follow-up tasks and reminders at each stage.

## Folders

- `database` - PostgreSQL tables, home page views and sample data
- `backend` - Python FastAPI APIs (how to run and the API list are in `backend/README.md`)
- `frontend` - React app
- `docs` - project documents

## Quick start

With Docker Desktop running, from this folder:

```
docker compose up --build
```

- App (React frontend): http://localhost:5173
- API docs: http://localhost:8001/docs
- PostgreSQL: localhost:5433 (user `crm_user`, password `crm_pass`, database `crm_db`)

Sample users (password `Password@123`): priya@crm.test (Manager), ravi@crm.test, anita@crm.test (Salespeople).

To start again with fresh sample data: `docker compose down -v`, then `docker compose up --build`.
