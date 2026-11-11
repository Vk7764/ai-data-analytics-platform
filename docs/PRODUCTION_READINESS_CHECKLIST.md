# Production Readiness Checklist

This checklist is for deploying and operating the Data Analytics app safely.

It does not change application behavior. It documents the current safety, observability, and operational practices added during the stability/intelligence batches.

---

## 1. Service Health

### Health endpoint

The API exposes a lightweight health endpoint:

```text
GET /health
```

Example response:

```json
{
  "status": "ok",
  "service": "data-analytics-api",
  "timestamp": "2026-11-11T10:00:00+00:00",
  "ai_generated": false
}
```

Use this for:

- uptime monitoring
- load balancer health checks
- container restart probes
- basic incident triage

Important:

- `/health` does not require authentication.
- `/health` does not access user datasets.
- `/health` does not consume AI quota.

---

## 2. Environment Configuration

Before production deployment, verify these categories:

### API / backend

- Secret/session signing keys
- Database/storage paths
- AI provider keys, if AI features are enabled
- SMTP/email sender settings
- Rate limit configuration
- Upload size limits
- Report/temp file directories

### Frontend

- API base URL
- Production build environment variables
- Sentry/error monitoring DSN, if used
- Feature flags, if any

### General

- Timezone expectations
- Backup schedule
- Log retention policy
- SSL/TLS termination
- Reverse proxy timeout settings

Do not commit real secrets to git.

---

## 3. Storage and Backups

The app stores user datasets, metadata, notes, shares, saved analyses, schedules, and generated reports.

Production should have:

- regular database/storage backups
- upload directory backups
- report/temp directory cleanup policy
- restore drill before launch
- documented retention period for:
  - datasets
  - share links
  - saved analyses
  - scheduled exports
  - audit logs
  - generated reports

Recommended:

- nightly backups for structured storage
- object-storage/file backup for uploads and reports
- tested restore procedure
- separated staging and production storage

---

## 4. Rate Limits

The backend uses separated rate limiters for different classes of traffic:

```text
llm_limiter        AI-powered endpoints
login_limiter      auth brute-force protection
upload_limiter     file uploads
export_limiter     chart/export endpoints
report_limiter     report generation + schedule run-now
sql_limiter        local SQL queries
share_view_limiter public read-only share viewer
write_limiter      lightweight DB writes
security_limiter   share link create/revoke
```

Production review should confirm these limits match expected traffic.

If behind a reverse proxy, ensure client IP forwarding is configured correctly so rate limiting sees real client IPs, not only proxy IPs.

---

## 5. Security Hygiene

Current safeguards added across batches include:

- ownership checks for dataset endpoints
- public share token resolution guards
- share link create/revoke rate limiting
- upload filename sanitization
- SQL save-as-dataset filename sanitization
- report file path validation
- branding accent color validation
- report logo bytes validation
- account deletion password/attempt guards
- email verification requirements for sensitive actions
- request-ID-aware frontend error messages
- JSON-safe backend response normalization

Production should additionally review:

- HTTPS enforced everywhere
- secure cookies where applicable
- CSP headers for frontend
- CORS restricted to known frontend origins
- API keys/secrets rotated periodically
- admin/support access audited
- email links HTTPS-only
- temporary report files cleaned regularly

---

## 6. Observability

Recommended production logging:

- request logs with:
  - timestamp
  - method
  - path
  - status code
  - latency
  - user ID where safe
  - request ID where available
- error logs with stack traces stored server-side, not exposed to users in production
- AI provider usage logs
- quota usage logs
- upload failures
- report generation failures
- share link invalid/expired/revoked access attempts
- schedule delivery failures

Frontend error messages may include request IDs when backend provides them. Support should ask users for:

- dataset ID
- action attempted
- timestamp
- visible error message
- request ID if shown
- browser console errors
- whether data was modified
- whether undo was attempted

---

## 7. AI Quota vs Deterministic Features

AI-generated features may consume quota:

