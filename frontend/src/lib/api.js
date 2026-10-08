import axios from "axios";

function getApiBase() {
  const envUrl = (process.env.REACT_APP_BACKEND_URL || "").trim().replace(/\/+$/, "");
  if (envUrl && !envUrl.includes("emergentagent.com") && !envUrl.includes("preview")) {
    return envUrl.endsWith("/api") ? envUrl : `${envUrl}/api`;
  }
  return "/api";
}

export const API_BASE = getApiBase();
export const api = axios.create({ baseURL: API_BASE });

const ACCESS_KEY = "wavygo_access";
const REFRESH_KEY = "wavygo_refresh";

export const tokens = {
  get access() { return localStorage.getItem(ACCESS_KEY); },
  get refresh() { return localStorage.getItem(REFRESH_KEY); },
  set(access, refresh) {
    if (access) localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

api.interceptors.request.use((cfg) => {
  const t = tokens.access;
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

// Endpoints that authenticate by credentials or refresh token, so a 401 from them must not trigger a refresh.
// Everything else (including /auth/me and /auth/logout, so an expired access token still revokes the
// session server-side) retries once with a fresh access token.
const NO_REFRESH = /\/auth\/(login|refresh|forgot-password|reset-password)/;

const PUBLIC_PATHS = /^\/(login|accept-invite|reset-password)\/?$/;

let refreshing = null;
api.interceptors.response.use(
  (r) => r,
  async (err) => {
    const original = err.config;
    if (err.response?.status === 401 && original && !original._retry && tokens.refresh && !NO_REFRESH.test(original.url || "")) {
      original._retry = true;
      try {
        refreshing = refreshing || axios.post(`${API_BASE}/auth/refresh`, { refresh_token: tokens.refresh });
        const { data } = await refreshing;
        refreshing = null;
        tokens.set(data.access_token, data.refresh_token);
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return api(original);
      } catch (e) {
        refreshing = null;
        tokens.clear();
        // Public pages (invite / reset links) must stay put: a stale session there would otherwise bounce the
        // user to /login and lose the one-time token in the URL.
        if (typeof window !== "undefined" && !PUBLIC_PATHS.test(window.location.pathname)) window.location.href = "/login";
      }
    }
    // A user deactivated mid-session gets 403 on every call; end the session instead of leaving a broken app.
    if (err.response?.status === 403 && tokens.access && /^Account is deactivated/.test(err.response?.data?.detail || "")) {
      tokens.clear();
      if (typeof window !== "undefined" && !PUBLIC_PATHS.test(window.location.pathname)) window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export function formatApiError(e) {
  const d = e?.response?.data?.detail;
  if (!d) return e?.message || "Something went wrong";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(" ");
  return String(d);
}
