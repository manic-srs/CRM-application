# SalesTrack — React frontend

React + Vite UI integrated with the team's FastAPI backend in `../backend`. The backend owns persistence, validation, stage transitions, conversion, follow-up automation, notes, and notifications. This frontend no longer uses localStorage or frontend sample records; it displays records supplied by the backend, including its sample database.

## Run the team backend

With Docker Desktop running, in a terminal from this `frontend` folder:

```sh
cd ..
docker compose up --build
```

Follow the backend's own README for database configuration. Its default Docker API URL is `http://127.0.0.1:8001`, with API docs at `/docs`. The frontend does not change the backend repository, schema, or seed data. Docker's first-time initialization may load the team's existing seed data; the frontend displays whatever records the backend returns.

## Run the frontend

In another terminal, from the repository's `frontend` folder:

```sh
npm install
npm run dev
```

Open the URL printed by Vite. Requests to `/api` are proxied to port 8001, so both `localhost` and `127.0.0.1` frontend URLs work without changing CORS.

If your backend runs elsewhere, copy `.env.example` to `.env.local`, set `API_PROXY_TARGET` to that backend's origin (without `/api`), and restart Vite. This is a development proxy setting. Never place passwords or private API keys in `VITE_*` variables.

For a built frontend, configure hosting to proxy `/api`, or set the public `VITE_API_BASE_URL` during the build and configure the backend to allow the deployed frontend origin. `npm run preview` also uses the development proxy configuration.

## Behavior matched to the backend

- **Home:** metrics, pipeline, due/overdue follow-ups, and Won/Lost results use `GET /api/home`. Zero summary values remain visually blank.
- **Leads:** separate first/last names; last name and company required; optional email; backend source/salutation choices; owners loaded from `/users`; demo scheduling supported.
- **Lifecycle:** New → Nurturing → Demo → Converted/Lost. Leads cannot be Won directly. Conversion creates an account (or uses a selected account), contact, and opportunity.
- **Opportunities:** created through conversion, with expected value, expected close date, probability, owner, and primary contact. Only existing opportunities can be edited. Proposal updates probability to 75%; Won uses an entered final value or the expected value.
- **Tasks:** server-created follow-ups are identified as Automatic. Stage changes and closure auto-close old follow-ups. Statuses are Open, Done, and Auto-closed; priorities are Low, Normal, and High. Completed tasks cannot be reopened. Existing task relationships cannot be edited because the backend doesn't support that operation.
- **Lost:** required reason from the backend's allowed choices, with optional details.
- **Notes and history:** notes use `/notes`; record detail responses supply notes and authoritative stage history. Notes are added separately rather than pretending a record edit saves them.
- **Notifications:** choose an actual backend user in the bell menu to load their notifications. Clicking a notification marks it read and opens Tasks. No fake identity is selected.
- **Loading/errors:** failed saves remain in the form; load errors offer Reload data. Successful writes that fail to refresh produce an explicit saved-but-refresh-failed notice.

### Current backend limitations

There is **no currency field** and **no estimated-value field on a lead** in the cloned schemas. The UI therefore collects expected value during conversion/opportunity editing, displays numeric amounts without assuming INR or another currency, and does not pretend to persist currency selections. To restore preferred currencies, the team must add currency support to the API and database.

The backend currently checks login credentials without issuing tokens, and its endpoints do not enforce token authentication. The requested direct-to-dashboard behavior remains; this work does not add a demo login or invent an authentication mechanism. Follow the team's security plan before deployment.

The backend defines due dates, overdue flags, and dashboard day grouping using its server time. The UI uses those returned flags and home results rather than applying a different day boundary for filtering.

Previously saved browser-only records are left untouched and are not automatically imported into the team database.

## Checks

```sh
npm test
npm run build
```

The nine frontend tests cover payload contracts, IDs, task statuses, backend-supplied dashboard results, lifecycle endpoint routing, and readable errors. The team's existing backend suite can be run following its README.

An optional live integration test exercises a complete lifecycle. It creates records and must run **only against a disposable database**, never shared team data. Point a separate Vite instance at the isolated backend, then run:

```sh
CRM_TEST_ORIGIN=http://127.0.0.1:5175 npm run test:integration
```

Without `CRM_TEST_ORIGIN`, the live test is skipped. It covers lead creation/editing, demo scheduling, auto-closure, manual task completion, conversion, opportunity edits, Proposal/Won, Lost validation, notes, dashboard results, and notification reads.

## Source

- `src/main.jsx`: screens, sidebar, backend-aligned forms, and dialogs.
- `src/api.js`: request handling, payload serializers, record adapters, and endpoint actions.
- `src/useWorkspace.js`: loading and refreshing API state, confirmed mutations, and failure handling.
- `src/domain.js`: backend dropdown constants, formatting, and dashboard adapter.
- `vite.config.js`: development/preview API proxy.
- `.env.example`: configurable local backend target.
