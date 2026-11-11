// frontend/src/utils.js

/**
 * Strips markdown bold/italic markers (**text** or *text*) from LLM-generated text,
 * since we're rendering plain text, not markdown.
 */
export function cleanMarkdown(text) {
  if (!text) return "";
  return text.replace(/\*\*(.*?)\*\*/g, "$1").replace(/\*(.*?)\*/g, "$1");
}

/**
 * Builds a user-safe error message from an Axios error.
 * Includes backend detail and X-Request-ID when available, without exposing secrets.
 */
export function errorDetail(err, fallback = "Something went wrong. Please try again.") {
  const detail = err?.response?.data?.detail;
  const base = typeof detail === "string" && detail.trim()
    ? detail.trim()
    : fallback;

  let requestId = err?.requestId;

  if (!requestId) {
    const headers = err?.response?.headers;

    if (headers && typeof headers.get === "function") {
      requestId = headers.get("x-request-id") || headers.get("X-Request-ID");
    } else if (headers) {
      requestId = headers["x-request-id"] || headers["X-Request-ID"];
    }
  }

  if (
    requestId &&
    typeof requestId === "string" &&
    /^[A-Za-z0-9._-]{8,64}$/.test(requestId) &&
    !base.includes(requestId)
  ) {
    return `${base} (Request ID: ${requestId})`;
  }

  return base;
}