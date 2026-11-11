# Release Checklist

Use this checklist before every release. Complete each item in a non-production environment first.

## 1. Backend startup

- [ ] Install dependencies from `requirements.txt` in a clean virtual environment.
- [ ] Start the backend (`uvicorn backend.main:app --port 8000`) without errors.
- [ ] `APP_SECRET_KEY` is set to the same value for every container and worker.
- [ ] `ALLOW_UNSAFE_LOCAL_EXEC` is not set in production.

## 2. Health endpoint

- [ ] If your deployment exposes a health endpoint, `GET /health` returns `{"status": "ok"}`.
- [ ] If no health endpoint is configured, confirm from backend startup logs that the app is listening.

## 3. Frontend build and smoke check

- [ ] `npm run build` completes in the `frontend` directory without errors.
- [ ] `npm run dev` starts, and the login page loads at the configured origin.
- [ ] Upload, cleaning preview, and the dashboard load with a sample dataset.

## 4. Backend smoke tests

- [ ] Run `python -m pytest backend/tests -q` from the project root.
- [ ] All tests pass, or skipped optional-package tests have a clear reason.
- [ ] No unexpected failures, collection errors, or import errors appear.

## 5. Report generation

- [ ] Generate a PDF and a PowerPoint report for a sample dataset.
- [ ] Methodology or data-lineage content is present for deterministic sections.
- [ ] AI-written sections are labelled "AI-generated" when they are present.
- [ ] Forecast sections are not labelled as AI.
- [ ] PDF visual rendering is checked manually. Automated PDF text extraction may show spacing artifacts because of font/kerning; visual rendering is authoritative.

## 6. Share links

- [ ] Create a read-only share link as the dataset owner. The full link is displayed once.
- [ ] Open the link in a private browser window. The preview and profile load.
- [ ] Confirm the public viewer shows only bounded preview/profile data and no owner account data.
- [ ] Revoke the link. Opening it again returns "not found".

## 7. Saved analyses

- [ ] Save a dashboard, time-series, forecast, anomaly, or root-cause configuration.
- [ ] Change the dataset in a test copy. Load the saved analysis. The stale-data warning appears.
- [ ] Loading a saved analysis does not change the dataset.
- [ ] Loading a saved anomaly or root-cause configuration does not consume AI quota unless the user explicitly requests an AI explanation.

## 8. Request ID and security headers

- [ ] Normal application API responses include an `X-Request-ID` header.
- [ ] Normal application API responses include `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Permissions-Policy`.
- [ ] CORS preflight responses may be handled separately and are not required for this check.

## 9. Secrets and configuration

- [ ] No AI provider API keys, tokens, or `.env` files are committed to the repository.
- [ ] Provider keys are supplied through environment variables or a secrets manager.
- [ ] `APP_SECRET_KEY` is not stored in source control.

## 10. Sign-off

- [ ] Release notes list the changes, known limitations, and any configuration changes.
- [ ] The operator runbook (`docs/OPERATOR_RUNBOOK.md`) reflects the release.
- [ ] The quickstart (`docs/QUICKSTART.md`) reflects the release.