import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useLiveRefresh } from "@/hooks/useLiveRefresh";

export const COMPANY_TZ = "Asia/Kolkata";

export function inr(n) {
  if (n === null || n === undefined) return "—";
  const v = Number(n) || 0;
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  return `${sign}₹${Math.round(a).toLocaleString("en-IN")}`;
}

export function fmtDate(value, withTime = false) {
  if (!value) return "—";
  const d = value.length === 10 ? new Date(`${value}T00:00:00+05:30`) : new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    timeZone: COMPANY_TZ, day: "numeric", month: "short", year: "numeric",
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
  });
}

/** YYYY-MM-DD for today in the company timezone. */
export function todayLocal(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toLocaleDateString("en-CA", { timeZone: COMPANY_TZ });
}

export function relativeDays(days) {
  if (days === null || days === undefined) return "Never";
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 60) return `${days} days ago`;
  if (days < 730) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
}

export const LIFECYCLE = {
  lead: { label: "Lead", cls: "bg-muted text-foreground/70" },
  new: { label: "New", cls: "bg-info/10 text-info" },
  active: { label: "Active", cls: "bg-success/10 text-success" },
  at_risk: { label: "At risk", cls: "bg-warning/10 text-warning" },
  churned: { label: "Churned", cls: "bg-destructive/10 text-destructive" },
};
export const LIFECYCLE_KEYS = Object.keys(LIFECYCLE);

export function initials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");
}

export const CHART_TOOLTIP = { background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 };
export const AXIS_TICK = { fill: "hsl(var(--muted-foreground))", fontSize: 11 };

/**
 * GET a resource with loading / error state. Refreshes quietly every minute and when the window regains
 * focus; background refreshes keep the last data on screen and never surface errors.
 */
export function useResource(url, params, { enabled = true, paused = false } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(Boolean(enabled && url));
  const [tick, setTick] = useState(0);
  const background = useRef(false);
  const reqId = useRef(0);
  const key = JSON.stringify(params || {});

  useEffect(() => {
    if (!enabled || !url) return undefined;
    const id = ++reqId.current;
    const controller = new AbortController();
    const quiet = background.current;
    background.current = false;
    if (!quiet) { setLoading(true); setError(null); }
    api.get(url, { params: JSON.parse(key), signal: controller.signal })
      .then(({ data: body }) => { if (id === reqId.current) { setData(body); setError(null); } })
      .catch((e) => {
        if (id !== reqId.current || controller.signal.aborted || quiet) return;
        setError(formatApiError(e));
      })
      .finally(() => { if (id === reqId.current) setLoading(false); });
    return () => controller.abort();
  }, [url, key, tick, enabled]);

  const reload = useCallback((opts) => {
    if (opts?.background) background.current = true;
    setTick((t) => t + 1);
  }, []);

  useLiveRefresh(() => { if (enabled && url && !paused) reload({ background: true }); }, 60000);

  return { data, error, loading, reload, setData };
}
