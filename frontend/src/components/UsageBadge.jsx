// frontend/src/components/UsageBadge.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { useLanguage } from "../i18n";

function UsageBadge() {
  const { t } = useLanguage();
  const [usage, setUsage] = useState(null);

  useEffect(() => {
    const load = () => api.get("/usage").then((res) => setUsage(res.data)).catch(() => {});
    load();
    const interval = setInterval(load, 20000);
    window.addEventListener("ai-usage-updated", load);
    return () => {
      clearInterval(interval);
      window.removeEventListener("ai-usage-updated", load);
    };
  }, []);

  if (!usage) return null;

  const used = Number.isFinite(Number(usage.used))
    ? Math.max(0, Number(usage.used))
    : 0;

  const limit = Number.isFinite(Number(usage.limit))
    ? Math.max(0, Number(usage.limit))
    : 0;

  const nearLimit = limit > 0 && used >= limit * 0.8;
  const limitText = limit > 0 ? String(limit) : "—";

  return (
    <span
      className={`usage-badge ${nearLimit ? "usage-badge-warn" : ""}`}
      title="AI requests used today. Reset timing depends on deployment configuration."
    >
      {t("aiToday")} {used}/{limitText}
    </span>
  );
}

export default UsageBadge;