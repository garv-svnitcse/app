import { useState, useEffect } from "react";

const STORAGE_KEY = "wavygo_login_at";

function readLoginAt() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw == null) return null;
    const ts = Number(raw);
    if (!Number.isFinite(ts) || ts <= 0) return null;
    return ts;
  } catch {
    return null;
  }
}

function computeElapsed(loginAt) {
  if (loginAt == null) return null;
  const diff = Math.floor((Date.now() - loginAt) / 1000);
  if (diff < 0) return null;
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = diff % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return { elapsed: diff, formatted: `${pad(h)}:${pad(m)}:${pad(s)}` };
}

// Returns { elapsed, formatted } or null when the stored timestamp is
// missing, corrupt, negative, or in the future.
export function useLoggedTime() {
  const [result, setResult] = useState(() => computeElapsed(readLoginAt()));

  useEffect(() => {
    const tick = () => setResult(computeElapsed(readLoginAt()));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return result;
}

export default useLoggedTime;
