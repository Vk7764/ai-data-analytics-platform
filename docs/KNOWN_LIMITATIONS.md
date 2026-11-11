# Known Limitations and Deferred Work

This document lists known limitations and deferred work so reviewers and operators are not surprised. For security controls, see [SECURITY.md](SECURITY.md). For release gates, see [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md).

## 1. Frontend automated tests are deferred

- No frontend test runner (Vitest, Jest, or Testing Library) is configured in the project.
- Adding one was out of scope for the hardening track. Frontend behavior is currently verified through the manual gates in `docs/RELEASE_CHECKLIST.md` and the frontend build.

## 2. Application-layer CSP and HSTS are not set

- Content-Security-Policy and Strict-Transport-Security are intentionally not set by the application.
- Configure them at the TLS termination or reverse-proxy layer where applicable.

## 3. Deployment-configurable numeric limits

- Upload size, large-upload warning thresholds, logo size, quota reset time, dataset count, and similar limits are deployment-configurable.
- These values are not promised in the documentation unless the running configuration confirms them.

## 4. Provider-specific behavior

- Model names, provider rate limits, and refund timing depend on the configured AI provider.
- The application does not guarantee provider behavior.

## 5. Test-suite warnings

Completed in the current hardening/maintenance track:

- `datetime.utcnow()` usage in backend production code has been replaced with timezone-aware UTC creation converted to naive UTC values where needed, avoiding the deprecated API while preserving existing stored timestamp format.
- FastAPI `on_event` startup/shutdown hooks have been replaced with a `lifespan` context manager for the scheduler supervisor.
- fpdf report generation has been migrated from deprecated `cell(..., ln=True)` to `new_x=XPos.LMARGIN, new_y=YPos.NEXT`.
- Pandas date-format inference warnings in profiling are suppressed locally around date-type detection; profiling behavior and returned types are unchanged.

Current verified backend test output has no warnings. If future dependency upgrades introduce new warnings, review them before adding broad filters. Pytest `--max-warnings` is available in pytest 9.1+ and can be used later as a ratchet if desired.

## 6. Public share previews are by design

- Share links expose a bounded preview (up to 10 rows) and a profile summary to anyone holding the link.
- This is intended behavior. The dataset owner accepts this risk when sharing. Do not share datasets with sensitive personal information unless that risk is accepted. See [USER_GUIDE.md](USER_GUIDE.md).

## 7. PDF text extraction may show spacing artifacts

- Text extracted from PDF reports may show spacing or kerning artifacts caused by fonts.
- Visual rendering in a standard PDF viewer is the authoritative reference. See [SUPPORT_GUIDE.md](SUPPORT_GUIDE.md).