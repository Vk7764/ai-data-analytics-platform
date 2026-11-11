# Technical Debt and Maintenance Backlog

This backlog lists future non-breaking cleanup items. Each item should be scheduled as a separate, reviewed change. For current limitations, see [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md). For release gates, see [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md).

## 1. Replace `datetime.utcnow()` — completed

- Backend production code no longer uses `datetime.utcnow()`.
- Replacement uses `datetime.now(datetime.timezone.utc).replace(tzinfo=None)` to preserve naive UTC ISO strings and avoid naive/aware comparison errors.
- Backend smoke tests and the full pytest suite passed after the change. Timestamp creation/comparison paths were not exhaustively exercised by tests; manual verification is recommended for expiry/retention-sensitive flows such as share links, account deletion, scheduler leases, AI cache cutoff, and rate limits.

## 2. Replace fpdf `ln=True` with positioning parameters — completed

- Backend report generation now imports `XPos` and `YPos` from `fpdf.enums`.
- Deprecated `cell(..., ln=True)` calls have been replaced with `new_x=XPos.LMARGIN, new_y=YPos.NEXT`.
- The migration was verified with the backend test suite, which passes without warnings after the change.
- Manual visual PDF checking remains recommended before production release, because automated tests verify generation but not pixel-perfect rendering.

## 3. Replace FastAPI `on_event` hooks with a lifespan context manager — completed

- `backend/main.py` now uses an `@asynccontextmanager` lifespan to start the scheduler supervisor and cancel it during shutdown.
- The deprecated startup handler was removed. No shutdown event handler was present in the verified file state.
- The lifespan cancels the scheduler task during shutdown; verify graceful scheduler lease release in deployment logs if required.
- The full backend test suite and frontend build passed after the change.

## 4. Pytest warning-ratcheting plan — locked

- The temporary `pytest.ini` fpdf warning filter was removed after migrating fpdf report generation to the newer `new_x` / `new_y` API.
- Current verified backend test output has no warnings.
- `pytest.ini` now sets `max_warnings = 0`, locking the suite in a warning-free state.
- A regression guard (`backend/tests/test_deprecated_patterns.py`) now prevents reintroduction of `datetime.utcnow()`, fpdf `ln=True`, and FastAPI `@app.on_event`, and checks that `backend/main.py` uses lifespan wiring.
- If all tests pass but a future change introduces warnings, pytest exits with code 6 (`MAX_WARNINGS_ERROR`).
- If tests fail, pytest still exits with code 1 (`TESTS_FAILED`) regardless of warning count.
- Filtered warnings do not count toward the threshold.
- If a future dependency upgrade introduces unavoidable warnings, review them explicitly before changing the threshold. Prefer targeted local suppression or migration over broad global filters.

## 5. Frontend test runner, separate approved item

- No Vitest, Jest, or Testing Library is currently configured.
- Adding one is a separate approved item. Evaluate the dependency addition, test scope, and CI impact before starting it.

## 6. Application-layer CSP and HSTS, review required

- The application intentionally omits Content-Security-Policy and Strict-Transport-Security.
- Evaluate them only together with a reverse-proxy and TLS deployment review.
- Inline styles, chart delivery, and report downloads must be checked before any policy is enforced.

## 7. Provider and numeric limit review

- Review provider configuration, quota refund behavior, and exact numeric limits against the real deployment settings before writing fixed values into documentation.
- Update [USER_GUIDE.md](USER_GUIDE.md) and [SUPPORT_GUIDE.md](SUPPORT_GUIDE.md) only after the values are confirmed.

## 8. Keep the known-limitations list current

- When any item in this backlog is completed, update [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) in the same change.
- Record the completed item in [CHANGELOG.md](CHANGELOG.md).