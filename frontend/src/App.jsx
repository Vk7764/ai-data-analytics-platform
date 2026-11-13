// frontend/src/App.jsx
import { useState, useEffect, Component, lazy, Suspense } from "react";

class SectionErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error: String(error?.message || error) };
  }

  componentDidCatch(error, info) {
    console.error("Section crashed:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="dashboard-card">
          <p className="error-text">Could not render this section: {this.state.error}</p>
          <button onClick={() => this.setState({ error: null })}>Retry Section</button>
        </div>
      );
    }
    return this.props.children;
  }
}
import LandingPage from "./components/LandingPage";
import LoginForm from "./components/LoginForm";
import LegalPage from "./components/LegalPage";
import ResetPasswordPage from "./components/ResetPasswordPage";
import VerifyEmailPage from "./components/VerifyEmailPage";
import SharedDatasetView from "./components/SharedDatasetView";
import ConfirmDeletePage from "./components/ConfirmDeletePage";
import VerifyEmailBanner from "./components/VerifyEmailBanner";
import UsageBadge from "./components/UsageBadge";
import HistoryDrawer from "./components/HistoryDrawer";
import AccountPage from "./components/AccountPage";
import UploadForm from "./components/UploadForm";
import BrandingSettings from "./components/BrandingSettings";
import CompareDatasets from "./components/CompareDatasets";
import SandboxNotice from "./components/SandboxNotice";
import { useLanguage } from "./i18n";

const DataCleaning = lazy(() => import("./components/DataCleaning"));
const AnalysisDashboard = lazy(() => import("./components/AnalysisDashboard"));
const TimeSeriesExplorer = lazy(() => import("./components/TimeSeriesExplorer"));
const CorrelationHeatmap = lazy(() => import("./components/CorrelationHeatmap"));
const AnomalyView = lazy(() => import("./components/AnomalyView"));
const RootCauseView = lazy(() => import("./components/RootCauseView"));
const ForecastView = lazy(() => import("./components/ForecastView"));
const ChatInterface = lazy(() => import("./components/ChatInterface"));
const ReportDownload = lazy(() => import("./components/ReportDownload"));
const ScheduledExports = lazy(() => import("./components/ScheduledExports"));
const DataProfile = lazy(() => import("./components/DataProfile"));

import "./App.css";

function LanguageToggle() {
  const { lang, setLanguage } = useLanguage();
  return (
    <button className="logout-button" onClick={() => setLanguage(lang === "hi" ? "en" : "hi")}>
      {lang === "hi" ? "English" : "हिंदी"}
    </button>
  );
}

