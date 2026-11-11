# Changelog

## v1.1.0 — Deterministic Intelligence + Stability Hardening Release

### Added

- Deterministic Quality Report endpoint:
  - `GET /dataset/{dataset_id}/quality-report`
- Deterministic Quality Summary endpoint:
  - `GET /dataset/{dataset_id}/quality-summary`
- Deterministic Metric Catalog endpoint:
  - `GET /dataset/{dataset_id}/metric-catalog`
- Deterministic Narrative Summary endpoint:
  - `GET /dataset/{dataset_id}/narrative-summary`
- Deterministic Cleaning Plan endpoint:
  - `GET /dataset/{dataset_id}/cleaning-plan`
- Combined Dataset Intelligence endpoint:
  - `GET /dataset/{dataset_id}/intelligence`
- Production health endpoint:
  - `GET /health`
- Frontend Dataset Intelligence panel:
  - Quality Report tab
  - Metric Catalog tab
  - Narrative Summary tab
  - Cleaning Plan tab
  - Save/load intelligence configs
  - Download JSON
  - Download Markdown
  - Copy Markdown
  - Stale dataset warning
  - Version badge
  - Collapsible/auto-expand UI
- Frontend Quality Summary card:
  - Health score
  - Completeness
  - Missing cells
  - Duplicate rows
  - Issue count
  - Primary key candidates
  - Freshness
  - Cleaning plan summary
  - Download JSON
  - Download Markdown
  - Copy Markdown
  - Stale dataset warning
  - Collapsible/auto-expand UI
- Frontend Deterministic Cleaning Plan card:
  - Load/refresh cleaning plan
  - Select recommended action
  - View selected action request JSON
  - Copy selected action request JSON
  - Preview selected action
  - Apply previewed action with confirmation
  - Save selected cleaning config
  - Load saved cleaning config
  - Download plan JSON
  - Download plan Markdown
  - Copy plan Markdown
  - Stale dataset warning
  - Version badge
  - Collapsible/auto-expand UI
- Saved analysis support for deterministic intelligence types:
  - `quality_report`
  - `metric_catalog`
  - `narrative_summary`
  - `cleaning_plan`
- Optional saved analyses type filter:
  - `GET /dataset/{dataset_id}/saved-analyses?analysis_type=...`
- Deterministic executive summary fallback in reports:
  - `GET /dataset/{dataset_id}/report?include_deterministic_summary=true`
- Documentation:
  - `docs/DETERMINISTIC_INTELLIGENCE.md`
  - `docs/PRODUCTION_READINESS_CHECKLIST.md`
  - `docs/FINAL_RELEASE_NOTES.md`
  - `scripts/final_smoke.ps1`

### Improved

- Backend endpoint stability across upload, cleaning, undo, duplicate, rename, notes, shares, saved analyses, schedules, reports, account/auth, charts, pivot, correlation, compare, forecast, anomaly, root-cause, chat, SQL, and Python analysis.
- AI response JSON-safe normalization to reduce serialization crashes.
- Cleaning write-order safety:
  - dataset update happens before snapshot/log best-effort operations.
- Upload filename sanitization.
- SQL save-as-dataset filename sanitization.
- Report file path validation.
- Public share preview safety.
- Share link create/revoke security limiting.
- Scheduled export input validation and safer run-now handling.
- Account/password/email/deletion flow error handling.
- Rate-limit separation:
  - `llm_limiter`
  - `login_limiter`
  - `upload_limiter`
  - `export_limiter`
  - `report_limiter`
  - `sql_limiter`
  - `share_view_limiter`
  - `write_limiter`
  - `security_limiter`
- Frontend error messages made more request-ID-aware where backend provides request IDs.
- AI trust wording:
  - AI-generated labels
  - verification disclaimers
  - cache/freshness disclaimers
  - deployment-safe usage reset wording
- Deterministic features clearly labelled as:
  - `0 AI quota`
  - `Not AI-generated`
  - `Rule-based`
- Dataset-change synchronization:
  - cleaning plan apply dispatches `dataset-changed`
  - intelligence panel shows stale warning
  - quality summary card shows stale warning
  - cleaning plan card shows stale warning
- Frontend malformed-data guards across tables, charts, chat results, compare datasets, correlation heatmap, saved analyses, history search, and shared preview.

### Preserved

- No existing user-facing feature was deleted.
- AI Cleaning Advisor remains available.
- AI Insight remains available.
- Chat With Your Data remains available.
- AI SQL Query remains available.
- Python Analysis remains available.
- Forecast remains available.
- Anomaly Detection remains available.
- Root Cause Analysis remains available.
- Time Series Explorer remains available.
- Pivot, Correlation, Compare Datasets remain available.
- Share Links remain available.
- Scheduled Exports remain available.
- Reports remain available.
- Account management remains available.

### Verification

- Backend tests:
  - `63 passed, 4 skipped`
- Frontend production build:
  - clean build
  - `681 modules transformed`