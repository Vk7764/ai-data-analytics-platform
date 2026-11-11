// frontend/src/components/TimeSeriesExplorer.jsx
import { useState, useEffect } from "react";
import { ComposedChart, Bar, Line, Legend, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../api";
import { errorDetail } from "../utils";
import MethodologyPanel from "./MethodologyPanel";

// Computes the date range a clicked bucket represents, and which
// granularity to zoom INTO when the user clicks it.
function getDrillRange(bucketLabel, currentGranularity) {
  if (currentGranularity === "year") {
    return { start: `${bucketLabel}-01-01`, end: `${bucketLabel}-12-31`, nextGranularity: "month" };
  }
  if (currentGranularity === "month") {
    const [year, month] = bucketLabel.split("-").map(Number);
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return {
      start: `${bucketLabel}-01`,
      end: `${bucketLabel}-${String(lastDay).padStart(2, "0")}`,
      nextGranularity: "week",
    };
  }
  if (currentGranularity === "week") {
    const d = new Date(`${bucketLabel}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + 6);
    return { start: bucketLabel, end: d.toISOString().slice(0, 10), nextGranularity: "day" };
  }
  if (currentGranularity === "day") {
    return { start: `${bucketLabel} 00:00:00`, end: `${bucketLabel} 23:59:59`, nextGranularity: "hour" };
  }
  return null;
}

function TimeSeriesExplorer({ datasetId, columns: rawColumns = [], dataVersion = 0 }) {
  const columns = Array.isArray(rawColumns)
    ? rawColumns.filter((c) => c && typeof c === "object" && typeof c.name === "string" && c.name)
    : [];

  const [dateColumn, setDateColumn] = useState("");
  const [valueColumn, setValueColumn] = useState("");
  const [chart, setChart] = useState(null);
  const [chartColumns, setChartColumns] = useState(null);
  const [breadcrumb, setBreadcrumb] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [maWindow, setMaWindow] = useState(0);
  const [isPremium, setIsPremium] = useState(null); // null = plan not loaded yet

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

  useEffect(() => {
    api.get("/me").then((res) => setIsPremium(res.data.plan === "premium")).catch(() => setIsPremium(false));
  }, []);

  // Keep the user's column selections, but drop results that no longer match the edited data.
  useEffect(() => {
    setChart(null);
    setChartColumns(null);
    setBreadcrumb([]);
    setError(null);
  }, [dataVersion]);

  const numericColumns = columns.filter((c) => c.inferred_type === "numeric");
  const dateColumns = columns.filter((c) => c.inferred_type === "date");
  const nameLooksLikeDate = (name) => /date|time|timestamp/i.test(name);
  const dateColumnOptions = dateColumns.length > 0
    ? dateColumns
    : [
        ...columns.filter((c) => c.inferred_type !== "numeric" && nameLooksLikeDate(c.name)),
        ...columns.filter((c) => c.inferred_type !== "numeric" && !nameLooksLikeDate(c.name)),
      ];

  const chartPoints = (() => {
    const rows = Array.isArray(chart?.data)
      ? chart.data.filter((row) => row && typeof row === "object")
      : [];
    const valKey = chartColumns?.valueColumn;

    if (maWindow <= 1 || !valKey) return rows;

    return rows.map((row, idx) => {
      if (idx < maWindow - 1) return { ...row, moving_avg: null };

      const windowRows = rows.slice(idx - maWindow + 1, idx + 1);
      const avg =
        windowRows.reduce((sum, r) => sum + Number(r?.[valKey] || 0), 0) / maWindow;

      return { ...row, moving_avg: Math.round(avg * 100) / 100 };
    });
  })();

  const downloadTimeseriesCsv = () => {
    if (!chartColumns || typeof chartColumns !== "object" || chartPoints.length === 0) return;

    const dateCol = chartColumns.dateColumn;
    const valueCol = chartColumns.valueColumn;

    if (!dateCol || !valueCol) return;

    const headers = [dateCol, valueCol, ...(maWindow > 1 ? ["moving_avg"] : [])];

    const esc = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };

    const lines = [
      headers.map(esc).join(","),
      ...chartPoints.map((r) => headers.map((h) => esc(r?.[h])).join(",")),
    ];

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "timeseries.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const fetchChart = async (granularity, start, end, cols) => {
    if (!cols || !cols.dateColumn || !cols.valueColumn) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.get(`/dataset/${datasetId}/chart/timeseries`, {
        params: { date_column: cols.dateColumn, value_column: cols.valueColumn, granularity, start, end },
      });
      setChart(response.data);
      setChartColumns(cols);
    } catch (err) {
      setError(errorDetail(err, "Could not load time series."));
    } finally {
      setLoading(false);
    }
  };

  const getSafeCurrentColumns = () => {
    if (
      typeof chartColumns !== "undefined" &&
      chartColumns &&
      chartColumns.dateColumn &&
      chartColumns.valueColumn
    ) {
      return {
        dateColumn: chartColumns.dateColumn,
        valueColumn: chartColumns.valueColumn,
      };
    }

    if (
      typeof dateColumn !== "undefined" &&
      typeof valueColumn !== "undefined" &&
      dateColumn &&
      valueColumn
    ) {
      return { dateColumn, valueColumn };
    }

    return null;
  };

  const getLastCrumb = () => {
    if (
      typeof breadcrumb !== "undefined" &&
      Array.isArray(breadcrumb) &&
      breadcrumb.length > 0
    ) {
      return breadcrumb[breadcrumb.length - 1] || null;
    }

    return null;
  };

  const safeSetState = (setter, value) => {
    if (typeof setter === "function") {
      setter(value);
    }
  };

  const fetchSavedTimeSeries = async (cols, params) => {
    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      return false;
    }

    const canUpdateChart = typeof setChart === "function";

    safeSetState(typeof setLoading === "function" ? setLoading : null, true);
    safeSetState(typeof setError === "function" ? setError : null, null);

    try {
      const res = await api.get(`/dataset/${datasetId}/chart/timeseries`, {
        params: {
          date_column: cols.dateColumn,
          value_column: cols.valueColumn,
          granularity: params.granularity || undefined,
          start: params.start || undefined,
          end: params.end || undefined,
        },
      });

      if (canUpdateChart) {
        safeSetState(setChart, res.data);
        safeSetState(typeof setBreadcrumb === "function" ? setBreadcrumb : null, []);
      }

      return canUpdateChart;
    } catch (err) {
      safeSetState(
        typeof setError === "function" ? setError : null,
        errorDetail(err, "Could not load this saved time-series view.")
      );
      return false;
    } finally {
      safeSetState(typeof setLoading === "function" ? setLoading : null, false);
    }
  };

  const handleSaveAnalysis = async () => {
    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    const cols = getSafeCurrentColumns();
    if (!cols) {
      setSavedMessage("Choose a date column and a value column first.");
      return;
    }

    const rawTitle = window.prompt("Name this time-series analysis:", "");
    if (rawTitle === null) return;

    const title = String(rawTitle).trim();
    if (!title) return;

    if (title.length > 120) {
      setSavedMessage("Title must be 120 characters or fewer.");
      return;
    }

    const lastCrumb = getLastCrumb();
    const ma = typeof maWindow !== "undefined" ? Number(maWindow) : 0;

    const currentGranularity =
      typeof granularity !== "undefined"
        ? granularity
        : typeof chart !== "undefined" && chart
        ? chart.granularity
        : null;

    try {
      await api.post(`/dataset/${datasetId}/saved-analyses`, {
        title,
        analysis_type: "time_series",
        parameters: {
          date_column: cols.dateColumn,
          value_column: cols.valueColumn,
          granularity: currentGranularity ?? null,
          start: lastCrumb ? lastCrumb.start ?? null : null,
          end: lastCrumb ? lastCrumb.end ?? null : null,
          ma_window: ma > 1 ? ma : null,
        },
      });

      setSavedMessage("Analysis saved.");
      setSavedStale(false);
      await refreshSavedAnalyses();
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not save this analysis."));
    }
  };

  const handleLoadAnalysis = async (analysisId) => {
    if (!analysisId) return;

    if (typeof api === "undefined" || typeof datasetId === "undefined" || !datasetId) {
      setSavedMessage("Saved analyses are unavailable.");
      return;
    }

    try {
      const res = await api.get(`/dataset/${datasetId}/saved-analyses/${analysisId}`);
      const analysis = res?.data?.analysis || {};

      if (analysis.analysis_type !== "time_series") {
        setSavedMessage("This saved analysis is not a time-series configuration.");
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

      const ma = [0, 3, 7].includes(Number(p.ma_window)) ? Number(p.ma_window) : 0;
      const cols = {
        dateColumn: p.date_column,
        valueColumn: p.value_column,
      };

      safeSetState(typeof setDateColumn === "function" ? setDateColumn : null, p.date_column);
      safeSetState(typeof setValueColumn === "function" ? setValueColumn : null, p.value_column);
      safeSetState(typeof setMaWindow === "function" ? setMaWindow : null, ma);
      safeSetState(typeof setBreadcrumb === "function" ? setBreadcrumb : null, []);
      safeSetState(typeof setGranularity === "function" ? setGranularity : null, p.granularity || null);
      safeSetState(typeof setStart === "function" ? setStart : null, p.start || null);
      safeSetState(typeof setEnd === "function" ? setEnd : null, p.end || null);

      setSavedStale(Boolean(res?.data?.is_stale));
      setSavedMessage(`Loaded "${analysis.title || "Saved analysis"}".`);

      const loaded = await fetchSavedTimeSeries(cols, {
        granularity: p.granularity || null,
        start: p.start || null,
        end: p.end || null,
      });

      if (!loaded && typeof fetchChart === "function") {
        try {
          await fetchChart(p.granularity || null, p.start || null, p.end || null, cols);
        } catch (err) {
          // Existing fetchChart error handling is expected to set component error state.
        }
      }
    } catch (err) {
      setSavedMessage(errorDetail(err, "Could not load this analysis."));
    }
  };

  const handleExplore = () => {
    setBreadcrumb([]);
    fetchChart(null, null, null, { dateColumn, valueColumn });
  };

  const handleBarClick = (point) => {
    if (!chart || !chart.can_drill_down || !chartColumns) return;
    const bucketLabel = point[chartColumns.dateColumn];
    const drill = getDrillRange(bucketLabel, chart.granularity);
    if (!drill) return;

    setBreadcrumb((prev) => [...prev, {
      label: bucketLabel,
      start: drill.start,
      end: drill.end,
      granularity: drill.nextGranularity,
    }]);
    fetchChart(drill.nextGranularity, drill.start, drill.end, chartColumns);
  };

  const handleBreadcrumbClick = (index) => {
    if (!chartColumns) return;
    if (index === -1) {
      setBreadcrumb([]);
      fetchChart(null, null, null, chartColumns);
      return;
    }
    const target = breadcrumb[index];
    setBreadcrumb(breadcrumb.slice(0, index + 1));
    fetchChart(target.granularity, target.start, target.end, chartColumns);
  };

  const handleDownload = async (format) => {
    if (!chartColumns) return;
    setDownloading(true);
    try {
      const params = {
        date_column: chartColumns.dateColumn,
        value_column: chartColumns.valueColumn,
        format,
        granularity: chart.granularity,
        ma_window: maWindow > 1 ? maWindow : undefined,
      };
      const lastCrumb = breadcrumb[breadcrumb.length - 1];
      if (lastCrumb) {
        params.start = lastCrumb.start;
        params.end = lastCrumb.end;
      }
      const response = await api.get(`/dataset/${datasetId}/chart/export`, { params, responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.download = `chart.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      if (err.response?.status === 403) {
        alert("This feature requires a Premium plan.");
      } else {
        alert(errorDetail(err, "Could not download chart."));
      }
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="dashboard-card">
      <h2>Time Series Explorer <span className="premium-tag">⭐ Premium</span></h2>
      <p className="subtitle">Click any bar to zoom in — year → month → week → day → hour.</p>

      <div className="forecast-controls">
        <select value={dateColumn} onChange={(e) => setDateColumn(e.target.value)}>
          <option value="">Select date column</option>
          {dateColumnOptions.map((col) => (
            <option key={col.name} value={col.name}>{col.name}</option>
          ))}
        </select>
        <select value={valueColumn} onChange={(e) => setValueColumn(e.target.value)}>
          <option value="">Select value column</option>
          {numericColumns.map((col) => (
            <option key={col.name} value={col.name}>{col.name}</option>
          ))}
        </select>
        <button onClick={handleExplore} disabled={loading || isPremium !== true}>
          {loading ? "Loading..." : "Explore"}
        </button>
        <select value={maWindow} onChange={(e) => setMaWindow(Number(e.target.value))}>
          <option value={0}>No Moving Avg</option>
          <option value={3}>3-Period Moving Avg</option>
          <option value={7}>7-Period Moving Avg</option>
        </select>
        {chart && chartPoints.length > 0 && (
          <button className="demo-button" onClick={downloadTimeseriesCsv}>Download CSV</button>
        )}
      </div>

      {isPremium === true && (
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
            <strong>Saved time-series analyses</strong>
            <button
              type="button"
              className="logout-button"
              style={{ fontSize: "12px", padding: "4px 10px" }}
              disabled={(typeof loading !== "undefined" && loading) || !getSafeCurrentColumns()}
              onClick={handleSaveAnalysis}
            >
              Save current view
            </button>
          </div>

          {(() => {
            const items = Array.isArray(savedAnalyses)
              ? savedAnalyses.filter((a) => a && a.analysis_type === "time_series")
              : [];

            if (items.length === 0) {
              return (
                <p className="subtitle" style={{ fontSize: "12px" }}>
                  No saved time-series analyses yet.
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
                      onClick={() => handleLoadAnalysis(a.analysis_id)}
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
              The data has changed since this analysis was saved. The chart shows the current data.
            </p>
          )}

          {savedMessage && (
            <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
              {String(savedMessage)}
            </p>
          )}
        </div>
      )}

      {isPremium === false && (
        <p className="subtitle">Premium feature: upgrade to explore and export time series.</p>
      )}

      {error && <p className="error-text">{error}</p>}

      {chart && chartColumns && (
        <>
          <div className="breadcrumb-row">
            <button className="breadcrumb-item" onClick={() => handleBreadcrumbClick(-1)}>All time</button>
            {breadcrumb.map((crumb, idx) => (
              <span key={idx}>
                {" › "}
                <button className="breadcrumb-item" onClick={() => handleBreadcrumbClick(idx)}>
                  {crumb.label}
                </button>
              </span>
            ))}
            <span className="granularity-badge">{chart.granularity}</span>
          </div>

          {chart.data.length === 0 ? (
            <p className="subtitle">No data for this range.</p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart
                data={chartPoints}
                onClick={(e) => e?.activePayload?.[0] && handleBarClick(e.activePayload[0].payload)}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={chartColumns.dateColumn} />
                <YAxis />
                <Tooltip />
                <Bar
                  dataKey={chartColumns.valueColumn}
                  fill="#0e7c66"
                  cursor={chart.can_drill_down ? "pointer" : "default"}
                />
                {maWindow > 1 && (
                  <Line
                    type="monotone"
                    dataKey="moving_avg"
                    name={`${maWindow}-Period Avg`}
                    stroke="#c85a32"
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    dot={false}
                    connectNulls
                  />
                )}
                {maWindow > 1 && <Legend />}
              </ComposedChart>
            </ResponsiveContainer>
          )}

          {chart.skipped_invalid_dates > 0 && (
            <p className="subtitle" style={{ color: "var(--amber)" }}>
              {chart.skipped_invalid_dates} row(s) were excluded because their date could not be read.
            </p>
          )}

          {chart.can_drill_down && <p className="subtitle">Click a bar to zoom in further.</p>}

          <MethodologyPanel methodology={chart.methodology} />

          <div className="report-buttons">
            <button onClick={() => handleDownload("png")} disabled={downloading}>Download PNG</button>
            <button onClick={() => handleDownload("svg")} disabled={downloading}>Download SVG</button>
            <button onClick={() => handleDownload("pdf")} disabled={downloading}>Download PDF</button>
          </div>
        </>
      )}
    </div>
  );
}

export default TimeSeriesExplorer;