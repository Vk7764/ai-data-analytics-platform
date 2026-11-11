// frontend/src/api.js
import axios from "axios";

// In development this falls back to the local backend. In production,
// VITE_API_BASE_URL is set to "" (empty) so requests go to a RELATIVE
// path ("/api/...") — nginx then reverse-proxies that to the backend
// container, so the frontend never needs to know the backend's real
// address or port.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

// Only AI-powered endpoints dispatch the usage-updated event.
const AI_ENDPOINT_PATTERN = /(^|\/)(query|analyze|insights|anomalies|root-cause|chat|report|cleaning-advice)$/;

const api = axios.create({
  baseURL: `${BASE_URL}/api`,
  headers: {
    "Cache-Control": "no-cache",
    Pragma: "no-cache",
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // AI endpoints get a client timeout just under the nginx proxy timeout (180s); uploads stay untimed.
  if (AI_ENDPOINT_PATTERN.test(config.url || "") && config.timeout === undefined) {
    config.timeout = 175000;
  }
  return config;
});

api.interceptors.response.use(
  (response) => {
    if (AI_ENDPOINT_PATTERN.test(response.config?.url || "")) {
      window.dispatchEvent(new Event("ai-usage-updated"));
    }
    return response;
  },
  (error) => {
    // Attach the backend request id as a support identifier only.
    // The response body, detail, message, and original error behavior are never modified.
    if (error && typeof error === "object") {
      try {
        const headers = error.response?.headers;
        let rawId;

        if (headers && typeof headers.get === "function") {
          rawId = headers.get("x-request-id") || headers.get("X-Request-ID");
        } else if (headers) {
          rawId = headers["x-request-id"] || headers["X-Request-ID"];
        }

        if (
          typeof rawId === "string" &&
          error.requestId === undefined &&
          /^[A-Za-z0-9._-]{8,64}$/.test(rawId)
        ) {
          error.requestId = rawId;
        }
      } catch {
        // Header unavailable, malformed, or blocked by CORS: keep the original error unchanged.
      }
    }

    if (AI_ENDPOINT_PATTERN.test(error?.config?.url || "")) {
      window.dispatchEvent(new Event("ai-usage-updated"));
    }
    if (error.response?.status === 401) {
      localStorage.removeItem("access_token");
      window.location.reload();
    }
    return Promise.reject(error);
  }
);

export default api;
export { BASE_URL };