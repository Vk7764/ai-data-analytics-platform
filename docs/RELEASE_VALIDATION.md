# Release Validation

## 1. Scope

This document is the final pre-ship gate for a release candidate. It references `docs/RELEASE_CHECKLIST.md`, `docs/DEPLOYMENT_CHECKLIST.md`, `docs/SECURITY.md`, `docs/CHANGELOG.md`, and `docs/OPERATOR_RUNBOOK.md` rather than duplicating them. Complete those documents alongside this gate.

## 2. Automated gates (must pass before ship)

- [ ] Backend smoke tests pass: `python -m pytest backend/tests -q` (run from the project root). Skipped optional-package tests show a clear reason.
- [ ] Documentation link integrity is verified by the same pytest run (`backend/tests/test_docs_links.py`), including `docs/README.md` index links and root `README.md` docs links.
- [ ] Deprecated-pattern regression guard passes (`backend/tests/test_deprecated_patterns.py`), covered by the same pytest run.
- [ ] Frontend build succeeds: `npm run build` inside the `frontend` directory, with no errors.
- [ ] Runtime sanity checks pass (`backend/tests/test_runtime_sanity.py`), covered by the same pytest run.

> Note: deprecation and informational warnings in the pytest output (for example `datetime.utcnow()`, `fpdf` `ln=True`, or FastAPI `on_event`) do not fail this gate. The gate is based on the pass/fail/skip counts. Only treat warnings as errors, or set a `--max-warnings` threshold, if the deployment policy explicitly requires it.

## 3. Manual gates (must be checked in staging)

- [ ] Login, upload, dashboard, report, and share-link happy paths work.
- [ ] One report is generated. The methodology or data-lineage section is present, AI sections are labelled when present, and the forecast is not labelled as AI.
- [ ] One read-only share link is created and then revoked.
- [ ] One saved analysis is loaded after a dataset change, and the stale-data warning appears.
- [ ] A normal API response carries `X-Request-ID` and the three conservative security headers (`X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`).

## 4. Configuration gates

- [ ] `APP_SECRET_KEY` is set consistently across all containers and workers, and is not committed.
- [ ] Provider API keys are supplied only through environment variables or a secrets manager.
- [ ] CORS allows only trusted origins.
- [ ] `ALLOW_UNSAFE_LOCAL_EXEC` is not set in production.
- [ ] `RATE_LIMIT_SHARED` is enabled for multi-worker deployments where shared rate limiting is required.

## 5. Privacy and AI disclosure gates

- [ ] AI-generated labels and cache/freshness disclaimers are visible in the UI and in reports.
- [ ] The public share viewer does not expose owner account data.
- [ ] No exact quota reset times, upload limits, or provider behavior are promised unless the deployment configuration confirms them.

## 6. Sign-off

- [ ] `docs/CHANGELOG.md` is updated.
- [ ] The `docs/README.md` documentation index is valid.
- [ ] No secrets or customer data are committed.
- [ ] Release notes list the changes, known limitations, and configuration changes.

## 7. Rollback

If any gate fails, do not ship. Revert the release candidate, re-run the automated gates, and record the failure and its resolution in the release notes.