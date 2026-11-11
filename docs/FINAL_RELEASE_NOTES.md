# Final Release Notes — v1.1.0

This release closes the major stability, deterministic intelligence, cleaning governance, AI trust, and production-readiness workstream.

---

## 1. Release Summary

Version:

```text
v1.1.0
```

Theme:

```text
Deterministic Intelligence + Stability Hardening + Production Readiness
```

This release adds a rule-based analytics layer that does not consume AI quota, improves cleaning governance, hardens backend/frontend failure paths, and adds operational documentation.

---

## 2. What is new for users?

### Dataset Intelligence

Users now have a deterministic intelligence panel with:

- Quality Report
- Metric Catalog
- Narrative Summary
- Cleaning Plan

This panel is labelled:

```text
0 AI quota
Not AI-generated
Rule-based
```

It supports:

- Load/Refresh
- Save current view
- Load saved config
- Download JSON
- Download Markdown
- Copy Markdown
- Stale dataset warning
- Version badge
- Collapse/expand

---

### Quality Summary Card

Dataset profile now includes a compact quality card:

- Health score
- Completeness
- Missing cells
- Duplicate rows
- Issue count
- Primary key candidates
- Freshness
- Recommended cleaning plan

It supports:

- Load/Refresh
- Download JSON
- Download Markdown
- Copy Markdown
- Stale warning
- Collapse/expand

---

### Deterministic Cleaning Plan

Inside Data Quality Check, users can now load a rule-based cleaning plan.

The plan shows:

- recommended action
- target column
- risk level
- reason
- preview request

Users can:

- select an action
- view request JSON
- copy request JSON
- preview action safely
- apply previewed action with confirmation
- save selected cleaning config
- load saved cleaning config
- download plan JSON/Markdown
- copy plan Markdown

Important:

- The cleaning plan does not modify data automatically.
- Apply is only possible after preview.
- Existing undo remains available.

---

## 3. What is new for operators/support?

### Health endpoint

```text
GET /health
```

Returns:

```json
{
  "status": "ok",
  "service": "data-analytics-api",
  "timestamp": "...",
  "ai_generated": false
}
```

Useful for:

- uptime monitoring
- load balancer checks
- container probes

---

### Deterministic endpoints

New endpoints:

```text
GET /dataset/{dataset_id}/quality-report
GET /dataset/{dataset_id}/quality-summary
GET /dataset/{dataset_id}/metric-catalog
GET /dataset/{dataset_id}/narrative-summary
GET /dataset/{dataset_id}/cleaning-plan
GET /dataset/{dataset_id}/intelligence
```

These do not use AI quota.

---

### Saved analyses type filter

```text
GET /dataset/{dataset_id}/saved-analyses?analysis_type=cleaning_plan
```

Supported deterministic types:

```text
quality_report
metric_catalog
narrative_summary
cleaning_plan
```

---

### Report deterministic fallback

Report endpoint supports:

```text
GET /dataset/{dataset_id}/report?include_deterministic_summary=true
```

Default:

```text
true
```

If AI executive summary is unavailable, the report includes a deterministic summary labelled:

```text
Deterministic summary (rule-based, not AI-generated):
```

---

## 4. Stability improvements

Backend and frontend were hardened across major flows:

- upload
- dataset list
- dataset delete
- clean
- clean-all
- undo
- duplicate
- rename
- notes
- saved analyses
- share links
- public share preview
- SQL query
- SQL save-as-dataset
- chart
- histogram
- pivot
- correlation
- compare datasets
- forecast
- anomaly detection
- root cause
- time series
- chat
- AI insights
- AI cleaning advice
- reports
- account/auth
- scheduled exports

Key principles:

- unexpected store/engine/AI failures should produce clean errors instead of raw crashes
- malformed response shapes should be normalized safely
- successful mutations should not be falsely reported as failures due to secondary logging/profile failures
- frontend should not crash on unexpected backend shapes
- AI output should be clearly labelled
- deterministic output should be clearly labelled as zero-quota

---

## 5. AI trust improvements

AI-generated features now have clearer labels/disclaimers:

- AI Cleaning Advisor:
  - `AI-generated`
  - verify recommendations
  - output may be cached until dataset changes
- AI Insight / anomaly explanation wording:
  - cached output may be reused if dataset has not changed
- Usage badge:
  - reset timing depends on deployment configuration

Deterministic features are clearly separated:

- `0 AI quota`
- `Not AI-generated`
- `Rule-based`

---

## 6. Rate-limit separation

Limiters are now separated by workload:

```text
llm_limiter
login_limiter
upload_limiter
export_limiter
report_limiter
sql_limiter
share_view_limiter
write_limiter
security_limiter
```

This reduces cross-workload interference.

---

## 7. Documentation

Added:

```text
docs/DETERMINISTIC_INTELLIGENCE.md
docs/PRODUCTION_READINESS_CHECKLIST.md
docs/FINAL_RELEASE_NOTES.md
CHANGELOG.md
scripts/final_smoke.ps1
```

---

## 8. Verification status

Backend:

```text
63 passed, 4 skipped
```

Frontend:

```text
✓ built in ...
681 modules transformed
```

---

## 9. Recommended final smoke command

From project root:

```powershell
.\scripts\final_smoke.ps1
```

Or manually:

```powershell
.\venv\Scripts\activate
python -m pytest backend/tests -q
Push-Location .\frontend
npm run build
Pop-Location
```

---

## 10. Suggested release commit

```powershell
git add .
git commit -m "release: v1.1.0 deterministic intelligence, cleaning plan, stability hardening, production docs"
git tag -a v1.1.0 -m "Deterministic intelligence and stability release"
```

Optional push:

```powershell
git push origin main
git push origin v1.1.0
```

Use your actual branch name if not `main`.
