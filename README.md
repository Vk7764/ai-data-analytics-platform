---
title: AI Data Analytics Backend
emoji: 📊
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
---

# AI Data Analytics Platform

AI-assisted data analytics platform for dataset profiling, cleaning previews, saved analyses, reports, forecasts, anomaly detection, root-cause analysis, chat with data, scheduled exports, and sandboxed analysis execution.

## Documentation

- Documentation index: [`docs/README.md`](docs/README.md)
- Quickstart: [`docs/QUICKSTART.md`](docs/QUICKSTART.md)
- Operator runbook: [`docs/OPERATOR_RUNBOOK.md`](docs/OPERATOR_RUNBOOK.md)

## Main capabilities

- Upload CSV, Excel, JSON, and SQL datasets
- Automatic dataset profiling
- Cleaning preview before apply, cancel support, undo, and audit log
- Saved analyses for dashboard, time series, forecast, anomaly check, and root cause
- Read-only dataset share links with expiry and revoke support
- Report generation: PDF, Excel, PowerPoint, CSV, JSON, and SQL export
- Forecasts, anomaly detection, root-cause analysis, and AI chat
- AI-generated text labels and verification/cache disclaimers
- Report methodology and data-lineage sections
- Backend request IDs for support debugging
- Conservative security headers
- Backend smoke tests using a temporary database

## Local development

First, copy `.env.example` to `.env` and fill in your values. At minimum set
`APP_SECRET_KEY`, `FRONTEND_URL`, `APP_CORS_ORIGINS`, your AI provider keys,
and the Gmail credentials for email features.

Run backend and frontend in separate terminals from the project root.

Backend:

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The frontend development server commonly runs at `http://localhost:5173`. Configure backend CORS for trusted origins only.

## Tests

Install pytest in a development environment. Pytest is intentionally not part of runtime `requirements.txt`.

```bash
python -m pytest backend/tests -q
```

The backend tests use a temporary database and do not contact external AI providers.

## Security and configuration highlights

- Set `APP_SECRET_KEY` consistently across containers/workers and keep it out of source control.
- Optionally set `REQUIRE_APP_SECRET_KEY=1` to refuse startup without `APP_SECRET_KEY`.
- Never set `ALLOW_UNSAFE_LOCAL_EXEC=1` in production.
- Set `RATE_LIMIT_SHARED=1` for multi-worker deployments if shared rate limiting is needed.
- Store provider API keys only in environment variables or a secrets manager.
- Do not commit secrets, tokens, customer data, PII examples, or provider keys.

## AI trust and reporting

- AI-produced insights, explanations, and chat answers are labelled as AI-generated.
- AI output may be cached until the dataset changes; regenerate after cleaning or editing data.
- Deterministic outputs such as KPI cards, charts, anomaly lists, root-cause tables, and methodology panels are not labelled as AI.
- PDF and PowerPoint reports include methodology/data-lineage sections and label AI-written sections separately.

## Read-only sharing

- Dataset owners can create read-only share links.
- The full link is shown once and must be copied immediately.
- Only a SHA-256 hash of the token is stored.
- Public viewer shows filename, profile summary, and a bounded preview of at most 10 rows.
- Links can expire and can be revoked by the owner.
- Invalid, expired, and revoked links return “not found”.