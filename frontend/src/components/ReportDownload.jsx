// frontend/src/components/ReportDownload.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function ReportDownload({ datasetId }) {
  const [loading, setLoading] = useState(null);
  const [error, setError] = useState(null);
  const [isPremium, setIsPremium] = useState(false);

  useEffect(() => {
    api.get("/me").then((res) => setIsPremium(res.data.plan === "premium")).catch(() => {});
  }, []);

  const extensions = { pdf: "pdf", excel: "xlsx", pptx: "pptx", json: "json", sql: "sql", csv: "csv" };

  const handleDownload = async (format) => {
    setLoading(format);
    setError(null);

    try {
      const response = await api.get(`/dataset/${datasetId}/report`, {
        params: { format, include_ai_sections: true },
        responseType: "blob",
      });

      if (!response?.data) {
        throw new Error("Empty report response.");
      }

      let url = null;
      try {
        const blob = new Blob([response.data]);
        url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `report.${extensions[format] || format}`;
        document.body.appendChild(link);
        link.click();
        link.remove();
      } finally {
        if (url) {
          window.URL.revokeObjectURL(url);
        }
      }
    } catch (err) {
      if (err.response?.status === 403) {
        setError("This format requires a Premium plan.");
      } else {
        setError(errorDetail(err, "Could not generate the report. Please try again."));
      }
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="report-card">
      <h2>Generate Report</h2>
      <p className="privacy-note">
        🔒 Your data stays on this server and is never sent anywhere except to the AI provider for generating insights/queries. Delete it anytime from the History panel.
      </p>
      <p className="subtitle">
        Download a full report including key metrics, data quality notes, and AI-generated insights.
        {isPremium && " Premium reports also include an embedded chart and your custom branding."}
      </p>

      <div className="report-buttons">
        <button onClick={() => handleDownload("pdf")} disabled={loading !== null}>
          {loading === "pdf" ? "Generating..." : "Download PDF"}
        </button>
        <button onClick={() => handleDownload("excel")} disabled={loading !== null}>
          {loading === "excel" ? "Generating..." : "Download Excel (.xlsx)"}
        </button>
        <button onClick={() => handleDownload("pptx")} disabled={loading !== null}>
          {loading === "pptx" ? "Generating..." : "Download PPT"}
        </button>
        <button onClick={() => handleDownload("csv")} disabled={loading !== null}>
          {loading === "csv" ? "Generating..." : "Download CSV"}
        </button>
        <button
          onClick={() => handleDownload("json")}
          disabled={loading !== null || !isPremium}
          title={isPremium ? undefined : "Premium feature: upgrade to export JSON."}
        >
          {loading === "json" ? "Generating..." : "⭐ Download JSON"}
        </button>
        <button
          onClick={() => handleDownload("sql")}
          disabled={loading !== null || !isPremium}
          title={isPremium ? undefined : "Premium feature: upgrade to export SQL scripts."}
        >
          {loading === "sql" ? "Generating..." : "⭐ Download SQL Script"}
        </button>
      </div>

      {!isPremium && (
        <p className="subtitle">JSON and SQL exports are Premium features. Contact us to upgrade.</p>
      )}

      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

export default ReportDownload;