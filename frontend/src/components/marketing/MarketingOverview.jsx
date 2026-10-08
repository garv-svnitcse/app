import { Info, Megaphone, PiggyBank, Rocket, TrendingUp } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { EmptyState, StatCard } from "@/components/module/ModulePrimitives";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { AXIS_TICK, CHART_TOOLTIP, inr, useResource } from "@/components/crm/crmShared";
import { ErrorBlock, StatSkeletons } from "@/components/crm/StateBlocks";
import { CHANNEL_LABELS, CampaignStatus, STATUS_META, roiText } from "./marketingShared";

export default function MarketingOverview({ onOpenCampaign, onCreate, refreshKey }) {
  const { data, error, loading, reload } = useResource("/marketing/overview", { _k: refreshKey });

  if (error && !data) return <ErrorBlock title="Couldn't load the marketing overview" error={error} onRetry={reload} />;
  if (loading && !data) {
    return (
      <div className="space-y-6">
        <StatSkeletons />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"><Skeleton className="h-[300px] rounded-xl" /><Skeleton className="h-[300px] rounded-xl" /></div>
      </div>
    );
  }
  const t = data.totals;
  if (t.campaigns === 0) {
    return <EmptyState icon={Megaphone} title="No campaigns yet" description="Plan a campaign with a budget, channels, target cities and linked coupons." action={onCreate} />;
  }
  const channels = data.spend_by_channel.map((c) => ({ ...c, label: CHANNEL_LABELS[c.channel] || c.channel }));

  return (
    <div className="space-y-6" data-testid="marketing-overview">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Active campaigns" value={t.active} sub={`${t.scheduled} scheduled`} icon={Rocket} tone="success" />
        <StatCard label="Budget (launched)" value={inr(t.total_budget)} sub={`${t.campaigns} total`} icon={PiggyBank} />
        <StatCard label="Spend to date" value={inr(t.total_spend)} sub={t.budget_used_pct === null ? null : `${t.budget_used_pct}% of budget`} icon={Megaphone} tone={t.budget_used_pct > 100 ? "danger" : "info"} />
        <StatCard label="Attributed revenue" value={t.attributed_revenue === null ? "—" : inr(t.attributed_revenue)}
                  sub={t.attributed_bookings === null ? "not tracked" : `${t.attributed_bookings} bookings`} icon={TrendingUp} tone="warning" />
      </div>

      {!data.attribution.supported && (
        <div className="flex gap-2.5 rounded-lg border border-info/30 bg-info/5 p-3 text-[12.5px]">
          <Info className="h-4 w-4 text-info shrink-0 mt-0.5" /><span>{data.attribution.reason}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[16px]">Spend by channel</CardTitle>
            <CardDescription className="text-[12px]">Excludes drafts. A campaign's spend is split evenly across its channels.</CardDescription>
          </CardHeader>
          <CardContent>
            {channels.length === 0 ? (
              <div className="h-[240px] flex items-center justify-center text-[13px] text-muted-foreground">No spend recorded yet.</div>
            ) : (
              <div style={{ height: Math.max(160, channels.length * 38 + 30) }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={channels} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 0 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} tickFormatter={(v) => inr(v)} />
                    <YAxis type="category" dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} width={84} />
                    <Tooltip contentStyle={CHART_TOOLTIP} cursor={{ fill: "hsl(var(--muted))" }} formatter={(v) => [inr(v), "Spend"]} />
                    <Bar dataKey="spend" fill="hsl(var(--chart-1))" radius={[0, 4, 4, 0]} maxBarSize={22} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[16px]">Campaigns by status</CardTitle>
            <CardDescription className="text-[12px]">Budget used across launched campaigns: {t.budget_used_pct ?? 0}%</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Progress value={Math.min(100, t.budget_used_pct ?? 0)} className="h-2" />
            <ul className="divide-y divide-border">
              {data.by_status.map((s) => (
                <li key={s.status} className="flex items-center justify-between py-2 text-[13px]">
                  <CampaignStatus status={s.status} />
                  <span className="tabular-nums font-medium">{s.count}<span className="text-muted-foreground font-normal"> {STATUS_META[s.status].label.toLowerCase()}</span></span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border">
        <CardHeader className="pb-2">
          <CardTitle className="font-display text-[16px]">Top campaigns by attributed revenue</CardTitle>
        </CardHeader>
        <CardContent>
          {!data.attribution.supported ? (
            <div className="text-[13px] text-muted-foreground py-6 text-center">Available once bookings redeem a coupon.</div>
          ) : data.top_campaigns.length === 0 ? (
            <div className="text-[13px] text-muted-foreground py-6 text-center">No attributed bookings yet.</div>
          ) : (
            <ul className="divide-y divide-border">
              {data.top_campaigns.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => onOpenCampaign(c.id)} className="w-full flex items-center gap-3 py-2.5 px-2 -mx-2 rounded-md text-left hover:bg-muted/40">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium truncate">{c.name}</div>
                      <div className="text-[11.5px] text-muted-foreground">{c.bookings} bookings · spend {inr(c.spend)} · ROI {roiText(c.roi)}</div>
                    </div>
                    <CampaignStatus status={c.status} className="hidden sm:inline-flex" />
                    <span className="font-display font-semibold tabular-nums">{inr(c.revenue)}</span>
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
