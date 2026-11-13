// frontend/src/components/SandboxNotice.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { useLanguage } from "../i18n";

function SandboxNotice() {
  const { t } = useLanguage();
  // Assume available until the server says otherwise, so the banner never
  // flashes for users on a full Docker deployment.
  const [sandboxAvailable, setSandboxAvailable] = useState(true);

  useEffect(() => {
    let mounted = true;
    api
      .get("/system/status")
      .then((res) => {
        if (mounted) setSandboxAvailable(res?.data?.sandbox_available !== false);
      })
      .catch(() => {
        // If the status check fails, stay quiet rather than blocking the app.
      });
    return () => {
      mounted = false;
    };
  }, []);

  if (sandboxAvailable) return null;

  return (
    <div className="dashboard-card" style={{ borderLeft: "4px solid #d97706", marginBottom: 16 }}>
      <p className="subtitle">{t("demoMode")}</p>
    </div>
  );
}

export default SandboxNotice;