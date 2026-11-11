// frontend/src/components/CompareDatasets.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function CompareDatasets({ dataVersion }) {
  const [datasets, setDatasets] = useState([]);
  const [metricKey, setMetricKey] = useState("average");
  const [idA, setIdA] = useState("");
  const [idB, setIdB] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get("/datasets")
      .then((res) => {
        const list = Array.isArray(res?.data?.datasets) ? res.data.datasets : [];
        setDatasets(
          list.filter(
            (d) => d && typeof d === "object" && typeof d.dataset_id === "string" && d.dataset_id
          )
        );
      })
      .catch(() => setDatasets([]));
  }, [dataVersion]);

  const handleCompare = async () => {
    if (!idA || !idB) {
      setError("Please select two datasets to compare.");
      return;
    }
    if (idA === idB) {
      setError("Please select two different datasets.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await api.get("/compare", { params: { dataset_id_a: idA, dataset_id_b: idB } });
      setResult(response.data);
    } catch (err) {
      setError(errorDetail(err, "Could not compare datasets."));
    } finally {
      setLoading(false);
    }
  };

  const buildKpiRows = () => {
    if (!result || typeof result !== "object") return [];

    const normalizeKpis = (kpis) =>
      Array.isArray(kpis)
        ? kpis.filter(
            (k) =>
              k &&
              typeof k === "object" &&
              (typeof k.column === "string" || typeof k.column === "number")
          )
        : [];

    const kpisA = normalizeKpis(result.a?.kpis);
    const kpisB = normalizeKpis(result.b?.kpis);

    const kpiMapA = Object.fromEntries(kpisA.map((k) => [String(k.column), k]));
    const kpiMapB = Object.fromEntries(kpisB.map((k) => [String(k.column), k]));

    const allColumns = [...new Set([...Object.keys(kpiMapA), ...Object.keys(kpiMapB)])];

    return allColumns.map((col) => ({
      column: col,
      a: kpiMapA[col],
      b: kpiMapB[col],
    }));
  };

  const formatDelta = (valA, valB) => {
    if (typeof valA !== "number" || typeof valB !== "number") return "—";
    const diff = valB - valA;
    const diffText = `${diff >= 0 ? "+" : ""}${Math.round(diff * 100) / 100}`;
    if (valA === 0) return `${diffText} (n/a %)`;
    const pct = (diff / Math.abs(valA)) * 100;
    return `${diffText} (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`;
  };

  return (
    <div className="dashboard-card">
      <h2>Compare Datasets</h2>
      <p className="subtitle">Pick any two uploaded datasets to compare their key metrics side by side.</p>

      {datasets.length < 2 && (
        <p className="subtitle">Upload at least two datasets to compare them.</p>
      )}

      <div className="compare-controls">
        <select value={idA} onChange={(e) => setIdA(e.target.value)}>
          <option value="">Select dataset A</option>
          {datasets.map((d) => (
            <option key={d.dataset_id} value={d.dataset_id}>{d.filename} ({d.uploaded_at})</option>
          ))}
        </select>
        <select value={idB} onChange={(e) => setIdB(e.target.value)}>
          <option value="">Select dataset B</option>
          {datasets.map((d) => (
            <option key={d.dataset_id} value={d.dataset_id}>{d.filename} ({d.uploaded_at})</option>
          ))}
        </select>
        <button onClick={handleCompare} disabled={loading}>
          {loading ? "Comparing..." : "Compare"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {result && (
        <>
          <div className="compare-controls">
            <select value={metricKey} onChange={(e) => setMetricKey(e.target.value)}>
              <option value="average">Average</option>
              <option value="total">Total</option>
              <option value="median">Median</option>
              <option value="min">Min</option>
              <option value="max">Max</option>
            </select>
          </div>
          <div className="compare-headers">
            <div></div>
            <div className="compare-col-label">{result.a?.filename ?? "Dataset A"}</div>
            <div className="compare-col-label">{result.b?.filename ?? "Dataset B"}</div>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>{result.a?.filename ?? "Dataset A"}</th>
                <th>{result.b?.filename ?? "Dataset B"}</th>
                <th>Change (B vs A)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Rows</td>
                <td>{result.a?.profile?.num_rows ?? "—"}</td>
                <td>{result.b?.profile?.num_rows ?? "—"}</td>
                <td>{formatDelta(result.a?.profile?.num_rows, result.b?.profile?.num_rows)}</td>
              </tr>
              {buildKpiRows().map((row) => {
                const valA = row.a ? row.a[metricKey] : undefined;
                const valB = row.b ? row.b[metricKey] : undefined;
                return (
                  <tr key={row.column}>
                    <td>{row.column} ({metricKey})</td>
                    <td>{valA ?? "—"}</td>
                    <td>{valB ?? "—"}</td>
                    <td>{formatDelta(valA, valB)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

export default CompareDatasets;