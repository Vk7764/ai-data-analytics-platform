# Quickstart

## 1. Project purpose

AI Data Analytics Platform is an AI-assisted data analytics application. It supports:

- Dataset upload (CSV, Excel, JSON, SQL) and automatic profiling
- Cleaning with preview before apply, cancel, undo, and an audit log
- Saved analyses for the dashboard, time series, forecast, anomaly check, and root cause
- Read-only dataset share links
- Reports (PDF, Excel, PowerPoint, CSV, JSON, SQL)
- Forecasts, anomaly detection, root-cause analysis, and chat with your data
- Scheduled report exports where enabled
- Sandboxed execution of generated analysis code where configured

## 2. Local development setup

Run the backend and the frontend in separate terminals, from the project root.

**Backend (FastAPI):**

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

**Frontend (React + Vite):**

```bash
cd frontend
npm install
npm run dev
```

The frontend development server commonly runs at `http://localhost:5173`. If your frontend uses a different origin, configure the backend CORS setting used by your deployment so that only trusted origins are allowed.

If your backend exposes a health endpoint, check it after startup, for example:

```text
http://localhost:8000/health
```

## 3. Backend smoke tests

Install pytest in your development environment (it is intentionally not part of `requirements.txt`), then run from the project root:

```bash
python -m pytest backend/tests -q
```

The tests use a temporary database and do not contact external AI providers.

## 4. Operator runbook

Operational details, such as deployment checks, release checks, report/share quick validations, and log lookup by request ID, are in `docs/OPERATOR_RUNBOOK.md`.

## 5. Security and configuration

- **`APP_SECRET_KEY`**: set the same value for every container and worker. Keep it out of source control. Optionally set `REQUIRE_APP_SECRET_KEY=1` to refuse startup without it.
- **`ALLOW_UNSAFE_LOCAL_EXEC`**: never set this in production. It allows analysis code to run without the sandbox.
- **`RATE_LIMIT_SHARED`**: set to `1` for multi-worker deployments so rate limits are shared through the database.
- **Provider API keys**: store them in environment variables or a secrets manager only. Never commit them or write them to logs.
- **CORS**: allow only trusted frontend origins. Do not use wildcard origins in production unless explicitly reviewed.

## 6. AI trust and reporting

- AI-produced text (insights, explanations, and chat answers) is labelled “AI-generated” and carries a verification note.
- A neutral note states that AI output may be cached until the dataset changes. Regenerate it after cleaning or editing data.
- Deterministic outputs (KPI cards, charts, anomaly lists, root-cause tables, and methodology panels) are not labelled as AI.
- Reports include a methodology and data-lineage section for deterministic parts. AI-written report sections are labelled in PDF and PowerPoint output.
- Forecast sections are deterministic and are not labelled as AI.

## 7. Sharing

- Read-only share links are created by the dataset owner. The full link is shown once and must be copied immediately.
- Only a SHA-256 hash of the token is stored. The plaintext token is not stored in the database or browser storage.
- The public viewer (`/shared/{token}`) shows the filename, a profile summary, and a preview of at most 10 rows. It does not show owner account data.
- Links expire after 1 to 90 days, with a default of 30 days. Owners can revoke a link at any time.
- Invalid, expired, and revoked links all return “not found”.