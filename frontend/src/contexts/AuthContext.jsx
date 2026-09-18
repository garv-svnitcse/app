import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, tokens, formatApiError } from "@/lib/api";

const AuthContext = createContext(null);
const LAST_ACTIVITY_KEY = "wavygo_last_activity";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);       // null while checking, false = not logged in
  const [loading, setLoading] = useState(true);

  const bootstrap = useCallback(async () => {
    if (!tokens.access) { setUser(false); setLoading(false); return; }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      tokens.clear();
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
      localStorage.setItem(LAST_ACTIVITY_KEY, Date.now().toString());
      setUser(data.user);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: formatApiError(e) };
    }
  }

  async function logout() {
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    tokens.clear();
    localStorage.removeItem(LAST_ACTIVITY_KEY);
    setUser(false);
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
