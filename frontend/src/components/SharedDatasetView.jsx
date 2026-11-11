// frontend/src/components/SharedDatasetView.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

const NOT_AVAILABLE_MESSAGE =
  "This share link is invalid, expired, or has been revoked.";
const MAX_SHARED_DISPLAY_LENGTH = 5000;

// Renders any backend value safely: null/undefined become a dash, objects are serialized.
function displayValue(value) {
  if (value === null || value === undefined) return "—";

  if (typeof value === "object") {
    try {
      const text = JSON.stringify(value);
      return text.length > MAX_SHARED_DISPLAY_LENGTH
        ? `${text.slice(0, MAX_SHARED_DISPLAY_LENGTH)}...`
        : text;
    } catch (err) {
      return "[unreadable]";
    }
  }

  return String(value);
}

function numberOrDash(value) {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : "—";
}

function duplicateRowsDisplay(value) {
  if (value === null || value === undefined) return "—";

  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "—";
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return "—";

    const n = Number(trimmed);
    return Number.isFinite(n) ? String(n) : "—";
  }

  if (typeof value === "object") {
    const count =
      value.count ??
      value.duplicate_count ??
      value.num_duplicates ??
      value.rows;

    if (count !== null && count !== undefined) {
      const n = Number(count);
      if (Number.isFinite(n)) return String(n);
    }

    return "—";
  }

  return "—";
}

function duplicateRowsMessage(value) {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed && !Number.isFinite(Number(trimmed))) return trimmed;
    return "";
  }

  if (value && typeof value === "object" && typeof value.message === "string") {
    return value.message.trim();
  }

  return "";
}

function healthScoreDisplay(value) {
  if (value === null || value === undefined) return "—";

  const n = Number(value);
  if (Number.isFinite(n)) return `${n}%`;

  if (typeof value === "string" && value.trim()) return value.trim();

  return "—";
}

function errorMessage(err) {
  const status = err?.response?.status;

  if (!err?.response) {
    return "Network error. Check your connection and try again.";
  }

  if (status === 404) {
    return NOT_AVAILABLE_MESSAGE;
  }

  if (status === 429) {
    return errorDetail(err, "Too many requests. Please wait a moment and try again.");
  }

  return errorDetail(err, "This shared dataset could not be loaded right now.");
}

function SharedDatasetView({ token }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      setData(null);

      if (!token) {
        setError(NOT_AVAILABLE_MESSAGE);
        setLoading(false);
        return;
      }

      try {
        const res = await api.get(`/shared/${encodeURIComponent(token)}`);

        if (!cancelled) {
          setData(res?.data && typeof res.data === "object" ? res.data : null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(errorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();

    return () => {
      cancelled = true;
    };
  }, [token]);

  const profile =
    data?.profile && typeof data.profile === "object" ? data.profile : {};

  const columns = Array.isArray(profile.columns)
    ? profile.columns.filter((c) => c && typeof c === "object")
    : [];

  const preview = Array.isArray(data?.preview)
    ? data.preview.filter((r) => r && typeof r === "object")
    : [];

  const previewColumns =
    columns.length > 0
      ? columns.map((c) => String(c.name ?? ""))
      : preview.length > 0
      ? Object.keys(preview[0])
      : [];

  const duplicateMessage = duplicateRowsMessage(profile.duplicate_rows);

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="app-header-left">
          <h1>Shared dataset</h1>
        </div>
        <a
          href="/"
          className="logout-button"
          style={{ textDecoration: "none", padding: "8px 16px" }}
        >
          Go to the app
        </a>
      </header>

      {loading && <p className="subtitle">Loading shared dataset...</p>}

      {!loading && error && (
        <div className="dashboard-card">
          <p className="error-text">{error}</p>
        </div>
      )}

      {!loading && !error && data && (
        <>
          <div className="verify-banner">
            <span>
              This dataset is shared read-only by its owner. You can view the
              preview and profile summary here. Editing, cleaning, downloads and
              analysis are not available on this page.
            </span>
          </div>

          <div className="dashboard-card">
            <h2>{displayValue(data.filename || "Shared dataset")}</h2>

            <div className="stats-row">
              <div className="stat-box">
                <span className="stat-value">
                  {numberOrDash(profile.num_rows)}
                </span>
                <span className="stat-label">Rows</span>
              </div>

              <div className="stat-box">
                <span className="stat-value">
                  {numberOrDash(profile.num_columns)}
                </span>
                <span className="stat-label">Columns</span>
              </div>

              <div className="stat-box">
                <span className="stat-value">
                  {duplicateRowsDisplay(profile.duplicate_rows)}
                </span>
                <span className="stat-label">Duplicate Rows</span>
              </div>

              <div className="stat-box">
                <span className="stat-value">
                  {healthScoreDisplay(profile.health_score)}
                </span>
                <span className="stat-label">Health Score</span>
              </div>
            </div>

            {duplicateMessage && (
              <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
                {duplicateMessage}
              </p>
            )}

            {columns.length > 0 && (
              <>
                <h3>Columns</h3>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Missing</th>
                        <th>Unique</th>
                      </tr>
                    </thead>
                    <tbody>
                      {columns.map((c, i) => (
                        <tr key={`${displayValue(c.name)}-${i}`}>
                          <td>{displayValue(c.name)}</td>
                          <td>{displayValue(c.inferred_type)}</td>
                          <td>
                            {displayValue(c.missing_values)} (
                            {displayValue(c.missing_percent)}%)
                          </td>
                          <td>{displayValue(c.unique_values)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            <h3>Preview (first {preview.length} rows)</h3>

            {preview.length === 0 ? (
              <p className="subtitle">No rows to preview.</p>
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      {previewColumns.map((name, i) => (
                        <th key={`${name}-${i}`}>{name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {previewColumns.map((name, colIndex) => (
                          <td key={`${name}-${colIndex}`}>
                            {displayValue(row[name])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default SharedDatasetView;