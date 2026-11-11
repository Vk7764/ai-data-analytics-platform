// frontend/src/App.jsx
import { useState, useEffect, Component } from "react";

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
import DataCleaning from "./components/DataCleaning";
import AnalysisDashboard from "./components/AnalysisDashboard";
import TimeSeriesExplorer from "./components/TimeSeriesExplorer";
import CorrelationHeatmap from "./components/CorrelationHeatmap";
import AnomalyView from "./components/AnomalyView";
import RootCauseView from "./components/RootCauseView";
import ForecastView from "./components/ForecastView";
import ChatInterface from "./components/ChatInterface";
import ReportDownload from "./components/ReportDownload";
import ScheduledExports from "./components/ScheduledExports";
import DataProfile from "./components/DataProfile";
import "./App.css";

function App() {
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
  const [, forceRender] = useState(0);

  useEffect(() => {
    const handlePopState = () => forceRender((n) => n + 1);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
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
    return <LoginForm initialMode={authMode} onLoginSuccess={() => setIsLoggedIn(true)} />;
  }

  // ---------- The app ----------

  return (
    <div className="app-container">
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
          <UsageBadge />
          <button
            className="logout-button"
            onClick={() => setPage(page === "account" ? "dashboard" : "account")}
          >
            {page === "account" ? "Dashboard" : "Account"}
          </button>
          <button className="logout-button" onClick={handleLogout}>Log Out</button>
        </div>
      </header>

      {page === "account" ? (
        <AccountPage onBack={() => setPage("dashboard")} />
      ) : (
        <main>
          <VerifyEmailBanner />
          <UploadForm onUploadSuccess={handleUploadSuccess} />
          <BrandingSettings />
          <CompareDatasets dataVersion={dataVersion} />

          {datasetData && (
            <>
              <nav className="section-nav">
                <a href="#section-cleaning">Cleaning</a>
                <a href="#section-analysis">Analysis</a>
                <a href="#section-timeseries">Time Series</a>
                <a href="#section-correlation">Correlation</a>
                <a href="#section-anomalies">Anomalies</a>
                <a href="#section-rootcause">Root Cause</a>
                <a href="#section-forecast">Forecast</a>
                <a href="#section-chat">Chat</a>
                <a href="#section-reports">Reports</a>
                <a href="#section-overview">Overview &amp; Rows</a>
              </nav>

              <div id="section-cleaning">
                <SectionErrorBoundary key={`clean-${datasetData.dataset_id}`}>
                  <DataCleaning datasetId={datasetData.dataset_id} dataVersion={dataVersion} onCleaned={handleCleaned} />
                </SectionErrorBoundary>
              </div>
              <div id="section-analysis">
                <SectionErrorBoundary key={`analysis-${datasetData.dataset_id}`}>
                  <AnalysisDashboard datasetId={datasetData.dataset_id} dataVersion={dataVersion} columns={datasetData.profile.columns} />
                </SectionErrorBoundary>
              </div>
              <div id="section-timeseries">
                <SectionErrorBoundary key={`ts-${datasetData.dataset_id}`}>
                  <TimeSeriesExplorer datasetId={datasetData.dataset_id} columns={datasetData.profile.columns} dataVersion={dataVersion} />
                </SectionErrorBoundary>
              </div>
              <div id="section-correlation">
                <SectionErrorBoundary key={`corr-${datasetData.dataset_id}`}>
                  <CorrelationHeatmap datasetId={datasetData.dataset_id} dataVersion={dataVersion} />
                </SectionErrorBoundary>
              </div>
              <div id="section-anomalies">
                <SectionErrorBoundary key={`anom-${datasetData.dataset_id}`}>
                  <AnomalyView datasetId={datasetData.dataset_id} dataVersion={dataVersion} />
                </SectionErrorBoundary>
              </div>
              <div id="section-rootcause">
                <SectionErrorBoundary key={`rc-${datasetData.dataset_id}`}>
                  <RootCauseView datasetId={datasetData.dataset_id} columns={datasetData.profile.columns} dataVersion={dataVersion} />
                </SectionErrorBoundary>
              </div>
              <div id="section-forecast">
                <SectionErrorBoundary key={`fc-${datasetData.dataset_id}`}>
                  <ForecastView datasetId={datasetData.dataset_id} columns={datasetData.profile.columns} dataVersion={dataVersion} />
                </SectionErrorBoundary>
              </div>
              <div id="section-chat">
                <SectionErrorBoundary key={`chat-${datasetData.dataset_id}`}>
                  <ChatInterface
                    datasetId={datasetData.dataset_id}
                    columns={datasetData.profile.columns}
                    onDatasetCreated={() => setDataVersion((v) => v + 1)}
                  />
                </SectionErrorBoundary>
              </div>
              <div id="section-reports">
                <SectionErrorBoundary key={`rep-${datasetData.dataset_id}`}>
                  <ReportDownload datasetId={datasetData.dataset_id} />
                  <ScheduledExports datasetId={datasetData.dataset_id} />
                </SectionErrorBoundary>
              </div>
              <div id="section-overview">
                <SectionErrorBoundary key={`prof-${datasetData.dataset_id}`}>
                  <DataProfile data={datasetData} onCleaned={handleCleaned} />
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