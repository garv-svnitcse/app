import { useEffect } from "react";
import { Users, Repeat, Wallet, CalendarClock, Plus } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { StatCard, EmptyState } from "@/components/module/ModulePrimitives";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AXIS_TICK, CHART_TOOLTIP, inr, relativeDays, useResource } from "./crmShared";
import { ErrorBlock, LifecyclePill, StatSkeletons } from "./StateBlocks";

function monthLabel(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-IN", { month: "short", year: "2-digit" });
}

export default function CrmOverview({ onOpenCustomer, onPickStage, onAddCustomer, refreshKey }) {
  const { data, error, loading, reload } = useResource("/crm/overview");
  useEffect(() => { if (refreshKey) reload({ background: true }); }, [refreshKey, reload]);

  if (error) return <ErrorBlock title="Couldn't load the CRM overview" error={error} onRetry={reload} />;
  if (loading && !data) {
    return (
      <div className="space-y-6">
        <StatSkeletons />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-[320px] rounded-xl" /><Skeleton className="h-[320px] rounded-xl" />
        </div>
      </div>
    );
  }
  const t = data.totals;
  if (t.customers === 0) {
    return (
      <EmptyState icon={Users} title="No customers yet"
                  description="Add a customer here, or create them in Marketplace — they appear with their full booking history."
                  action={onAddCustomer && (
                    <Button size="sm" className="gap-1.5" onClick={onAddCustomer}><Plus className="h-4 w-4" /> Add customer</Button>
                  )} />
    );
  }
  const months = data.new_customers.map((m) => ({ ...m, label: monthLabel(m.month) }));

  return (
    <div className="space-y-6" data-testid="crm-overview">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Customers" value={t.customers.toLocaleString("en-IN")} sub={`${t.booked_customers} booked`} icon={Users} />
        <StatCard label="Repeat rate" value={t.repeat_rate === null ? "—" : `${t.repeat_rate}%`} sub={`${t.repeat_customers} repeat`} icon={Repeat} tone="info" />
        <StatCard label="Lifetime value" value={inr(t.total_ltv)} sub={t.avg_ltv === null ? null : `avg ${inr(t.avg_ltv)}`} icon={Wallet} tone="success" />
        <StatCard label="Open follow-ups" value={t.open_followups} sub={t.overdue_followups ? `${t.overdue_followups} overdue` : "none overdue"} icon={CalendarClock} tone={t.overdue_followups ? "warning" : "default"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[16px]">Customers by lifecycle</CardTitle>
            <CardDescription className="text-[12px]">Click a stage to see its customers.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {data.by_lifecycle.map((s) => {
              const pct = t.customers ? (s.count / t.customers) * 100 : 0;
              return (
                <button key={s.stage} type="button" onClick={() => onPickStage(s.stage)}
                        className="w-full text-left group" data-testid={`crm-stage-${s.stage}`}>
                  <div className="flex items-center justify-between text-[12.5px] mb-1">
                    <LifecyclePill stage={s.stage} />
                    <span className="text-muted-foreground group-hover:text-foreground">
                      <span className="font-medium text-foreground">{s.count}</span> · {pct.toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-muted overflow-hidden">
                    <div className="h-full rounded-full bg-primary/80 group-hover:bg-primary transition-colors" style={{ width: `${pct}%` }} />
                  </div>
                </button>
              );
            })}
          </CardContent>
        </Card>

        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[16px]">New customers</CardTitle>
            <CardDescription className="text-[12px]">Sign-ups per month, last 12 months (IST).</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={months} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                  <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={CHART_TOOLTIP} cursor={{ fill: "hsl(var(--muted))" }} formatter={(v) => [v, "New customers"]} />
                  <Bar dataKey="count" fill="hsl(var(--chart-1))" radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border">
        <CardHeader className="pb-2">
          <CardTitle className="font-display text-[16px]">Top customers by lifetime value</CardTitle>
          <CardDescription className="text-[12px]">Lifetime value counts confirmed, active and completed bookings.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.top_customers.length === 0 ? (
            <div className="text-[13px] text-muted-foreground py-6 text-center">No revenue-generating bookings yet.</div>
          ) : (
            <ul className="divide-y divide-border">
              {data.top_customers.map((c, i) => (
                <li key={c.id}>
                  <button type="button" onClick={() => onOpenCustomer(c.id)}
                          className="w-full flex items-center gap-3 py-2.5 text-left hover:bg-muted/40 rounded-md px-2 -mx-2">
                    <span className="w-5 text-[12px] text-muted-foreground tabular-nums">{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium truncate">{c.name}</div>
                      <div className="text-[11.5px] text-muted-foreground truncate">
                        {c.city || "—"} · {c.bookings} booking{c.bookings === 1 ? "" : "s"} · last {relativeDays(c.days_since_last_booking).toLowerCase()}
                      </div>
                    </div>
                    <LifecyclePill stage={c.lifecycle} className="hidden sm:inline-flex" />
                    <span className="font-display font-semibold tabular-nums text-[14px]">{inr(c.ltv)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
