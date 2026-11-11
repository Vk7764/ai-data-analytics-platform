// frontend/src/components/DatasetShareLinks.jsx
import { useState, useEffect, useCallback } from "react";
import api from "../api";
import { errorDetail } from "../utils";

const DEFAULT_EXPIRY_DAYS = 30;
const MAX_EXPIRY_DAYS = 90;
const MAX_LABEL_LENGTH = 120;

function formatDate(value) {
  if (typeof value !== "string" || !value) return "—";

  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);

  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function detailText(detail) {
  if (typeof detail === "string" && detail.trim()) return detail;
  return null;
}

function errorMessage(err, fallback) {
  const status = err?.response?.status;

  if (!err?.response) {
    return "Network error. Check your connection and try again.";
  }

  if (status === 401) {
    return errorDetail(err, "Your session has expired. Please log in again.");
  }

  if (status === 403) {
    return errorDetail(
      err,
      "You do not have permission to manage share links for this dataset."
    );
  }

  if (status === 404) {
    return errorDetail(err, "This dataset or share link no longer exists.");
  }

  return errorDetail(err, fallback);
}

// Builds the full human-facing URL. Prefers the viewer path "/shared/...".
// The legacy API path "/api/shared/..." is accepted for compatibility and mapped to the viewer path.
function buildShareUrl(path) {
  if (typeof path !== "string") return null;

  const viewerPath = path.startsWith("/api/shared/")
    ? path.slice("/api".length)
    : path;

  if (!viewerPath.startsWith("/shared/")) return null;

  const origin =
    typeof window !== "undefined" && window.location
      ? window.location.origin
      : "";

  return `${origin}${viewerPath}`;
}

// Clipboard copy with a textarea fallback. Never throws; resolves to true only on success.
async function copyText(text) {
  try {
    if (
      typeof navigator !== "undefined" &&
      navigator.clipboard &&
      navigator.clipboard.writeText
    ) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) {
    // Fall through to the textarea method.
  }

  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-9999px";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return Boolean(ok);
  } catch (err) {
    return false;
  }
}

