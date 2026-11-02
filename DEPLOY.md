# Deploying SalesTrack CRM on a server

SalesTrack runs as four Docker containers (PostgreSQL, the API, the web app, a test mailbox), started by one
command. These steps set it up on a Linux server and keep it updated.

## 1. What the server needs

- Linux (Ubuntu 22.04 or later is fine) with **Docker Engine** and the **Docker Compose plugin**
  (`docker compose version` should work).
- About 2 CPUs, 4 GB RAM and 20 GB disk to start.
- Ports: the app port open to users (80, or 443 behind a reverse proxy with HTTPS). Nothing else needs to be public.
- A DNS name for the app, e.g. `crm.srsconsultinginc.com` (needed for links in emails and for unsubscribe links).

## 2. Get the code

```bash
git clone https://github.com/manic-srs/CRM-application.git
cd CRM-application
git checkout main          # after phase 2 and email campaigns are merged; before that: git checkout email-campaigns
```

## 3. Create `.env` (settings and secrets, never committed)

```bash
cp .env.example .env
nano .env                  # remove the # in front of each line you set
```

Set at least these for a server:

| Setting | Example | Why |
| --- | --- | --- |
| `APP_URL` | `https://crm.srsconsultinginc.com` | Links in notification emails |
| `PUBLIC_URL` | `https://crm.srsconsultinginc.com` | Unsubscribe / Subscribe links in campaign emails |
| `APP_PORT` | `80` | Port the app listens on (or keep 5173 behind a reverse proxy) |
| `API_PORT` / `DB_PORT` / `MAILPIT_PORT` | `127.0.0.1:8001` / `127.0.0.1:5433` / `127.0.0.1:8026` | Keeps the API docs, database and test inbox private to the server |
| `SECRET_KEY` | a long random text (`openssl rand -hex 32`) | Signs logins and unsubscribe links |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | the first Admin's login | Created on the first start; change the password after logging in |
| `ALLOWED_EMAIL_DOMAINS` | `srsconsultinginc.com` | Only company emails can be users |
| `COMPANY_NAME` | `SRS Consulting` | Used in emails |
| `OPENAI_API_KEY` | `sk-...` | AI Assistant and AI email drafts (optional) |
| `APOLLO_API_KEY` | | LinkedIn autofill on New Lead (optional) |

**Email (Outlook).** Pick one. Until it's set, every email goes to the private test inbox and nothing is sent.

- **Option A, for now: a mailbox's own login (SMTP).** `SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`,
  `SMTP_TLS=true`, `SMTP_USER` / `SMTP_PASSWORD` / `MAIL_FROM` = that mailbox. SMTP AUTH must be allowed for the
  mailbox, and Microsoft turns this sign-in off by default in late December 2026.
- **Option B, recommended: Microsoft 365 OAuth (Graph).** IT registers an Entra ID app with the Graph `Mail.Send`
  application permission (admin consent, limited to the CRM mailbox). Then set `MAIL_PROVIDER=graph`,
  `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` and `MAIL_FROM=crm@srsconsultinginc.com`.

Switching later is only a change in `.env` and a restart (step 6); nothing else changes.

**Campaign pace.** One Microsoft 365 mailbox may send 30 emails a minute, 10,000 recipients a day, and 2,000
*external* recipients a day. SalesTrack sends 20 a minute and at most 1,800 a day by default
(`CAMPAIGN_PER_MINUTE`, `CAMPAIGN_PER_DAY`), across all campaigns.

## 4. Start it

```bash
docker compose up -d --build
docker compose ps          # all four containers "running"; db "healthy"
```

The first start creates the database tables. Open `APP_URL`, log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`,
**change the password** (profile menu > Change Password), then add users in Manage Access (one by one or
Upload Users).

## 5. Check email

From the server: `http://127.0.0.1:8001/docs` (or an SSH tunnel). Authorize with an Admin token, then call
`GET /api/health/email` (which mailbox and mode) and `POST /api/health/email/test` (sends one test email).

## 6. Update to a new version

```bash
cd CRM-application
git pull
docker compose up -d --build
```

The database stays (it lives in the `crm_pg_data` volume). New columns and tables are added automatically on start.
After changing `.env` only: `docker compose up -d`.

## 7. Back up and restore the database

```bash
# back up (daily, e.g. from cron)
docker compose exec -T db pg_dump -U crm_user crm_db | gzip > backup-$(date +%F).sql.gz
# restore into an empty database
gunzip -c backup-YYYY-MM-DD.sql.gz | docker compose exec -T db psql -U crm_user crm_db
```

## 8. HTTPS

Put a reverse proxy in front of the app port (Nginx, Caddy, or the company load balancer) with a certificate for
the DNS name, forwarding to `http://127.0.0.1:<APP_PORT>`. Set `APP_URL` and `PUBLIC_URL` to the `https://` address.

## 9. Logs and troubleshooting

| Problem | Check |
| --- | --- |
| App doesn't open | `docker compose ps`; `docker compose logs frontend` |
| Errors or emails not sending | `docker compose logs api --tail 200` (look for `crm.mail` / `crm.campaigns`) |
| Campaign paused | The campaign page shows why (e.g. the mail login was refused); fix `.env`, restart, then Resume |
| Unsubscribe link doesn't open for a lead | `PUBLIC_URL` must be the public `https://` address |
| Start over with an empty database (deletes all data) | `docker compose down -v && docker compose up -d --build` |
