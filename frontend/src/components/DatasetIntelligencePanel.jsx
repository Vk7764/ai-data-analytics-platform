import { useState, useCallback, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

const TABS = [
  { id: "quality", label: "Quality Report" },
  { id: "catalog", label: "Metric Catalog" },
  { id: "narrative", label: "Narrative Summary" },
  { id: "cleaning", label: "Cleaning Plan" },
];

const INTELLIGENCE_TAB_TO_TYPE = {
  quality: "quality_report",
  catalog: "metric_catalog",
  narrative: "narrative_summary",
  cleaning: "cleaning_plan",
};

const INTELLIGENCE_SAVED_TYPES = new Set(
  Object.values(INTELLIGENCE_TAB_TO_TYPE)
);

const VALID_TAB_IDS = new Set(Object.keys(INTELLIGENCE_TAB_TO_TYPE));

function asNumber(value, fallback = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function asPercent(value) {
  const num = Number(value);
  return Number.isFinite(num) ? `${num.toFixed(2)}%` : "—";
}

function asList(value) {
  return Array.isArray(value) ? value.filter((item) => item !== null && item !== undefined) : [];
}

function asObjects(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object") : [];
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

function StatCard({ label, value, sub, tone = "neutral" }) {
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
          <Badge tone={tone}>{tone === "good" ? "Healthy" : tone === "warn" ? "Review" : "Attention"}</Badge>
        </div>
      ) : null}
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <div style={{ fontWeight: 700, margin: "12px 0 6px", fontSize: "13px" }}>
      {children}
    </div>
  );
}

function EmptyState({ message }) {
  return (
    <p className="subtitle" style={{ fontSize: "12px", margin: "6px 0" }}>
      {message}
    </p>
  );
}

