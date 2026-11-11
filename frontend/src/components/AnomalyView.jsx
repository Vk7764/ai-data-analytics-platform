// frontend/src/components/AnomalyView.jsx
import { useState, useEffect } from "react";
import api from "../api";
import MethodologyPanel from "./MethodologyPanel";
import { cleanMarkdown, errorDetail } from "../utils";

function AnomalyView({ datasetId, dataVersion }) {
  const [anomalies, setAnomalies] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [method, setMethod] = useState("zscore");
  const [threshold, setThreshold] = useState(2.5);
  const [explaining, setExplaining] = useState(false);
  const [anomalyMethodology, setAnomalyMethodology] = useState(null);

  const [savedAnalyses, setSavedAnalyses] = useState([]);
  const [savedStale, setSavedStale] = useState(false);
  const [savedMessage, setSavedMessage] = useState(null);
  // Incremented when a saved configuration is loaded, so the detection request re-runs even if the controls are unchanged.
  const [reloadNonce, setReloadNonce] = useState(0);

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

  const handleSaveAnomalyCheck = async () => {
    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    const rawTitle = window.prompt("Name this anomaly check:", "");
    if (rawTitle === null) return;

    const title = String(rawTitle).trim();
    if (!title) return;

    if (title.length > 120) {
      setSavedMessage("Title must be 120 characters or fewer.");
      return;
    }

    const currentMethod = typeof method !== "undefined" ? method : "zscore";
    const currentThreshold = typeof threshold !== "undefined" ? Number(threshold) : 2.5;
    const safeThreshold = Number.isFinite(currentThreshold)
      ? Math.min(5.0, Math.max(1.5, currentThreshold))
      : 2.5;

    try {
      await api.post(`/dataset/${datasetId}/saved-analyses`, {
        title,
        analysis_type: "anomaly",
        parameters: {
          method: currentMethod === "iqr" ? "iqr" : "zscore",
          threshold: safeThreshold,
          explain: false,
        },
      });

      setSavedMessage("Anomaly check saved.");
      setSavedStale(false);
      await refreshSavedAnalyses();
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not save this anomaly check."));
    }
  };

  const handleLoadAnomalyCheck = async (analysisId) => {
    if (!analysisId) return;

    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    try {
      const res = await api.get(`/dataset/${datasetId}/saved-analyses/${analysisId}`);
      const analysis = res?.data?.analysis || {};

      if (analysis.analysis_type !== "anomaly") {
        setSavedMessage("This saved analysis is not an anomaly check.");
        return;
      }

      const p = analysis.parameters || {};
      const loadedMethod = p.method === "iqr" ? "iqr" : "zscore";

      const rawThreshold = Number(p.threshold);
      const loadedThreshold = Number.isFinite(rawThreshold)
        ? Math.min(5.0, Math.max(1.5, rawThreshold))
        : 2.5;

      // Only the view controls change; the detection is read-only and no AI explanation is requested.
      safeSetState(typeof setMethod === "function" ? setMethod : null, loadedMethod);
      safeSetState(typeof setThreshold === "function" ? setThreshold : null, loadedThreshold);
      safeSetState(typeof setExplanation === "function" ? setExplanation : null, null);

      setSavedStale(Boolean(res?.data?.is_stale));
      setSavedMessage(`Loaded "${analysis.title || "Saved anomaly check"}".`);
      setReloadNonce((n) => n + 1);
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not load this anomaly check."));
    }
  };

  useEffect(() => {
    const fetchAnomalies = async () => {
      setLoading(true);
      setError(null);
      try {
        // Detection is free; the AI explanation is requested manually so edits never consume AI quota.
        const response = await api.get(`/dataset/${datasetId}/anomalies`, {
          params: { explain: false, method, threshold },
        });
        setAnomalies(response.data.anomalies);
        setAnomalyMethodology(response.data.methodology || null);
        setExplanation(null);
      } catch (err) {
        setError(errorDetail(err, "Could not load anomaly detection."));
      } finally {
        setLoading(false);
      }
    };

    fetchAnomalies();
  }, [datasetId, dataVersion, method, threshold, reloadNonce]);

  const handleExplain = async () => {
    setExplaining(true);
    try {
      const response = await api.get(`/dataset/${datasetId}/anomalies`, {
        params: { explain: true, method, threshold },
      });
      setExplanation(response.data.explanation || "No explanation was returned.");
    } catch (err) {
      setExplanation(errorDetail(err, "AI explanation is unavailable right now."));
    } finally {
      setExplaining(false);
    }
  };

  const numericOutliers = anomalies?.numeric_outliers || [];
  const categoryAnomalies = anomalies?.category_anomalies || [];
  const totalAnomalies = numericOutliers.length;
  const noAnomalies = totalAnomalies === 0 && categoryAnomalies.length === 0;

  const downloadAnomaliesCsv = () => {
    if (numericOutliers.length === 0) return;
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [
      "column,row_index,value,z_score,direction",
      ...numericOutliers.map((a) => [a.column, a.row_index, a.value, a.score, a.direction].map(esc).join(",")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "anomalies.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  if (loading) return <div className="anomaly-card"><p>Scanning for anomalies...</p></div>;
  if (error) return <div className="anomaly-card"><p className="error-text">{error}</p></div>;
  if (!anomalies) return null;

  return (
    <div className="anomaly-card">
      <h2>Anomaly Detection</h2>

      <div className="forecast-controls">
        <select value={method} onChange={(e) => setMethod(e.target.value)}>
          <option value="zscore">Z-Score Method</option>
          <option value="iqr">IQR (Boxplot) Method</option>
        </select>
        <select value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}>
          <option value={2.0}>High Sensitivity (2.0)</option>
          <option value={2.5}>Standard (2.5)</option>
          <option value={3.0}>Strict Outliers Only (3.0)</option>
        </select>
        {totalAnomalies > 0 && (
          <button onClick={downloadAnomaliesCsv}>Download Anomalies CSV</button>
        )}
      </div>

      {noAnomalies && <p className="success-text">✓ No unusual patterns detected.</p>}

      {numericOutliers.length > 0 && (
        <>
          <h3>Numeric Outliers</h3>
          <div className="anomaly-list">
            {numericOutliers.map((a, idx) => (
              <div className="anomaly-row" key={idx}>
                <span>
                  <strong>{a.column}</strong> — row {a.row_index}: value <strong>{a.value}</strong>
                </span>
                <span className="anomaly-badge">
                  {Array.isArray(a.expected_range)
                    ? `expected ${a.expected_range[0]} to ${a.expected_range[1]}`
                    : `${a.z_score ?? a.score ?? ""} std devs (${a.direction})`}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {categoryAnomalies.length > 0 && (
        <>
          <h3>Category Anomalies</h3>
          <div className="anomaly-list">
            {categoryAnomalies.map((a, idx) => (
              <div className="anomaly-row" key={idx}>
                <span>
                  <strong>{a.group_value}</strong> ({a.group_column}) has an average {a.value_column} that is{" "}
                  <strong>{a.direction}</strong> the overall average
                </span>
                <span className="anomaly-badge">
                  {a.group_average} vs overall {a.overall_average} ({a.direction})
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {typeof savedAnalyses !== "undefined" && (
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
            <strong>Saved anomaly checks</strong>
            <button
              type="button"
              className="logout-button"
              style={{ fontSize: "12px", padding: "4px 10px" }}
              disabled={typeof loading !== "undefined" && loading}
              onClick={handleSaveAnomalyCheck}
            >
              Save current check
            </button>
          </div>

          {(() => {
            const items = Array.isArray(savedAnalyses)
              ? savedAnalyses.filter((a) => a && a.analysis_type === "anomaly")
              : [];

            if (items.length === 0) {
              return (
                <p className="subtitle" style={{ fontSize: "12px" }}>
                  No saved anomaly checks yet.
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
                      onClick={() => handleLoadAnomalyCheck(a.analysis_id)}
                    >
                      Load
                    </button>
                  </li>
                ))}
              </ul>
            );
          })()}

          {savedStale && (
            <p className="error-text" style={{ marginTop: "8px" }}>
              The data has changed since this check was saved. The results show the current data.
            </p>
          )}

          {savedMessage && (
            <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
              {String(savedMessage)}
            </p>
          )}
        </div>
      )}

      <MethodologyPanel methodology={anomalyMethodology} />

      {!noAnomalies && (
        <div style={{ marginTop: "16px" }}>
          <button type="button" style={{ marginLeft: 0 }} onClick={handleExplain} disabled={explaining}>
            {explaining ? "Explaining..." : explanation ? "Regenerate AI Explanation" : "Explain with AI"}
          </button>
          <span className="subtitle" style={{ marginLeft: "12px", fontSize: "12px" }}>
            Uses 1 AI request. Cached output may be reused if the dataset has not changed.
          </span>
        </div>
      )}

      {explanation && (
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
            Written by an AI model to interpret the detected anomalies. Verify important figures against the data.
          </p>
          <p className="subtitle" style={{ fontSize: "11px", margin: "0 0 8px" }}>
            AI output may be cached until the dataset changes. Regenerate after cleaning or editing data.
          </p>
          <p>{cleanMarkdown(explanation)}</p>
        </div>
      )}
    </div>
  );
}

export default AnomalyView;