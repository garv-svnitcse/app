import { useState } from "react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import {
  Activity, Bike, CalendarClock, ChevronRight, Gauge, IndianRupee, MapPin, Receipt, Repeat,
  UserPlus, Users, XCircle,
} from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusPill } from "@/components/module/ModulePrimitives";
import { cn } from "@/lib/utils";
import {
  AXIS_TICK, GRID_STROKE, ChartCard, ChartTooltip, ExportButton, KpiGrid,
  formatInr, formatNumber, formatPct, titleCase, useAnalyticsData,
} from "./shared";
import { CohortHeatmap, BookingHeatmap } from "./Heatmaps";
import CityDrilldownSheet from "./CityDrilldownSheet";

const KPI_ICONS = {
  revenue: IndianRupee, bookings: Bike, avg_booking_value: Receipt, customers: Users,
  new_customers: UserPlus, repeat_rate: Repeat, cancellation_rate: XCircle, utilisation: Gauge,
};

const TH = "text-[11px] uppercase tracking-[0.1em]";

function Bars({ rows, valueKey, max = 100, format, labelKey, sub }) {
  return (
    <div className="space-y-3">
      {rows.map((r) => {
        const v = r[valueKey];
        const width = v === null || v === undefined || !max ? 0 : Math.min(100, (v / max) * 100);
        return (
          <div key={r[labelKey]}>
            <div className="flex items-baseline justify-between gap-2 text-[13px]">
              <span className="font-medium text-foreground truncate">{titleCase(r[labelKey])}</span>
              <span className="tabular-nums text-foreground">{format(v)}</span>
            </div>
            <div className="mt-1 h-2 rounded-full bg-muted overflow-hidden">
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${width}%` }} />
            </div>
            {sub && <div className="text-[11px] text-muted-foreground mt-1">{sub(r)}</div>}
          </div>
        );
      })}
    </div>
  );
}

export default function MarketplaceTab({ range, city, canExport }) {
  const params = { days: range.days, from: range.from, to: range.to, ...(city ? { city } : {}) };
  const rangeParams = { days: range.days, from: range.from, to: range.to };
  const [drill, setDrill] = useState(null);

  const summary = useAnalyticsData("/analytics/marketplace/summary", params);
  const trend = useAnalyticsData("/analytics/marketplace/trend", params);
  const cohorts = useAnalyticsData("/analytics/marketplace/cohorts", params);
  const cities = useAnalyticsData("/analytics/marketplace/cities", rangeParams);
  const fleet = useAnalyticsData("/analytics/marketplace/fleet", params);
  const funnel = useAnalyticsData("/analytics/marketplace/funnel", params);
  const heatmap = useAnalyticsData("/analytics/marketplace/heatmap", params);

  const series = trend.data?.series || [];
  const noTrend = !series.some((s) => s.bookings > 0);
  const gran = trend.data?.granularity || "day";
  const cityRows = cities.data?.cities || [];
  const cohortRows = cohorts.data?.cohorts || [];
  const exp = (dataset, p = params) => <ExportButton dataset={dataset} params={p} canExport={canExport} />;

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex justify-end -mb-2">{exp("summary")}</div>
      <KpiGrid kpis={summary.data?.kpis} loading={summary.loading} error={summary.error} onRetry={summary.reload} icons={KPI_ICONS} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard
          className="lg:col-span-2" testId="analytics-revenue-trend"
          title="Revenue trend" description={`Paid booking revenue per ${gran} · by booking date (IST)`}
          actions={exp("trend")} loading={trend.loading} error={trend.error} onRetry={trend.reload}
          empty={noTrend} emptyIcon={IndianRupee} emptyDescription="No bookings were created in this range."
        >
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ top: 10, right: 12, left: -6, bottom: 0 }}>
                <defs>
                  <linearGradient id="anaRevFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={16} />
                <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} tickFormatter={(v) => formatInr(v)} width={72} />
                <Tooltip
                  content={<ChartTooltip formatters={{ revenue: (v) => formatInr(v, { compact: false }) }} />}
                  cursor={{ stroke: GRID_STROKE }}
                />
                <Area type="monotone" dataKey="revenue" stroke="hsl(var(--chart-1))" fill="url(#anaRevFill)" strokeWidth={2.5} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard
          title="Bookings" description={`Created per ${gran} · cancelled shown separately`}
          loading={trend.loading} error={trend.error} onRetry={trend.reload}
          empty={noTrend} emptyIcon={Bike} emptyDescription="No bookings were created in this range."
        >
          <div className="h-[236px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={series} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={16} />
                <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTooltip names={{ paid: "Paid", cancelled: "Cancelled" }} />} cursor={{ fill: "hsl(var(--muted) / 0.5)" }} />
                <Bar dataKey="paid" stackId="b" fill="hsl(var(--chart-1))" maxBarSize={28} />
                <Bar dataKey="cancelled" stackId="b" fill="hsl(var(--chart-3))" radius={[4, 4, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[hsl(var(--chart-1))]" />Paid</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[hsl(var(--chart-3))]" />Cancelled</span>
            <span>Pending bookings are counted in totals only</span>
          </div>
        </ChartCard>
      </div>

      <ChartCard
        testId="analytics-cohorts" title="Cohort retention"
        description="Customers grouped by first paid-booking month · % who booked again in each following month"
        actions={exp("cohorts")} loading={cohorts.loading} error={cohorts.error} onRetry={cohorts.reload} height={220}
        empty={!cohortRows.some((c) => c.size > 0)} emptyIcon={Repeat} emptyTitle="No new customers in this range"
        emptyDescription="Cohorts start from each customer's first paid booking. Try a longer range such as 90D."
      >
        {cohorts.data && <CohortHeatmap data={cohorts.data} />}
      </ChartCard>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard
          className="lg:col-span-2" testId="analytics-cities" title="Cities"
          description="Tap a city to drill down · utilisation = booked ÷ available vehicle-days"
          actions={exp("cities", rangeParams)} loading={cities.loading} error={cities.error} onRetry={cities.reload}
          empty={!cityRows.length} emptyIcon={MapPin} emptyTitle="No city activity"
          emptyDescription="No bookings or active vehicles in any city for this range."
        >
          <div className="overflow-x-auto -mx-2">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className={TH}>City</TableHead>
                  <TableHead className={`${TH} text-right`}>Bookings</TableHead>
                  <TableHead className={`${TH} text-right`}>Revenue</TableHead>
                  <TableHead className={`${TH} text-right hidden sm:table-cell`}>Cancel</TableHead>
                  <TableHead className={`${TH} text-right`}>Util.</TableHead>
                  <TableHead className="w-6" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {cityRows.map((c) => (
                  <TableRow
                    key={c.city}
                    className={cn("border-border cursor-pointer", city === c.city && "bg-primary/5")}
                    onClick={() => setDrill(c.city)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setDrill(c.city); } }}
                    tabIndex={0} role="button" aria-label={`Open ${c.city} drill-down`}
                    data-testid={`analytics-city-row-${c.city}`}
                  >
                    <TableCell className="py-2.5">
                      <div className="font-medium text-foreground">{c.city}</div>
                      <div className="text-[11px] text-muted-foreground">{formatNumber(c.customers)} customers · {formatNumber(c.vehicles)} vehicles</div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(c.bookings)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatInr(c.revenue)}</TableCell>
                    <TableCell className="text-right tabular-nums hidden sm:table-cell">{formatPct(c.cancellation_rate)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPct(c.utilisation)}</TableCell>
                    <TableCell className="pl-0"><ChevronRight className="h-4 w-4 text-muted-foreground" /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </ChartCard>

        <ChartCard
          title="Booking funnel" description="Bookings created in range by furthest stage reached"
          actions={exp("funnel")} loading={funnel.loading} error={funnel.error} onRetry={funnel.reload}
          empty={!funnel.data?.total} emptyIcon={Activity}
        >
          {funnel.data && (
            <div className="space-y-5">
              <Bars
                rows={funnel.data.steps} labelKey="step" valueKey="count" max={funnel.data.total}
                format={(v) => formatNumber(v)}
                sub={(r) => `${formatPct(r.share)} of created`}
              />
              <div className="flex flex-wrap gap-1.5 pt-1 border-t border-border">
                {funnel.data.statuses.filter((s) => s.count).map((s) => (
                  <span key={s.status} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground pt-2">
                    <StatusPill status={s.status} />{formatNumber(s.count)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard
          title="Fleet utilisation" description="By vehicle type · booked ÷ available vehicle-days"
          actions={exp("fleet")} loading={fleet.loading} error={fleet.error} onRetry={fleet.reload}
          empty={!fleet.data?.kinds?.length} emptyIcon={Gauge} emptyTitle="No active vehicles"
          emptyDescription="Add vehicles in Marketplace to track utilisation."
        >
          {fleet.data && (
            <Bars
              rows={fleet.data.kinds} labelKey="kind" valueKey="utilisation" max={100}
              format={formatPct}
              sub={(k) => `${formatNumber(k.vehicles)} vehicles · ${k.booked_days} of ${k.available_days} days · ${formatInr(k.revenue)}`}
            />
          )}
        </ChartCard>

        <ChartCard
          className="lg:col-span-2" title="When bookings start" description="Day of week × hour of day · excludes cancelled"
          actions={exp("heatmap")} loading={heatmap.loading} error={heatmap.error} onRetry={heatmap.reload} height={200}
          empty={!heatmap.data?.total} emptyIcon={CalendarClock}
        >
          {heatmap.data && <BookingHeatmap data={heatmap.data} />}
        </ChartCard>
      </div>

      <CityDrilldownSheet
        city={drill} range={range} canExport={canExport}
        onOpenChange={(open) => { if (!open) setDrill(null); }}
      />
    </div>
  );
}
