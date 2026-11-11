import { useState, useCallback, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function asNumber(value, fallback = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function asPercent(value) {
  const num = Number(value);
  return Number.isFinite(num) ? `${num.toFixed(2)}%` : "—";
}

function asList(value) {
  return Array.isArray(value)
    ? value.filter((item) => item !== null && item !== undefined)
    : [];
}

function asObjects(value) {
  return Array.isArray(value)
    ? value.filter((item) => item && typeof item === "object")
    : [];
}

function text(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function Badge({ children, tone = "neutral" }) {
  const tones = {
    neutral: { background: "rgba(15, 23, 42, 0.08)", color: "#0f172a" },
    good: { background: "rgba(13, 148, 136, 0.14)", color: "#0e7c66" },
    warn: { background: "rgba(217, 119, 6, 0.14)", color: "#b45309" },
    bad: { background: "rgba(220, 38, 38, 0.12)", color: "#b91c1c" },
  };

  const style = tones[tone] || tones.neutral;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: "999px",
        fontSize: "11px",
        fontWeight: 600,
        background: style.background,
        color: style.color,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function StatBox({ label, value, sub, tone = "neutral" }) {
  return (
    <div
      style={{
        border: "1px solid rgba(15, 23, 42, 0.12)",
        borderRadius: "10px",
        padding: "10px 12px",
        background: "rgba(255,255,255,0.55)",
        minWidth: 0,
      }}
    >
      <div className="subtitle" style={{ fontSize: "11px", marginBottom: "4px" }}>
        {label}
      </div>
      <div style={{ fontWeight: 700, fontSize: "16px", wordBreak: "break-word" }}>
        {value}
      </div>
      {sub ? (
        <div className="subtitle" style={{ fontSize: "11px", marginTop: "4px" }}>
          {sub}
        </div>
      ) : null}
      {tone !== "neutral" ? (
        <div style={{ marginTop: "6px" }}>
          <Badge tone={tone}>
            {tone === "good" ? "Healthy" : tone === "warn" ? "Review" : "Attention"}
          </Badge>
        </div>
      ) : null}
    </div>
  );
}

export default function QualitySummaryCard({ datasetId, currentDataVersion = null }) {
  const [quality, setQuality] = useState(null);
  const [plan, setPlan] = useState(null);
  const [dataVersion, setDataVersion] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);
  const [copyMessage, setCopyMessage] = useState(null);
  const [open, setOpen] = useState(true);

  const resetState = useCallback(() => {
    setQuality(null);
    setPlan(null);
    setDataVersion(null);
    setLoaded(false);
    setError(null);
    setWarning(null);
    setCopyMessage(null);
  }, []);

  useEffect(() => {
    resetState();
  }, [datasetId, resetState]);

  useEffect(() => {
    const handleDatasetChanged = (event) => {
      const changedId = event?.detail?.dataset_id;

      if (
        changedId &&
        datasetId &&
        String(changedId) !== String(datasetId)
      ) {
        return;
      }

      setWarning("Dataset changed. Refresh quality summary to see current results.");
      setCopyMessage(null);
    };

    window.addEventListener("dataset-changed", handleDatasetChanged);

    return () => {
      window.removeEventListener("dataset-changed", handleDatasetChanged);
    };
  }, [datasetId]);

  const loadSummary = useCallback(async () => {
    if (!datasetId) return;

    setLoading(true);
    setError(null);
    setWarning(null);
    setCopyMessage(null);

    try {
      const results = await Promise.allSettled([
        api.get(`/dataset/${datasetId}/quality-summary`),
        api.get(`/dataset/${datasetId}/cleaning-plan`),
      ]);

      const qualityPayload =
        results[0].status === "fulfilled" &&
        results[0].value?.data &&
        typeof results[0].value.data === "object"
          ? results[0].value.data
          : null;

      const planPayload =
        results[1].status === "fulfilled" &&
        results[1].value?.data &&
        typeof results[1].value.data === "object"
          ? results[1].value.data
          : null;

      const firstError =
        results.find((result) => result.status === "rejected")?.reason || null;

      setQuality(qualityPayload);
      setPlan(planPayload);

      const nextVersion =
        qualityPayload?.data_version ||
        planPayload?.data_version ||
        null;

      setDataVersion(typeof nextVersion === "string" ? nextVersion : null);

      if (!qualityPayload && !planPayload) {
        setError(errorDetail(firstError, "Could not load quality summary."));
        setLoaded(false);
      } else {
        setLoaded(true);
        setOpen(true);

        if (!qualityPayload || !planPayload) {
          setWarning("Some quality/cleaning sections could not load. Try refreshing.");
        }
      }
    } catch (err) {
      setError(errorDetail(err, "Could not load quality summary."));
      setLoaded(false);
    } finally {
      setLoading(false);
    }
  }, [datasetId]);

  const isStale = Boolean(
    currentDataVersion &&
    dataVersion &&
    String(currentDataVersion) !== String(dataVersion)
  );

  const buildSummaryMarkdown = () => {
    const lines = [];

    lines.push(`# Quality Summary & Cleaning Plan — ${text(datasetId)}`);
    lines.push("");
    lines.push(`Exported at: ${new Date().toISOString()}`);
    lines.push(`Data version: ${text(dataVersion, "unknown")}`);
    lines.push("Generated by deterministic rules. Not AI-generated.");
    lines.push("");

    if (quality && typeof quality === "object") {
      lines.push("## Quality Summary");
      lines.push("");
      lines.push(`- Health score: ${asNumber(quality.health_score).toFixed(2)} / 100`);
      lines.push(`- Completeness: ${asPercent(quality.completeness_percent)}`);
      lines.push(`- Rows: ${asNumber(quality.row_count).toLocaleString()}`);
      lines.push(`- Columns: ${asNumber(quality.column_count).toLocaleString()}`);
      lines.push(`- Missing cells: ${asNumber(quality.missing_cells).toLocaleString()}`);
      lines.push(`- Duplicate rows: ${asNumber(quality.duplicate_rows).toLocaleString()}`);
      lines.push(`- Total issues: ${asNumber(quality.total_issue_count).toLocaleString()}`);

      const pk = asList(quality.primary_key_candidates).slice(0, 10);
      if (pk.length) {
        lines.push(`- Primary key candidates: ${pk.map((x) => text(x)).join(", ")}`);
      }

      const freshness =
        quality.freshness && typeof quality.freshness === "object"
          ? quality.freshness
          : null;

      if (freshness) {
        lines.push(`- Latest date column: ${text(freshness.latest_date_column)}`);
        lines.push(`- Latest date: ${text(freshness.latest_date)}`);

        if (
          freshness.days_since_latest !== null &&
          freshness.days_since_latest !== undefined
        ) {
          lines.push(`- Age: ${asNumber(freshness.days_since_latest)} day(s)`);
        }
      }

      const worst = asObjects(quality.worst_missing_columns).slice(0, 10);
      if (worst.length) {
        lines.push("");
        lines.push("### Worst Missing Columns");

        for (const col of worst) {
          lines.push(
            `- ${text(col.name)}: ${asNumber(col.missing_values).toLocaleString()} missing (${asPercent(col.missing_percent)})`
          );
        }
      }
    } else {
      lines.push("Quality summary is not available.");
    }

    if (plan && typeof plan === "object") {
      lines.push("");
      lines.push("## Cleaning Plan");
      lines.push("");
      lines.push(`- Health score: ${asNumber(plan.health_score).toFixed(2)} / 100`);
      lines.push(`- Total issues: ${asNumber(plan.total_issue_count).toLocaleString()}`);
      lines.push(`- Safe actions: ${asNumber(plan.safe_action_count).toLocaleString()}`);
      lines.push(`- Review actions: ${asNumber(plan.review_action_count).toLocaleString()}`);

      const rows = asObjects(plan.plan).slice(0, 50);

      if (rows.length) {
        lines.push("");
        lines.push("### Recommended Actions");

        for (const row of rows) {
          const action = text(row.action);
          const column = row.column ? ` on ${text(row.column)}` : "";
          const risk = text(row.risk, "review");
          const reason = text(row.reason, "—");

          lines.push(`- ${action}${column} (${risk}): ${reason}`);
        }
      } else {
        lines.push("");
        lines.push("No specific cleaning actions were recommended.");
      }

      if (plan.plan_truncated) {
        lines.push("");
        lines.push("Note: plan truncated to first 50 actions in this card.");
      }

      lines.push("");
      lines.push(
        `Disclaimer: ${text(
          plan.disclaimer,
          "This plan is rule-based. Review preview before applying destructive actions."
        )}`
      );
    } else {
      lines.push("");
      lines.push("Cleaning plan is not available.");
    }

    return lines.join("\n");
  };

  const downloadSummaryMarkdown = () => {
    try {
      const markdown = buildSummaryMarkdown();
      const blob = new Blob([markdown], {
        type: "text/markdown;charset=utf-8;",
      });

      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `quality-summary-${datasetId}-${stamp}.md`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorDetail(err, "Could not download quality summary Markdown."));
    }
  };

  const copySummaryMarkdown = async () => {
    try {
      const markdown = buildSummaryMarkdown();

      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(markdown);
        setCopyMessage("Copied quality summary Markdown to clipboard.");
      } else {
        setWarning("Clipboard copy is not available in this browser context.");
      }
    } catch {
      setWarning("Could not copy quality summary Markdown.");
    }
  };

  const downloadJson = () => {
    try {
      const payload = {
        dataset_id: datasetId,
        data_version: dataVersion,
        exported_at: new Date().toISOString(),
        generated_by: "deterministic-quality-summary-card",
        ai_generated: false,
        quality,
        cleaning_plan: plan,
      };

      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });

      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `quality-summary-${datasetId}-${stamp}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorDetail(err, "Could not download quality summary JSON."));
    }
  };

  if (!datasetId) return null;

  const healthScore = asNumber(quality?.health_score ?? plan?.health_score, 0);
  const completeness = quality?.completeness_percent;
  const missingCells = asNumber(quality?.missing_cells, 0);
  const duplicateRows = asNumber(quality?.duplicate_rows, 0);
  const totalIssues = asNumber(quality?.total_issue_count ?? plan?.total_issue_count, 0);
  const rowCount = asNumber(quality?.row_count ?? plan?.row_count, 0);
  const columnCount = asNumber(quality?.column_count ?? plan?.column_count, 0);

  const primaryKeyCandidates = asList(quality?.primary_key_candidates).slice(0, 8);
  const freshness =
    quality?.freshness && typeof quality.freshness === "object"
      ? quality.freshness
      : null;

  const planRows = asObjects(plan?.plan).slice(0, 50);
  const safeCount = asNumber(plan?.safe_action_count, 0);
  const reviewCount = asNumber(plan?.review_action_count, 0);

  const healthTone = healthScore >= 80 ? "good" : healthScore >= 55 ? "warn" : "bad";
  const duplicateTone = duplicateRows > 0 ? "warn" : "good";
  const missingTone = missingCells > 0 ? "warn" : "good";
  const issueTone = totalIssues > 0 ? "warn" : "good";

  return (
    <div className="history-panel" style={{ marginTop: "12px", marginBottom: "12px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "8px",
          flexWrap: "wrap",
          marginBottom: "6px",
        }}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          title={open ? "Collapse" : "Expand"}
          style={{
            background: "transparent",
            border: "0",
            padding: 0,
            font: "inherit",
            fontWeight: 700,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          {open ? "▾" : "▸"} Quality Summary & Cleaning Plan
        </button>
        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
          <Badge tone="good">0 AI quota</Badge>
          <Badge tone={dataVersion ? "neutral" : "warn"}>
            {dataVersion ? `Version ${String(dataVersion).slice(0, 8)}` : "No version"}
          </Badge>
          {isStale ? (
            <Badge tone="bad">Stale</Badge>
          ) : dataVersion ? (
            <Badge tone="good">Current</Badge>
          ) : null}
        </div>
      </div>

      <p className="subtitle" style={{ fontSize: "12px", margin: "0 0 8px" }}>
        Rule-based dataset health and safe cleaning suggestions. This does not modify data automatically.
      </p>

      <div className="button-group" style={{ marginBottom: "8px", flexWrap: "wrap" }}>
        <button
          type="button"
          className="demo-button"
          onClick={loadSummary}
          disabled={loading}
        >
          {loading
            ? "Loading..."
            : isStale
            ? "Refresh Stale Summary"
            : loaded
            ? "Refresh Summary"
            : "Load Quality Summary"}
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={downloadJson}
          disabled={!loaded || loading}
        >
          Download JSON
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={downloadSummaryMarkdown}
          disabled={!loaded || loading}
        >
          Download Markdown
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={copySummaryMarkdown}
          disabled={!loaded || loading}
        >
          Copy Markdown
        </button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}

      {warning ? (
        <p className="subtitle" style={{ fontSize: "12px", color: "#b45309" }}>
          {warning}
        </p>
      ) : null}

      {copyMessage ? (
        <p className="subtitle" style={{ fontSize: "12px", color: "#0e7c66" }}>
          {copyMessage}
        </p>
      ) : null}

      {isStale ? (
        <p className="subtitle" style={{ fontSize: "12px", color: "#b91c1c" }}>
          The dataset has changed since this summary was loaded. Refresh to see current results.
        </p>
      ) : null}

      {open && loaded ? (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: "8px",
              marginBottom: "10px",
            }}
          >
            <StatBox
              label="Health Score"
              value={`${healthScore.toFixed(2)} / 100`}
              sub="Deterministic quality score"
              tone={healthTone}
            />
            <StatBox
              label="Completeness"
              value={asPercent(completeness)}
              sub={`${missingCells} missing cells`}
              tone={missingTone}
            />
            <StatBox
              label="Rows"
              value={rowCount.toLocaleString()}
              sub={`${columnCount} columns`}
            />
            <StatBox
              label="Duplicate Rows"
              value={duplicateRows.toLocaleString()}
              sub={asPercent(quality?.duplicate_row_percent)}
              tone={duplicateTone}
            />
            <StatBox
              label="Issues Detected"
              value={totalIssues.toLocaleString()}
              sub={`${safeCount} safe actions, ${reviewCount} review actions`}
              tone={issueTone}
            />
          </div>

          {primaryKeyCandidates.length > 0 ? (
            <div style={{ marginBottom: "10px" }}>
              <div style={{ fontWeight: 700, fontSize: "13px", marginBottom: "6px" }}>
                Primary Key Candidates
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {primaryKeyCandidates.map((name, idx) => (
                  <Badge key={`${text(name)}-${idx}`} tone="good">
                    {text(name)}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          {freshness ? (
            <div
              style={{
                border: "1px solid rgba(15, 23, 42, 0.12)",
                borderRadius: "10px",
                padding: "10px",
                fontSize: "12px",
                marginBottom: "10px",
              }}
            >
              <div>
                <strong>Latest date column:</strong> {text(freshness.latest_date_column)}
              </div>
              <div>
                <strong>Latest date:</strong> {text(freshness.latest_date)}
              </div>
              {freshness.days_since_latest !== null &&
              freshness.days_since_latest !== undefined ? (
                <div>
                  <strong>Age:</strong> {asNumber(freshness.days_since_latest)} day(s)
                </div>
              ) : null}
            </div>
          ) : null}

          <div style={{ fontWeight: 700, fontSize: "13px", margin: "12px 0 6px" }}>
            Recommended Cleaning Plan
          </div>

          {planRows.length === 0 ? (
            <p className="subtitle" style={{ fontSize: "12px" }}>
              No specific cleaning actions were recommended by the deterministic checker.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table" style={{ fontSize: "12px" }}>
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Column</th>
                    <th>Risk</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {planRows.map((item, idx) => {
                    const risk = text(item.risk, "review").toLowerCase();
                    const tone = risk === "safe" ? "good" : "warn";

                    return (
                      <tr key={`${text(item.action)}-${text(item.column)}-${idx}`}>
                        <td>{text(item.action)}</td>
                        <td>{text(item.column, "—")}</td>
                        <td>
                          <Badge tone={tone}>{risk}</Badge>
                        </td>
                        <td>{text(item.reason, "—")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {plan?.plan_truncated ? (
            <p className="subtitle" style={{ fontSize: "11px", marginTop: "6px" }}>
              Showing first 50 recommended actions only.
            </p>
          ) : null}

          {plan?.disclaimer ? (
            <p className="subtitle" style={{ fontSize: "11px", marginTop: "8px" }}>
              {text(plan.disclaimer)}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}