- AI Insight
- AI Cleaning Advisor
- AI anomaly explanation
- AI root-cause explanation
- AI SQL generation
- AI Python code generation
- AI chat replies

Deterministic features do **not** consume AI quota:

- Quality Report
- Quality Summary
- Metric Catalog
- Narrative Summary
- Cleaning Plan
- Combined Intelligence
- Deterministic report fallback

UI labels distinguish these:

```text
AI-generated
0 AI quota
Not AI-generated
Rule-based
```

Operationally, deterministic features can be used as fallback when AI provider is down or quota is exhausted.

---

## 8. Report Generation

Report endpoint:

```text
GET /dataset/{dataset_id}/report
```

Supported formats include:

- pdf
- excel/xlsx
- pptx
- csv
- json
- sql

Important production notes:

- report generation is protected by `report_limiter`
- expired report cleanup failures are non-fatal
- invalid report paths return clean errors instead of crashing
- premium branding logo/accent validation prevents malformed branding crashes
- deterministic executive summary fallback can be enabled/disabled with:

```text
include_deterministic_summary=true
```

Default is `true`.

---

## 9. Sharing and Public Access

Share links are read-only public previews.

Operational rules:

- share token material is not returned in owner-facing share lists
- invalid/expired/revoked links return a generic unavailable message
- public share viewer uses `share_view_limiter`
- preview is bounded to 10 rows
- owner account details are not disclosed through public share endpoint

Before production launch, verify:

- share link expiry behavior
- revoke behavior
- HTTPS links
- email link domain correctness
- no sensitive columns exposed unexpectedly in preview/profile

---

## 10. Scheduled Exports

Scheduled exports are premium features.

Production checks:

- email delivery works
- webhook destinations are allowed and validated
- schedule run-now uses report limiter
- failed deliveries are marked safely
- schedule deletion is rate-limited/store-safe
- schedules tied to deleted datasets are cleaned safely

Recommended:

- monitor failed schedule deliveries
- alert on repeated email/webhook failures
- keep schedule audit/history for support debugging

---

## 11. Frontend Build and Static Serving

Before deployment:

```powershell
Push-Location .\frontend
npm run build
Pop-Location
```

Expected:

```text
✓ built in ...
```

Serve the generated `frontend/dist` assets through:

- HTTPS
- correct cache headers
- SPA fallback only where needed
- static asset compression, e.g. gzip/brotli

After backend changes:

```powershell
.\venv\Scripts\activate
python -m pytest backend/tests -q
```

Expected:

```text
63 passed, 4 skipped
```

---

## 12. Rollback Plan

Before release:

- tag git commit
- backup database/storage
- keep previous frontend build artifacts
- keep previous backend container/package version ready

If release fails:

1. stop traffic if needed
2. restore previous backend version
3. restore previous frontend assets
4. verify `/health`
5. run smoke tests
6. restore backups only if data corruption is suspected

---

## 13. Post-Deploy Smoke Test

Minimum production smoke test:

### API

- `GET /health` returns `status: ok`
- login works
- signup/verification flow works if enabled
- dataset upload works
- dataset profile loads
- rows table loads
- chart loads
- pivot loads
- correlation loads
- compare datasets loads
- chat loads
- AI insight loads if quota available
- quality summary loads
- intelligence panel loads
- cleaning plan loads
- cleaning preview works
- cleaning apply + undo works
- share link create/revoke works
- public share viewer works
- report PDF/Excel/CSV downloads work
- account page loads
- usage badge loads

### Console

- no new red browser console errors
- no uncaught React errors
- no failed critical API calls in Network tab

---

## 14. Current Known Operational Signals

The app now has several operational signals:

- request-ID-aware frontend errors
- deterministic intelligence endpoints
- deterministic cleaning plan preview/apply workflow
- dataset-changed stale warnings
- JSON/Markdown exports for intelligence and cleaning plans
- saved intelligence/cleaning configs
- report deterministic fallback
- backend response JSON-safe normalization
- separated rate limiters
- health endpoint

These are intended to make support, debugging, and production operation easier without removing existing user-facing features.