import { useState } from "react";
import { cn } from "@/lib/utils";
import { formatNumber } from "./shared";

// Sequential single-hue scale on the primary chart token (works in light and dark themes).
function cellStyle(value, max) {
  if (value === null || value === undefined) return {};
  if (!max || value <= 0) return { background: "hsl(var(--muted) / 0.6)" };
  const t = Math.min(1, value / max);
  return { background: `hsl(var(--chart-1) / ${(0.12 + t * 0.78).toFixed(2)})` };
}

function inkClass(value, max) {
  return max && value / max > 0.55 ? "text-primary-foreground" : "text-foreground";
}

function ScaleLegend({ low, high }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <span>{low}</span>
      <span className="h-2 w-24 rounded-full" style={{ background: "linear-gradient(90deg, hsl(var(--chart-1) / 0.12), hsl(var(--chart-1) / 0.9))" }} />
      <span>{high}</span>
    </div>
  );
}

/** Cohort retention matrix: rows = first-booking month, columns = month +1..+N. */
export function CohortHeatmap({ data }) {
  const offsets = data.offsets || 11;
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full border-separate text-[11px]" style={{ borderSpacing: 2 }} data-testid="analytics-cohort-table">
          <thead>
            <tr className="text-muted-foreground">
              <th className="text-left font-medium uppercase tracking-[0.08em] px-2 py-1 sticky left-0 bg-card z-10">Cohort</th>
              <th className="text-right font-medium uppercase tracking-[0.08em] px-2 py-1">Customers</th>
              {Array.from({ length: offsets }).map((_, i) => (
                <th key={i} className="font-medium px-1 py-1 min-w-[44px] text-center">M+{i + 1}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.cohorts.map((c) => (
              <tr key={c.cohort}>
                <td className="px-2 py-1.5 font-medium text-foreground whitespace-nowrap sticky left-0 bg-card z-10">{c.label}</td>
                <td className="px-2 py-1.5 text-right tabular-nums text-foreground">{formatNumber(c.size)}</td>
                {c.retention.map((p, i) => (
                  <td
                    key={i}
                    className={cn("h-8 text-center tabular-nums rounded-[4px]", p === null ? "text-muted-foreground/50" : inkClass(p, 100))}
                    style={cellStyle(p, 100)}
                    title={p === null
                      ? (c.size ? `${c.label} · M+${i + 1}: not reached yet` : `${c.label}: no new customers`)
                      : `${c.label} · M+${i + 1}: ${c.retained[i]} of ${c.size} customers booked again (${p}%)`}
                  >
                    {p === null ? "·" : `${Math.round(p)}%`}
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <td className="px-2 py-1.5 font-semibold text-muted-foreground uppercase tracking-[0.08em] sticky left-0 bg-card z-10">Weighted avg</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{formatNumber(data.customers)}</td>
              {data.average.map((p, i) => (
                <td key={i} className="h-8 text-center tabular-nums font-semibold text-foreground rounded-[4px] border border-border" title={p === null ? "No eligible cohorts" : `Average M+${i + 1} retention: ${p}%`}>
                  {p === null ? "·" : `${Math.round(p)}%`}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ScaleLegend low="0%" high="100%" />
        <span className="text-[11px] text-muted-foreground">· = month not reached yet or empty cohort</span>
      </div>
    </div>
  );
}

const HOUR_LABELS = [0, 3, 6, 9, 12, 15, 18, 21];

/** Day-of-week × hour-of-day heatmap of booking starts (IST). */
export function BookingHeatmap({ data }) {
  const [hover, setHover] = useState(null);
  const max = data.max || 0;
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto -mx-1 px-1">
        <div className="min-w-[520px]" onMouseLeave={() => setHover(null)}>
          <div className="grid gap-[2px]" style={{ gridTemplateColumns: "36px repeat(24, minmax(0, 1fr))" }}>
            {data.matrix.map((row, d) => (
              <div key={d} className="contents">
                <div className="text-[11px] text-muted-foreground flex items-center">{data.days[d]}</div>
                {row.map((n, h) => (
                  <div
                    key={h}
                    className={cn("h-6 rounded-[3px] transition-[outline] outline-offset-0", hover && hover.d === d && hover.h === h && "outline outline-2 outline-foreground/40")}
                    style={cellStyle(n, max)}
                    onMouseEnter={() => setHover({ d, h, n })}
                    title={`${data.days[d]} ${String(h).padStart(2, "0")}:00 – ${String(h).padStart(2, "0")}:59 · ${n} booking${n === 1 ? "" : "s"}`}
                  />
                ))}
              </div>
            ))}
            <div />
            {Array.from({ length: 24 }).map((_, h) => (
              <div key={h} className="text-[10px] text-muted-foreground text-center pt-1">
                {HOUR_LABELS.includes(h) ? String(h).padStart(2, "0") : ""}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ScaleLegend low="0" high={formatNumber(max)} />
        <span className="text-[11px] text-muted-foreground min-h-[16px]">
          {hover ? `${data.days[hover.d]} ${String(hover.h).padStart(2, "0")}:00 · ${hover.n} booking${hover.n === 1 ? "" : "s"}` : "Booking start times · IST"}
        </span>
      </div>
    </div>
  );
}
