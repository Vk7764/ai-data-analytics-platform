// frontend/src/components/RootCauseView.jsx
import { useState, useEffect } from "react";
import { cleanMarkdown, errorDetail } from "../utils";
import api from "../api";
import MethodologyPanel from "./MethodologyPanel";

function RootCauseView({ datasetId, columns: rawColumns = [], dataVersion = 0 }) {
  const columns = Array.isArray(rawColumns)
    ? rawColumns.filter((c) => c && typeof c === "object" && typeof c.name === "string" && c.name)
    : [];

  const [metricColumn, setMetricColumn] = useState("");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // Per-dimension choice: "auto" (default), "include" or "exclude".
  const [dimModes, setDimModes] = useState({});

  const [savedAnalyses, setSavedAnalyses] = useState([]);
  const [savedStale, setSavedStale] = useState(false);
  const [savedMessage, setSavedMessage] = useState(null);

  const safeSetState = (setter, value) => {
    if (typeof setter === "function") {
      setter(value);
    }
  };

  const refreshSavedAnalyses = async () => {
    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedAnalyses([]);
      return;
    }

    try {
      const res = await api.get(`/dataset/${datasetId}/saved-analyses`);
      const list = Array.isArray(res?.data?.analyses) ? res.data.analyses : [];
      setSavedAnalyses(list.filter((a) => a && typeof a === "object"));
    } catch (err) {
      setSavedAnalyses([]);
    }
  };

  useEffect(() => {
    setSavedStale(false);
    setSavedMessage(null);
    refreshSavedAnalyses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId]);

  // Names containing a comma cannot be sent in a comma-separated list, so they are not selectable.
  const dimensionCandidates = columns.filter((c) => c.inferred_type !== "numeric" && !c.name.includes(","));
  const includedDimensions = dimensionCandidates.filter((c) => dimModes[c.name] === "include").map((c) => c.name);
  const excludedDimensions = dimensionCandidates.filter((c) => dimModes[c.name] === "exclude").map((c) => c.name);

  // Runs the root-cause request with explicit arguments, so a loaded configuration does not depend on pending state.
  // explain=false is intentional: loading a saved configuration must not consume AI quota unless the user explicitly asks for AI explanation.
  const runRootCause = async ({ metric, questionText, included, excluded }) => {
    if (!metric) {
      safeSetState(
        typeof setError === "function" ? setError : null,
        "Please select a metric column first."
      );
      return;
    }

    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      safeSetState(
        typeof setError === "function" ? setError : null,
        "Saved analyses are unavailable."
      );
      return;
    }

    safeSetState(typeof setLoading === "function" ? setLoading : null, true);
    safeSetState(typeof setError === "function" ? setError : null, null);
    safeSetState(typeof setResult === "function" ? setResult : null, null);

    try {
      const response = await api.get(`/dataset/${datasetId}/root-cause`, {
        params: {
          metric_column: metric,
          question: (questionText || "").trim() || undefined,
          dimension_columns:
            Array.isArray(included) && included.length > 0 ? included.join(",") : undefined,
          exclude_columns:
            Array.isArray(excluded) && excluded.length > 0 ? excluded.join(",") : undefined,
          explain: false,
        },
      });

      safeSetState(typeof setResult === "function" ? setResult : null, response.data);
    } catch (err) {
      safeSetState(
        typeof setError === "function" ? setError : null,
        errorDetail(err, "Could not run root cause analysis.")
      );
    } finally {
      safeSetState(typeof setLoading === "function" ? setLoading : null, false);
    }
  };

  const handleSaveRootCause = async () => {
    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    if (typeof metricColumn === "undefined" || !metricColumn) {
      setSavedMessage("Choose a metric column first.");
      return;
    }

    const rawTitle = window.prompt("Name this root-cause analysis:", "");
    if (rawTitle === null) return;

    const title = String(rawTitle).trim();
    if (!title) return;

    if (title.length > 120) {
      setSavedMessage("Title must be 120 characters or fewer.");
      return;
    }

    const includedForSave =
      typeof includedDimensions !== "undefined" && Array.isArray(includedDimensions)
        ? includedDimensions
        : [];

    const excludedForSave =
      typeof excludedDimensions !== "undefined" && Array.isArray(excludedDimensions)
        ? excludedDimensions
        : [];

    const questionForSave =
      typeof question !== "undefined" ? String(question || "").trim() : "";

    try {
      await api.post(`/dataset/${datasetId}/saved-analyses`, {
        title,
        analysis_type: "root_cause",
        parameters: {
          metric_column: metricColumn,
          dimension_columns: includedForSave,
          exclude_columns: excludedForSave,
          question: questionForSave || null,
          explain: false,
        },
      });

      setSavedMessage("Root-cause analysis saved.");
      setSavedStale(false);
      await refreshSavedAnalyses();
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not save this analysis."));
    }
  };

  const handleLoadRootCause = async (analysisId) => {
    if (!analysisId) return;

    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    try {
      const res = await api.get(`/dataset/${datasetId}/saved-analyses/${analysisId}`);
      const analysis = res?.data?.analysis || {};

      if (analysis.analysis_type !== "root_cause") {
        setSavedMessage("This saved analysis is not a root-cause configuration.");
        return;
      }

      const p =
        analysis.parameters && typeof analysis.parameters === "object"
          ? analysis.parameters
          : {};
      const metricCandidate = p.metric_column || "";

      let metric = "";
      if (typeof numericColumns !== "undefined" && Array.isArray(numericColumns)) {
        metric = numericColumns.some((c) => c && c.name === metricCandidate)
          ? metricCandidate
          : "";
      } else {
        metric = metricCandidate;
      }

      if (!metric) {
        setSavedMessage("This saved analysis refers to a metric column that is not available.");
        return;
      }

      const knownNames =
        typeof dimensionCandidates !== "undefined" && Array.isArray(dimensionCandidates)
          ? new Set(
              dimensionCandidates
                .map((c) => c && c.name)
                .filter(Boolean)
            )
          : null;

      const includedRaw = Array.isArray(p.dimension_columns)
        ? p.dimension_columns.filter((n) => typeof n === "string")
        : [];

      const excludedRaw = Array.isArray(p.exclude_columns)
        ? p.exclude_columns.filter((n) => typeof n === "string")
        : [];

      const included = knownNames
        ? includedRaw.filter((n) => knownNames.has(n))
        : includedRaw;

      const excluded = knownNames
        ? excludedRaw.filter((n) => knownNames.has(n) && !included.includes(n))
        : excludedRaw.filter((n) => !included.includes(n));

      const questionText =
        typeof p.question === "string"
          ? p.question
          : typeof question !== "undefined"
          ? question
          : "";

      const nextModes = {};
      included.forEach((n) => {
        nextModes[n] = "include";
      });
      excluded.forEach((n) => {
        nextModes[n] = "exclude";
      });

      // Only the view controls change; the analysis is read-only and no AI explanation is requested.
      safeSetState(typeof setMetricColumn === "function" ? setMetricColumn : null, metric);
      safeSetState(typeof setDimModes === "function" ? setDimModes : null, nextModes);
      safeSetState(typeof setQuestion === "function" ? setQuestion : null, questionText);

      setSavedStale(Boolean(res?.data?.is_stale));
      setSavedMessage(`Loaded "${analysis.title || "Saved root-cause analysis"}".`);

      await runRootCause({
        metric,
        questionText,
        included,
        excluded,
      });
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not load this analysis."));
    }
  };

  // Keep the user's selections, but drop an analysis computed from data that has since changed.
  useEffect(() => {
    setResult(null);
    setError(null);
  }, [dataVersion]);

  const numericColumns = columns.filter((c) => c.inferred_type === "numeric");

  const handleAnalyze = async () => {
    if (!metricColumn) {
      setError("Please select a metric column first.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await api.get(`/dataset/${datasetId}/root-cause`, {
        params: {
          metric_column: metricColumn,
          question: question.trim() || undefined,
          dimension_columns: includedDimensions.length > 0 ? includedDimensions.join(",") : undefined,
          exclude_columns: excludedDimensions.length > 0 ? excludedDimensions.join(",") : undefined,
        },
      });
      setResult(response.data);
    } catch (err) {
      setError(errorDetail(err, "Could not run root cause analysis."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rootcause-card">
      <h2>Root Cause Analysis</h2>
      <p className="subtitle">Find which factors explain the most variation in a metric.</p>

      <div className="rootcause-controls">
        <select value={metricColumn} onChange={(e) => setMetricColumn(e.target.value)}>
          <option value="">Select a metric (e.g. Sales)</option>
          {numericColumns.map((col) => (
            <option key={col.name} value={col.name}>{col.name}</option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Optional question (e.g. Why did sales vary?)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          style={{ flex: 1, minWidth: "200px", padding: "10px 14px", border: "1px solid var(--line)", borderRadius: "6px" }}
        />

        <button onClick={handleAnalyze} disabled={loading}>
          {loading ? "Analyzing..." : "Analyze"}
        </button>
      </div>

      {dimensionCandidates.length > 0 && (
        <details style={{ marginBottom: "16px" }}>
          <summary className="subtitle" style={{ cursor: "pointer" }}>
            Dimensions: {includedDimensions.length > 0
              ? `${includedDimensions.length} included`
              : "automatic selection"}
            {excludedDimensions.length > 0 ? `, ${excludedDimensions.length} excluded` : ""}
          </summary>
          <p className="subtitle" style={{ fontSize: "12px" }}>
            Leave everything on Auto to let the analysis choose. Include limits the analysis to the chosen
            dimensions; Exclude removes a dimension from the analysis.
          </p>
          <div className="forecast-controls">
            {dimensionCandidates.map((c) => (
              <label key={c.name} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                <span>{c.name}</span>
                <select
                  value={dimModes[c.name] || "auto"}
                  onChange={(e) => setDimModes((prev) => ({ ...prev, [c.name]: e.target.value }))}
                >
                  <option value="auto">Auto</option>
                  <option value="include">Include</option>
                  <option value="exclude">Exclude</option>
                </select>
              </label>
            ))}
            {(includedDimensions.length > 0 || excludedDimensions.length > 0) && (
              <button
                type="button"
                style={{ fontSize: "12px", padding: "4px 10px", marginLeft: 0 }}
                onClick={() => setDimModes({})}
              >
                Reset to Auto
              </button>
            )}
          </div>
        </details>
      )}

      {typeof savedAnalyses !== "undefined" &&
        typeof handleSaveRootCause === "function" &&
        typeof handleLoadRootCause === "function" && (
          <div className="history-panel" style={{ marginTop: "12px" }}>
            <div
              className="history-panel-row"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "8px",
              }}
            >
              <strong>Saved root-cause analyses</strong>
              <button
                type="button"
                className="logout-button"
                style={{ fontSize: "12px", padding: "4px 10px" }}
                disabled={
                  (typeof loading !== "undefined" && loading) ||
                  !(typeof metricColumn !== "undefined" && metricColumn)
                }
                onClick={handleSaveRootCause}
              >
                Save current analysis
              </button>
            </div>

            {(() => {
              const items = Array.isArray(savedAnalyses)
                ? savedAnalyses.filter((a) => a && a.analysis_type === "root_cause")
                : [];

              if (items.length === 0) {
                return (
                  <p className="subtitle" style={{ fontSize: "12px" }}>
                    No saved root-cause analyses yet.
                  </p>
                );
              }

              return (
                <ul className="audit-log">
                  {items.map((a, i) => (
                    <li
                      key={a.analysis_id || String(i)}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: "8px",
                      }}
                    >
                      <span className="audit-detail">{String(a.title ?? "Untitled")}</span>
                      <button
                        type="button"
                        className="logout-button"
                        style={{ fontSize: "12px", padding: "2px 10px" }}
                        disabled={typeof loading !== "undefined" && loading}
                        onClick={() => handleLoadRootCause(a.analysis_id)}
                      >
                        Load
                      </button>
                    </li>
                  ))}
                </ul>
              );
            })()}

            {typeof savedStale !== "undefined" && savedStale && (
              <p className="error-text" style={{ marginTop: "8px" }}>
                The data has changed since this analysis was saved. The results show the current data.
              </p>
            )}

            {typeof savedMessage !== "undefined" && savedMessage && (
              <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
                {String(savedMessage)}
              </p>
            )}
          </div>
        )}

      {error && <p className="error-text">{error}</p>}

      {result && (
        <>
          {!Array.isArray(result.breakdown) || result.breakdown.length === 0 ? (
            <p className="subtitle">Not enough categorical dimensions found to analyze.</p>
          ) : (
            <div className="breakdown-list">
              {result.breakdown
                .filter((dim) => dim && typeof dim === "object")
                .map((dim, dimIndex) => (
                  <div
                    className="breakdown-row"
                    key={`${String(dim.dimension ?? `dimension_${dimIndex}`)}-${dimIndex}`}
                  >
                    <div className="breakdown-header">
                      <strong>{String(dim.dimension ?? "Dimension")}</strong>
                      <span className="variance-badge">
                        {Number.isFinite(Number(dim.variance_explained))
                          ? (Number(dim.variance_explained) * 100).toFixed(1)
                          : "0.0"}
                        % of variation explained
                      </span>
                    </div>
                    <div className="breakdown-groups">
                      <span className="group-high">
                        Highest: {String(dim.highest_group?.value ?? "-")} (
                        {String(dim.highest_group?.average ?? "-")})
                      </span>
                      <span className="group-low">
                        Lowest: {String(dim.lowest_group?.value ?? "-")} (
                        {String(dim.lowest_group?.average ?? "-")})
                      </span>
                    </div>
                  </div>
                ))}
            </div>
          )}

          <MethodologyPanel methodology={result.methodology} />

          {result.explanation && (
            <div className="insight-box">
              <h3>
                AI Explanation{" "}
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
                Written by an AI model to interpret the breakdown above. It is a probable cause, not a proven one.
              </p>
              <p className="subtitle" style={{ fontSize: "11px", margin: "0 0 8px" }}>
                AI output may be cached until the dataset changes. Regenerate after cleaning or editing data.
              </p>
                            <p>{cleanMarkdown(result.explanation)}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default RootCauseView;