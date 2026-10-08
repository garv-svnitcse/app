import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Download, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

// ------------------------- formatting -------------------------

export function formatInr(value, { compact = true } = {}) {
  const v = Number(value) || 0;
  if (compact && Math.abs(v) >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (compact && Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

export function formatNumber(value) {
  return (Number(value) || 0).toLocaleString("en-IN");
}

export function formatPct(value) {
  return value === null || value === undefined ? "—" : `${value}%`;
}

export function formatKpi(k) {
  if (k.format === "inr") return formatInr(k.value);
  if (k.format === "pct") return formatPct(k.value);
  if (k.format === "raw") return k.value;
  return formatNumber(k.value);
}

export function titleCase(s) {
  return String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ------------------------- chart styling (mirrors Dashboard.jsx) -------------------------

export const AXIS_TICK = { fill: "hsl(var(--muted-foreground))", fontSize: 11 };
export const GRID_STROKE = "hsl(var(--border))";
export const CHART_COLORS = ["hsl(var(--chart-1))", "hsl(var(--chart-2))", "hsl(var(--chart-3))", "hsl(var(--chart-4))", "hsl(var(--chart-5))"];

export function ChartTooltip({ active, payload, label, formatters = {}, names = {} }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 shadow-lg text-xs">
      <div className="font-medium text-foreground mb-1">{label}</div>
      {payload.map((p) => {
        const fmt = formatters[p.dataKey] || formatNumber;
        return (
          <div key={p.dataKey} className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
            <span className="text-muted-foreground">{names[p.dataKey] || titleCase(p.dataKey)}</span>
            <span className="font-medium text-foreground ml-auto pl-3">{fmt(p.value)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function Legend({ items }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: i.color }} />{i.label}
        </span>
      ))}
    </div>
  );
}

export function DeltaBadge({ kpi }) {
  const { delta, delta_unit: unit, inverse, value } = kpi;
  if (delta === null || delta === undefined) {
    return (
      <span title="No comparable previous period" className="inline-flex items-center text-[11px] font-semibold px-1.5 py-0.5 rounded text-muted-foreground bg-muted">
        {value ? "New" : "—"}
      </span>
    );
  }
  const up = delta >= 0;
  const good = inverse ? delta <= 0 : delta >= 0;
  return (
    <span title="vs previous period" className={cn(
      "inline-flex items-center gap-1 text-[11px] font-semibold px-1.5 py-0.5 rounded",
      delta === 0 ? "text-muted-foreground bg-muted" : good ? "text-success bg-success/10" : "text-destructive bg-destructive/10",
    )}>
      {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {delta > 0 ? "+" : ""}{delta}{unit === "pp" ? " pp" : "%"}
    </span>
  );
}

// ------------------------- data loading -------------------------

/** GET an analytics endpoint; refetches silently when the window regains focus. */
export function useAnalyticsData(path, params, enabled = true) {
  const key = JSON.stringify(params || {});
  const [state, setState] = useState({ data: null, loading: enabled, error: null });
  const seq = useRef(0);

  const load = useCallback(({ background = false } = {}) => {
    if (!enabled || !path) return;
    const id = ++seq.current;
    if (!background) setState((s) => ({ ...s, loading: true, error: null }));
    api.get(path, { params: JSON.parse(key) })
      .then(({ data }) => { if (id === seq.current) setState({ data, loading: false, error: null }); })
      .catch((e) => {
        if (id !== seq.current) return;
        setState((s) => background ? s : { ...s, loading: false, error: formatApiError(e) });
      });
  }, [path, key, enabled]);

  useEffect(() => {
    if (!enabled) { setState({ data: null, loading: false, error: null }); return; }
    setState((s) => ({ ...s, data: null }));
    load();
  }, [load, enabled]);

  useEffect(() => {
    let last = Date.now();
    const onFocus = () => {
      if (document.visibilityState !== "visible" || Date.now() - last < 5000) return;
      last = Date.now();
      load({ background: true });
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [load]);

  return { ...state, reload: load };
}

const OPERATIONS_DATASETS = new Set(["tasks", "overdue", "pipeline", "attendance", "leave", "calendar"]);

/** Same name the server puts in Content-Disposition, which the browser hides on a cross-origin API. */
function exportFileName(dataset, params = {}) {
  const parts = ["wavygo", dataset];
  if (params.city && !OPERATIONS_DATASETS.has(dataset)) {
    parts.push(Array.from(params.city, (ch) => (/[\p{L}\p{N}]/u.test(ch) ? ch : "-")).join("").toLowerCase());
  }
  if (params.from && params.to) parts.push(params.from, params.to);
  return `${parts.join("_")}.csv`;
}

export async function downloadCsv(dataset, params) {
  try {
    const res = await api.get(`/analytics/export/${dataset}`, { params, responseType: "blob" });
    const cd = res.headers?.["content-disposition"] || "";
    const name = /filename="?([^";]+)"?/.exec(cd)?.[1] || exportFileName(dataset, params);
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success(`Exported ${name}`);
  } catch (e) {
    let msg = formatApiError(e);
    const blob = e?.response?.data;
    if (blob instanceof Blob) {
      try { msg = JSON.parse(await blob.text())?.detail || msg; } catch { /* keep generic message */ }
    }
    toast.error(`Export failed: ${msg}`);
  }
}

export function ExportButton({ dataset, params, canExport, label = "CSV" }) {
  const [busy, setBusy] = useState(false);
  if (!canExport) return null;
  return (
    <Button
      variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground shrink-0"
      disabled={busy} aria-label={`Export ${dataset} as CSV`}
      onClick={async () => { setBusy(true); await downloadCsv(dataset, params); setBusy(false); }}
    >
      <Download className="h-3.5 w-3.5 mr-1" />{label}
    </Button>
  );
}

// ------------------------- panels -------------------------

export function ErrorPanel({ error, onRetry, className }) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center p-6", className)}>
      <AlertTriangle className="h-6 w-6 text-destructive" />
      <div className="mt-2 text-sm font-medium text-foreground">Couldn&apos;t load this data</div>
      <div className="mt-1 text-xs text-muted-foreground max-w-xs">{String(error)}</div>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-3 h-8 text-xs" onClick={() => onRetry()}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyChart({ icon: Icon, title, description, className }) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center border border-dashed border-border rounded-lg bg-card/30 p-6", className)}>
      {Icon && (
        <div className="h-10 w-10 rounded-md bg-primary/10 text-primary flex items-center justify-center">
          <Icon className="h-4.5 w-4.5" />
        </div>
      )}
      <div className="font-display text-[14px] font-semibold text-foreground mt-2">{title}</div>
      {description && <div className="text-xs text-muted-foreground mt-1 max-w-sm">{description}</div>}
    </div>
  );
}

/** Card shell with loading skeleton, error + retry and empty handling for one dataset. */
export function ChartCard({
  title, description, actions, loading, error, onRetry, empty, emptyIcon, emptyTitle, emptyDescription,
  height = 260, className, children, testId,
}) {
  let body;
  if (loading) body = <Skeleton className="w-full rounded-lg" style={{ height }} />;
  else if (error) body = <ErrorPanel error={error} onRetry={onRetry} className="rounded-lg border border-dashed border-border" />;
  else if (empty) body = <EmptyChart icon={emptyIcon} title={emptyTitle || "No data in this range"} description={emptyDescription} className="min-h-[180px]" />;
  else body = children;
  return (
    <Card data-testid={testId} className={cn("border-border min-w-0", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="font-display text-[17px]">{title}</CardTitle>
            {description && <CardDescription className="mt-1">{description}</CardDescription>}
          </div>
          {actions && <div className="flex items-center gap-1 shrink-0">{actions}</div>}
        </div>
      </CardHeader>
      <CardContent className="pt-2">{body}</CardContent>
    </Card>
  );
}

export function KpiGrid({ kpis, loading, error, onRetry, icons = {}, count = 8 }) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        {Array.from({ length: count }).map((_, i) => <Skeleton key={i} className="h-[112px] rounded-xl" />)}
      </div>
    );
  }
  if (error) return <Card className="border-border"><ErrorPanel error={error} onRetry={onRetry} /></Card>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
      {(kpis || []).map((k) => {
        const Icon = icons[k.key];
        return (
          <Card key={k.key} data-testid={`analytics-kpi-${k.key}`} className="hover-lift border-border min-w-0">
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-start justify-between gap-2">
                {Icon ? (
                  <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0">
                    <Icon className="h-4.5 w-4.5" strokeWidth={2} />
                  </div>
                ) : <span />}
                {k.delta !== undefined && <DeltaBadge kpi={k} />}
              </div>
              <div className="mt-3">
                <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground truncate">{k.label}</div>
                <div className="font-display text-xl sm:text-2xl font-semibold text-foreground mt-1 tracking-tight truncate">{formatKpi(k)}</div>
                {k.hint && <div className="text-[11px] text-muted-foreground mt-0.5 truncate">{k.hint}</div>}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
