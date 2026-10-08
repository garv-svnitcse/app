import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusPill } from "@/components/module/ModulePrimitives";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { format } from "date-fns";

/** ₹1,23,456.50 — en-IN grouping, paise only when present. */
export function inr(n) {
  const v = Number(n) || 0;
  return `₹${v.toLocaleString("en-IN", { minimumFractionDigits: Number.isInteger(v) ? 0 : 2, maximumFractionDigits: 2 })}`;
}

/** Compact for chart axes: ₹1.2L, ₹3.4Cr, ₹12K. */
export function inrCompact(n) {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)}L`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(0)}K`;
  return `₹${v}`;
}

/** Today in the company timezone (Asia/Kolkata) as YYYY-MM-DD. */
export function todayIST() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

export function currentMonthIST() {
  return todayIST().slice(0, 7);
}

export function monthLabel(ym) {
  if (!ym) return "";
  const [y, m] = ym.split("-").map(Number);
  return format(new Date(y, m - 1, 1), "MMM yyyy");
}

/** Last `count` months, newest first, as YYYY-MM. */
export function recentMonths(count = 24) {
  const [y, m] = currentMonthIST().split("-").map(Number);
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(y, m - 1 - i, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
}

export function formatDate(value) {
  if (!value) return "—";
  try {
    const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
    return format(d, "d MMM yyyy");
  } catch { return value; }
}

const INVOICE_TONES = {
  draft: "bg-muted text-foreground/70",
  issued: "bg-info/10 text-info",
  paid: "bg-success/10 text-success",
  void: "bg-destructive/10 text-destructive",
};

export function FinanceStatus({ status }) {
  return <StatusPill status={status} className={INVOICE_TONES[status]} />;
}

/**
 * Loads data, refetches when the window regains focus and optionally on an interval.
 * Stale responses from superseded requests are ignored.
 */
export function useFinanceResource(path, params, { interval } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const key = JSON.stringify(params || {});

  const reload = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    return api.get(path, { params: JSON.parse(key) })
      .then(({ data }) => { if (id === seq.current) { setData(data); setError(null); } })
      .catch((e) => { if (id === seq.current) setError(formatApiError(e)); })
      .finally(() => { if (id === seq.current) setLoading(false); });
  }, [path, key]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    const onFocus = () => reload();
    window.addEventListener("focus", onFocus);
    const t = interval ? setInterval(reload, interval) : null;
    return () => { window.removeEventListener("focus", onFocus); if (t) clearInterval(t); };
  }, [reload, interval]);

  return { data, error, loading, reload };
}

/** Downloads a CSV from an authenticated endpoint. */
export async function downloadCsv(path, params, filename) {
  const res = await api.get(path, { params, responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function LoadError({ error, onRetry, loading, what = "data" }) {
  return (
    <Card className="border-border" data-testid="finance-error">
      <CardContent className="p-10 text-center">
        <AlertTriangle className="h-8 w-8 mx-auto text-destructive" />
        <div className="mt-3 text-sm font-medium text-foreground">Could not load {what}</div>
        <div className="mt-1 text-sm text-muted-foreground">{String(error)}</div>
        <Button variant="outline" size="sm" onClick={onRetry} disabled={loading} className="mt-4 h-8 text-xs" data-testid="finance-retry">
          <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", loading && "animate-spin")} />Retry
        </Button>
      </CardContent>
    </Card>
  );
}

export function SkeletonBlocks({ count = 4, className = "h-28" }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={cn("rounded-xl bg-muted animate-pulse", className)} />
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 5 }) {
  return (
    <div className="p-4 space-y-2">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="h-9 rounded-md bg-muted animate-pulse" />)}
    </div>
  );
}

export function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 shadow-lg text-xs">
      <div className="font-medium text-foreground mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="font-medium text-foreground ml-auto pl-3">{inr(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function MonthSelect({ value, onChange, allowAll = false, testid, className, disabled }) {
  const months = recentMonths(24);
  return (
    <Select value={value || "all"} onValueChange={(v) => onChange(v === "all" ? "" : v)} disabled={disabled}>
      <SelectTrigger className={cn("h-9 w-full sm:w-[150px]", className)} data-testid={testid}>
        <SelectValue placeholder="Month" />
      </SelectTrigger>
      <SelectContent>
        {allowAll && <SelectItem value="all">All months</SelectItem>}
        {months.map((m) => <SelectItem key={m} value={m}>{monthLabel(m)}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

export const TH = "text-[11px] uppercase tracking-[0.1em]";

export const VENDOR_CATEGORIES = [
  { value: "fleet_partner", label: "Fleet partner" },
  { value: "maintenance", label: "Maintenance & repairs" },
  { value: "fuel_charging", label: "Fuel & charging" },
  { value: "insurance", label: "Insurance" },
  { value: "marketing", label: "Marketing" },
  { value: "software", label: "Software & SaaS" },
  { value: "rent_utilities", label: "Rent & utilities" },
  { value: "logistics", label: "Logistics" },
  { value: "professional_services", label: "Professional services" },
  { value: "office_supplies", label: "Office supplies" },
  { value: "other", label: "Other" },
];

export function categoryLabel(value) {
  return VENDOR_CATEGORIES.find((c) => c.value === value)?.label || value || "—";
}

const BILL_TONES = {
  pending: "bg-warning/10 text-warning",
  paid: "bg-success/10 text-success",
  cancelled: "bg-destructive/10 text-destructive",
};

export function BillStatus({ status, overdue }) {
  if (overdue) return <StatusPill status="overdue" className="bg-destructive/10 text-destructive" />;
  return <StatusPill status={status} className={BILL_TONES[status]} />;
}

/**
 * Vendor picker for filters and forms. `vendors` is [{ id, name }]; an empty value means "all"
 * when `allLabel` is given, otherwise the placeholder is shown.
 */
export function VendorSelect({ vendors, value, onChange, allLabel, placeholder = "Select vendor", testid, className, disabled }) {
  const none = allLabel ? "all" : "";
  return (
    <Select value={value || none} onValueChange={(v) => onChange(v === "all" ? "" : v)} disabled={disabled}>
      <SelectTrigger className={cn("h-9 w-full sm:w-[190px]", className)} data-testid={testid}>
        <SelectValue placeholder={vendors ? placeholder : "Loading vendors…"} />
      </SelectTrigger>
      <SelectContent>
        {allLabel && <SelectItem value="all">{allLabel}</SelectItem>}
        {(vendors || []).map((v) => (
          <SelectItem key={v.id} value={v.id}>
            {v.name}{v.status === "inactive" || v.active === false ? " (inactive)" : ""}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
