# CRM Back End (Python FastAPI)

APIs for the CRM application. The React front end calls these, and they read and write the MySQL database.

## Run it

From the `backend` folder:

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # uses a local SQLite file until MySQL is ready
uvicorn main:app --reload
```

Open **http://localhost:8000/docs** to see and try every API in the browser.

## Run with Docker (API + MySQL)

Needs Docker Desktop running. From the `backend` folder:

```bash
docker compose up --build
```

This starts MySQL and the API together. Open **http://localhost:8001/docs** (Docker uses port 8001).
Stop with `Ctrl + C`, or `docker compose down` (add `-v` to also delete the MySQL data).

## Run the tests

```bash
pytest -v
```

## APIs ready (Day 1)

| API | What it does |
| --- | --- |
| `POST /leads` | Create a lead (starts at **New**) |
| `GET /leads` | List leads; filters: `stage`, `owner_id`, `search`, `skip`, `limit` |
| `GET /leads/{id}` | View one lead |
| `PUT /leads/{id}` | Edit lead details (send only the fields to change) |
| `PUT /leads/{id}/stage` | Change stage to `New`, `Nurturing` or `Demo` (also for manual corrections) |
| `POST /leads/{id}/lost` | Mark as Lost; `lost_reason` is required |
| `GET /leads/{id}/history` | All stage changes of the lead |

Rules: Converted and Lost leads are closed, so their stage can't change. Every stage change is saved in `stage_history`.

## Example requests

Create a lead:

```json
POST /leads
{
  "first_name": "Arjun",
  "last_name": "Mehta",
  "company": "Bright Future Coaching Centre",
  "email": "arjun@brightfuture.com",
  "lead_source": "Web"
}
```

Change stage:

```json
PUT /leads/1/stage
{ "stage": "Nurturing" }
```

Mark as Lost:

```json
POST /leads/1/lost
{ "lost_reason": "Price too high" }
```

## Switching to MySQL

In `.env`, set:

```
DATABASE_URL=mysql+pymysql://USER:PASSWORD@localhost:3306/crm_db
```

Table and column names in `models.py` match `database/schema.sql`. Never commit `.env`.

## Files

| File | Purpose |
| --- | --- |
| `main.py` | Starts the app, allows the React front end to call it |
| `database.py` | Database connection |
| `models.py` | Tables: `users`, `leads`, `stage_history` |
| `schemas.py` | What each API accepts and returns |
| `routers/leads.py` | Lead APIs, stage change, Mark as Lost, history |
| `tests/test_leads.py` | Automatic tests |

## Next (Day 2)

Convert lead, opportunities, tasks, and auto-completing tasks on stage change.
