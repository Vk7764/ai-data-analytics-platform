// frontend/src/components/AnalysisDashboard.jsx
import { useState, useEffect } from "react";
import { BarChart, Bar, LineChart, Line, ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { cleanMarkdown, errorDetail } from "../utils";
import api from "../api";
import MethodologyPanel from "./MethodologyPanel";

function AnalysisDashboard({ datasetId, dataVersion, columns = [] }) {
  const [kpis, setKpis] = useState([]);
  const [chart, setChart] = useState(null);
  const [insight, setInsight] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState("auto");
  const [xColumn, setXColumn] = useState("");
  const [yColumn, setYColumn] = useState("");
  const [histBins, setHistBins] = useState(10);
  const [chartError, setChartError] = useState(null);
  const [agg, setAgg] = useState("sum");
  const [splitColumn, setSplitColumn] = useState("");
  const [pivotData, setPivotData] = useState(null);
  const [note, setNote] = useState("");
  const [noteSaved, setNoteSaved] = useState(false);
  const [insightLoading, setInsightLoading] = useState(false);
  const [kpiMethodology, setKpiMethodology] = useState(null);

  const [isPremium, setIsPremium] = useState(false);

  const [savedAnalyses, setSavedAnalyses] = useState([]);
  const [savedLoading, setSavedLoading] = useState(false);
  const [savedSaving, setSavedSaving] = useState(false);
  const [savedError, setSavedError] = useState(null);
  const [savedTitle, setSavedTitle] = useState("");
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [selectedSaved, setSelectedSaved] = useState(null);
  const [selectedSavedLoading, setSelectedSavedLoading] = useState(false);

  useEffect(() => {
    api.get("/me").then((res) => setIsPremium(res.data.plan === "premium")).catch(() => {});
  }, []);

  const numericColumns = columns.filter((c) => c.inferred_type === "numeric").map((c) => c.name);
  const allColumns = columns.map((c) => c.name);

  useEffect(() => {
    setMode("auto");
    setXColumn("");
    setYColumn("");
    setAgg("sum");
    setSplitColumn("");
    setPivotData(null);
    setChartError(null);
    setNoteSaved(false);
    setSelectedSavedId("");
    setSelectedSaved(null);
    setSavedError(null);
    setSavedTitle("");
    api
      .get(`/dataset/${datasetId}/note`)
      .then((res) => setNote(res.data.note || ""))
      .catch(() => setNote(""));
  }, [datasetId]);

  const handleSaveNote = async () => {
    try {
      const safeNote = String(note ?? "");
      await api.put(`/dataset/${datasetId}/note`, { note: safeNote });
      setNote(safeNote);
      setNoteSaved(true);
    } catch (err) {
      setNoteSaved(false);
      setChartError(errorDetail(err, "Could not save the note."));
    }
  };

  const fetchSavedAnalyses = async () => {
    setSavedLoading(true);
    setSavedError(null);
    try {
            const res = await api.get(`/dataset/${datasetId}/saved-analyses`);
      const list = Array.isArray(res?.data?.analyses) ? res.data.analyses : [];
      setSavedAnalyses(list.filter((a) => a && typeof a === "object"));
    } catch (err) {
      setSavedAnalyses([]);
      setSavedError(errorDetail(err, "Could not load saved analyses."));
    } finally {
      setSavedLoading(false);
    }
  };

  const handleRefreshSaved = () => {
    fetchSavedAnalyses();
  };

  const buildCurrentAnalysisPayload = () => {
    const analysisType = mode === "pivot" ? "pivot" : "chart";
    const parameters = {
      mode,
      agg,
      xColumn,
      yColumn,
      histBins,
      splitColumn,
      note,
      source: "analysis_dashboard",
    };
    return { analysisType, parameters };
  };

  const fetchChartFromConfig = async (cfg) => {
    setChartError(null);
    const nextMode = cfg?.mode || "auto";
    const nextAgg = cfg?.agg || agg;
    const nextX = cfg?.xColumn || "";
    const nextY = cfg?.yColumn || "";
    const nextSplit = cfg?.splitColumn || "";
    const nextBins = Number(cfg?.histBins) || histBins || 10;

    try {
      if (nextMode === "pivot") {
        if (!nextX || !nextY) {
          setChartError("Saved pivot is missing required columns.");
          return;
        }
        const res = await api.get(`/dataset/${datasetId}/pivot`, {
          params: {
            group_by: nextX,
            value_column: nextY,
            agg: nextAgg,
            split_by: nextSplit || undefined,
          },
        });
        setPivotData(res.data);
      } else if (nextMode === "histogram") {
        if (!nextY) {
          setChartError("Saved histogram is missing a numeric column.");
          return;
        }
        const res = await api.get(`/dataset/${datasetId}/chart/histogram`, {
          params: { column: nextY, bins: nextBins },
        });
        setChart(res.data);
      } else if (nextMode === "custom") {
        if (!nextX || !nextY) {
          setChartError("Saved custom chart is missing required columns.");
          return;
        }
        const res = await api.get(`/dataset/${datasetId}/chart`, {
          params: { x_column: nextX, y_column: nextY, agg: nextAgg },
        });
        setChart(res.data);
      } else {
        const res = await api.get(`/dataset/${datasetId}/chart`, {
          params: { agg: nextAgg },
        });
        setChart(res.data);
      }
    } catch (err) {
      setChartError(errorDetail(err, "Could not draw this chart."));
    }
  };

  const applySavedConfig = (params) => {
    const cfg = {
      mode: params?.mode || "auto",
      agg: params?.agg || "sum",
      xColumn: params?.xColumn || "",
      yColumn: params?.yColumn || "",
      histBins: Number(params?.histBins) || 10,
      splitColumn: params?.splitColumn || "",
      note: params?.note || "",
    };

    setMode(cfg.mode);
    setAgg(cfg.agg);
    setXColumn(cfg.xColumn);
    setYColumn(cfg.yColumn);
    setHistBins(cfg.histBins);
    setSplitColumn(cfg.splitColumn);
    setNote(cfg.note);
    setPivotData(null);
    setNoteSaved(false);
    setChartError(null);
    fetchChartFromConfig(cfg);
  };

  const handleSaveCurrentAnalysis = async () => {
    const title = (savedTitle || "").trim();
    if (!title) {
      setSavedError("Enter a title before saving.");
      return;
    }
    if (title.length > 120) {
      setSavedError("Title must be 120 characters or fewer.");
      return;
    }

    const { analysisType, parameters } = buildCurrentAnalysisPayload();
    setSavedSaving(true);
    setSavedError(null);

    try {
      await api.post(`/dataset/${datasetId}/saved-analyses`, {
        title,
        analysis_type: analysisType,
        parameters,
      });
      setSavedTitle("");
      await fetchSavedAnalyses();
    } catch (err) {
      setSavedError(errorDetail(err, "Could not save this analysis."));
    } finally {
      setSavedSaving(false);
    }
  };

  const handleSelectSaved = async (rawAnalysisId) => {
    const analysisId =
      typeof rawAnalysisId === "string" || typeof rawAnalysisId === "number"
        ? String(rawAnalysisId).trim()
        : "";

    setSelectedSavedId(analysisId);
    setSelectedSaved(null);
    setSavedError(null);

    if (!analysisId) return;

    setSelectedSavedLoading(true);
    try {
      const res = await api.get(
        `/dataset/${datasetId}/saved-analyses/${encodeURIComponent(analysisId)}`
      );
      const data = res?.data && typeof res.data === "object" ? res.data : null;
      setSelectedSaved(data);
    } catch (err) {
      setSavedError(errorDetail(err, "Could not load this saved analysis."));
    } finally {
      setSelectedSavedLoading(false);
    }
  };

  const handleApplySaved = () => {
    const params = selectedSaved?.analysis?.parameters;
    if (!params || typeof params !== "object") {
      setSavedError("No saved configuration is selected.");
      return;
    }
    setSavedError(null);
    applySavedConfig(params);
  };

  const fetchCustomChart = async (nextMode = mode, nextAgg = agg) => {
    setChartError(null);
    try {
      if (nextMode === "pivot") {
        if (!xColumn || !yColumn) return;
        const res = await api.get(`/dataset/${datasetId}/pivot`, {
          params: {
            group_by: xColumn,
            value_column: yColumn,
            agg: nextAgg,
            split_by: splitColumn || undefined,
          },
        });
        setPivotData(res.data);
      } else if (nextMode === "histogram") {
        if (!yColumn) return;
        const res = await api.get(`/dataset/${datasetId}/chart/histogram`, {
          params: { column: yColumn, bins: histBins },
        });
        setChart(res.data);
      } else if (nextMode === "custom") {
        if (!xColumn || !yColumn) return;
        const res = await api.get(`/dataset/${datasetId}/chart`, {
          params: { x_column: xColumn, y_column: yColumn, agg: nextAgg },
        });
        setChart(res.data);
      }
    } catch (err) {
      setChartError(err.response?.data?.detail || "Could not draw this chart.");
    }
  };

  const loadAutoChart = async (aggValue) => {
    try {
      const res = await api.get(`/dataset/${datasetId}/chart`, { params: { agg: aggValue } });
      setChart(res.data);
      setChartError(null);
    } catch (err) {
      setChartError(errorDetail(err, "Could not load the chart."));
    }
  };

  const handleModeChange = async (newMode) => {
    setMode(newMode);
    if (newMode === "auto") {
      await loadAutoChart(agg);
    } else {
      fetchCustomChart(newMode, agg);
    }
  };

  const handleAggChange = async (newAgg) => {
    setAgg(newAgg);
    if (mode === "auto") {
      await loadAutoChart(newAgg);
    } else if ((mode === "custom" || mode === "pivot") && xColumn && yColumn) {
      fetchCustomChart(mode, newAgg);
    }
  };

  const handleDownloadChart = async () => {
    try {
      const params = { format: "png", agg };
      if (mode === "custom" && xColumn && yColumn) {
        params.x_column = xColumn;
        params.y_column = yColumn;
      }
      const response = await api.get(`/dataset/${datasetId}/chart/export`, {
        params,
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.download = "chart.png";
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
    }
  };

    useEffect(() => {
    const loadDashboard = async () => {
      setLoading(true);
      setError(null);
      setInsight(null);

      try {
        const [kpiRes, chartRes] = await Promise.all([
          api.get(`/dataset/${datasetId}/kpis`),
          api.get(`/dataset/${datasetId}/chart`),
        ]);
        setKpis(kpiRes.data.kpis);
        setKpiMethodology(kpiRes.data.methodology || null);
        setChart(chartRes.data);
        fetchSavedAnalyses();
      } catch (err) {
        setError(errorDetail(err, "Could not load the analysis dashboard."));
        setLoading(false);
        return;
      }
      setLoading(false);
      // The AI insight is generated only on request, so routine data edits never consume AI quota.
    };

    loadDashboard();
  }, [datasetId, dataVersion]);

  const handleGenerateInsight = async () => {
    setInsightLoading(true);
    try {
      const insightRes = await api.post(`/dataset/${datasetId}/insights`, {});
      setInsight(insightRes.data.insight);
    } catch (err) {
      setInsight(`AI insight unavailable: ${errorDetail(err, "please try again later.")}`);
    } finally {
      setInsightLoading(false);
    }
  };

  const handleDownloadPivotCsv = () => {
    try {
      if (!pivotData?.rows?.length) return;

      const esc = (v) => {
        const s = v === null || v === undefined ? "" : String(v);
        return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };

      const columns = Array.isArray(pivotData.columns) ? pivotData.columns : [];
      const rows = Array.isArray(pivotData.rows) ? pivotData.rows : [];

      if (!columns.length || !rows.length) return;

      const lines = [
        columns.map(esc).join(","),
        ...rows.map((r) => columns.map((c) => esc(r?.[c])).join(",")),
      ];

      const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "pivot.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(errorDetail(err, "Could not download pivot CSV."));
    }
  };

  const handleDownloadChartCsv = () => {
    try {
      if (!chart || !Array.isArray(chart.data) || chart.data.length === 0 || !chart.x_column || !chart.y_column) return;

      const esc = (v) => {
        const s = v === null || v === undefined ? "" : String(v);
        return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };

      const lines = [
        [chart.x_column, chart.y_column].map(esc).join(","),
        ...chart.data.map((r) => [r?.[chart.x_column], r?.[chart.y_column]].map(esc).join(",")),
      ];

      const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "chart.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(errorDetail(err, "Could not download chart CSV."));
    }
  };

  const renderPivotTable = () => {
    if (!pivotData) return <p className="subtitle">Choose columns and click Build Table.</p>;
    if (pivotData.rows.length === 0) return <p className="subtitle">No data to show.</p>;
    return (
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {pivotData.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pivotData.rows.map((row, i) => (
              <tr key={i}>
                {pivotData.columns.map((c) => (
                  <td key={c}>{String(row[c] ?? "-")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderChart = () => {
    if (mode === "pivot") return renderPivotTable();
    if (!chart || chart.chart_type === "table" || chart.data.length === 0) {
      return <p className="subtitle">Not enough data to draw a chart.</p>;
    }

    if (chart.chart_type === "histogram") {
      return (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chart.data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="bin" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="count" fill="#0d9488" />
          </BarChart>
        </ResponsiveContainer>
      );
    }

    if (chart.chart_type === "bar") {
      return (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chart.data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={chart.x_column} />
            <YAxis />
            <Tooltip />
            <Bar dataKey={chart.y_column} fill="#4f46e5" />
          </BarChart>
        </ResponsiveContainer>
      );
    }

    if (chart.chart_type === "line") {
      return (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chart.data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={chart.x_column} />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey={chart.y_column} stroke="#4f46e5" />
          </LineChart>
        </ResponsiveContainer>
      );
    }

    if (chart.chart_type === "scatter") {
      return (
        <ResponsiveContainer width="100%" height={280}>
          <ScatterChart>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={chart.x_column} />
            <YAxis dataKey={chart.y_column} />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            <Scatter data={chart.data} fill="#4f46e5" />
          </ScatterChart>
        </ResponsiveContainer>
      );
    }

    return null;
  };

  if (loading) return <div className="dashboard-card"><p>Loading analysis...</p></div>;
  if (error) return <div className="dashboard-card"><p className="error-text">{error}</p></div>;

  return (
    <div className="dashboard-card">
      <h2>Analysis Dashboard</h2>

      {kpis.length > 0 && (
        <div className="kpi-grid">
          {kpis.map((kpi) => (
            <div className="kpi-box" key={kpi.column}>
              <span className="kpi-title">{kpi.column}</span>
              <span className="kpi-main">{kpi.average}</span>
               <span className="kpi-sub">avg (min {kpi.min}, max {kpi.max}, median {kpi.median})</span>
            </div>
          ))}
        </div>
      )}

            <MethodologyPanel methodology={kpiMethodology} title="How these metrics were calculated" />

      <div className="chart-header-row">
        <h3>{mode === "pivot" ? "Pivot / Group-By Table" : chart ? `${chart.chart_type.charAt(0).toUpperCase() + chart.chart_type.slice(1)} Chart` : "Chart"}</h3>
        {mode !== "pivot" && chart && chart.chart_type !== "table" && chart.chart_type !== "histogram" && (
          <button
            className="premium-button"
            onClick={handleDownloadChart}
            disabled={!isPremium}
            title={isPremium ? undefined : "Premium feature: upgrade to download high-resolution charts."}
          >
            ⭐ Download High-Res
          </button>
        )}
        {mode !== "pivot" && chart && chart.chart_type !== "table" && chart.chart_type !== "histogram" && chart.data && chart.data.length > 0 && (
          <button
            type="button"
            className="demo-button"
            style={{ marginLeft: "auto", marginRight: "8px", fontSize: "12px", padding: "6px 14px" }}
            onClick={handleDownloadChartCsv}
          >
            Download Chart CSV
          </button>
        )}
      </div>

      <div className="forecast-controls">
        <select value={mode} onChange={(e) => handleModeChange(e.target.value)}>
          <option value="auto">Auto Chart</option>
          <option value="custom">Custom X / Y</option>
          <option value="histogram">Histogram</option>
          <option value="pivot">Pivot / Group-By Table</option>
        </select>

        {(mode === "auto" || mode === "custom" || mode === "pivot") && (
          <select value={agg} onChange={(e) => handleAggChange(e.target.value)}>
            <option value="sum">Sum</option>
            <option value="mean">Average</option>
            <option value="median">Median</option>
            <option value="count">Count</option>
            <option value="min">Min</option>
            <option value="max">Max</option>
          </select>
        )}

        {mode === "custom" && (
          <>
            <select value={xColumn} onChange={(e) => setXColumn(e.target.value)}>
              <option value="">X column</option>
              {allColumns.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
            <select value={yColumn} onChange={(e) => setYColumn(e.target.value)}>
              <option value="">Y column</option>
              {numericColumns.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
            <button onClick={() => fetchCustomChart("custom")} disabled={!xColumn || !yColumn}>Draw</button>
          </>
        )}

        {mode === "histogram" && (
          <>
            <select value={yColumn} onChange={(e) => setYColumn(e.target.value)}>
              <option value="">Numeric column</option>
              {numericColumns.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
            <input
              type="number"
              min="2"
              max="100"
              value={histBins}
              onChange={(e) => setHistBins(Number(e.target.value))}
              className="periods-input"
            />
            <button onClick={() => fetchCustomChart("histogram")} disabled={!yColumn}>Draw</button>
          </>
        )}
      </div>

      {mode === "pivot" && (
        <div className="forecast-controls">
          <select value={xColumn} onChange={(e) => setXColumn(e.target.value)}>
            <option value="">Group by</option>
            {allColumns.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <select value={splitColumn} onChange={(e) => setSplitColumn(e.target.value)}>
            <option value="">No split</option>
            {allColumns.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <select value={yColumn} onChange={(e) => setYColumn(e.target.value)}>
            <option value="">Value column</option>
            {numericColumns.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <button onClick={() => fetchCustomChart("pivot", agg)} disabled={!xColumn || !yColumn}>Build Table</button>
          {pivotData?.rows?.length > 0 && (
            <button className="demo-button" onClick={handleDownloadPivotCsv}>Download Pivot CSV</button>
          )}
        </div>
      )}

      <details className="history-panel" style={{ marginBottom: "12px" }}>
        <summary className="subtitle" style={{ cursor: "pointer" }}>
          Saved analyses ({savedAnalyses.length})
        </summary>

        <div className="forecast-controls" style={{ marginTop: "8px" }}>
          <input
            type="text"
            placeholder="Save current chart/pivot as..."
            value={savedTitle}
            onChange={(e) => setSavedTitle(e.target.value)}
            disabled={savedSaving || savedLoading}
            style={{ flex: 1, minWidth: "180px" }}
          />
          <button
            type="button"
            onClick={handleSaveCurrentAnalysis}
            disabled={savedSaving || savedLoading || !savedTitle.trim()}
          >
            {savedSaving ? "Saving..." : "Save current"}
          </button>
          <button
            type="button"
            className="demo-button"
            onClick={handleRefreshSaved}
            disabled={savedLoading}
          >
            {savedLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {savedError && (
          <p className="error-text" style={{ marginTop: "8px" }}>
            {String(savedError)}
          </p>
        )}

        <div className="forecast-controls" style={{ marginTop: "8px" }}>
          <select
            value={selectedSavedId}
            onChange={(e) => handleSelectSaved(e.target.value)}
            disabled={savedLoading || selectedSavedLoading}
          >
            <option value="">Load saved analysis...</option>
            {savedAnalyses.map((a, i) => (
              <option key={a.analysis_id || i} value={a.analysis_id || ""}>
                {String(a.title || "Untitled")} ({String(a.analysis_type || "chart")})
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleApplySaved}
            disabled={!selectedSaved || selectedSavedLoading}
          >
            Apply saved
          </button>
        </div>

        {selectedSavedLoading && (
          <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
            Loading saved configuration...
          </p>
        )}

        {selectedSaved?.analysis && (
          <div className="subtitle" style={{ marginTop: "8px", fontSize: "12px" }}>
            <div>
              <strong>Title:</strong> {String(selectedSaved.analysis.title || "Untitled")}
            </div>
            <div>
              <strong>Type:</strong> {String(selectedSaved.analysis.analysis_type || "chart")}
            </div>
            <div>
              <strong>Saved:</strong> {String(selectedSaved.analysis.created_at || "-")}
            </div>
            <div>
              <strong>Data version:</strong> {String(selectedSaved.analysis.data_version || "-")}
            </div>
            {selectedSaved.is_stale && (
              <p style={{ color: "#b45309", margin: "6px 0 0" }}>
                This configuration was saved against a different data version. Applying it will not change the dataset, but results may differ.
              </p>
            )}
          </div>
        )}
      </details>

      {chartError && <p className="error-text">{chartError}</p>}
      {renderChart()}

      <div className="forecast-controls" style={{ marginTop: "14px" }}>
        <input
          type="text"
          placeholder="Add a chart note or takeaway (saved per dataset & included in PNG exports)..."
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
            setNoteSaved(false);
          }}
          style={{ flex: 1 }}
        />
        <button onClick={handleSaveNote}>{noteSaved ? "✓ Saved" : "Save Note"}</button>
      </div>

      <div style={{ marginTop: "16px" }}>
        <button
          type="button"
          style={{ marginLeft: 0 }}
          onClick={handleGenerateInsight}
          disabled={insightLoading}
        >
          {insightLoading ? "Generating..." : insight ? "Regenerate AI Insight" : "Generate AI Insight"}
        </button>
        <span className="subtitle" style={{ marginLeft: "12px", fontSize: "12px" }}>
          Uses 1 AI request. Cached output may be reused if the dataset has not changed.
        </span>
      </div>

      {insight && (
        <div className="insight-box">
          <h3>
            AI Insight{" "}
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
            Written by an AI model from summary statistics. Verify important figures against the data.
          </p>
          <p className="subtitle" style={{ fontSize: "11px", margin: "0 0 8px" }}>
            AI output may be cached until the dataset changes. Regenerate after cleaning or editing data.
          </p>
                    <p>{cleanMarkdown(insight)}</p>
        </div>
      )}
    </div>
  );
}

export default AnalysisDashboard;