function QualityTab({ data }) {
  if (!data || typeof data !== "object") {
    return <EmptyState message="Quality report is not available." />;
  }

  const columns = asObjects(data.columns).slice(0, 30);
  const issueCounts = data.issue_counts && typeof data.issue_counts === "object" ? data.issue_counts : {};
  const issueRows = Object.entries(issueCounts)
    .filter(([, value]) => asNumber(value) > 0)
    .slice(0, 20);

  const primaryKeyCandidates = asList(data.primary_key_candidates).slice(0, 10);
  const freshness = data.freshness && typeof data.freshness === "object" ? data.freshness : null;

  const healthScore = asNumber(data.health_score, 0);
  const duplicateRows = asNumber(data.duplicate_rows, 0);
  const missingCells = asNumber(data.missing_cells, 0);
  const totalIssues = asNumber(data.total_issue_count, 0);

  const healthTone = healthScore >= 80 ? "good" : healthScore >= 55 ? "warn" : "bad";
  const duplicateTone = duplicateRows > 0 ? "warn" : "good";
  const missingTone = missingCells > 0 ? "warn" : "good";
  const issueTone = totalIssues > 0 ? "warn" : "good";

  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: "8px",
          marginBottom: "10px",
        }}
      >
        <StatCard
          label="Health Score"
          value={`${healthScore.toFixed(2)} / 100`}
          sub="Deterministic quality score"
          tone={healthTone}
        />
        <StatCard
          label="Completeness"
          value={asPercent(data.completeness_percent)}
          sub={`${missingCells} missing cells`}
          tone={missingTone}
        />
        <StatCard
          label="Rows"
          value={asNumber(data.row_count).toLocaleString()}
          sub={`${asNumber(data.column_count)} columns`}
        />
        <StatCard
          label="Duplicate Rows"
          value={duplicateRows.toLocaleString()}
          sub={asPercent(data.duplicate_row_percent)}
          tone={duplicateTone}
        />
        <StatCard
          label="Total Issues"
          value={totalIssues.toLocaleString()}
          sub="From deterministic checker"
          tone={issueTone}
        />
        <StatCard
          label="Avg Unique Ratio"
          value={asNumber(data.average_unique_ratio).toFixed(4)}
          sub="Column uniqueness signal"
        />
      </div>

      {primaryKeyCandidates.length > 0 ? (
        <>
          <SectionTitle>Primary Key Candidates</SectionTitle>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
            {primaryKeyCandidates.map((name, idx) => (
              <Badge key={`${text(name)}-${idx}`} tone="good">
                {text(name)}
              </Badge>
            ))}
          </div>
        </>
      ) : (
        <EmptyState message="No single-column primary key candidate detected." />
      )}

      {freshness ? (
        <>
          <SectionTitle>Freshness</SectionTitle>
          <div
            style={{
              border: "1px solid rgba(15, 23, 42, 0.12)",
              borderRadius: "10px",
              padding: "10px",
              fontSize: "12px",
            }}
          >
            <div>
              <strong>Latest date column:</strong> {text(freshness.latest_date_column)}
            </div>
            <div>
              <strong>Latest date:</strong> {text(freshness.latest_date)}
            </div>
            {freshness.days_since_latest !== null && freshness.days_since_latest !== undefined ? (
              <div>
                <strong>Age:</strong> {asNumber(freshness.days_since_latest)} day(s)
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      <SectionTitle>Issue Counts</SectionTitle>
      {issueRows.length === 0 ? (
        <EmptyState message="No major issue buckets detected." />
      ) : (
        <div className="table-scroll">
          <table className="data-table" style={{ fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Issue</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {issueRows.map(([key, value], idx) => (
                <tr key={`${key}-${idx}`}>
                  <td>{text(key)}</td>
                  <td>{asNumber(value).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SectionTitle>Column Quality</SectionTitle>
      {columns.length === 0 ? (
        <EmptyState message="No column quality rows available." />
      ) : (
        <div className="table-scroll">
          <table className="data-table" style={{ fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Column</th>
                <th>Kind</th>
                <th>Missing</th>
                <th>Unique</th>
                <th>Unique Ratio</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {columns.map((col, idx) => {
                const flags = asList(col.flags).slice(0, 5);

                return (
                  <tr key={`${text(col.name)}-${idx}`}>
                    <td>{text(col.name)}</td>
                    <td>{text(col.kind)}</td>
                    <td>
                      {asNumber(col.missing_values).toLocaleString()} ({asPercent(col.missing_percent)})
                    </td>
                    <td>{asNumber(col.unique_values).toLocaleString()}</td>
                    <td>{asNumber(col.unique_ratio).toFixed(4)}</td>
                    <td>
                      {flags.length === 0 ? (
                        "—"
                      ) : (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                          {flags.map((flag, flagIdx) => (
                            <Badge key={`${text(flag)}-${flagIdx}`} tone="warn">
                              {text(flag)}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data.columns_truncated ? (
        <p className="subtitle" style={{ fontSize: "11px", marginTop: "6px" }}>
          Showing first 30 columns only.
        </p>
      ) : null}
    </div>
  );
}

function CatalogTab({ data }) {
  if (!data || typeof data !== "object") {
    return <EmptyState message="Metric catalog is not available." />;
  }

  const measures = asObjects(data.measures).slice(0, 30);
  const dimensions = asObjects(data.dimensions).slice(0, 30);
  const timeColumns = asObjects(data.time_columns).slice(0, 20);
  const candidateKeys = asList(data.candidate_keys).slice(0, 20);

  return (
    <div>
      <SectionTitle>Candidate Measures</SectionTitle>
      {measures.length === 0 ? (
        <EmptyState message="No numeric measure candidates detected." />
      ) : (
        <div className="table-scroll">
          <table className="data-table" style={{ fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Measure</th>
                <th>Default Aggregation</th>
                <th>Supported Aggregations</th>
              </tr>
            </thead>
            <tbody>
              {measures.map((measure, idx) => (
                <tr key={`${text(measure.name)}-${idx}`}>
                  <td>{text(measure.name)}</td>
                  <td>{text(measure.default_aggregation, "sum")}</td>
                  <td>{asList(measure.recommended_aggregations).map(String).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SectionTitle>Candidate Dimensions</SectionTitle>
      {dimensions.length === 0 ? (
        <EmptyState message="No dimension candidates detected." />
      ) : (
        <div className="table-scroll">
          <table className="data-table" style={{ fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Dimension</th>
                <th>Role</th>
                <th>Time Based</th>
              </tr>
            </thead>
            <tbody>
              {dimensions.map((dim, idx) => (
                <tr key={`${text(dim.name)}-${idx}`}>
                  <td>{text(dim.name)}</td>
                  <td>{text(dim.role)}</td>
                  <td>{dim.is_time_based ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SectionTitle>Time Columns</SectionTitle>
      {timeColumns.length === 0 ? (
        <EmptyState message="No time columns detected." />
      ) : (
        <div className="table-scroll">
          <table className="data-table" style={{ fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Time Column</th>
                <th>Supported Grains</th>
              </tr>
            </thead>
            <tbody>
              {timeColumns.map((col, idx) => (
                <tr key={`${text(col.name)}-${idx}`}>
                  <td>{text(col.name)}</td>
                  <td>{asList(col.supported_grains).map(String).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SectionTitle>Candidate Keys</SectionTitle>
      {candidateKeys.length === 0 ? (
        <EmptyState message="No unique-key candidates detected." />
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
          {candidateKeys.map((name, idx) => (
            <Badge key={`${text(name)}-${idx}`} tone="good">
              {text(name)}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function NarrativeTab({ data }) {
  if (!data || typeof data !== "object") {
    return <EmptyState message="Narrative summary is not available." />;
  }

  const bullets = asList(data.bullets).slice(0, 30);
  const summary = text(data.summary, "");
  const disclaimer = text(
    data.disclaimer,
    "Generated by deterministic rules. This is not AI-generated and does not use AI quota."
  );

  const copySummary = async () => {
    const value = summary || bullets.map(String).join("\n");
    if (!value) return;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      }
    } catch {
      // Clipboard can fail in private/incognito contexts; silently ignore.
    }
  };

  return (
    <div>
      <SectionTitle>Deterministic Summary</SectionTitle>
      {summary ? (
        <pre
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontFamily: "inherit",
            fontSize: "12px",
            margin: "0 0 10px",
            padding: "10px",
            border: "1px solid rgba(15, 23, 42, 0.12)",
            borderRadius: "10px",
            background: "rgba(255,255,255,0.55)",
          }}
        >
          {summary}
        </pre>
      ) : (
        <EmptyState message="No summary text available." />
      )}

      <div className="button-group" style={{ marginBottom: "10px" }}>
        <button
          type="button"
          className="logout-button"
          onClick={copySummary}
          disabled={!summary && bullets.length === 0}
        >
          Copy summary
        </button>
      </div>

      <SectionTitle>Bullets</SectionTitle>
      {bullets.length === 0 ? (
        <EmptyState message="No narrative bullets available." />
      ) : (
        <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "12px" }}>
          {bullets.map((bullet, idx) => (
            <li key={`${text(bullet)}-${idx}`} style={{ marginBottom: "4px" }}>
              {text(bullet)}
            </li>
          ))}
        </ul>
      )}

      <p className="subtitle" style={{ fontSize: "11px", marginTop: "10px" }}>
        {disclaimer}
      </p>
    </div>
  );
}

function CleaningTab({ data }) {
  if (!data || typeof data !== "object") {
    return <EmptyState message="Cleaning plan is not available." />;
  }

  const rows = asObjects(data.plan).slice(0, 50);
  const safeCount = asNumber(data.safe_action_count, 0);
  const reviewCount = asNumber(data.review_action_count, 0);
  const totalIssues = asNumber(data.total_issue_count, 0);
  const healthScore = asNumber(data.health_score, 0);
  const disclaimer = text(
    data.disclaimer,
    "This plan is rule-based. Review preview before applying destructive actions."
  );

  const healthTone = healthScore >= 80 ? "good" : healthScore >= 55 ? "warn" : "bad";
  const issueTone = totalIssues > 0 ? "warn" : "good";

  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: "8px",
          marginBottom: "10px",
        }}
      >
        <StatCard
          label="Health Score"
          value={`${healthScore.toFixed(2)} / 100`}
          sub="Deterministic quality score"
          tone={healthTone}
        />
        <StatCard
          label="Total Issues"
          value={totalIssues.toLocaleString()}
          sub="From deterministic checker"
          tone={issueTone}
        />
        <StatCard
          label="Safe Actions"
          value={safeCount.toLocaleString()}
          sub="Usually low-risk"
          tone="good"
        />
        <StatCard
          label="Review Actions"
          value={reviewCount.toLocaleString()}
          sub="Preview before applying"
          tone="warn"
        />
      </div>

      <SectionTitle>Recommended Cleaning Plan</SectionTitle>

      {rows.length === 0 ? (
        <EmptyState message="No specific cleaning actions were recommended by the deterministic checker." />
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
              {rows.map((row, idx) => {
                const risk = text(row.risk, "review").toLowerCase();
                const tone = risk === "safe" ? "good" : "warn";

                return (
                  <tr key={`${text(row.action)}-${text(row.column)}-${idx}`}>
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

      {data.plan_truncated ? (
        <p className="subtitle" style={{ fontSize: "11px", marginTop: "6px" }}>
          Showing first 50 recommended actions only.
        </p>
      ) : null}

      <p className="subtitle" style={{ fontSize: "11px", marginTop: "10px" }}>
        {disclaimer}
      </p>
    </div>
  );
}

export default function DatasetIntelligencePanel({ datasetId, currentDataVersion = null }) {
  const [activeTab, setActiveTab] = useState("quality");
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);

  const [quality, setQuality] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [narrative, setNarrative] = useState(null);
  const [cleaning, setCleaning] = useState(null);
  const [dataVersion, setDataVersion] = useState(null);

  const [savedAnalyses, setSavedAnalyses] = useState([]);
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [saveTitle, setSaveTitle] = useState("");
  const [savedError, setSavedError] = useState(null);
  const [savedMessage, setSavedMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [open, setOpen] = useState(true);

  const loadAll = useCallback(async () => {
    if (!datasetId) return;

    setLoading(true);
    setError(null);
    setWarning(null);
    setDataVersion(null);

    let qualityData = null;
    let catalogData = null;
    let narrativeData = null;
    let cleaningData = null;
    let firstError = null;
    let fallbackResults = null;

    try {
      try {
        const combined = await api.get(`/dataset/${datasetId}/intelligence`);
        const payload =
          combined?.data && typeof combined.data === "object" ? combined.data : {};

        const nextDataVersion =
          typeof payload.data_version === "string" && payload.data_version
            ? payload.data_version
            : null;

        setDataVersion(nextDataVersion);

        qualityData =
          payload.quality && typeof payload.quality === "object"
            ? payload.quality
            : null;

        catalogData =
          payload.catalog && typeof payload.catalog === "object"
            ? payload.catalog
            : null;

        narrativeData =
          payload.narrative && typeof payload.narrative === "object"
            ? payload.narrative
            : null;

        cleaningData =
          payload.cleaning_plan && typeof payload.cleaning_plan === "object"
            ? payload.cleaning_plan
            : null;
      } catch (err) {
        firstError = err;
      }

      if (!qualityData || !catalogData || !narrativeData || !cleaningData) {
        fallbackResults = await Promise.allSettled([
          qualityData
            ? Promise.resolve({ data: qualityData })
            : api.get(`/dataset/${datasetId}/quality-report`),
          catalogData
            ? Promise.resolve({ data: catalogData })
            : api.get(`/dataset/${datasetId}/metric-catalog`),
          narrativeData
            ? Promise.resolve({ data: narrativeData })
            : api.get(`/dataset/${datasetId}/narrative-summary`),
          cleaningData
            ? Promise.resolve({ data: cleaningData })
            : api.get(`/dataset/${datasetId}/cleaning-plan`),
        ]);

        const getData = (result) =>
          result.status === "fulfilled" &&
          result.value?.data &&
          typeof result.value.data === "object"
            ? result.value.data
            : null;

        qualityData = qualityData || getData(fallbackResults[0]);
        catalogData = catalogData || getData(fallbackResults[1]);
        narrativeData = narrativeData || getData(fallbackResults[2]);
        cleaningData = cleaningData || getData(fallbackResults[3]);
      }

      setQuality(qualityData);
      setCatalog(catalogData);
      setNarrative(narrativeData);
      setCleaning(cleaningData);

      const successCount = [qualityData, catalogData, narrativeData, cleaningData].filter(Boolean).length;

      if (!firstError && fallbackResults) {
        firstError =
          fallbackResults.find((result) => result.status === "rejected")?.reason || null;
      }

      if (successCount === 0) {
        setError(errorDetail(firstError, "Could not load dataset intelligence."));
        setLoaded(false);
      } else {
        setLoaded(true);
        setOpen(true);
        if (successCount < 4) {
          setWarning("Some intelligence sections could not load. Try refreshing.");
        }
      }
    } catch (err) {
      setError(errorDetail(err, "Could not load dataset intelligence."));
      setLoaded(false);
    } finally {
      setLoading(false);
    }
  }, [datasetId]);

  const fetchSavedAnalyses = useCallback(async () => {
    if (!datasetId) {
      setSavedAnalyses([]);
      return;
    }

    setLoadingSaved(true);
    setSavedError(null);

    try {
      const res = await api.get(`/dataset/${datasetId}/saved-analyses`);
      const list = Array.isArray(res?.data?.analyses) ? res.data.analyses : [];

      const safeList = [];
      for (const item of list) {
        if (!item || typeof item !== "object") continue;

        const id = String(item.analysis_id || item.id || "").trim();
        const type = String(item.analysis_type || "").trim();

        if (!id || !INTELLIGENCE_SAVED_TYPES.has(type)) continue;

        const label =
          String(item.title || "Untitled intelligence").trim() ||
          "Untitled intelligence";

        const typeLabel = type
          .replace(/_/g, " ")
          .replace(/\b\w/g, (ch) => ch.toUpperCase());

        safeList.push({
          id,
          title: label,
          analysis_type: type,
          label: `${label} • ${typeLabel}`,
        });
      }

      setSavedAnalyses(safeList);
    } catch (err) {
      setSavedAnalyses([]);
      setSavedError(errorDetail(err, "Could not load saved intelligence configs."));
    } finally {
      setLoadingSaved(false);
    }
  }, [datasetId]);

  useEffect(() => {
    fetchSavedAnalyses();
  }, [fetchSavedAnalyses]);

  useEffect(() => {
    setQuality(null);
    setCatalog(null);
    setNarrative(null);
    setCleaning(null);
    setDataVersion(null);
    setLoaded(false);
    setError(null);
    setWarning(null);
    setSavedError(null);
    setSavedMessage(null);
    setSelectedSavedId("");
  }, [datasetId]);

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

      setWarning("Dataset changed. Refresh intelligence to see current results.");
      setSavedMessage(null);
    };

    window.addEventListener("dataset-changed", handleDatasetChanged);

    return () => {
      window.removeEventListener("dataset-changed", handleDatasetChanged);
    };
  }, [datasetId]);

  const handleSaveIntelligence = async () => {
    if (!datasetId) return;

    if (!loaded) {
      setSavedError("Load intelligence before saving a config.");
      return;
    }

    const title =
      String(saveTitle || "").trim() ||
      `Intelligence ${new Date().toLocaleString()}`;

    const analysisType =
      INTELLIGENCE_TAB_TO_TYPE[activeTab] || "narrative_summary";

    const tabLabel =
      TABS.find((tab) => tab.id === activeTab)?.label || activeTab;

    setSaving(true);
    setSavedError(null);
    setSavedMessage(null);

    try {
      await api.post(`/dataset/${datasetId}/saved-analyses`, {
        title: title.slice(0, 120),
        analysis_type: analysisType,
        parameters: {
          active_tab: activeTab,
          tab_label: tabLabel,
          data_version: dataVersion,
          saved_at: new Date().toISOString(),
        },
      });

      setSavedMessage("Intelligence config saved.");
      setSaveTitle("");
      await fetchSavedAnalyses();
    } catch (err) {
      setSavedError(errorDetail(err, "Could not save intelligence config."));
    } finally {
      setSaving(false);
    }
  };

  const handleLoadIntelligenceConfig = async () => {
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

      const nextTab = VALID_TAB_IDS.has(params.active_tab)
        ? params.active_tab
        : activeTab;

      setActiveTab(nextTab);
      setOpen(true);

      if (!loaded) {
        await loadAll();
      }

      const savedTitle = String(analysis?.title || selectedSavedId);

      const savedTabLabel =
        typeof params.tab_label === "string" && params.tab_label.trim()
          ? params.tab_label.trim()
          : TABS.find((tab) => tab.id === nextTab)?.label || nextTab;

      setSavedMessage(
        isStale
          ? `Loaded saved intelligence (${savedTitle} • ${savedTabLabel}), but the dataset has changed since it was saved. Refresh intelligence to see current results.`
          : `Loaded saved intelligence: ${savedTitle} • ${savedTabLabel}`
      );
    } catch (err) {
      setSavedError(errorDetail(err, "Could not load saved intelligence config."));
    } finally {
      setLoadingSaved(false);
    }
  };

  const downloadIntelligenceJson = () => {
    try {
      const payload = {
        dataset_id: datasetId,
        data_version: dataVersion,
        exported_at: new Date().toISOString(),
        generated_by: "deterministic-intelligence-panel",
        ai_generated: false,
        quality,
        catalog,
        narrative,
        cleaning_plan: cleaning,
      };

      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });

      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `dataset-intelligence-${datasetId}-${stamp}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorDetail(err, "Could not export intelligence JSON."));
    }
  };

  const isStale = Boolean(
    currentDataVersion &&
    dataVersion &&
    String(currentDataVersion) !== String(dataVersion)
  );

  const copyText = async (value, successMessage) => {
    const textValue = String(value || "");
    if (!textValue) return;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(textValue);
        setSavedMessage(successMessage);
      } else {
        setWarning("Clipboard copy is not available in this browser context.");
      }
    } catch {
      setWarning("Could not copy to clipboard.");
    }
  };

  const buildIntelligenceMarkdown = () => {
    const lines = [];

    lines.push(`# Dataset Intelligence — ${datasetId}`);
    lines.push("");
    lines.push(`Exported at: ${new Date().toISOString()}`);
    lines.push(`Data version: ${dataVersion || "unknown"}`);
    lines.push("Generated by deterministic rules. Not AI-generated.");
    lines.push("");

    if (quality && typeof quality === "object") {
      lines.push("## Quality Report");
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

      const issueCounts =
        quality.issue_counts && typeof quality.issue_counts === "object"
          ? quality.issue_counts
          : {};

      const issueRows = Object.entries(issueCounts)
        .filter(([, value]) => asNumber(value) > 0)
        .slice(0, 20);

      if (issueRows.length) {
        lines.push("");
        lines.push("### Issue counts");

        for (const [key, value] of issueRows) {
          lines.push(`- ${text(key)}: ${asNumber(value).toLocaleString()}`);
        }
      }
    }

    if (catalog && typeof catalog === "object") {
      lines.push("");
      lines.push("## Metric Catalog");
      lines.push("");

      const measures = asObjects(catalog.measures).slice(0, 20);
      if (measures.length) {
        lines.push("### Measures");

        for (const m of measures) {
          lines.push(`- ${text(m.name)} (default: ${text(m.default_aggregation, "sum")})`);
        }
      }

      const dimensions = asObjects(catalog.dimensions).slice(0, 20);
      if (dimensions.length) {
        lines.push("");
        lines.push("### Dimensions");

        for (const d of dimensions) {
          lines.push(`- ${text(d.name)} (${text(d.role)})`);
        }
      }

      const timeColumns = asObjects(catalog.time_columns).slice(0, 20);
      if (timeColumns.length) {
        lines.push("");
        lines.push("### Time columns");

        for (const t of timeColumns) {
          lines.push(
            `- ${text(t.name)}: ${asList(t.supported_grains).map(String).join(", ") || "—"}`
          );
        }
      }

      const keys = asList(catalog.candidate_keys).slice(0, 20);
      if (keys.length) {
        lines.push("");
        lines.push("### Candidate keys");
        lines.push(`- ${keys.map((k) => text(k)).join(", ")}`);
      }
    }

    if (narrative && typeof narrative === "object") {
      lines.push("");
      lines.push("## Narrative Summary");
      lines.push("");

      const summary = text(narrative.summary, "");
      if (summary) {
        lines.push(summary);
      }

      const bullets = asList(narrative.bullets).slice(0, 30);
      if (bullets.length) {
        lines.push("");

        for (const b of bullets) {
          lines.push(`- ${text(b)}`);
        }
      }
    }

    if (cleaning && typeof cleaning === "object") {
      lines.push("");
      lines.push("## Cleaning Plan");
      lines.push("");

      lines.push(`- Health score: ${asNumber(cleaning.health_score).toFixed(2)} / 100`);
      lines.push(`- Total issues: ${asNumber(cleaning.total_issue_count).toLocaleString()}`);
      lines.push(`- Safe actions: ${asNumber(cleaning.safe_action_count).toLocaleString()}`);
      lines.push(`- Review actions: ${asNumber(cleaning.review_action_count).toLocaleString()}`);

      const rows = asObjects(cleaning.plan).slice(0, 30);

      if (rows.length) {
        lines.push("");
        lines.push("### Recommended actions");

        for (const row of rows) {
          const action = text(row.action);
          const column = row.column ? ` on ${text(row.column)}` : "";
          const risk = text(row.risk, "review");
          const reason = text(row.reason, "—");

          lines.push(`- ${action}${column} (${risk}): ${reason}`);
        }
      } else {
        lines.push("");
        lines.push("- No specific cleaning actions were recommended.");
      }

      const disclaimer = text(
        cleaning.disclaimer,
        "This plan is rule-based. Review preview before applying destructive actions."
      );

      lines.push("");
      lines.push(`Disclaimer: ${disclaimer}`);
    }

    return lines.join("\n");
  };

  const downloadIntelligenceMarkdown = () => {
    try {
      const markdown = buildIntelligenceMarkdown();
      const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8;" });
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `dataset-intelligence-${datasetId}-${stamp}.md`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorDetail(err, "Could not export intelligence Markdown."));
    }
  };

  if (!datasetId) return null;

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
          {open ? "▾" : "▸"} Dataset Intelligence (Deterministic)
        </button>
        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
          <Badge tone="good">0 AI quota</Badge>
          <Badge tone={dataVersion ? "neutral" : "warn"}>
            {dataVersion
              ? `Version ${String(dataVersion).slice(0, 8)}`
              : "No version"}
          </Badge>
          {isStale ? (
            <Badge tone="bad">Stale</Badge>
          ) : dataVersion ? (
            <Badge tone="good">Current</Badge>
          ) : null}
        </div>
      </div>

      <p className="subtitle" style={{ fontSize: "12px", margin: "0 0 8px" }}>
        Rule-based quality report, metric catalog, and narrative summary. Not AI-generated.
      </p>

      <div
        className="button-group"
        style={{ marginBottom: "8px", flexWrap: "wrap" }}
      >
        <button
          type="button"
          className="demo-button"
          onClick={loadAll}
          disabled={loading}
        >
          {loading
            ? "Loading..."
            : isStale
            ? "Refresh Stale Intelligence"
            : loaded
            ? "Refresh Intelligence"
            : "Load Intelligence"}
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={downloadIntelligenceJson}
          disabled={!loaded || loading}
        >
          Download JSON
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={downloadIntelligenceMarkdown}
          disabled={!loaded || loading}
        >
          Download Markdown
        </button>

        <button
          type="button"
          className="logout-button"
          onClick={() => copyText(buildIntelligenceMarkdown(), "Copied intelligence Markdown.")}
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

      {isStale ? (
        <p className="subtitle" style={{ fontSize: "12px", color: "#b91c1c" }}>
          The dataset has changed since this intelligence was loaded. Refresh intelligence to see current results.
        </p>
      ) : null}

      {open && loaded ? (
        <>
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
              placeholder="Optional config name"
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
              onClick={handleSaveIntelligence}
              disabled={saving || loading}
            >
              {saving ? "Saving..." : "Save current view"}
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
              {savedAnalyses.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label || `${item.title} (${item.analysis_type})`}
                </option>
              ))}
            </select>

            <button
              type="button"
              className="logout-button"
              onClick={handleLoadIntelligenceConfig}
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

          <div className="button-group" style={{ marginBottom: "10px", flexWrap: "wrap" }}>
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={activeTab === tab.id ? "demo-button" : "logout-button"}
                onClick={() => setActiveTab(tab.id)}
                disabled={loading}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === "quality" ? <QualityTab data={quality} /> : null}
          {activeTab === "catalog" ? <CatalogTab data={catalog} /> : null}
          {activeTab === "narrative" ? <NarrativeTab data={narrative} /> : null}
          {activeTab === "cleaning" ? <CleaningTab data={cleaning} /> : null}
        </>
      ) : null}
    </div>
  );
}