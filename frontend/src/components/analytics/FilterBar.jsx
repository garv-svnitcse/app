import { format, parseISO, subDays } from "date-fns";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

/** Rolling windows (IST days, ending today). Keys double as the `days` API param. */
export const PRESETS = [
  { days: 1, label: "1D", title: "Today" },
  { days: 3, label: "3D", title: "Last 3 days" },
  { days: 7, label: "7D", title: "Last 7 days" },
  { days: 30, label: "30D", title: "Last 30 days" },
  { days: 90, label: "90D", title: "Last 90 days" },
];
export const DEFAULT_DAYS = 30;
const ALLOWED = new Set(PRESETS.map((p) => p.days));

const ALL = "__all__";

/** Today's date (YYYY-MM-DD) in IST, from the client clock. */
export function todayIST() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

/** Parse a `days` value (e.g. from the URL); falls back to the default window. */
export function parseDays(value) {
  const n = Number(value);
  return ALLOWED.has(n) ? n : DEFAULT_DAYS;
}

/** Inclusive IST date range for a window of `days`, anchored on the server's "today". */
export function presetRange(days, today) {
  const end = today ? parseISO(today) : new Date();
  return { from: format(subDays(end, days - 1), "yyyy-MM-dd"), to: format(end, "yyyy-MM-dd"), days };
}

export function rangeLabel(range) {
  try {
    const f = parseISO(range.from);
    const t = parseISO(range.to);
    if (range.from === range.to) return format(t, "d MMM yyyy");
    const sameYear = f.getFullYear() === t.getFullYear();
    return `${format(f, sameYear ? "d MMM" : "d MMM yyyy")} – ${format(t, "d MMM yyyy")}`;
  } catch {
    return `${range.from} – ${range.to}`;
  }
}

export default function FilterBar({
  days, range, onDays, cities, city, onCity, showCity,
  departments, department, onDepartment, showDepartment, departmentLocked, onRefresh, refreshing,
}) {
  return (
    <div className="flex flex-col lg:flex-row lg:items-center gap-2 lg:gap-3 rounded-xl border border-border bg-card p-2 sm:p-3" data-testid="analytics-filters">
      <div className="flex items-center gap-1 flex-wrap">
        <div className="inline-flex items-center rounded-md bg-muted p-0.5" role="group" aria-label="Time range">
          {PRESETS.map((p) => (
            <button
              key={p.days}
              type="button"
              onClick={() => onDays(p.days)}
              aria-pressed={days === p.days}
              aria-label={p.title}
              title={p.title}
              data-testid={`analytics-preset-${p.days}d`}
              className={cn(
                "h-7 px-2.5 rounded text-xs font-medium transition-colors",
                days === p.days ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground px-1 hidden sm:inline">{rangeLabel(range)}</span>
      </div>

      <div className="flex items-center gap-2 lg:ml-auto min-w-0">
        {showCity && (
          <Select value={city || ALL} onValueChange={(v) => onCity(v === ALL ? "" : v)}>
            <SelectTrigger className="h-8 w-full sm:w-44 text-xs" data-testid="analytics-city" aria-label="City filter">
              <SelectValue placeholder="All cities" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All cities</SelectItem>
              {(cities || []).map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
        {showDepartment && (
          <Select value={department || ALL} onValueChange={(v) => onDepartment(v === ALL ? "" : v)} disabled={!!departmentLocked}>
            <SelectTrigger className="h-8 w-full sm:w-44 text-xs" data-testid="analytics-department" aria-label="Department filter">
              <SelectValue placeholder="All departments" />
            </SelectTrigger>
            <SelectContent>
              {!departmentLocked && <SelectItem value={ALL}>All departments</SelectItem>}
              {(departments || []).map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0 shrink-0" onClick={onRefresh} aria-label="Refresh analytics" data-testid="analytics-refresh">
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
        </Button>
      </div>
      <span className="text-[11px] text-muted-foreground px-1 sm:hidden">{rangeLabel(range)} · IST</span>
    </div>
  );
}
