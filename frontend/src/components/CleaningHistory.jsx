// frontend/src/components/CleaningHistory.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function CleaningHistory({ datasetId, onUndone, refreshKey }) {
  const [undoStatus, setUndoStatus] = useState(null);
  const [auditLog, setAuditLog] = useState([]);
  const [showLog, setShowLog] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const [error, setError] = useState(null);

  const fetchStatus = async () => {
    try {
      const [undoRes, logRes] = await Promise.all([
        api.get(`/dataset/${datasetId}/undo-status`),
        api.get(`/dataset/${datasetId}/audit-log`),
      ]);
      const pending = undoRes.data.pending_undo;
      setUndoStatus(pending && typeof pending === "object" ? pending : null);

      const log = Array.isArray(logRes.data.log) ? logRes.data.log : [];
      setAuditLog(log.filter((entry) => entry && typeof entry === "object"));
    } catch (err) {
      // silently ignore — this is a secondary panel, not critical
    }
  };

  useEffect(() => {
    fetchStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, refreshKey]);

  const handleUndo = async () => {
    setUndoing(true);
    setError(null);
    try {
      const response = await api.post(`/dataset/${datasetId}/undo`);
      onUndone(response.data);
      await fetchStatus();
    } catch (err) {
      setError(errorDetail(err, "Could not undo."));
    } finally {
      setUndoing(false);
    }
  };

  const downloadAuditCsv = () => {
    if (auditLog.length === 0) return;
    const esc = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [
      "action,column_name,details,created_at",
      ...auditLog.map((e) => [e.action, e.column, e.details, e.timestamp].map(esc).join(",")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "audit_log.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  if (auditLog.length === 0 && !undoStatus) return null;

  return (
    <div className="history-panel">
      <div className="history-panel-row">
        {undoStatus ? (
          <>
            <span className="undo-label">
              Last action: {undoStatus.action_label} ({undoStatus.steps_available || 1} step(s))
            </span>
            <button disabled={undoing} onClick={handleUndo} className="undo-button">
              {undoing ? "Undoing..." : "Undo"}
            </button>
          </>
        ) : (
          <span className="undo-label">No pending undo</span>
        )}
        {auditLog.length > 0 && (
          <button
            className="logout-button"
            style={{ fontSize: "12px", padding: "4px 10px" }}
            onClick={downloadAuditCsv}
          >
            Export Audit CSV
          </button>
        )}
        <button className="log-toggle" onClick={() => setShowLog(!showLog)}>
          {showLog ? "Hide log" : `View change log (${auditLog.length})`}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {showLog && (
        <ul className="audit-log">
          {auditLog.map((entry, idx) => (
            <li key={idx} style={{ flexDirection: "column", alignItems: "flex-start", gap: "2px" }}>
              <span className="audit-detail">
                {entry.action && (
                  <strong>{String(entry.action).replace(/_/g, " ")}</strong>
                )}
                {entry.column && <span> · column '{String(entry.column)}'</span>}
              </span>
              {entry.details && <span className="audit-detail">{String(entry.details)}</span>}
              {entry.timestamp && <span className="audit-time">{String(entry.timestamp)}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default CleaningHistory;