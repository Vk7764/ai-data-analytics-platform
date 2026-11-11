import { useState, useCallback, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function asNumber(value, fallback = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
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
            {tone === "good" ? "Low risk" : tone === "warn" ? "Review" : "Attention"}
          </Badge>
        </div>
      ) : null}
    </div>
  );
}

export default function CleaningPlanCard({ datasetId, onDatasetChanged }) {
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [previewing, setPreviewing] = useState(false);
  const [previewResult, setPreviewResult] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [applying, setApplying] = useState(false);
  const [appliedMessage, setAppliedMessage] = useState(null);
  const [applyError, setApplyError] = useState(null);
  const [copyMessage, setCopyMessage] = useState(null);

  const [savedConfigs, setSavedConfigs] = useState([]);
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [saveTitle, setSaveTitle] = useState("");
  const [savedError, setSavedError] = useState(null);
  const [savedMessage, setSavedMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [open, setOpen] = useState(true);

  const resetPreview = useCallback(() => {
    setPreviewResult(null);
    setPreviewError(null);
    setApplyError(null);
  }, []);

  const resetState = useCallback(() => {
    setPlan(null);
    setLoaded(false);
    setError(null);
    setWarning(null);
    setSelectedIndex(0);
    setAppliedMessage(null);
    setCopyMessage(null);
    setSavedError(null);
    setSavedMessage(null);
    setSelectedSavedId("");
    setSaveTitle("");
    resetPreview();
  }, [resetPreview]);

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

      setWarning("Dataset changed. Refresh cleaning plan to see updated recommendations.");
      setAppliedMessage(null);
      setCopyMessage(null);
      setSavedMessage(null);
      resetPreview();
    };

    window.addEventListener("dataset-changed", handleDatasetChanged);

    return () => {
      window.removeEventListener("dataset-changed", handleDatasetChanged);
    };
  }, [datasetId, resetPreview]);

  const loadPlan = useCallback(async () => {
    if (!datasetId) return;

    setLoading(true);
    setError(null);
    setWarning(null);
    setAppliedMessage(null);
    setCopyMessage(null);
    setSavedError(null);
    setSavedMessage(null);
    resetPreview();

    try {
      const res = await api.get(`/dataset/${datasetId}/cleaning-plan`);
      const data = res?.data && typeof res.data === "object" ? res.data : null;

      if (!data) {
        setError("Cleaning plan returned an unexpected result.");
        setLoaded(false);
        return;
      }

      setPlan(data);
      setLoaded(true);
      setOpen(true);
      setSelectedIndex(0);

      const rows = asObjects(data.plan);
      if (rows.length === 0) {
        setWarning("No cleaning actions were recommended.");
      }
    } catch (err) {
      setPlan(null);
      setLoaded(false);
      setError(errorDetail(err, "Could not load cleaning plan."));
    } finally {
      setLoading(false);
    }
  }, [datasetId, resetPreview]);

  const rows = asObjects(plan?.plan).slice(0, 50);
  const selected = rows[selectedIndex] || null;

  const selectedRequestJson = (() => {
    if (!selected) return "";

    const payload =
      selected.preview_request && typeof selected.preview_request === "object"
        ? selected.preview_request
        : {
            action: selected.action,
            column: selected.column || undefined,
          };

    try {
      return JSON.stringify(payload, null, 2);
    } catch {
      return "";
    }
  })();

  const fetchSavedConfigs = useCallback(async () => {
    if (!datasetId) {
      setSavedConfigs([]);
      return;
    }

    setLoadingSaved(true);
    setSavedError(null);

    try {
      const res = await api.get(
        `/dataset/${datasetId}/saved-analyses?analysis_type=cleaning_plan`
      );

      const list = Array.isArray(res?.data?.analyses) ? res.data.analyses : [];
      const safe = [];

      for (const item of list) {
        if (!item || typeof item !== "object") continue;

        const id = String(item.analysis_id || item.id || "").trim();
        if (!id) continue;

        safe.push({
          id,
          title: String(item.title || "Untitled cleaning config"),
          analysis_type: "cleaning_plan",
        });
      }

      setSavedConfigs(safe);
    } catch (err) {
      setSavedConfigs([]);
      setSavedError(errorDetail(err, "Could not load saved cleaning configs."));
    } finally {
      setLoadingSaved(false);
    }
  }, [datasetId]);

  useEffect(() => {
    fetchSavedConfigs();
  }, [fetchSavedConfigs]);

  const handleSaveConfig = async () => {
    if (!datasetId || !loaded) {
      setSavedError("Load cleaning plan before saving a config.");
      return;
    }

    if (!selected) {
      setSavedError("Select a cleaning action before saving.");
      return;
    }

    const title =
      String(saveTitle || "").trim() ||
      `Cleaning plan ${new Date().toLocaleString()}`;

    const selectedRow = rows[selectedIndex] || null;

    setSaving(true);
    setSavedError(null);
    setSavedMessage(null);

    try {
      await api.post(`/dataset/${datasetId}/saved-analyses`, {
        title: title.slice(0, 120),
        analysis_type: "cleaning_plan",
        parameters: {
          selected_index: selectedIndex,
          selected_action: selectedRow?.action || null,
          selected_column: selectedRow?.column || null,
          data_version: plan?.data_version || null,
          saved_at: new Date().toISOString(),
        },
      });

      setSavedMessage("Cleaning config saved.");
      setSaveTitle("");
      await fetchSavedConfigs();
    } catch (err) {
      setSavedError(errorDetail(err, "Could not save cleaning config."));
    } finally {
      setSaving(false);
    }
  };

  const handleLoadConfig = async () => {
    if (!datasetId || !selectedSavedId) return;

    setLoadingSaved(true);
    setSavedError(null);
    setSavedMessage(null);

    try {
      const res = await api.get(
        `/dataset/${datasetId}/saved-analyses/${encodeURIComponent(selectedSavedId)}`
      );

      const analysis = res?.data?.analysis;
      const isStale = Boolean(res?.data?.is_stale);

      const params =
        analysis?.parameters && typeof analysis?.parameters === "object"
          ? analysis.parameters
          : {};

      const nextIndex = Number(params.selected_index);
      const validIndex =
        Number.isInteger(nextIndex) && nextIndex >= 0 ? nextIndex : 0;

      if (!loaded) {
        await loadPlan();
      }

      setSelectedIndex(validIndex);
      setOpen(true);
      resetPreview();

      const savedTitle = String(analysis?.title || selectedSavedId);

      const savedAction =
        typeof params.selected_action === "string" && params.selected_action
          ? params.selected_action
          : "";

      const savedColumn =
        typeof params.selected_column === "string" && params.selected_column
          ? params.selected_column
          : "";

      const label = savedAction
        ? `${savedTitle} • ${savedAction}${savedColumn ? ` on ${savedColumn}` : ""}`
        : savedTitle;

      setSavedMessage(
        isStale
          ? `Loaded saved cleaning config (${label}), but the dataset has changed since it was saved. Refresh plan to see current recommendations.`
          : `Loaded saved cleaning config: ${label}`
      );
    } catch (err) {
      setSavedError(errorDetail(err, "Could not load saved cleaning config."));
    } finally {
      setLoadingSaved(false);
    }
  };

  const previewSelectedAction = async () => {
    if (!datasetId || !selected) return;

    setPreviewing(true);
    setPreviewError(null);
    setPreviewResult(null);

    const payload =
      selected.preview_request && typeof selected.preview_request === "object"
        ? selected.preview_request
        : {
            action: selected.action,
            column: selected.column || undefined,
          };

    try {
      const res = await api.post(`/dataset/${datasetId}/clean/preview`, payload);
      const data = res?.data && typeof res.data === "object" ? res.data : null;

      if (!data) {
        setPreviewError("Preview returned an unexpected result.");
        return;
      }

      setPreviewResult(data);
    } catch (err) {
      setPreviewError(errorDetail(err, "Could not preview this cleaning action."));
    } finally {
      setPreviewing(false);
    }
  };

  const applySelectedAction = async () => {
    if (!datasetId || !selected || !previewResult) return;

    const confirmed = window.confirm(
      `Apply "${text(selected.action)}"${
        selected.column ? ` on ${text(selected.column)}` : ""
      }? You can undo this action from Cleaning History if needed.`
    );

    if (!confirmed) return;

    setApplying(true);
    setApplyError(null);
    setAppliedMessage(null);

    const payload =
      selected.preview_request && typeof selected.preview_request === "object"
        ? selected.preview_request
        : {
            action: selected.action,
            column: selected.column || undefined,
          };

    try {
      const res = await api.post(`/dataset/${datasetId}/clean`, payload);
      const data = res?.data && typeof res.data === "object" ? res.data : null;

      if (!data) {
        setApplyError("Apply returned an unexpected result.");
        return;
      }

      setAppliedMessage(data.message || "Cleaning action applied.");
      setWarning("Dataset changed. Refresh cleaning plan to see updated recommendations.");
      setCopyMessage(null);
      resetPreview();

      try {
        window.dispatchEvent(
          new CustomEvent("dataset-changed", {
            detail: {
              dataset_id: datasetId,
              source: "cleaning_plan_apply",
            },
          })
        );
      } catch {
        // Older browser contexts may not support CustomEvent.
        // The direct callback below is still enough.
      }

      if (typeof onDatasetChanged === "function") {
        try {
          onDatasetChanged();
        } catch {
          // Parent refresh hook failed; dataset itself was updated successfully.
        }
      }
    } catch (err) {
      setApplyError(errorDetail(err, "Could not apply this cleaning action."));
    } finally {
      setApplying(false);
    }
  };

  const buildPlanMarkdown = () => {
    const lines = [];

    lines.push(`# Deterministic Cleaning Plan — ${text(datasetId)}`);
    lines.push("");
    lines.push(`Exported at: ${new Date().toISOString()}`);
    lines.push(`Data version: ${text(plan?.data_version, "unknown")}`);
    lines.push("Generated by deterministic rules. Not AI-generated.");
    lines.push("");

    lines.push(`- Health score: ${asNumber(plan?.health_score).toFixed(2)} / 100`);
    lines.push(`- Total issues: ${asNumber(plan?.total_issue_count).toLocaleString()}`);
    lines.push(`- Safe actions: ${asNumber(plan?.safe_action_count).toLocaleString()}`);
    lines.push(`- Review actions: ${asNumber(plan?.review_action_count).toLocaleString()}`);

    const items = asObjects(plan?.plan).slice(0, 50);

    if (items.length > 0) {
      lines.push("");
      lines.push("## Recommended actions");
      lines.push("");

      for (const item of items) {
        const action = text(item.action);
        const column = item.column ? ` on ${text(item.column)}` : "";
        const risk = text(item.risk, "review");
        const reason = text(item.reason, "—");

        lines.push(`- ${action}${column} (${risk}): ${reason}`);
      }
    } else {
      lines.push("");
      lines.push("No specific cleaning actions were recommended.");
    }

    if (plan?.plan_truncated) {
      lines.push("");
      lines.push("Note: plan truncated to first 50 actions in this card.");
    }

    lines.push("");
    lines.push(
      `Disclaimer: ${text(
        plan?.disclaimer,
        "This plan is rule-based. Review preview before applying destructive actions."
      )}`
    );

    return lines.join("\n");
  };

  const downloadPlanMarkdown = () => {
    try {
      const markdown = buildPlanMarkdown();
      const blob = new Blob([markdown], {
        type: "text/markdown;charset=utf-8;",
      });

      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `cleaning-plan-${datasetId}-${stamp}.md`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorDetail(err, "Could not download cleaning plan Markdown."));
    }
  };

  const copyPlanMarkdown = async () => {
    try {
      const markdown = buildPlanMarkdown();

      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(markdown);
        setCopyMessage("Copied cleaning plan Markdown to clipboard.");
      } else {
        setWarning("Clipboard copy is not available in this browser context.");
      }
    } catch {
      setWarning("Could not copy cleaning plan Markdown.");
    }
  };

  const copyPreviewRequest = async () => {
    if (!selected) return;

    const payload =
      selected.preview_request && typeof selected.preview_request === "object"
        ? selected.preview_request
        : {
            action: selected.action,
            column: selected.column || undefined,
          };

    try {
      const json = JSON.stringify(payload, null, 2);

      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(json);
        setCopyMessage("Copied selected action request JSON.");
      } else {
        setWarning("Clipboard copy is not available in this browser context.");
      }
    } catch {
      setWarning("Could not copy selected action request JSON.");
    }
  };

  const downloadPlanJson = () => {
    try {
      const payload = {
        dataset_id: datasetId,
        exported_at: new Date().toISOString(),
        generated_by: "deterministic-cleaning-plan-card",
        ai_generated: false,
        cleaning_plan: plan,
      };

      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });

      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `cleaning-plan-${datasetId}-${stamp}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorDetail(err, "Could not download cleaning plan JSON."));
    }
  };

  if (!datasetId) return null;

  const safeCount = asNumber(plan?.safe_action_count, 0);
  const reviewCount = asNumber(plan?.review_action_count, 0);
  const totalIssues = asNumber(plan?.total_issue_count, 0);
  const healthScore = asNumber(plan?.health_score, 0);

  const healthTone = healthScore >= 80 ? "good" : healthScore >= 55 ? "warn" : "bad";
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
          {open ? "▾" : "▸"} Deterministic Cleaning Plan
        </button>
        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
          <Badge tone="good">0 AI quota</Badge>
          {plan?.data_version ? (
            <Badge tone="neutral">
              Version {String(plan.data_version).slice(0, 8)}
            </Badge>
          ) : null}
        </div>
      </div>

      <p className="subtitle" style={{ fontSize: "12px", margin: "0 0 8px" }}>
        Rule-based cleaning suggestions from detected data quality issues. This card only previews actions; it does not modify data automatically.
      </p>

      <div className="button-group" style={{ marginBottom: "8px", flexWrap: "wrap" }}>
        <button
          type="button"
          className="demo-button"
          onClick={loadPlan}
          disabled={loading}
        >
          {loading ? "Loading..." : loaded ? "Refresh Plan" : "Load Cleaning Plan"}
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={downloadPlanJson}
          disabled={!loaded || loading}
        >
          Download Plan JSON
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={downloadPlanMarkdown}
          disabled={!loaded || loading}
        >
          Download Plan Markdown
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={copyPlanMarkdown}
          disabled={!loaded || loading}
        >
          Copy Plan Markdown
        </button>
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "8px",
          alignItems: "center",
          marginBottom: "10px",
          padding: "10px",
          border: "1px solid rgba(15, 23, 42, 0.12)",
          borderRadius: "10px",
          background: "rgba(255,255,255,0.45)",
        }}
      >
        <input
          type="text"
          value={saveTitle}
          onChange={(e) => setSaveTitle(e.target.value)}
          placeholder="Optional cleaning config name"
          maxLength={120}
          style={{
            minWidth: "180px",
            flex: "1 1 180px",
            padding: "6px 8px",
            borderRadius: "6px",
            border: "1px solid rgba(15, 23, 42, 0.18)",
          }}
        />

        <button
          type="button"
          className="demo-button"
          onClick={handleSaveConfig}
          disabled={saving || loading || !loaded || !selected}
          title={!selected ? "Select an action before saving" : undefined}
        >
          {saving ? "Saving..." : "Save selected action"}
        </button>

        <select
          value={selectedSavedId}
          onChange={(e) => setSelectedSavedId(e.target.value)}
          style={{
            minWidth: "180px",
            flex: "1 1 180px",
            padding: "6px 8px",
            borderRadius: "6px",
            border: "1px solid rgba(15, 23, 42, 0.18)",
          }}
        >
          <option value="">Load saved config...</option>
          {savedConfigs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title}
            </option>
          ))}
        </select>

        <button
          type="button"
          className="logout-button"
          onClick={handleLoadConfig}
          disabled={!selectedSavedId || loadingSaved || loading}
        >
          {loadingSaved ? "Loading..." : "Load"}
        </button>
      </div>

      {savedError ? <p className="error-text">{savedError}</p> : null}

      {savedMessage ? (
        <p
          className="subtitle"
          style={{
            fontSize: "12px",
            color: "#0e7c66",
            margin: "0 0 8px",
          }}
        >
          {savedMessage}
        </p>
      ) : null}

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
              label="Total Issues"
              value={totalIssues.toLocaleString()}
              sub="From deterministic checker"
              tone={issueTone}
            />
            <StatBox
              label="Safe Actions"
              value={safeCount.toLocaleString()}
              sub="Usually low-risk"
              tone="good"
            />
            <StatBox
              label="Review Actions"
              value={reviewCount.toLocaleString()}
              sub="Preview before applying"
              tone="warn"
            />
          </div>

          {rows.length === 0 ? (
            <p className="subtitle" style={{ fontSize: "12px" }}>
              No specific cleaning actions were recommended by the deterministic checker.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table" style={{ fontSize: "12px" }}>
                <thead>
                  <tr>
                    <th>Select</th>
                    <th>Action</th>
                    <th>Column</th>
                    <th>Risk</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, idx) => {
                    const risk = text(row.risk, "review").toLowerCase();
                    const tone = risk === "safe" ? "good" : "warn";

                    return (
                      <tr key={`${text(row.action)}-${text(row.column)}-${idx}`}>
                        <td>
                          <input
                            type="radio"
                            name="cleaning-plan-action"
                            checked={selectedIndex === idx}
                            onChange={() => {
                              setSelectedIndex(idx);
                              setAppliedMessage(null);
                              resetPreview();
                            }}
                          />
                        </td>
                        <td>{text(row.action)}</td>
                        <td>{text(row.column, "—")}</td>
                        <td>
                          <Badge tone={tone}>{risk}</Badge>
                        </td>
                        <td>{text(row.reason, "—")}</td>
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

          {selected ? (
            <div
              style={{
                marginTop: "10px",
                padding: "10px",
                border: "1px solid rgba(15, 23, 42, 0.12)",
                borderRadius: "10px",
                background: "rgba(255,255,255,0.45)",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: "13px", marginBottom: "6px" }}>
                Selected action preview
              </div>

              <div className="subtitle" style={{ fontSize: "12px", marginBottom: "8px" }}>
                {text(selected.action)}
                {selected.column ? ` on ${text(selected.column)}` : ""}
              </div>

              <div
                className="button-group"
                style={{ marginBottom: "8px", flexWrap: "wrap" }}
              >
                <button
                  type="button"
                  className="demo-button"
                  onClick={previewSelectedAction}
                  disabled={previewing || loading}
                >
                  {previewing ? "Previewing..." : "Preview Selected Action"}
                </button>

                <button
                  type="button"
                  className="logout-button"
                  onClick={applySelectedAction}
                  disabled={!previewResult || applying || loading}
                  title={!previewResult ? "Preview the action before applying" : undefined}
                >
                  {applying ? "Applying..." : "Apply Previewed Action"}
                </button>

                <button
                  type="button"
                  className="logout-button"
                  onClick={copyPreviewRequest}
                  disabled={!selected || loading}
                >
                  Copy Request JSON
                </button>
              </div>

              {selectedRequestJson ? (
                <details
                  style={{
                    marginBottom: "8px",
                    fontSize: "12px",
                  }}
                >
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                    View selected action request JSON
                  </summary>
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      fontFamily: "inherit",
                      fontSize: "12px",
                      margin: "8px 0 0",
                      padding: "10px",
                      border: "1px solid rgba(15, 23, 42, 0.12)",
                      borderRadius: "10px",
                      background: "rgba(255,255,255,0.55)",
                    }}
                  >
                    {selectedRequestJson}
                  </pre>
                </details>
              ) : null}

              {appliedMessage ? (
                <p
                  className="subtitle"
                  style={{
                    fontSize: "12px",
                    color: "#0e7c66",
                    margin: "0 0 8px",
                  }}
                >
                  {appliedMessage}
                </p>
              ) : null}

              {applyError ? (
                <p className="error-text" style={{ marginTop: "8px" }}>
                  {applyError}
                </p>
              ) : null}

              {previewError ? (
                <p className="error-text" style={{ marginTop: "8px" }}>
                  {previewError}
                </p>
              ) : null}

              {previewResult ? (
                <div style={{ marginTop: "10px", fontSize: "12px" }}>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                      gap: "8px",
                      marginBottom: "8px",
                    }}
                  >
                    <div>
                      <strong>Rows before:</strong>{" "}
                      {asNumber(previewResult.rows_before).toLocaleString()}
                    </div>
                    <div>
                      <strong>Rows after:</strong>{" "}
                      {asNumber(previewResult.rows_after).toLocaleString()}
                    </div>
                    <div>
                      <strong>Cells changed:</strong>{" "}
                      {asNumber(previewResult.cells_changed).toLocaleString()}
                    </div>
                  </div>

                  {asList(previewResult.columns_affected).length > 0 ? (
                    <div style={{ marginBottom: "8px" }}>
                      <strong>Columns affected:</strong>{" "}
                      {asList(previewResult.columns_affected).map((c) => text(c)).join(", ")}
                    </div>
                  ) : null}

                  {asList(previewResult.warnings).length > 0 ? (
                    <div style={{ marginBottom: "8px" }}>
                      <strong>Warnings:</strong>
                      <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
                        {asList(previewResult.warnings).map((w, idx) => (
                          <li key={`${text(w)}-${idx}`}>{text(w)}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {asObjects(previewResult.sample_changes).length > 0 ? (
                    <div className="table-scroll">
                      <table className="data-table" style={{ fontSize: "12px" }}>
                        <thead>
                          <tr>
                            <th>Column</th>
                            <th>Row</th>
                            <th>Identifier</th>
                            <th>Old value</th>
                            <th>New value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {asObjects(previewResult.sample_changes).slice(0, 20).map((change, idx) => (
                            <tr key={`${text(change.column)}-${text(change.row_index)}-${idx}`}>
                              <td>{text(change.column)}</td>
                              <td>{asNumber(change.row_index).toLocaleString()}</td>
                              <td>{text(change.identifier, "—")}</td>
                              <td>{text(change.old_value, "—")}</td>
                              <td>{text(change.new_value, "—")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {previewResult.sample_changes_truncated ? (
                    <p className="subtitle" style={{ fontSize: "11px", marginTop: "6px" }}>
                      Sample changes truncated.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          {plan?.disclaimer ? (
            <p className="subtitle" style={{ fontSize: "11px", marginTop: "10px" }}>
              {text(plan.disclaimer)}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}