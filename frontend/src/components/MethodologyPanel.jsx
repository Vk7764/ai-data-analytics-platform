// frontend/src/components/MethodologyPanel.jsx
import React from "react";

const MAX_DEPTH = 4;
const MAX_ENTRIES_PER_LEVEL = 50;
const MAX_JSON_LENGTH = 1000;

function truncateText(text) {
  const s = String(text ?? "");
  return s.length > MAX_JSON_LENGTH ? `${s.slice(0, MAX_JSON_LENGTH)}…` : s;
}

function isEmptyValue(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return value.trim() === "";
  if (Array.isArray(value)) return value.every(isEmptyValue);
  if (typeof value === "object") return Object.values(value).every(isEmptyValue);
  return false;
}

function formatLabel(key) {
  const text = String(key).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function renderScalar(value) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function renderValue(value, depth) {
  if (Array.isArray(value)) {
    const items = value.filter((item) => !isEmptyValue(item));
    const cappedItems = items.slice(0, MAX_ENTRIES_PER_LEVEL);
    const allScalar = cappedItems.every((item) => typeof item !== "object");

    if (allScalar) {
      return <span>{truncateText(cappedItems.map(renderScalar).join(", "))}</span>;
    }

    return (
      <ul style={{ margin: "2px 0 2px 16px", padding: 0 }}>
        {cappedItems.map((item, i) => (
          <li key={i}>{renderValue(item, depth + 1)}</li>
        ))}
        {items.length > cappedItems.length && (
          <li key="__methodology_array_truncated">…</li>
        )}
      </ul>
    );
  }
  if (value !== null && typeof value === "object") {
    if (depth >= MAX_DEPTH) {
      try {
        return <span>{truncateText(JSON.stringify(value))}</span>;
      } catch {
        return <span>[unreadable]</span>;
      }
    }

    const entries = Object.entries(value).filter(([, v]) => !isEmptyValue(v));
    const cappedEntries = entries.slice(0, MAX_ENTRIES_PER_LEVEL);

    return (
      <ul style={{ margin: "2px 0 2px 16px", padding: 0, listStyle: "none" }}>
        {cappedEntries.map(([k, v]) => (
          <li key={k}>
            <strong>{formatLabel(k)}:</strong> {renderValue(v, depth + 1)}
          </li>
        ))}
        {entries.length > cappedEntries.length && (
          <li key="__methodology_object_truncated">…</li>
        )}
      </ul>
    );
  }
  return <span>{renderScalar(value)}</span>;
}

// Compact collapsible panel that safely renders a backend "methodology" object.
// Renders nothing when the object is missing or has no usable values.
function MethodologyPanel({ methodology, title = "How this was calculated" }) {
  if (!methodology || typeof methodology !== "object" || isEmptyValue(methodology)) return null;

  return (
    <details className="code-transparency" style={{ marginTop: "12px" }}>
      <summary>{title}</summary>
      <div className="subtitle" style={{ fontSize: "12px", margin: "8px 0 0", lineHeight: 1.6 }}>
        {renderValue(methodology, 0)}
      </div>
    </details>
  );
}

export default MethodologyPanel;