import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { Bike, Handshake, MapPin } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  AXIS_TICK, GRID_STROKE, ChartTooltip, EmptyChart, ErrorPanel, ExportButton,
  formatInr, formatNumber, formatPct, titleCase, useAnalyticsData,
} from "./shared";
import { rangeLabel } from "./FilterBar";

function Metric({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 min-w-0">
      <div className="text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground truncate">{label}</div>
      <div className="font-display text-lg font-semibold text-foreground mt-0.5 tracking-tight truncate">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground truncate">{sub}</div>}
    </div>
  );
}

const TH = "text-[11px] uppercase tracking-[0.1em]";

export default function CityDrilldownSheet({ city, range, onOpenChange, canExport }) {
  const params = { days: range.days, from: range.from, to: range.to };
  const { data, loading, error, reload } = useAnalyticsData(
    city ? `/analytics/marketplace/cities/${encodeURIComponent(city)}` : null, params, !!city,
  );
  const exportParams = { ...params, city };
  const s = data?.summary;
  const series = data?.trend?.series || [];
  const hasTrend = series.some((p) => p.bookings > 0);

  return (
    <Sheet open={!!city} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto p-4 sm:p-6" data-testid="analytics-city-sheet">
        <SheetHeader className="text-left pr-6">
          <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground flex items-center gap-1">
            <MapPin className="h-3 w-3" />City drill-down
          </div>
          <SheetTitle className="font-display text-2xl font-semibold tracking-tight">{city}</SheetTitle>
          <SheetDescription>{rangeLabel(range)} · revenue from confirmed, active and completed bookings</SheetDescription>
        </SheetHeader>

        {loading && (
          <div className="space-y-3 mt-6">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[70px] rounded-lg" />)}</div>
            <Skeleton className="h-[200px] rounded-lg" />
            <Skeleton className="h-[160px] rounded-lg" />
          </div>
        )}
        {!loading && error && <ErrorPanel error={error} onRetry={reload} className="mt-6 rounded-lg border border-dashed border-border" />}

        {!loading && !error && s && (
          <div className="space-y-6 mt-6">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <Metric label="Revenue" value={formatInr(s.revenue)} sub={`${formatNumber(s.paid_bookings)} paid bookings`} />
              <Metric label="Bookings" value={formatNumber(s.bookings)} sub={`${formatNumber(s.cancelled)} cancelled`} />
              <Metric label="Avg booking value" value={s.paid_bookings ? formatInr(s.avg_value, { compact: false }) : "—"} />
              <Metric label="Utilisation" value={formatPct(s.utilisation)} sub={`${s.booked_days} of ${s.available_days} vehicle-days`} />
              <Metric label="Cancellation rate" value={formatPct(s.cancellation_rate)} />
              <Metric label="Active fleet" value={formatNumber(s.vehicles)} sub="non-retired vehicles" />
            </div>

            <section>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-display text-[15px] font-semibold text-foreground">Revenue trend</h3>
                <span className="text-[11px] text-muted-foreground">per {data.trend.granularity}</span>
              </div>
              {hasTrend ? (
                <div className="h-[200px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                      <defs>
                        <linearGradient id="cityRevFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={16} />
                      <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} tickFormatter={(v) => formatInr(v)} width={70} />
                      <Tooltip content={<ChartTooltip formatters={{ revenue: (v) => formatInr(v, { compact: false }) }} />} cursor={{ stroke: GRID_STROKE }} />
                      <Area type="monotone" dataKey="revenue" stroke="hsl(var(--chart-1))" fill="url(#cityRevFill)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyChart title="No bookings in this range" description={`Nothing was booked in ${city} between these dates.`} className="min-h-[140px]" />
              )}
            </section>

            <section>
              <div className="flex items-center justify-between mb-1">
                <h3 className="font-display text-[15px] font-semibold text-foreground">Top vehicles</h3>
                <ExportButton dataset="city_vehicles" params={exportParams} canExport={canExport} />
              </div>
              {data.top_vehicles.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-border hover:bg-transparent">
                        <TableHead className={TH}>Vehicle</TableHead>
                        <TableHead className={`${TH} text-right`}>Bookings</TableHead>
                        <TableHead className={`${TH} text-right`}>Revenue</TableHead>
                        <TableHead className={`${TH} text-right`}>Utilisation</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.top_vehicles.map((v) => (
                        <TableRow key={v.id} className="border-border">
                          <TableCell className="py-2">
                            <div className="text-sm font-medium text-foreground">{v.model}</div>
                            <div className="text-[11px] text-muted-foreground">{v.plate} · {titleCase(v.kind)}</div>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{formatNumber(v.bookings)}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatInr(v.revenue, { compact: false })}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatPct(v.utilisation)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : <EmptyChart icon={Bike} title="No active vehicles" description="This city has no non-retired vehicles." className="min-h-[120px]" />}
            </section>

            <section>
              <div className="flex items-center justify-between mb-1">
                <h3 className="font-display text-[15px] font-semibold text-foreground">Vendors</h3>
                <ExportButton dataset="city_vendors" params={exportParams} canExport={canExport} />
              </div>
              {data.vendors.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-border hover:bg-transparent">
                        <TableHead className={TH}>Vendor</TableHead>
                        <TableHead className={`${TH} text-right`}>Fleet</TableHead>
                        <TableHead className={`${TH} text-right`}>Bookings</TableHead>
                        <TableHead className={`${TH} text-right`}>Revenue</TableHead>
                        <TableHead className={`${TH} text-right`}>Util.</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.vendors.map((v) => (
                        <TableRow key={v.vendor_id || v.vendor} className="border-border">
                          <TableCell className="py-2">
                            <div className="text-sm font-medium text-foreground">{v.vendor}</div>
                            <div className="text-[11px] text-muted-foreground">
                              {v.rating ? `★ ${v.rating}` : "No rating"} · cancel {formatPct(v.cancellation_rate)}
                            </div>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{formatNumber(v.vehicles)}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatNumber(v.bookings)}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatInr(v.revenue, { compact: false })}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatPct(v.utilisation)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : <EmptyChart icon={Handshake} title="No vendors yet" description="No vendor vehicles or bookings in this city." className="min-h-[120px]" />}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
