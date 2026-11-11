// frontend/src/components/ScheduledExports.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function ScheduledExports({ datasetId }) {
  const [isPremium, setIsPremium] = useState(false);
  const [schedules, setSchedules] = useState([]);
  const [format, setFormat] = useState("pdf");
  const [frequency, setFrequency] = useState("weekly");
  const [destinationType, setDestinationType] = useState("email");
  const [destination, setDestination] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);

  const loadSchedules = async () => {
    try {
      const [meRes, schedulesRes] = await Promise.all([api.get("/me"), api.get("/schedules")]);

      setIsPremium(meRes?.data?.plan === "premium");

      const scheduleList = Array.isArray(schedulesRes?.data?.schedules)
        ? schedulesRes.data.schedules
        : [];

      setSchedules(
        scheduleList.filter(
          (s) => s && typeof s === "object" && s.dataset_id === datasetId
        )
      );
    } catch (err) {
      // ignore
    }
  };

  useEffect(() => {
    loadSchedules();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId]);

  if (!isPremium) return null;

  const handleCreate = async () => {
    if (!destination.trim()) {
      setMessage("Please enter a destination.");
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      await api.post("/schedules", { dataset_id: datasetId, format, frequency, destination_type: destinationType, destination });
      setDestination("");
      setMessage("Schedule created.");
      loadSchedules();
    } catch (err) {
      setMessage(errorDetail(err, "Could not create schedule."));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (scheduleId) => {
    try {
      await api.delete(`/schedules/${scheduleId}`);
      loadSchedules();
    } catch (err) {
      setMessage(errorDetail(err, "Could not delete schedule."));
    }
  };

  const handleRunNow = async (scheduleId) => {
    setMessage(null);
    try {
      await api.post(`/schedules/${scheduleId}/run-now`);
      setMessage("Report sent!");
      loadSchedules();
    } catch (err) {
      setMessage(errorDetail(err, "Could not send report."));
      loadSchedules();
    }
  };

  return (
    <div className="dashboard-card">
      <h2>Scheduled Exports <span className="premium-tag">⭐ Premium</span></h2>
      <p className="subtitle">Automatically email (or send to a webhook) a fresh report on a weekly or monthly basis.</p>

      <div className="schedule-controls">
        <select value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="pdf">PDF</option>
          <option value="excel">Excel</option>
          <option value="pptx">PPT</option>
          <option value="csv">CSV</option>
          <option value="json">JSON</option>
          <option value="sql">SQL Script</option>
        </select>
        <select value={frequency} onChange={(e) => setFrequency(e.target.value)}>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
        <select value={destinationType} onChange={(e) => setDestinationType(e.target.value)}>
          <option value="email">Email</option>
          <option value="webhook">Webhook</option>
        </select>
        <input
          type="text"
          placeholder={destinationType === "email" ? "you@example.com" : "https://your-webhook-url.com"}
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
        />
        <button onClick={handleCreate} disabled={loading}>Add Schedule</button>
      </div>

      {message && <p className="subtitle">{message}</p>}

      {schedules.length > 0 && (
        <ul className="history-list">
          {schedules.map((s) => (
            <li key={s.schedule_id} className="history-item">
              <div>
                <strong>{s.format.toUpperCase()} · {s.frequency}</strong>
                <p>To: {s.destination} — next run: {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}</p>
                {s.last_status === "failed" && (
                  <p style={{ color: "var(--rust)", fontSize: "12px" }}>
                    Last run failed
                    {s.last_attempt_at ? ` (${new Date(`${s.last_attempt_at}Z`).toLocaleString()})` : ""}
                    : {s.last_error || "unknown error"}. A retry or the next regular run is scheduled.
                  </p>
                )}
                {s.last_status === "success" && (
                  <p style={{ color: "var(--teal-dark)", fontSize: "12px" }}>
                    Last run delivered successfully
                    {s.last_run_at ? ` (${new Date(`${s.last_run_at}Z`).toLocaleString()})` : ""}.
                  </p>
                )}
              </div>
              <div className="button-group">
                <button onClick={() => handleRunNow(s.schedule_id)}>Run Now</button>
                <button className="delete-button" onClick={() => handleDelete(s.schedule_id)}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default ScheduledExports;