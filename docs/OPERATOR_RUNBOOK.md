# Operator Runbook

This runbook describes the operator-facing capabilities of the AI Data Analytics Platform and how to check them.

## 1. Cleaning preview, cancel, and audit log

- Cleaning actions (single action and "Clean All") show a preview before anything is applied.
- The preview lists rows before and after, cells changed, columns affected, warnings, and a bounded sample of at most 20 changes.
- Cancel closes the preview. The apply endpoint is not called.
- Every applied cleaning action is recorded in the dataset's change log, with the action label, column, and timestamp.
- Preview endpoints do not modify the dataset and do not create undo snapshots:
  - `POST /api/dataset/{dataset_id}/clean/preview`
  - `POST /api/dataset/{dataset_id}/clean-all/preview`

## 2. Saved analyses

- Users can save named configurations for the dashboard, time series, forecast, anomaly check, and root-cause analysis.
- Endpoints (all authenticated and owner-scoped):
  - `GET /api/dataset/{dataset_id}/saved-analyses`
  - `POST /api/dataset/{dataset_id}/saved-analyses`
  - `GET /api/dataset/{dataset_id}/saved-analyses/{analysis_id}`
- Loading a saved analysis changes only the view controls. It never modifies the dataset.
- Each saved analysis stores the data version at save time. When the data has changed since then, the response sets `is_stale` to true, and the interface shows a stale-data warning.
- Saved anomaly and root-cause configurations are loaded with `explain=false`, so they do not request AI explanations and do not use AI quota.

## 3. Read-only dataset share links

- The owner creates a share link from the dataset list (expiry: 1 to 90 days, default 30).
- The full link is shown once. It cannot be displayed again, so the owner must copy it immediately.
- Only a SHA-256 hash of the token is stored. The plaintext token is never written to the database or to browser storage.
- Public viewer: `/shared/{token}` (API: `GET /api/shared/{token}`).
  - Returns the filename, a profile summary, and a preview of at most 10 rows.
  - Does not return owner email, plan, branding, or account data.
  - Does not use AI features or quota, and does not modify the dataset.
- Invalid, expired, and revoked tokens all return 404.
- Owners can list active links (token material is never listed) and revoke any link immediately.
- Deleting a dataset also removes its share links.

## 4. AI-generated labels and cache disclaimers

- AI-produced text (insights, anomaly explanations, root-cause explanations, and chat answers) is labelled "AI-generated" and carries a short verification note.
- A neutral note states that AI output may be cached until the dataset changes. Regenerate after cleaning or editing data.
- Deterministic outputs (KPI cards, charts, anomaly lists, root-cause tables, and methodology panels) are not labelled as AI.

## 5. Report fidelity

- PDF and PPTX reports include a **Methodology & Data Lineage** section for deterministic statistics.
- AI-written report sections, such as executive summary, recommendations, and anomaly explanation, carry an AI-generated disclaimer.
- Forecast sections are deterministic and are not labelled as AI.
- Automated PDF text extraction may show spacing artifacts because of font/kerning. Visual rendering is authoritative.

## 6. Request IDs for support

- Application API responses normally include an `X-Request-ID` header. A valid incoming `X-Request-ID` is reused; otherwise a UUID is generated.
- CORS preflight responses may be handled by the CORS middleware and are not guaranteed to include application middleware headers.
- The header is exposed to browsers through CORS, so support staff can match a user's report to a server log line.
- Each completed request writes one structured access line containing the request ID, method, normalized path, status code, and duration.
- Unhandled errors log the request ID, method, path, exception type, and a shortened, redacted message.
- Request bodies, headers, cookies, uploaded content, SQL text, prompts, and row values are not logged.
- Ask users for the request ID shown with an error, then search the server log for it.

## 7. Security headers

- Application API responses include `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a restrictive `Permissions-Policy`.
- Content-Security-Policy and HSTS are intentionally not set by the application. Configure HSTS at the TLS termination point for production.

## 8. Configuration notes

- Set `APP_SECRET_KEY` to the same value for every container and worker. Keep it out of source control.
- Optional: set `REQUIRE_APP_SECRET_KEY=1` to refuse to start without `APP_SECRET_KEY`.
- Sandboxed analysis code runs in a restricted container. Unsandboxed local execution is only allowed when `ALLOW_UNSAFE_LOCAL_EXEC=1` is set, and that setting must never be used in production.
- The shared rate limiter is off by default. Enable it with `RATE_LIMIT_SHARED=1` for multi-worker deployments.
- Keep all provider API keys in the environment or a secrets manager. Never place them in the repository or in logs.

## 9. Backend smoke tests

Install pytest in a development environment (it is intentionally not part of `requirements.txt`), then run from the project root:

```bash
python -m pytest backend/tests -q
```

- The tests use a temporary database for every test and do not contact external LLM providers or external services.
- `backend/tests/test_backend_smoke.py` checks ownership, clean preview, saved analyses, share links, SQL safety, and JSON-safe serialization.
- `backend/tests/test_runtime_sanity.py` checks that the critical modules and runtime packages import. Missing optional packages are reported as skipped.
- `backend/tests/test_report_smoke.py` checks deterministic report generation and report cleanup, writing only to a temporary directory.

## 10. Operational checklist

- After deployment, confirm that `/health` returns `{"status": "ok"}`.
- Run the smoke tests in a non-production environment before each release.
- Confirm that a normal API response carries an `X-Request-ID` header.
- Review the server log for `error_type=` lines after each release.
- Generate one PDF report and confirm the Methodology & Data Lineage section appears.
- Create one share link, revoke it, and confirm the public viewer returns 404.