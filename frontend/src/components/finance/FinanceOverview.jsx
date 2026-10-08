import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import {
  IndianRupee, Percent, Receipt, Wallet, FileWarning, Landmark, RefreshCw, BarChart3, Building2, Scale, ChevronRight,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatCard, EmptyState } from "@/components/module/ModulePrimitives";
import { cn } from "@/lib/utils";
import {
  inr, inrCompact, useFinanceResource, LoadError, SkeletonBlocks, ChartTooltip, monthLabel, categoryLabel, formatDate,
} from "@/components/finance/financeShared";

function vsLast(cur, prev) {
  if (!prev) return cur ? "New this month" : "No revenue yet";
  const d = ((cur - prev) / prev) * 100;
  return `${d >= 0 ? "+" : ""}${d.toFixed(1)}% vs last month`;
}

function TopVendors({ top, onOpenVendor, onNavigate }) {
  const items = top?.items || [];
  const max = Math.max(...items.map((v) => v.spent || v.billed), 1);
  return (
    <Card className="border-border" data-testid="finance-top-vendors">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="font-display text-[17px]">Top vendors by spend</CardTitle>
            <CardDescription>
              Paid bills and linked booking payouts · last {top?.days ?? 90} days{top?.since ? ` (since ${formatDate(top.since)})` : ""}
            </CardDescription>
          </div>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => onNavigate("vendors")}>All vendors</Button>
        </div>
      </CardHeader>
      <CardContent className="pt-1">
        {items.length === 0 ? (
          <EmptyState icon={Building2} title="No vendor spend yet"
                      description="Vendor bills and linked payouts from the last 90 days will rank here." />
        ) : (
          <ul className="divide-y divide-border">
            {items.map((v, i) => (
              <li key={v.vendor_id}>
                <button type="button" onClick={() => onOpenVendor(v.vendor_id)}
                        className="w-full flex items-center gap-3 py-2.5 text-left group" data-testid="finance-top-vendor">
                  <span className="w-5 text-[12px] text-muted-foreground tabular-nums">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="truncate text-[13.5px] font-medium text-foreground group-hover:text-primary">{v.name}</span>
                      <span className="whitespace-nowrap tabular-nums text-[13.5px] font-semibold">{inr(v.spent)}</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(((v.spent || v.billed) / max) * 100, 2)}%` }} />
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-2 text-[11.5px] text-muted-foreground">
                      <span>{categoryLabel(v.category)}</span>
                      <span>· billed {inr(v.billed)}</span>
                      {v.bills_outstanding > 0 && <span>· {inr(v.bills_outstanding)} outstanding</span>}
                      {v.overdue > 0 && <span className="text-destructive">· {inr(v.overdue)} overdue</span>}
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function FinanceOverview({ onNavigate, onOpenVendor }) {
  const { data, error, loading, reload } = useFinanceResource("/finance/overview", null, { interval: 60000 });

  if (!data && error) return <LoadError error={error} onRetry={reload} loading={loading} what="the finance overview" />;
  if (!data) {
    return (
      <div className="space-y-4">
        <SkeletonBlocks count={6} />
        <div className="h-[320px] rounded-xl bg-muted animate-pulse" />
      </div>
    );
  }

  const c = data.cards;
  const hasSeries = data.series.some((s) => s.revenue > 0);

  return (
    <div className="space-y-6" data-testid="finance-overview">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted-foreground">
        <span>
          {monthLabel(data.month)} to date · platform commission <span className="font-medium text-foreground">{data.commission_pct}%</span>
          {" "}· GST <span className="font-medium text-foreground">{data.gst_pct}%</span>
          {" "}<button type="button" className="text-primary hover:underline" onClick={() => onNavigate("settings")}>Edit</button>
          {error && <span className="text-destructive"> · Refresh failed: {error}</span>}
        </span>
        <Button variant="ghost" size="sm" onClick={reload} disabled={loading} className="h-8" aria-label="Refresh overview" data-testid="finance-overview-refresh">
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        <StatCard label="Gross booking revenue (MTD)" value={inr(c.gross_mtd)} icon={IndianRupee}
                  sub={vsLast(c.gross_mtd, c.gross_prev)} />
        <StatCard label="Platform commission (MTD)" value={inr(c.commission_mtd)} icon={Percent} tone="success"
                  sub={`${c.bookings_mtd} revenue booking${c.bookings_mtd === 1 ? "" : "s"}`} />
        <StatCard label="GST collected (MTD)" value={inr(c.gst_mtd)} icon={Landmark} tone="info" sub="Issued + paid invoices" />
        <StatCard label="Receivables" value={inr(c.receivable)} icon={Receipt} tone="warning"
                  sub={`${c.receivable_count} unpaid invoice${c.receivable_count === 1 ? "" : "s"}`} />
        <StatCard label="Vendor payouts pending" value={inr(c.payouts_pending)} icon={Wallet} tone="warning"
                  sub={`${c.payouts_pending_count} awaiting transfer`} />
        <StatCard label="Bookings to invoice" value={c.uninvoiced_bookings.toLocaleString("en-IN")} icon={FileWarning}
                  tone={c.uninvoiced_bookings ? "danger" : "default"}
                  sub={c.draft_invoices ? `${c.draft_invoices} draft invoice${c.draft_invoices === 1 ? "" : "s"}` : "Confirmed · active · completed"} />
        <StatCard label="Net after vendor bills (MTD)" value={inr(c.net_mtd)} icon={Scale}
                  tone={c.net_mtd < 0 ? "danger" : "success"}
                  sub={`Commission − ${inr(c.bills_paid_mtd)} bills paid`} />
        {c.bills_pending_count > 0 && (
          <button type="button" className="text-left" onClick={() => onNavigate("bills")} data-testid="finance-overview-bills">
            <StatCard label="Vendor bills payable" value={inr(c.bills_pending)} icon={Building2}
                      tone={c.bills_overdue ? "danger" : "warning"}
                      sub={c.bills_overdue ? `${inr(c.bills_overdue)} overdue` : `${c.bills_pending_count} pending bill${c.bills_pending_count === 1 ? "" : "s"}`} />
          </button>
        )}
      </div>

      <Card className="border-border" data-testid="finance-revenue-chart">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="font-display text-[17px]">Revenue & commission</CardTitle>
              <CardDescription>Gross booking revenue vs WavyGo's commission · last 12 months (IST)</CardDescription>
            </div>
            <Badge variant="secondary" className="text-[10px]">12M</Badge>
          </div>
        </CardHeader>
        <CardContent className="pt-2">
          {!hasSeries ? (
            <EmptyState icon={BarChart3} title="No revenue in the last 12 months"
                        description="Confirmed, active and completed marketplace bookings will appear here." />
          ) : (
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.series} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="finRevFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="finComFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--chart-2))" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="hsl(var(--chart-2))" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={inrCompact} width={56} tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} cursor={{ stroke: "hsl(var(--border))" }} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" dataKey="revenue" name="Gross revenue" stroke="hsl(var(--chart-1))" fill="url(#finRevFill)" strokeWidth={2.5} />
                  <Area type="monotone" dataKey="commission" name="Commission" stroke="hsl(var(--chart-2))" fill="url(#finComFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <TopVendors top={data.top_vendors} onOpenVendor={onOpenVendor} onNavigate={onNavigate} />
    </div>
  );
}
