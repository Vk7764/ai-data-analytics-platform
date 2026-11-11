// frontend/src/components/DataCleaning.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { cleanMarkdown, errorDetail } from "../utils";
import CleaningPlanCard from "./CleaningPlanCard";
import CleaningHistory from "./CleaningHistory";

function DataCleaning({ datasetId, dataVersion = 0, onCleaned }) {
  const [issues, setIssues] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [advice, setAdvice] = useState(null);
  const [adviceLoading, setAdviceLoading] = useState(false);
  // Pending preview awaiting explicit confirmation: { label, applyPath, payload, failureMessage, data }
  const [pendingPreview, setPendingPreview] = useState(null);

  const fetchAdvice = async () => {
    setAdviceLoading(true);
    try {
      const response = await api.get(`/dataset/${datasetId}/cleaning-advice`);
      setAdvice(response.data.advice);
    } catch (err) {
      setAdvice(errorDetail(err, "Could not load cleaning advice."));
    } finally {
      setAdviceLoading(false);
    }
  };

  const fetchIssues = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get(`/dataset/${datasetId}/issues`);
      setIssues(response.data.issues);
    } catch (err) {
      setError(errorDetail(err, "Could not load data quality issues."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setAdvice(null);
    fetchIssues();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, dataVersion]);

  // Renders any backend value safely: null/undefined become "null", objects are serialized.
  const displayValue = (value) => {
    if (value === null || value === undefined) return "null";
    if (typeof value === "object") {
      try {
        return JSON.stringify(value);
      } catch (err) {
        return "[unreadable]";
      }
    }
    return String(value);
  };

  // Runs the preview endpoint only. Nothing is applied until the user confirms.
  const runPreview = async ({ label, previewPath, applyPath, payload, failureMessage }) => {
    setActionLoading(true);
    setError(null);
    try {
      const response = await api.post(previewPath, payload ?? undefined);
      setPendingPreview({ label, applyPath, payload, failureMessage, data: response.data });
    } catch (err) {
      setError(errorDetail(err, "Could not preview this cleaning action."));
    } finally {
      setActionLoading(false);
    }
  };

  const handleAction = async (action, column = null, strategy = "mean") => {
    await runPreview({
      label: `Action "${action}"${column ? ` on '${column}'` : ""}`,
      previewPath: `/dataset/${datasetId}/clean/preview`,
      applyPath: `/dataset/${datasetId}/clean`,
      payload: { action, column, strategy },
      failureMessage: "Cleaning action failed.",
    });
  };

  const handleCleanAllPreview = async () => {
    await runPreview({
      label: "Auto-clean all (safe fixes)",
      previewPath: `/dataset/${datasetId}/clean-all/preview`,
      applyPath: `/dataset/${datasetId}/clean-all`,
      payload: null,
      failureMessage: "Auto-clean failed.",
    });
  };

  const cancelPreview = () => {
    setPendingPreview(null);
  };

  // Applies the previously previewed request. Only reachable through the explicit Apply button.
  const confirmPreview = async () => {
    if (!pendingPreview) return;
    const { applyPath, payload, failureMessage } = pendingPreview;
    setPendingPreview(null);
    setActionLoading(true);
    setError(null);
    try {
      const response = await api.post(applyPath, payload ?? undefined);
      onCleaned(response.data);
      await fetchIssues();
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(errorDetail(err, failureMessage));
    } finally {
      setActionLoading(false);
    }
  };

  const handleUndone = (data) => {
    onCleaned(data);
    fetchIssues();
  };

  if (loading) return <div className="cleaning-card"><p>Checking for data quality issues...</p></div>;
  if (error && !issues) return <div className="cleaning-card"><p className="error-text">{error}</p></div>;
  if (!issues) return null;

  const hasDuplicates = Number(issues?.duplicate_rows?.count) > 0;
  const hasKeyDuplicates = issues.key_duplicates && issues.key_duplicates.length > 0;
  const hasMissing = issues.missing_values.length > 0;
  const hasOutliers = issues.outliers.length > 0;
  const hasNegative = issues.negative_values && issues.negative_values.length > 0;
  const hasInconsistent = issues.inconsistent_values && issues.inconsistent_values.length > 0;
  const hasFuzzy = issues.fuzzy_category_issues && issues.fuzzy_category_issues.length > 0;
  const hasDateFormatIssues = issues.date_format_issues && issues.date_format_issues.length > 0;
  const hasNumericFormatIssues = issues.numeric_format_issues && issues.numeric_format_issues.length > 0;
  const hasEmailIssues = issues.email_format_issues && issues.email_format_issues.length > 0;

  const noIssues = !hasDuplicates && !hasKeyDuplicates && !hasMissing && !hasOutliers && !hasNegative
    && !hasInconsistent && !hasFuzzy && !hasDateFormatIssues && !hasNumericFormatIssues && !hasEmailIssues;

  return (
    <div className="cleaning-card">
      <h2>Data Quality Check</h2>
      
      <button
        className="clean-all-button"
        disabled={actionLoading}
        onClick={handleCleanAllPreview}
      >
        Clean All (Safe Fixes)
      </button>

      <button className="demo-button" disabled={actionLoading} onClick={() => handleAction("auto_clean_safe")}>
        ✨ Auto-Clean Safe Issues
      </button>

      <button className="demo-button" disabled={adviceLoading} onClick={fetchAdvice}>
        {adviceLoading ? "Thinking..." : "✨ AI Cleaning Advice"}
      </button>

      {advice && (
        <div className="insight-box">
          <h3>
            AI Cleaning Advisor{" "}
            <span
              style={{
                marginLeft: "8px",
                fontSize: "11px",
                padding: "2px 6px",
                borderRadius: "999px",
                background: "rgba(14,124,102,0.12)",
                color: "#0e7c66",
                fontWeight: 600,
              }}
            >
              AI-generated
            </span>
          </h3>
          <p className="subtitle" style={{ fontSize: "11px", margin: "0 0 8px" }}>
            Written by an AI model from dataset issues. Verify recommendations before applying cleaning actions.
          </p>
          <p className="subtitle" style={{ fontSize: "11px", margin: "0 0 8px" }}>
            AI output may be cached until the dataset changes. Regenerate after cleaning or editing data.
          </p>
          <p>{cleanMarkdown(advice)}</p>
        </div>
      )}

      <CleaningPlanCard
        datasetId={datasetId}
        onDatasetChanged={() => {
          setAdvice(null);
          setError(null);
        }}
      />

      <CleaningHistory datasetId={datasetId} onUndone={handleUndone} refreshKey={refreshKey + dataVersion} />

      {noIssues && <p className="success-text">✓ No issues found. Your data looks clean!</p>}
      {error && <p className="error-text">{error}</p>}

      {pendingPreview && (
        <div className="history-panel" style={{ marginBottom: "16px" }}>
          <strong>Preview: {pendingPreview.label}</strong>
          <p className="subtitle" style={{ fontSize: "12px" }}>
            Nothing has been changed yet. Review the effect, then apply or cancel.
          </p>

          <ul className="audit-log">
            <li>
              <span className="audit-detail">Rows before</span>
              <span className="audit-time">{displayValue(pendingPreview.data?.rows_before)}</span>
            </li>
            <li>
              <span className="audit-detail">Rows after</span>
              <span className="audit-time">{displayValue(pendingPreview.data?.rows_after)}</span>
            </li>
            <li>
              <span className="audit-detail">Cells changed</span>
              <span className="audit-time">{displayValue(pendingPreview.data?.cells_changed)}</span>
            </li>
            <li>
              <span className="audit-detail">Columns affected</span>
              <span className="audit-time">
                {Array.isArray(pendingPreview.data?.columns_affected) && pendingPreview.data.columns_affected.length > 0
                  ? pendingPreview.data.columns_affected.map(displayValue).join(", ")
                  : "none"}
              </span>
            </li>
          </ul>

          {Array.isArray(pendingPreview.data?.actions_applied) && pendingPreview.data.actions_applied.length > 0 && (
            <>
              <p className="subtitle" style={{ fontSize: "12px", margin: "8px 0 4px" }}>Steps that would run:</p>
              <ul className="audit-log">
                {pendingPreview.data.actions_applied.map((step, i) => (
                  <li key={i}><span className="audit-detail">{displayValue(step)}</span></li>
                ))}
              </ul>
            </>
          )}

          {Array.isArray(pendingPreview.data?.warnings) && pendingPreview.data.warnings.length > 0 && (
            <>
              <p className="subtitle" style={{ fontSize: "12px", margin: "8px 0 4px", color: "#b45309" }}>Warnings:</p>
              <ul className="audit-log">
                {pendingPreview.data.warnings.map((warning, i) => (
                  <li key={i}><span className="audit-detail">{displayValue(warning)}</span></li>
                ))}
              </ul>
            </>
          )}

          {Array.isArray(pendingPreview.data?.sample_changes) && pendingPreview.data.sample_changes.length > 0 ? (
            <>
              <p className="subtitle" style={{ fontSize: "12px", margin: "8px 0 4px" }}>
                Sample changes{pendingPreview.data.sample_changes_truncated ? " (first 20 shown)" : ""}:
              </p>
              <ul className="audit-log">
                {pendingPreview.data.sample_changes.slice(0, 20).map((change, i) => (
                  <li key={i}>
                    <span className="audit-detail">
                      {displayValue(change?.column)} · row {displayValue(change?.row_index)}
                      {" "}(id {displayValue(change?.identifier)}): {displayValue(change?.old_value)} → {displayValue(change?.new_value)}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="subtitle" style={{ fontSize: "12px" }}>No cell-level changes to show.</p>
          )}

          <div className="button-group" style={{ marginTop: "12px" }}>
            <button type="button" disabled={actionLoading} onClick={confirmPreview}>
              {actionLoading ? "Applying..." : "Apply Changes"}
            </button>
            <button type="button" className="logout-button" disabled={actionLoading} onClick={cancelPreview}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {hasDuplicates && (
        <div className="issue-row">
          <div>
            <strong>Duplicate Rows</strong>
            <p>{issues?.duplicate_rows?.message || ""}</p>
          </div>
          <button disabled={actionLoading} onClick={() => handleAction("remove_duplicates")}>
            Approve &amp; Remove
          </button>
        </div>
      )}

      {hasKeyDuplicates && issues.key_duplicates.map((k) => (
        <div className="issue-row" key={`key-${k.column}`}>
          <div>
            <strong>Duplicate records by '{k.column}'</strong>
            <p>
              {k.duplicate_key_count} id(s) repeated, {k.extra_row_count} extra row(s) — e.g. {k.example_keys.join(", ")}
            </p>
          </div>
          <button disabled={actionLoading} onClick={() => handleAction("resolve_key_duplicates", k.column)}>
            Keep First Only
          </button>
        </div>
      ))}

      {hasMissing && issues.missing_values.map((m) => (
        <div className="issue-row" key={m.column}>
          <div>
            <strong>Missing values in '{m.column}'</strong>
            <p>{m.missing_count} missing ({m.missing_percent}%)</p>
          </div>
          <div className="button-group">
            {m.is_numeric ? (
              <>
                <button disabled={actionLoading} onClick={() => handleAction("fill_missing", m.column, "mean")}>
                  Fill with Mean
                </button>
                <button disabled={actionLoading} onClick={() => handleAction("fill_missing", m.column, "median")}>
                  Fill with Median
                </button>
              </>
            ) : (
              <button disabled={actionLoading} onClick={() => handleAction("fill_missing", m.column, "mode")}>
                Fill with Mode
              </button>
            )}
            <button disabled={actionLoading} onClick={() => handleAction("drop_missing", m.column)}>
              Drop Rows
            </button>
          </div>
        </div>
      ))}

      {hasOutliers && issues.outliers.map((o) => (
        <div className="issue-row" key={o.column}>
          <div>
            <strong>Outliers in '{o.column}'</strong>
            <p>{o.outlier_count} outlier(s) — expected range {o.lower_bound} to {o.upper_bound}</p>
          </div>
          <div className="button-group">
            <span className="info-badge">Review manually</span>
            <button disabled={actionLoading} onClick={() => handleAction("clip_outliers", o.column)}>
              Cap to Range
            </button>
          </div>
        </div>
      ))}

      {hasNegative && issues.negative_values.map((n) => (
        <div className="issue-row" key={`neg-${n.column}`}>
          <div>
            <strong>Invalid negative values in '{n.column}'</strong>
            <p>{n.negative_count} value(s) — e.g. {n.example_values.join(", ")}</p>
          </div>
          <button disabled={actionLoading} onClick={() => handleAction("mark_negative_as_missing", n.column)}>
            Mark as Missing
          </button>
        </div>
      ))}

      {hasInconsistent && issues.inconsistent_values.map((inc) => (
        <div className="issue-row" key={inc.column}>
          <div>
            <strong>Inconsistent values in '{inc.column}'</strong>
            <p>
              {inc.raw_unique_count} raw variants collapse into {inc.normalized_unique_count} actual categories
              {inc.affected_groups.length > 0 && (
                <> (e.g. {inc.affected_groups[0].variants.map((v) => `"${v}"`).join(", ")})</>
              )}
            </p>
          </div>
          <button disabled={actionLoading} onClick={() => handleAction("normalize_text", inc.column)}>
            Approve &amp; Normalize
          </button>
        </div>
      ))}

      {hasFuzzy && issues.fuzzy_category_issues.map((f) => (
        <div className="issue-row" key={`fuzzy-${f.column}`}>
          <div>
            <strong>Possible duplicate categories in '{f.column}' (fuzzy match)</strong>
            <p>
              {f.affected_groups.length > 0 && (
                <>e.g. {f.affected_groups[0].variants.map((v) => `"${v}"`).join(", ")} — please review before approving</>
              )}
            </p>
          </div>
          <button disabled={actionLoading} onClick={() => handleAction("normalize_text_aggressive", f.column)}>
            Approve &amp; Merge
          </button>
        </div>
      ))}

      {hasDateFormatIssues && issues.date_format_issues.map((d) => (
        <div className="issue-row" key={d.column}>
          <div>
            <strong>Mixed date formats in '{d.column}'</strong>
            <p>
              Formats found: {Object.entries(d.formats_found).map(([fmt, count]) => `${fmt} (${count})`).join(", ")}
            </p>
          </div>
          <button disabled={actionLoading} onClick={() => handleAction("normalize_date_format", d.column)}>
            Approve &amp; Standardize
          </button>
        </div>
      ))}

      {hasNumericFormatIssues && issues.numeric_format_issues.map((n) => (
        <div className="issue-row" key={n.column}>
          <div>
            <strong>Numbers stored as text in '{n.column}'</strong>
            <p>{n.description}</p>
          </div>
          <button disabled={actionLoading} onClick={() => handleAction("clean_numeric_format", n.column)}>
            Approve &amp; Convert
          </button>
        </div>
      ))}

      {hasEmailIssues && issues.email_format_issues.map((e) => (
        <div className="issue-row" key={`email-${e.column}`}>
          <div>
            <strong>Email format issues in '{e.column}'</strong>
            <p>
              {e.invalid_count > 0 && `${e.invalid_count} malformed (e.g. ${e.example_invalid.join(", ")}) `}
              {e.has_case_issue && "— inconsistent capitalization found"}
            </p>
          </div>
          <div className="button-group">
            {e.invalid_count > 0 && (
              <button disabled={actionLoading} onClick={() => handleAction("flag_invalid_email_as_missing", e.column)}>
                Flag as Missing
              </button>
            )}
            {e.has_case_issue && (
              <button disabled={actionLoading} onClick={() => handleAction("lowercase_column", e.column)}>
                Lowercase All
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export default DataCleaning;