// frontend/src/components/ForecastView.jsx
import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import api from "../api";
import { errorDetail } from "../utils";
import MethodologyPanel from "./MethodologyPanel";

function ForecastView({ datasetId, columns: rawColumns = [], dataVersion = 0 }) {
  const columns = Array.isArray(rawColumns)
    ? rawColumns.filter((c) => c && typeof c === "object" && typeof c.name === "string" && c.name)
    : [];

  const [dateColumn, setDateColumn] = useState("");
  const [valueColumn, setValueColumn] = useState("");
  const [periods, setPeriods] = useState(3);
  const [forecastData, setForecastData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Keep the user's column selections, but drop a forecast computed from data that has since changed.
  useEffect(() => {
    setForecastData(null);
    setError(null);
  }, [dataVersion]);

  const [savedAnalyses, setSavedAnalyses] = useState([]);
  const [savedStale, setSavedStale] = useState(false);
  const [savedMessage, setSavedMessage] = useState(null);

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

  const safeSetState = (setter, value) => {
    if (typeof setter === "function") {
      setter(value);
    }
  };

  // Explicit-argument forecast request, so a loaded configuration does not depend on stale component state.
  const fetchForecastFor = async (dateCol, valueCol, periodCount) => {
    if (!dateCol || !valueCol) {
      safeSetState(
        typeof setError === "function" ? setError : null,
        "Please select both a date column and a value column."
      );
      return;
    }

    safeSetState(typeof setLoading === "function" ? setLoading : null, true);
    safeSetState(typeof setError === "function" ? setError : null, null);
    safeSetState(typeof setForecastData === "function" ? setForecastData : null, null);

    try {
      const response = await api.get(`/dataset/${datasetId}/forecast`, {
        params: {
          date_column: dateCol,
          value_column: valueCol,
          periods: periodCount,
        },
      });
      safeSetState(typeof setForecastData === "function" ? setForecastData : null, response.data);
    } catch (err) {
      safeSetState(
        typeof setError === "function" ? setError : null,
        errorDetail(err, "Could not generate a forecast for these columns.")
      );
    } finally {
      safeSetState(typeof setLoading === "function" ? setLoading : null, false);
    }
  };

  const handleSaveForecast = async () => {
    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    if (!dateColumn || !valueColumn) {
      setSavedMessage("Choose a date column and a value column first.");
      return;
    }

    const rawTitle = window.prompt("Name this forecast:", "");
    if (rawTitle === null) return;

    const title = String(rawTitle).trim();
    if (!title) return;

    if (title.length > 120) {
      setSavedMessage("Title must be 120 characters or fewer.");
      return;
    }

    const requestedPeriods = Number(periods);
    const periodCount =
      Number.isFinite(requestedPeriods) && requestedPeriods >= 1
        ? Math.floor(requestedPeriods)
        : 3;

    try {
      await api.post(`/dataset/${datasetId}/saved-analyses`, {
        title,
        analysis_type: "forecast",
        parameters: {
          date_column: dateColumn,
          value_column: valueColumn,
          periods: periodCount,
        },
      });

      setSavedMessage("Forecast saved.");
      setSavedStale(false);
      await refreshSavedAnalyses();
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not save this forecast."));
    }
  };

  const handleLoadForecast = async (analysisId) => {
    if (!analysisId) return;

    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    try {
      const res = await api.get(`/dataset/${datasetId}/saved-analyses/${analysisId}`);
      const analysis = res?.data?.analysis || {};

      if (analysis.analysis_type !== "forecast") {
        setSavedMessage("This saved analysis is not a forecast configuration.");
        return;
      }

      const p =
        analysis.parameters && typeof analysis.parameters === "object"
          ? analysis.parameters
          : {};

      if (!p.date_column || !p.value_column) {
        setSavedMessage("This saved analysis is missing its columns.");
        return;
      }

      const requested = Number(p.periods);
      const periodCount =
        Number.isFinite(requested) && requested >= 1
          ? Math.floor(requested)
          : 3;

      // Only the view state changes; the dataset itself is never modified.
      safeSetState(typeof setDateColumn === "function" ? setDateColumn : null, p.date_column);
      safeSetState(typeof setValueColumn === "function" ? setValueColumn : null, p.value_column);
      safeSetState(typeof setPeriods === "function" ? setPeriods : null, periodCount);

      setSavedStale(Boolean(res?.data?.is_stale));
      setSavedMessage(`Loaded "${analysis.title || "Saved forecast"}".`);

      await fetchForecastFor(p.date_column, p.value_column, periodCount);
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not load this forecast."));
    }
  };

  const downloadForecastCsv = () => {
    if (!forecastData || typeof forecastData !== "object") return;

    const forecastRows = Array.isArray(forecastData.forecast)
      ? forecastData.forecast.filter((f) => f && typeof f === "object")
      : [];

    if (forecastRows.length === 0) return;

    const esc = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };

    const lines = [
      "date,predicted_value,lower_bound,upper_bound",
      ...forecastRows.map((f) =>
        [f.date, f.predicted_value, f.lower_bound, f.upper_bound].map(esc).join(",")
      ),
    ];

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "forecast.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const handleForecast = async () => {
    if (!dateColumn || !valueColumn) {
      setError("Please select both a date column and a value column.");
      return;
    }

    setLoading(true);
    setError(null);
    setForecastData(null);

    try {
      const response = await api.get(`/dataset/${datasetId}/forecast`, {
        params: { date_column: dateColumn, value_column: valueColumn, periods },
      });
      setForecastData(response.data);
    } catch (err) {
      setError(errorDetail(err, "Could not generate a forecast for these columns."));
    } finally {
      setLoading(false);
    }
  };

  // Merge historical + forecast into one chart-friendly array
  const buildChartData = () => {
    if (!forecastData || typeof forecastData !== "object") return [];

    const historicalRows = Array.isArray(forecastData.historical)
      ? forecastData.historical.filter((h) => h && typeof h === "object")
      : [];
    const forecastRows = Array.isArray(forecastData.forecast)
      ? forecastData.forecast.filter((f) => f && typeof f === "object")
      : [];

    const historical = historicalRows.map((h) => ({
      date: h.date,
      actual: h.actual_value,
    }));
    const forecast = forecastRows.map((f) => ({
      date: f.date,
      predicted: f.predicted_value,
      lower: f.lower_bound,
      upper: f.upper_bound,
    }));

    return [...historical, ...forecast];
  };

  return (
    <div className="forecast-card">
      <h2>Forecast</h2>

      <div className="forecast-controls">
        <select value={dateColumn} onChange={(e) => setDateColumn(e.target.value)}>
          <option value="">Select date column</option>
          {columns.map((col) => (
            <option key={col.name} value={col.name}>{col.name}</option>
          ))}
        </select>

        <select value={valueColumn} onChange={(e) => setValueColumn(e.target.value)}>
          <option value="">Select value column</option>
          {columns.filter((c) => c.inferred_type === "numeric").map((col) => (
            <option key={col.name} value={col.name}>{col.name}</option>
          ))}
        </select>

        <input
          type="number"
          min="1"
          max="12"
          value={periods}
          onChange={(e) => setPeriods(Number(e.target.value))}
          className="periods-input"
        />

        <button onClick={handleForecast} disabled={loading}>
          {loading ? "Forecasting..." : "Generate Forecast"}
        </button>
      </div>

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
            <strong>Saved forecasts</strong>
            <button
              type="button"
              className="logout-button"
              style={{ fontSize: "12px", padding: "4px 10px" }}
              disabled={(typeof loading !== "undefined" && loading) || !dateColumn || !valueColumn}
              onClick={handleSaveForecast}
            >
              Save current forecast
            </button>
          </div>

          {(() => {
            const items = Array.isArray(savedAnalyses)
              ? savedAnalyses.filter((a) => a && a.analysis_type === "forecast")
              : [];

            if (items.length === 0) {
              return (
                <p className="subtitle" style={{ fontSize: "12px" }}>
                  No saved forecasts yet.
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
                      onClick={() => handleLoadForecast(a.analysis_id)}
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
              The data has changed since this forecast was saved. The forecast shows the current data.
            </p>
          )}

          {savedMessage && (
            <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
              {String(savedMessage)}
            </p>
          )}
        </div>
      )}

      {error && <p className="error-text">{error}</p>}

      {forecastData && (
        <>
          <p className="subtitle">
            Trend: <strong>{forecastData.trend_direction}</strong>
          </p>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={buildChartData()}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="actual" stroke="#4f46e5" name="Actual" connectNulls />
              <Line type="monotone" dataKey="predicted" stroke="#f59e0b" name="Predicted" strokeDasharray="5 5" connectNulls />
              <Line type="monotone" dataKey="upper" stroke="#fbbf24" name="Upper Bound" strokeWidth={1} dot={false} connectNulls />
              <Line type="monotone" dataKey="lower" stroke="#fbbf24" name="Lower Bound" strokeWidth={1} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>

          <table className="data-table" style={{ marginTop: "16px" }}>
            <thead>
              <tr>
                <th>Date</th>
                <th>Predicted</th>
                <th>Lower Bound</th>
                <th>Upper Bound</th>
              </tr>
            </thead>
            <tbody>
              {forecastData.forecast.map((f) => (
                <tr key={f.date}>
                  <td>{f.date}</td>
                  <td>{f.predicted_value}</td>
                  <td>{f.lower_bound}</td>
                  <td>{f.upper_bound}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <button className="demo-button" onClick={downloadForecastCsv}>Download Forecast CSV</button>

          <MethodologyPanel methodology={forecastData.methodology} />
        </>
      )}
    </div>
  );
}

export default ForecastView;