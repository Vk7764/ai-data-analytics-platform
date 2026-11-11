# Deployment Checklist

Use this checklist for every production deployment. Where a behavior depends on deployment policy or configuration, the wording says so.

## 1. Pre-deployment

- [ ] Code changes are merged and have been tested in a non-production environment.
- [ ] Backend smoke tests pass: `python -m pytest backend/tests -q` (run from the project root).
- [ ] Frontend build succeeds: `npm run build` (run inside the `frontend` directory).
- [ ] `docs/RELEASE_CHECKLIST.md` has been reviewed and completed.

## 2. Required configuration

- [ ] `APP_SECRET_KEY` is set to the same value for every container and worker, and is kept out of source control.
- [ ] Optionally, `REQUIRE_APP_SECRET_KEY=1` is set so the backend refuses to start without `APP_SECRET_KEY`.
- [ ] Provider API keys are supplied only through environment variables or a secrets manager.
- [ ] CORS allows only trusted frontend origins.

## 3. Optional and runtime configuration

- [ ] `RATE_LIMIT_SHARED` is enabled for multi-worker deployments if shared rate limiting is required.
- [ ] `ALLOW_UNSAFE_LOCAL_EXEC` is not enabled in production.
- [ ] Sandbox and container settings for generated analysis code follow the deployment security policy.
- [ ] Report output location and retention settings follow the operational storage policy.

## 4. Database and storage

- [ ] If the deployment uses local SQLite, the database file is on persistent storage.
- [ ] Backups are taken before a migration or release, where the deployment policy requires it.
- [ ] Operators understand that deleting a dataset also removes its share links and saved analyses.

## 5. Post-deployment smoke checks

- [ ] The backend starts without errors.
- [ ] If a health endpoint is configured, it returns OK.
- [ ] Normal API responses include an `X-Request-ID` header.
- [ ] Normal API responses include `X-Content-Type-Options`, `Referrer-Policy`, and `Permissions-Policy`.
- [ ] Login, upload, dashboard, report, and share-link flows are checked in a staging or non-production environment.
- [ ] One report is generated. The methodology or data-lineage section is present, and AI sections are labelled when they appear.
- [ ] One read-only share link is created and then revoked.

## 6. Logging and support

- [ ] Request-ID logging is enabled, and log retention follows the privacy policy.
- [ ] Logs are designed not to contain request bodies, uploaded content, Authorization headers, cookies, passwords, SQL text, AI prompts, dataset row values, or plaintext share tokens; email addresses in exception messages are redacted.
- [ ] Support staff use `docs/SUPPORT_GUIDE.md` for request-ID based debugging.

## 7. Privacy and AI provider disclosure

- [ ] `docs/OPERATOR_RUNBOOK.md` and `docs/USER_GUIDE.md` have been reviewed for user-facing privacy and AI disclosure behavior.
- [ ] Public share links do not expose owner account data.
- [ ] No exact quota reset times, upload limits, or provider behavior are promised to users unless the deployment configuration confirms them.

## 8. Sign-off

- [ ] Release notes are updated.
- [ ] `docs/CHANGELOG.md` reflects the completed work.
- [ ] The `docs/README.md` documentation index remains valid.
- [ ] No secrets or customer data are committed to the repository.