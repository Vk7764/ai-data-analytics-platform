# Support Guide

This guide helps support staff and operators diagnose common issues. Never ask users to paste passwords, tokens, full share links, API keys, session data, or personal data into a support message. For share-link issues, ask for the dataset ID/label, expiry, or request ID, not the plaintext token.

## 1. Match a user report to backend logs with X-Request-ID

1. Ask the user for the **request ID** shown with the error, or have them copy the `X-Request-ID` response header from their browser's developer tools (Network tab).
2. Search the backend server log for that exact ID, for example:

   ```text
   request_id=<id>
   ```

3. A normal access log line contains:
   - `request_id`
   - `method`
   - normalized `path`
   - `status_code`
   - `duration_ms`

4. An unhandled-error log line contains:
   - `request_id`
   - `method`
   - normalized `path`
   - `error_type`
   - shortened and redacted `error_message`

5. Logs are designed not to contain:
   - request bodies
   - uploaded file contents
   - Authorization headers
   - cookies
   - passwords
   - emails
   - bearer tokens
   - SQL text
   - AI prompts
   - dataset row values
   - plaintext share tokens

6. Share paths are masked in logs, for example:

   ```text
   /shared/:token
   ```

7. If the request ID is missing from the logs, check:
   - the time window
   - the environment
   - whether the request reached the backend
   - whether log capture is enabled

## 2. Common HTTP errors

| Status | Meaning for the user | What to check |
|---|---|---|
| 401 | Session expired or authentication missing. | Token lifetime, password change, account deletion, logout elsewhere. |
| 403 | Permission denied or feature requires Premium. | User plan, owner-only action, premium gating, share-management permission. |
| 404 | Dataset, share link, or saved analysis was not found, or the user does not have access. | Deleted dataset, expired/revoked share link, incorrect ID, non-owner access. |
| 413 | If returned by the deployment: upload/file too large or dataset/storage limit reached. | Configured upload limits, per-user dataset limits, storage policy. |
| 429 | Too many requests or daily AI limit reached. | Wait and retry, check AI usage badge, rate-limit configuration. |
| 500 | Server error. | Find request ID in logs, check `error_type=` line. |
| 503 | If returned by the deployment: AI provider or analysis sandbox unavailable. | Provider status, sandbox availability, quota refund policy if enabled. |

## 3. AI quota and cache guidance

- AI-generated answers consume quota according to the deployed AI quota policy. The header badge shows current usage/limit where configured.
- Repeating the same AI request on unchanged data may return cached output without consuming quota.
- After cleaning or editing data, the cache no longer matches, so the next AI request may consume quota again. This is expected.
- Failed AI requests may be refunded in deployments where refund logic is enabled. Verify the usage badge and quota policy before promising a refund.
- Deterministic features should not consume AI quota, including:
  - KPI cards
  - charts
  - correlation matrix
  - anomaly detection
  - root-cause breakdown
  - forecasts
  - Custom SQL where configured as non-AI
  - pivot/group-by summaries
  - saved analysis loads that use `explain=false`

## 4. Share link troubleshooting

- The public viewer returns the same “not found” style error for invalid, expired, and revoked links by design. This avoids leaking which state the link is in.
- Share links are shown only once at creation. If the owner lost the link, they must create a new one.
- Only the dataset owner can list, create, or revoke links. Other users should receive “not found” or permission errors.
- Revoking a link takes effect immediately.
- Deleting a dataset also removes its share links.
- The public view shows only:
  - filename
  - profile summary
  - bounded preview of at most 10 rows

- The public view does not show:
  - owner email
  - owner plan
  - branding/account data
  - full dataset rows
  - AI features
  - editing/cleaning/download actions

- Do not ask users to paste the full share link or token into support chat. Use request ID, dataset ID, share label, created time, or expiry time for debugging.

## 5. Saved analysis troubleshooting

- **Stale warning.** The dataset changed after the analysis was saved. The loaded view shows current data. Save the analysis again if the new state should be preserved.
- **Missing columns or column not available.** The saved column was renamed, removed, or changed type. Re-select the columns and save again.
- **Loading does not change data.** Loading a saved analysis only changes view controls. It does not mutate the dataset. If the dataset appears changed, check the cleaning change log and undo history.
- Saved analyses are owner-scoped. Other users cannot see or load them.
- Saved anomaly and root-cause configurations are loaded with `explain=false`, so they should not consume AI quota unless the user explicitly requests an AI explanation afterward.

## 6. Report troubleshooting

- **PDF or PowerPoint fails to generate.** Retry once. Check the server log using the request ID and look for `error_type=`.
- **Methodology/data-lineage section.** Current report generation includes a methodology/data-lineage section for deterministic report parts. If it is missing, confirm the deployment includes the report-fidelity changes and regenerate the report.
- **AI sections are missing.** AI-written report sections are optional. They may be omitted when no AI summary/recommendation/explanation is available, when quota is exhausted, or when providers are unavailable.
- **AI labels.** AI-written sections are labelled “AI-generated”. Deterministic statistics are not labelled as AI.
- **Forecast section.** Forecast output is deterministic and should not be labelled as AI.
- **Visual versus text extraction differences.** Automated PDF text extraction may show spacing artifacts because of font/kerning, for example:

  ```text
  Ke y Metrics
  R o w s : 361
  AI-g enerated text
  ```

  Visual rendering in a standard PDF viewer is authoritative. Ask the user to open the original file in a normal PDF viewer before reporting a defect.

- **Non-Latin characters.** PDF generation may replace unsupported characters when no Unicode font is configured. This is expected unless a Unicode font is available through deployment configuration.
- **Logo/branding issues.** Invalid or unreadable logos are ignored during report generation so the report can still be produced. Supported image type and size depend on the configured upload limits.

## 7. Upload troubleshooting

- Supported file types are configured by the backend. Common supported formats include CSV, Excel `.xlsx`, JSON, and SQL scripts. If an upload is rejected, check the file extension, file content, backend logs, and request ID.
- **File too large.** If the frontend or backend returns a size error, the file exceeds a configured limit. Warning thresholds and hard limits are deployment-configurable; do not promise exact MB values unless the current configuration confirms them.
- **Slow processing.** Large files take longer to parse, profile, and store. Wait for the progress indicator to finish.
- **Cancelled upload.** Cancelling stops the upload and no dataset is created.
- **Dataset limit.** If a per-user dataset limit is enforced, delete an unused dataset to free space.
- **Unexpected values.** Common data-quality issues include:
  - numbers stored as text
  - mixed date formats
  - missing values
  - duplicate rows
  - outliers

  Review the dataset profile, column summary, and cleaning preview before applying changes.

## 8. Privacy reminder

- Do not paste passwords, tokens, full share links, API keys, session data, customer personal information, or row values into a support message.
- Refer to datasets by name or dataset ID, and describe the problem without quoting row values.
- If sensitive data was shared by mistake:
  1. Delete the dataset if appropriate.
  2. Revoke any share links.
  3. Notify the security contact.
  4. Review request IDs/logs for access attempts, remembering that logs do not contain row values or plaintext tokens.