function LazySection({ children, fallbackLabel = "Loading section..." }) {
  return (
    <Suspense
      fallback={
        <div className="dashboard-card">
          <p className="subtitle">{fallbackLabel}</p>
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

function ServerWakingBanner() {
  const [waking, setWaking] = useState(false);

  useEffect(() => {
    const handler = (e) => setWaking(Boolean(e?.detail?.waking));
    window.addEventListener("server-waking", handler);
    return () => window.removeEventListener("server-waking", handler);
  }, []);

  if (!waking) return null;

  return (
    <div
      role="status"
      style={{
        position: "fixed",
        bottom: 16,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 200,
        background: "var(--amber-bg)",
        border: "1px solid var(--amber)",
        color: "var(--ink)",
        borderRadius: 8,
        padding: "10px 16px",
        fontSize: 13,
        maxWidth: "90vw",
        boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
      }}
    >
      Waking up the server (free tier may take ~30s on first load)...
    </div>
  );
}

function App() {
  const { t } = useLanguage();
  // The ?token= value from emailed links (password reset, email verification,
  // account deletion). The page path decides which page is shown.
  const safeLocation =
    typeof window !== "undefined" && window.location
      ? window.location
      : { search: "", pathname: "/" };

  let urlToken = null;
  try {
    urlToken = new URLSearchParams(safeLocation.search || "").get("token");
  } catch {
    urlToken = null;
  }

  const currentPath =
    typeof safeLocation.pathname === "string" ? safeLocation.pathname : "/";

  // All hooks must stay above every early return below.
  const [isLoggedIn, setIsLoggedIn] = useState(() => !!localStorage.getItem("access_token"));
  const [view, setView] = useState("landing"); // "landing" | "auth"
  const [authMode, setAuthMode] = useState("login"); // initial form shown by the auth screen
  const [page, setPage] = useState("dashboard"); // "dashboard" | "account"
  const [datasetData, setDatasetData] = useState(null);
  const [dataVersion, setDataVersion] = useState(0);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [, forceRender] = useState(0);

  useEffect(() => {
    const handlePopState = () => forceRender((n) => n + 1);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // A 401 from the backend means the login session expired or is invalid.
  // Show the login screen with a clear message instead of a hard page reload.
  useEffect(() => {
    const handleAuthExpired = () => {
      setIsLoggedIn(false);
      setView("auth");
      setAuthMode("login");
      setDatasetData(null);
      setPage("dashboard");
      setSessionExpired(true);
    };
    window.addEventListener("auth-expired", handleAuthExpired);
    return () => window.removeEventListener("auth-expired", handleAuthExpired);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    setIsLoggedIn(false);
    setDatasetData(null);
    setPage("dashboard");
  };

  const handleUploadSuccess = (data) => {
    setDatasetData(data);
    setDataVersion((v) => v + 1);
  };

  const handleCleaned = (updatedData) => {
    setDatasetData((prev) => ({
      ...prev,
      profile: updatedData.profile,
      preview: updatedData.preview,
    }));
    setDataVersion((v) => v + 1);
  };

  const handleSelectDataset = (data) => {
    setDatasetData(data);
    setDataVersion((v) => v + 1);
    setPage("dashboard");
  };

  // ---------- Public pages (work with or without login) ----------

  if (currentPath === "/verify-email") {
    return <VerifyEmailPage token={urlToken} />;
  }

  if (currentPath === "/confirm-delete") {
    return <ConfirmDeletePage token={urlToken} />;
  }

  if (currentPath === "/reset-password" && urlToken) {
    return <ResetPasswordPage token={urlToken} onDone={() => { window.location.href = "/"; }} />;
  }

  // Public read-only share viewer: /shared/:token (no login required, no mutations).
  if (currentPath.startsWith("/shared/")) {
    let shareToken = "";

    try {
      const rawToken = currentPath
        .slice("/shared/".length)
        .split("?")[0]
        .split("#")[0];

      shareToken = decodeURIComponent(rawToken);
    } catch (err) {
      shareToken = "";
    }

    return <SharedDatasetView token={shareToken} />;
  }

  if (currentPath === "/terms") {
    return <LegalPage title="Terms of Service" file="/terms.md" />;
  }

  if (currentPath === "/privacy") {
    return <LegalPage title="Privacy Policy" file="/privacy.md" />;
  }

  // ---------- Logged-out visitors ----------

  if (!isLoggedIn) {
    if (view === "landing") {
      return (
        <LandingPage
          onGetStarted={() => { setAuthMode("signup"); setView("auth"); }}
          onLogin={() => { setAuthMode("login"); setView("auth"); }}
        />
      );
    }
    return (
      <>
        <ServerWakingBanner />
        {sessionExpired && (
          <p className="subtitle" style={{ textAlign: "center", marginTop: 16 }}>
            {t("sessionExpired")}
          </p>
        )}
        <LoginForm
          initialMode={authMode}
          onLoginSuccess={() => { setSessionExpired(false); setIsLoggedIn(true); }}
        />
      </>
    );
  }

  // ---------- The app ----------

  return (
    <div className="app-container">
      <ServerWakingBanner />
      <header className="app-header">
        <div className="app-header-left">
          <HistoryDrawer
            onSelectDataset={handleSelectDataset}
            activeDatasetId={datasetData?.dataset_id}
            onDeleteDataset={(deletedId) => {
              if (datasetData?.dataset_id === deletedId) setDatasetData(null);
              setDataVersion((v) => v + 1);
            }}
          />
          <h1>AI Data Analytics Platform</h1>
        </div>
        <div className="app-header-right">
          <LanguageToggle />
          <UsageBadge />
          <button
            className="logout-button"
            onClick={() => setPage(page === "account" ? "dashboard" : "account")}
          >
            {page === "account" ? t("dashboard") : t("account")}
          </button>
          <button className="logout-button" onClick={handleLogout}>{t("logout")}</button>
        </div>
      </header>

      {page === "account" ? (
        <AccountPage onBack={() => setPage("dashboard")} />
      ) : (
        <main>
          <VerifyEmailBanner />
          <SandboxNotice />
          <UploadForm onUploadSuccess={handleUploadSuccess} />
          <BrandingSettings />
          <CompareDatasets dataVersion={dataVersion} />

          {datasetData && (
            <>
              <nav className="section-nav">
                <a href="#section-cleaning">{t("navCleaning")}</a>
                <a href="#section-analysis">{t("navAnalysis")}</a>
                <a href="#section-timeseries">{t("navTimeSeries")}</a>
                <a href="#section-correlation">{t("navCorrelation")}</a>
                <a href="#section-anomalies">{t("navAnomalies")}</a>
                <a href="#section-rootcause">{t("navRootCause")}</a>
                <a href="#section-forecast">{t("navForecast")}</a>
                <a href="#section-chat">{t("navChat")}</a>
                <a href="#section-reports">{t("navReports")}</a>
                <a href="#section-overview">{t("navOverview")}</a>
              </nav>

              <div id="section-cleaning">
                <SectionErrorBoundary key={`clean-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading cleaning tools...">
                    <DataCleaning datasetId={datasetData.dataset_id} dataVersion={dataVersion} onCleaned={handleCleaned} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-analysis">
                <SectionErrorBoundary key={`analysis-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading analysis dashboard...">
                    <AnalysisDashboard datasetId={datasetData.dataset_id} dataVersion={dataVersion} columns={datasetData.profile.columns} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-timeseries">
                <SectionErrorBoundary key={`ts-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading time series explorer...">
                    <TimeSeriesExplorer datasetId={datasetData.dataset_id} columns={datasetData.profile.columns} dataVersion={dataVersion} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-correlation">
                <SectionErrorBoundary key={`corr-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading correlation heatmap...">
                    <CorrelationHeatmap datasetId={datasetData.dataset_id} dataVersion={dataVersion} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-anomalies">
                <SectionErrorBoundary key={`anom-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading anomaly detection...">
                    <AnomalyView datasetId={datasetData.dataset_id} dataVersion={dataVersion} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-rootcause">
                <SectionErrorBoundary key={`rc-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading root cause analysis...">
                    <RootCauseView datasetId={datasetData.dataset_id} columns={datasetData.profile.columns} dataVersion={dataVersion} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-forecast">
                <SectionErrorBoundary key={`fc-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading forecast...">
                    <ForecastView datasetId={datasetData.dataset_id} columns={datasetData.profile.columns} dataVersion={dataVersion} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-chat">
                <SectionErrorBoundary key={`chat-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading chat...">
                    <ChatInterface
                      datasetId={datasetData.dataset_id}
                      columns={datasetData.profile.columns}
                      onDatasetCreated={() => setDataVersion((v) => v + 1)}
                    />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-reports">
                <SectionErrorBoundary key={`rep-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading reports and schedules...">
                    <ReportDownload datasetId={datasetData.dataset_id} />
                    <ScheduledExports datasetId={datasetData.dataset_id} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
              <div id="section-overview">
                <SectionErrorBoundary key={`prof-${datasetData.dataset_id}`}>
                  <LazySection fallbackLabel="Loading dataset overview...">
                    <DataProfile data={datasetData} onCleaned={handleCleaned} />
                  </LazySection>
                </SectionErrorBoundary>
              </div>
            </>
          )}
        </main>
      )}
    </div>
  );
}

export default App;