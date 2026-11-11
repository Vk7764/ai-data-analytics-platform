# Security Overview

This document summarizes the security controls implemented in the AI Data Analytics Platform for operators and reviewers. It is an implementation-level overview, not a formal penetration test or compliance certification. Where a control depends on deployment configuration, the wording says so. For operational steps, see [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) and [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md).

## 1. Owner-scoped data access

- Datasets, saved analyses, and share-link management are scoped to the owning account.
- Requests for another user's private resources return not-found or permission errors where implemented.

## 2. Read-only share links

- Only a SHA-256 hash of each share token is stored. The plaintext token is shown once at creation and is not stored in the database or in browser storage.
- The public viewer (`/shared/{token}`) returns only a bounded preview and a profile summary.
- The public viewer does not expose owner account data.
- Owners can list active links, and token material is never listed. Owners can revoke any link immediately. Expired and revoked links are rejected.
- Share links should not be used for datasets containing sensitive personal information unless the owner accepts that risk.

## 3. Cleaning safety

- Cleaning previews are non-destructive. They do not modify the dataset and do not create undo snapshots.
- Applied cleaning actions are recorded in the dataset change log.

## 4. Saved analyses

- Saved analyses are owner-scoped and store the data version at save time.
- Loading a saved analysis changes only view controls and never modifies the dataset.
- A stale-data warning is shown when the dataset has changed since the save.
- Saved anomaly and root-cause loads request no AI explanation, so they do not consume AI quota unless the user explicitly requests one.

## 5. SQL analysis

- SQL analysis is intended to be read-only. Where implemented, non-SELECT statements and dangerous keywords are rejected.
- SQL upload validation depends on the configured parser or allowlist. Specific statement restrictions should be confirmed from the deployment code or configuration before being promised to users.

## 6. Sandboxed code execution

- Generated analysis code runs in a sandbox where it is configured.
- `ALLOW_UNSAFE_LOCAL_EXEC` must not be enabled in production. It disables the sandbox requirement and is intended only for development.

## 7. Logging and request IDs

- Normal application API responses include an `X-Request-ID` header to support debugging. CORS preflight responses may be handled separately.
- Access logs record the request ID, method, normalized path, status code, and duration.
- Error logs record the exception type and a shortened, redacted message, with email addresses masked.
- Logs are designed not to contain request bodies, uploaded content, Authorization headers, cookies, passwords, SQL text, AI prompts, dataset row values, or plaintext share tokens.
- Log retention should follow the deployment privacy policy.

## 8. Security headers

- Normal API responses include `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a restrictive `Permissions-Policy`.
- Content-Security-Policy and Strict-Transport-Security are intentionally not set by the application. Configure them at the TLS termination or reverse-proxy layer where applicable.

## 9. Secrets and provider keys

- `APP_SECRET_KEY` must be the same for every container and worker and must not be committed. Optionally set `REQUIRE_APP_SECRET_KEY=1` to refuse startup without it.
- Provider API keys must be supplied only through environment variables or a secrets manager and must never be committed to the repository.

## 10. AI output labelling

- AI-produced text is labelled "AI-generated" and carries a verification note.
- A cache and freshness disclaimer states that AI output may be cached until the dataset changes.
- Deterministic outputs, such as KPI cards, charts, anomaly lists, root-cause tables, and methodology panels, are not labelled as AI.

## 11. Reporting a security issue

- Report suspected vulnerabilities to the deployment's designated security contact. Do not include secrets, tokens, or customer data in the report.