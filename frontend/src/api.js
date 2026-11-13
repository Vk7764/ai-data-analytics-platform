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

// Auth-flow requests where a 401 means "wrong credentials/link", not "session expired".
const AUTH_NO_LOGOUT_PATTERN = /^\/?(auth\/(login|signup|forgot-password|reset-password|verify-email)|account\/delete\/confirm)$/;

// Cold-start detector: a normal (non-AI, non-upload) request still pending after 4s shows the "waking up" banner.
const COLD_START_DELAY_MS = 4000;
const NO_WAKE_BANNER_PATTERN = /(upload|upload-url|report|export|load|sql|save-as-dataset|clean-all)$/;
let wakingCount = 0;

function dispatchWaking(waking) {
  try {
    window.dispatchEvent(new CustomEvent("server-waking", { detail: { waking } }));
  } catch {
    // CustomEvent unavailable: the banner is cosmetic only.
  }
}

function startWakeTimer(config) {
  const url = config?.url || "";
  if (AI_ENDPOINT_PATTERN.test(url) || NO_WAKE_BANNER_PATTERN.test(url)) return;
  config.__wakeTimer = setTimeout(() => {
    config.__wakeTimer = null;
    config.__wakeActive = true;
    wakingCount += 1;
    if (wakingCount === 1) dispatchWaking(true);
  }, COLD_START_DELAY_MS);
}

function settleWake(config) {
  if (!config) return;
  if (config.__wakeTimer) {
    clearTimeout(config.__wakeTimer);
    config.__wakeTimer = null;
  }
  if (config.__wakeActive) {
    config.__wakeActive = false;
    wakingCount = Math.max(0, wakingCount - 1);
    if (wakingCount === 0) dispatchWaking(false);
  }
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  startWakeTimer(config);
  // AI endpoints get a client timeout just under the nginx proxy timeout (180s); uploads stay untimed.
  if (AI_ENDPOINT_PATTERN.test(config.url || "") && config.timeout === undefined) {
    config.timeout = 175000;
  }
  // Other endpoints get a generous default timeout, so a hung request never
  // leaves a button spinning forever. File uploads use multipart via this same
  // instance; 120s is well above a normal 4-5MB upload on any real connection.
  if (config.timeout === undefined) {
    config.timeout = 120000;
  }
  return config;
});

api.interceptors.response.use(
  (response) => {
    settleWake(response.config);
    if (AI_ENDPOINT_PATTERN.test(response.config?.url || "")) {
      window.dispatchEvent(new Event("ai-usage-updated"));
    }
    return response;
  },
  (error) => {
    settleWake(error?.config);
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
    if (error.response?.status === 401 && !AUTH_NO_LOGOUT_PATTERN.test(error?.config?.url || "")) {
      // Session expired or invalid. Clear the token and notify the app so it
      // can show the login screen with a clear message, instead of a hard
      // page reload that throws away everything the user had open.
      localStorage.removeItem("access_token");
      window.dispatchEvent(new Event("auth-expired"));
    }
    return Promise.reject(error);
  }
);

export default api;
export { BASE_URL };