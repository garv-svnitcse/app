import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, tokens, formatApiError } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);       // null while checking, false = not logged in
  const [loading, setLoading] = useState(true);

  const bootstrap = useCallback(async () => {
    if (!tokens.access) { setUser(false); setLoading(false); return; }
    try {
      // An expired access token is refreshed by the api interceptor before this fails.
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch (e) {
      // Only drop the session when the server rejected it; a network blip keeps the tokens for the next load.
      if ([401, 403].includes(e?.response?.status)) tokens.clear();
      setUser(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { bootstrap(); }, [bootstrap]);

  async function login({ email, password, remember }) {
    try {
      const { data } = await api.post("/auth/login", { email, password, remember });
      tokens.set(data.access_token, data.refresh_token);
      localStorage.setItem("wavygo_login_at", String(Date.now()));
      setUser(data.user);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: formatApiError(e) };
    }
  }

  async function logout() {
    // Send the refresh token so the server revokes this session
    try { await api.post("/auth/logout", { refresh_token: tokens.refresh }); } catch { /* ignore */ }
    finally {
      tokens.clear();
      localStorage.removeItem("wavygo_login_at");
      setUser(false);
    }
  }

  async function refreshMe() {
    try { const { data } = await api.get("/auth/me"); setUser(data); } catch { /* noop */ }
  }

  const value = { user, loading, login, logout, refreshMe, setUser };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}