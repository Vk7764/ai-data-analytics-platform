// frontend/src/components/CorrelationHeatmap.jsx
import { useState, useEffect } from "react";
import api from "../api";

function describeRelationship(r) {
  const abs = Math.abs(r);
  const strength = abs >= 0.7 ? "Very Strong" : abs >= 0.5 ? "Strong" : abs >= 0.3 ? "Moderate" : "Weak";
  return `${strength} ${r >= 0 ? "Positive" : "Negative"}`;
}

function CorrelationHeatmap({ datasetId, dataVersion }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [minStrength, setMinStrength] = useState(0);

  useEffect(() => {
    const fetchCorrelation = async () => {
      setLoading(true);
      try {
        const res = await api.get(`/dataset/${datasetId}/correlation`);
        setData(res.data);
      } catch (err) {
        setData(null);
      } finally {
        setLoading(false);
      }
    };
    fetchCorrelation();
  }, [datasetId, dataVersion]);

  const safeColumns = Array.isArray(data?.columns)
    ? data.columns.map((c) => String(c ?? "")).filter(Boolean)
    : [];

  const safeMatrix = Array.isArray(data?.matrix) ? data.matrix : [];

  const topPairs = [];
  if (safeColumns.length >= 2) {
    for (let i = 0; i < safeColumns.length; i++) {
      const row = Array.isArray(safeMatrix[i]) ? safeMatrix[i] : [];

      for (let j = i + 1; j < safeColumns.length; j++) {
        const r = row[j];

        if (r === null || r === undefined || typeof r !== "number" || !Number.isFinite(r)) {
          continue;
        }

        if (Math.abs(r) >= minStrength) {
          topPairs.push({ a: safeColumns[i], b: safeColumns[j], r });
        }
      }
    }

    topPairs.sort((x, y) => Math.abs(y.r) - Math.abs(x.r));
  }

  const top = topPairs.slice(0, 10);

  if (loading) return null;
  if (safeColumns.length < 2) return null;

  // Turn a number from -1..+1 into a soft background color:
  // blue for negative, white for zero, red for positive.
  const getColor = (value) => {
    const num = typeof value === "number" && Number.isFinite(value) ? value : 0;
    const intensity = Math.round(Math.min(1, Math.abs(num)) * 180);

    if (num > 0) {
      return `rgb(255, ${255 - intensity}, ${255 - intensity})`;
    }
    if (num < 0) {
      return `rgb(${255 - intensity}, ${255 - intensity}, 255)`;
    }
    return "rgb(245, 245, 245)";
  };

  return (
    <div className="dashboard-card">
      <h2>Correlation Matrix</h2>
      <p className="subtitle">
        Shows how numeric columns move together (+1 = strong positive, -1 = strong negative, 0 = no relation).
      </p>

      <div className="forecast-controls">
        <select value={minStrength} onChange={(e) => setMinStrength(Number(e.target.value))}>
          <option value={0}>All Correlations</option>
          <option value={0.3}>Moderate+ (|r| &gt;= 0.3)</option>
          <option value={0.5}>Strong+ (|r| &gt;= 0.5)</option>
          <option value={0.7}>Very Strong (|r| &gt;= 0.7)</option>
        </select>
      </div>

      <div className="heatmap-scroll">
        <table className="heatmap-table">
          <thead>
            <tr>
              <th></th>
              {safeColumns.map((col, i) => (
                <th key={`${col}-${i}`}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {safeColumns.map((rowName, i) => {
              const rawRow = Array.isArray(safeMatrix[i]) ? safeMatrix[i] : [];
              const row =
                rawRow.length >= safeColumns.length
                  ? rawRow.slice(0, safeColumns.length)
                  : rawRow.concat(Array(safeColumns.length - rawRow.length).fill(null));

              return (
                <tr key={`${rowName}-${i}`}>
                  <th>{rowName}</th>
                  {safeColumns.map((colName, j) => {
                    const value = row[j];
                    const num = typeof value === "number" && Number.isFinite(value) ? value : null;

                    return (
                      <td
                        key={`${colName}-${j}`}
                        style={{
                          backgroundColor: getColor(num),
                          opacity:
                            i !== j &&
                            minStrength > 0 &&
                            (num === null || Math.abs(num) < minStrength)
                              ? 0.25
                              : 1,
                        }}
                      >
                        {num === null ? "n/a" : num.toFixed(2)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {top.length > 0 && (
        <>
          <h3 style={{ marginTop: "20px" }}>Top Correlated Pairs</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Column A</th>
                <th>Column B</th>
                <th>Correlation (r)</th>
                <th>Relationship</th>
              </tr>
            </thead>
            <tbody>
              {top.map((p) => (
                <tr key={`${p.a}-${p.b}`}>
                  <td>{p.a}</td>
                  <td>{p.b}</td>
                  <td>{p.r.toFixed(2)}</td>
                  <td>{describeRelationship(p.r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
export default CorrelationHeatmap;