function DatasetShareLinks({ datasetId, displayName, onClose }) {
  const [label, setLabel] = useState("");
  const [expiryInput, setExpiryInput] = useState(String(DEFAULT_EXPIRY_DAYS));
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  // Plaintext link shown once. Held only in component memory; cleared by "Dismiss" or when the panel closes.
  const [created, setCreated] = useState(null);
  const [copyMessage, setCopyMessage] = useState(null);

  const [shares, setShares] = useState([]);
  const [sharesLoading, setSharesLoading] = useState(false);
  const [sharesError, setSharesError] = useState(null);
  const [revokingId, setRevokingId] = useState(null);

  const requestClose = useCallback(() => {
    if (
      created &&
      !window.confirm(
        "Close this panel? The one-time share link will be lost and cannot be shown again."
      )
    ) {
      return;
    }

    if (typeof onClose === "function") {
      onClose();
    }
  }, [created, onClose]);

  const loadShares = useCallback(async () => {
    if (!datasetId) {
      setShares([]);
      setSharesError("Dataset id is missing.");
      return;
    }

    setSharesLoading(true);
    setSharesError(null);

    try {
      const res = await api.get(`/dataset/${datasetId}/shares`);
      const list = Array.isArray(res?.data?.shares) ? res.data.shares : [];

      setShares(
        list.filter(
          (s) => s && typeof s === "object" && typeof s.share_id === "string" && s.share_id
        )
      );
    } catch (err) {
      setShares([]);
      setSharesError(errorMessage(err, "Could not load share links."));
    } finally {
      setSharesLoading(false);
    }
  }, [datasetId]);

  useEffect(() => {
    loadShares();
  }, [loadShares]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        requestClose();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [requestClose]);

  const handleCreate = async () => {
    if (!datasetId) {
      setCreateError("Dataset id is missing.");
      return;
    }

    const days = Number(expiryInput);

    if (!Number.isInteger(days) || days < 1 || days > MAX_EXPIRY_DAYS) {
      setCreateError(
        `Expiry must be a whole number of days between 1 and ${MAX_EXPIRY_DAYS}.`
      );
      return;
    }

    setCreating(true);
    setCreateError(null);
    setCopyMessage(null);

    try {
      const res = await api.post(`/dataset/${datasetId}/shares`, {
        label: label.trim().slice(0, MAX_LABEL_LENGTH),
        expires_in_days: days,
      });

      const token =
        typeof res?.data?.token === "string" ? res.data.token : null;

      const path =
        res?.data?.share_path ||
        res?.data?.share_api_path ||
        (token ? `/api/shared/${encodeURIComponent(token)}` : null);

      const url = buildShareUrl(path);

      if (!url) {
        setCreateError(
          "The server returned an unexpected share path. The link may have been created but cannot be displayed here. Revoke it and create a new link if needed."
        );
      } else {
        setCreated({
          url,
          label:
            typeof res?.data?.label === "string"
              ? res.data.label
              : "Read-only link",
          expiresAt:
            typeof res?.data?.expires_at === "string"
              ? res.data.expires_at
              : null,
        });
        setLabel("");
      }

      await loadShares();
    } catch (err) {
      setCreateError(errorMessage(err, "Could not create a share link."));
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = async () => {
    if (!created) return;

    const ok = await copyText(created.url);
    setCopyMessage(
      ok
        ? "Link copied."
        : "Copy failed. Select the link and copy it manually."
    );
  };

  const handleDismissCreated = () => {
    setCreated(null);
    setCopyMessage(null);
  };

  const handleRevoke = async (shareId) => {
    if (
      !window.confirm(
        "Revoke this share link? Anyone using it will lose access immediately."
      )
    ) {
      return;
    }

    setRevokingId(shareId);
    setSharesError(null);

    try {
      await api.delete(
        `/dataset/${datasetId}/shares/${encodeURIComponent(String(shareId))}`
      );
      await loadShares();
    } catch (err) {
      setSharesError(errorMessage(err, "Could not revoke this link."));
    } finally {
      setRevokingId(null);
    }
  };

  const busy = creating || sharesLoading || revokingId !== null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={requestClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(27, 36, 48, 0.35)",
        zIndex: 120,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "16px",
      }}
    >
      <div
        className="dashboard-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: "520px",
          width: "100%",
          maxHeight: "90vh",
          overflowY: "auto",
          margin: 0,
        }}
      >
        <div
          className="history-panel-row"
          style={{ justifyContent: "space-between", alignItems: "center" }}
        >
          <h2 style={{ fontSize: "20px", margin: 0 }}>Share read-only link</h2>
          <button
            type="button"
            className="logout-button"
            style={{ marginLeft: 0 }}
            onClick={requestClose}
          >
            Close
          </button>
        </div>

        <p className="subtitle" style={{ fontSize: "12px" }}>
          Dataset: {String(displayName || "Untitled dataset")}
        </p>

        <p
          className="subtitle"
          style={{
            fontSize: "12px",
            marginBottom: "12px",
            color: "#b45309",
          }}
        >
          Anyone with this link can view a limited preview of this dataset,
          including up to 10 rows and profile summary. Do not share datasets
          containing sensitive personal data unless you accept that risk.
        </p>

        <h3>Create a link</h3>

        <div className="forecast-controls" style={{ marginBottom: "10px" }}>
          <input
            type="text"
            placeholder="Label (optional)"
            maxLength={MAX_LABEL_LENGTH}
            value={label}
            disabled={creating}
            onChange={(e) => setLabel(e.target.value)}
          />

          <input
            type="number"
            min={1}
            max={MAX_EXPIRY_DAYS}
            value={expiryInput}
            disabled={creating}
            onChange={(e) => setExpiryInput(e.target.value)}
            className="periods-input"
            aria-label="Expiry in days"
          />

          <span className="subtitle" style={{ fontSize: "12px" }}>
            days (max {MAX_EXPIRY_DAYS})
          </span>

          <button type="button" disabled={busy || !datasetId} onClick={handleCreate}>
            {creating ? "Creating..." : "Create link"}
          </button>
        </div>

        {createError && <p className="error-text">{createError}</p>}

        {created && (
          <div className="history-panel" style={{ marginBottom: "12px" }}>
            <strong>Copy this link now. It cannot be shown again.</strong>

            <p className="subtitle" style={{ fontSize: "12px", margin: "6px 0" }}>
              {created.label}
              {created.expiresAt ? ` · expires ${formatDate(created.expiresAt)}` : ""}
            </p>

            <input
              type="text"
              readOnly
              value={created.url}
              onFocus={(e) => e.target.select()}
              style={{ width: "100%", fontSize: "12px" }}
              aria-label="Share link"
            />

            <div className="button-group" style={{ marginTop: "8px" }}>
              <button type="button" onClick={handleCopy}>
                Copy link
              </button>
              <button
                type="button"
                className="logout-button"
                onClick={handleDismissCreated}
              >
                Dismiss
              </button>
            </div>

            {copyMessage && (
              <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
                {copyMessage}
              </p>
            )}
          </div>
        )}

        <h3>Active links</h3>

        {sharesLoading && (
          <p className="subtitle" style={{ fontSize: "12px" }}>
            Loading links...
          </p>
        )}

        {sharesError && <p className="error-text">{sharesError}</p>}

        {!sharesLoading && !sharesError && shares.length === 0 && (
          <p className="subtitle" style={{ fontSize: "12px" }}>
            No active share links.
          </p>
        )}

        {shares.length > 0 && (
          <ul className="audit-log" style={{ maxHeight: "none" }}>
            {shares.map((s) => (
              <li
                key={s.share_id}
                style={{
                  flexDirection: "column",
                  alignItems: "flex-start",
                  gap: "4px",
                }}
              >
                <span className="audit-detail">
                  {String(s.label || "Read-only link")}
                </span>

                <span className="audit-time">
                  Created {formatDate(s.created_at)} · Expires{" "}
                  {formatDate(s.expires_at)}
                </span>

                <button
                  type="button"
                  className="delete-button"
                  style={{
                    fontSize: "12px",
                    padding: "2px 10px",
                    marginLeft: 0,
                  }}
                  disabled={busy}
                  onClick={() => handleRevoke(s.share_id)}
                >
                  {revokingId === s.share_id ? "Revoking..." : "Revoke"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default DatasetShareLinks;