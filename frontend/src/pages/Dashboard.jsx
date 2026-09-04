import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  BarChart, Bar,
} from "recharts";
import {
  TrendingUp, TrendingDown, IndianRupee, Bike, Users, Building2, Handshake,
  Circle, ArrowUpRight, Plus, Bell, ClipboardList, ScrollText, Target,
  Shield, Server, CheckCircle2, AlertTriangle, Info, XCircle, Star, Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { DASHBOARD } from "@/constants/testIds";
import { useAuth } from "@/contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";

const KPI_ICONS = {
  revenue: IndianRupee, revenue_today: IndianRupee, revenue_week: IndianRupee,
  bookings: Bike, bookings_today: Bike, active_bookings: Zap,
  customers: Users, vehicles: Building2, vendors: Handshake,
  my_todo: ClipboardList, my_in_progress: Zap, my_review: Target,
  my_completed: CheckCircle2, my_leave: Bell,
};

function formatValue(k) {
  if (k.format === "inr") {
    if (k.value >= 1e7) return `₹${(k.value / 1e7).toFixed(2)} Cr`;
    if (k.value >= 1e5) return `₹${(k.value / 1e5).toFixed(2)} L`;
    return `₹${k.value.toLocaleString("en-IN")}`;
  }
  return k.value.toLocaleString("en-IN");
}

function ChartTooltip({ active, payload, label, unit }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 shadow-lg text-xs">
      <div className="font-medium text-foreground mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground capitalize">{p.dataKey}</span>
          <span className="font-medium text-foreground ml-auto">{p.value}{unit || ""}</span>
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [activity, setActivity] = useState([]);

  useEffect(() => {
    api.get("/dashboard/stats").then(({ data }) => setData(data)).catch(() => {});
    api.get("/activity?limit=6").then(({ data }) => setActivity(data)).catch(() => {});
  }, []);

  if (!data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-28 rounded-xl bg-muted animate-pulse" />
        ))}
      </div>
    );
  }

  const priorityStyle = {
    high: "text-destructive bg-destructive/10",
    medium: "text-warning bg-warning/10",
    low: "text-info bg-info/10",
  };

  const isEmployeeOrIntern = user?.role === "Employee" || user?.role === "Intern";

  return (
    <div data-testid={DASHBOARD.root} className="space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            {user?.role ? `${user.role} Dashboard` : "Dashboard"}
          </div>
          <h1 className="font-display text-3xl md:text-[34px] font-semibold tracking-tighter text-foreground mt-1">
            Welcome back, {(user?.name || "").split(" ")[0] || "there"}.
          </h1>
          <p className="text-sm text-muted-foreground mt-2 max-w-xl">
            {isEmployeeOrIntern
              ? "A summary of your tasks, pending leaves, and recent updates across the workspace."
              : "A live view of every city, vehicle and rupee moving through WavyGo Mobility. Updated moments ago."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!isEmployeeOrIntern && (
            <Button variant="outline" onClick={() => nav("/analytics")} className="h-9">
              Full analytics <ArrowUpRight className="ml-1.5 h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-5 gap-4">
        {data.kpis.map((k, idx) => {
          const Icon = KPI_ICONS[k.key] || TrendingUp;
          const positive = k.delta >= 0;
          return (
            <motion.div key={k.key} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.04 }}>
              <Card data-testid={DASHBOARD.kpi(k.key)} className="hover-lift border-border">
                <CardContent className="p-5">
                  <div className="flex items-start justify-between">
                    <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center">
                      <Icon className="h-4.5 w-4.5" strokeWidth={2} />
                    </div>
                    {k.delta !== 0 && (
                      <span className={cn(
                        "inline-flex items-center gap-1 text-[11px] font-semibold px-1.5 py-0.5 rounded",
                        positive ? "text-success bg-success/10" : "text-destructive bg-destructive/10"
                      )}>
                        {positive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                        {positive ? "+" : ""}{k.delta}%
                      </span>
                    )}
                  </div>
                  <div className="mt-4">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{k.label}</div>
                    <div className="font-display text-2xl font-semibold text-foreground mt-1 tracking-tight">
                      {formatValue(k)}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          );
        })}
      </div>

      {/* Charts row */}
      {!isEmployeeOrIntern && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card data-testid={DASHBOARD.revenueChart} className="lg:col-span-2 border-border">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="font-display text-[17px]">Revenue trajectory</CardTitle>
                  <CardDescription>Monthly revenue vs target · ₹ in lakhs</CardDescription>
                </div>
                <Badge variant="secondary" className="text-[10px]">6M</Badge>
              </div>
            </CardHeader>
            <CardContent className="pt-2">
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.revenue_series} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                    <defs>
                      <linearGradient id="revFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="month" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip unit="L" />} cursor={{ stroke: "hsl(var(--border))" }} />
                    <Area type="monotone" dataKey="target" stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4" fill="transparent" strokeWidth={1.5} />
                    <Area type="monotone" dataKey="revenue" stroke="hsl(var(--chart-1))" fill="url(#revFill)" strokeWidth={2.5} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card data-testid={DASHBOARD.bookingsChart} className="border-border">
            <CardHeader className="pb-2">
              <CardTitle className="font-display text-[17px]">Bookings this week</CardTitle>
              <CardDescription>Daily volume across all cities</CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.bookings_series} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="day" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted) / 0.5)" }} />
                    <Bar dataKey="bookings" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} maxBarSize={28} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Row: City table + tasks */}
      <div className={cn("grid grid-cols-1 gap-4", !isEmployeeOrIntern ? "lg:grid-cols-3" : "")}>
        {!isEmployeeOrIntern && (
          <Card data-testid={DASHBOARD.cityTable} className="lg:col-span-2 border-border">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="font-display text-[17px]">City performance</CardTitle>
                  <CardDescription>Live view · sorted by revenue</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => nav("/analytics")} className="text-xs">View all</Button>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <Table>
                <TableHeader>
                  <TableRow className="border-border hover:bg-transparent">
                    <TableHead className="text-[11px] uppercase tracking-[0.1em]">City</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Bookings</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Revenue (L)</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] w-[140px]">Growth</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.cities.map((c) => (
                    <TableRow key={c.city} className="border-border">
                      <TableCell className="font-medium text-foreground">{c.city}</TableCell>
                      <TableCell className="text-right text-muted-foreground">{c.bookings.toLocaleString("en-IN")}</TableCell>
                      <TableCell className="text-right font-medium text-foreground">₹{c.revenue}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Progress value={Math.min(100, c.growth * 6)} className="h-1.5" />
                          <span className="text-[11.5px] text-success font-medium min-w-[38px] text-right">+{c.growth}%</span>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        <Card data-testid={DASHBOARD.tasksList} className={cn("border-border", isEmployeeOrIntern ? "col-span-full" : "")}>
          <CardHeader className="pb-2">
            <div className="flex items-start justify-between">
              <div>
                <CardTitle className="font-display text-[17px]">Today's tasks</CardTitle>
                <CardDescription>{data.tasks_today.length} to close by end of day</CardDescription>
              </div>
              <ClipboardList className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            <ul className="space-y-3">
              {data.tasks_today.map((t) => (
                <li key={t.id} className="flex items-start gap-3">
                  <span className={cn("mt-1 h-6 px-1.5 rounded text-[10px] font-semibold uppercase tracking-wide flex items-center", priorityStyle[t.priority])}>
                    {t.priority}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] leading-tight text-foreground">{t.title}</div>
                    <div className="text-[11px] text-muted-foreground mt-1">Due · {t.due}</div>
                  </div>
                </li>
              ))}
            </ul>
            <Button variant="outline" size="sm" onClick={() => nav("/task-board")} className="w-full mt-4 h-8 text-xs">Open Task Board</Button>
          </CardContent>
        </Card>
      </div>

      {/* Row: Quick actions + Calendar + Activity */}
      {!isEmployeeOrIntern && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card data-testid={DASHBOARD.quickActions} className="border-border">
            <CardHeader className="pb-2">
              <CardTitle className="font-display text-[17px]">Quick actions</CardTitle>
              <CardDescription>Most-used flows for founders</CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              <div className="grid grid-cols-2 gap-2">
                {[
                  { icon: Plus, label: "New booking", to: "/marketplace" },
                  { icon: Handshake, label: "Onboard vendor", to: "/marketplace" },
                  { icon: Target, label: "Log opportunity", to: "/opportunity-hub" },
                  { icon: Bell, label: "Announce update", to: "/wavygo-connect" },
                ].map((a) => {
                  const Icon = a.icon;
                  return (
                    <button key={a.label} onClick={() => nav(a.to)}
                            className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-[13px] text-foreground hover:border-primary/40 hover:bg-primary/[0.03] transition-colors">
                      <Icon className="h-4 w-4 text-primary" />{a.label}
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          <Card data-testid={DASHBOARD.calendarList} className="border-border">
            <CardHeader className="pb-2">
              <CardTitle className="font-display text-[17px]">Upcoming calendar</CardTitle>
              <CardDescription>Next few days</CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              <ul className="space-y-3">
                {data.upcoming_events.map((e) => (
                  <li key={e.id} className="flex items-start gap-3">
                    <div className="h-9 w-9 rounded-md bg-info/10 text-info flex items-center justify-center shrink-0">
                      <Circle className="h-2.5 w-2.5 fill-info" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] leading-tight text-foreground">{e.title}</div>
                      <div className="text-[11.5px] text-muted-foreground mt-1">{e.when}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card data-testid={DASHBOARD.activityFeed} className="border-border">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="font-display text-[17px]">Recent activity</CardTitle>
                  <CardDescription>Team + system events</CardDescription>
                </div>
                <ScrollText className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent className="pt-2">
              <ul className="space-y-3">
                {activity.slice(0, 6).map((a) => (
                  <li key={a.id} className="flex items-start gap-3">
                    <div className="h-6 w-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-[10px] font-semibold shrink-0">
                      {(a.user_name || "?").split(" ").map(s => s[0]).slice(0, 2).join("")}
                    </div>
                    <div className="text-[13px] leading-tight">
                      <span className="font-medium text-foreground">{a.user_name}</span>{" "}
                      <span className="text-muted-foreground">{a.action.toLowerCase()}</span>{" "}
                      {a.target && <span className="text-foreground">· {a.target}</span>}
                      <div className="text-[11px] text-muted-foreground mt-0.5">{a.module} · {(() => { try { return formatDistanceToNow(new Date(a.created_at), { addSuffix: true }); } catch { return ""; } })()}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Opportunities */}
      {!isEmployeeOrIntern && (
        <Card data-testid={DASHBOARD.opportunities} className="border-border">
          <CardHeader className="pb-2">
            <div className="flex items-start justify-between">
              <div>
                <CardTitle className="font-display text-[17px]">Opportunity summary</CardTitle>
                <CardDescription>Deals in play · sum ₹{data.opportunities.reduce((a, o) => a + o.value, 0)} L pipeline</CardDescription>
              </div>
              <Button variant="ghost" size="sm" onClick={() => nav("/opportunity-hub")} className="text-xs">Open hub</Button>
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {data.opportunities.map((o) => (
                <div key={o.id} className="p-4 rounded-lg border border-border bg-card hover-lift">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-[13px] font-semibold text-foreground">{o.title}</div>
                      <div className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground mt-1">{o.stage}</div>
                    </div>
                    <Badge className="bg-primary/10 text-primary hover:bg-primary/10">₹{o.value}L</Badge>
                  </div>
                  <div className="mt-4">
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1.5">
                      <span>Probability</span><span className="font-medium text-foreground">{o.probability}%</span>
                    </div>
                    <Progress value={o.probability} className="h-1.5" />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ------------------ Part 2: Vendor performance + Company Health + System status ------------------ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {data.vendor_perf && data.vendor_perf.length > 0 && (
          <Card data-testid="vendor-performance" className="lg:col-span-2 border-border">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="font-display text-[17px]">Vendor performance</CardTitle>
                  <CardDescription>Top vendors by fleet size and rating</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => nav("/marketplace")} className="text-xs">Open marketplace</Button>
              </div>
            </CardHeader>
            <CardContent className="pt-2">
              <Table>
                <TableHeader>
                  <TableRow className="border-border hover:bg-transparent">
                    <TableHead className="text-[11px] uppercase tracking-[0.1em]">Vendor</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em]">City</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Vehicles</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Rating</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.vendor_perf.map((v) => (
                    <TableRow key={v.vendor} className="border-border">
                      <TableCell className="font-medium">{v.vendor}</TableCell>
                      <TableCell className="text-muted-foreground">{v.city}</TableCell>
                      <TableCell className="text-right">{v.vehicles}</TableCell>
                      <TableCell className="text-right">
                        <span className="inline-flex items-center gap-1 text-warning font-medium">
                          <Star className="h-3 w-3 fill-warning" /> {v.rating}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        {data.company_health && (
          <Card data-testid="company-health" className="border-border">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="font-display text-[17px]">Company health</CardTitle>
                  <CardDescription>Composite operational score</CardDescription>
                </div>
                <Shield className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent className="pt-2">
              <div className="flex items-baseline gap-2">
                <div className="font-display text-4xl font-semibold text-foreground tracking-tighter">{data.company_health.score}</div>
                <div className="text-xs text-muted-foreground">/ 100</div>
              </div>
              <Progress value={data.company_health.score} className="h-1.5 mt-2" />
              <ul className="mt-4 space-y-2">
                {data.company_health.signals.map((s) => (
                  <li key={s.label} className="flex items-center justify-between text-[12.5px]">
                    <span className="text-muted-foreground">{s.label}</span>
                    <div className="flex items-center gap-2 w-1/2">
                      <Progress value={s.value} className="h-1 flex-1" />
                      <span className="font-medium text-foreground w-8 text-right">{s.value}</span>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="mt-4 pt-3 border-t border-border grid grid-cols-3 gap-2 text-center">
                <div><div className="text-[10px] uppercase text-muted-foreground">KYC</div><div className="text-[13px] font-semibold">{data.company_health.flags.kyc_pending}</div></div>
                <div><div className="text-[10px] uppercase text-muted-foreground">Tickets</div><div className="text-[13px] font-semibold">{data.company_health.flags.open_tickets}</div></div>
                <div><div className="text-[10px] uppercase text-muted-foreground">Leave</div><div className="text-[13px] font-semibold">{data.company_health.flags.pending_leave}</div></div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* ------------------ Part 2: Live system status + Recent notifications ------------------ */}
      <div className={cn("grid grid-cols-1 gap-4", !isEmployeeOrIntern ? "lg:grid-cols-2" : "")}>
        {data.system_status && (
          <Card data-testid="system-status" className="border-border">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="font-display text-[17px]">Live system status</CardTitle>
                  <CardDescription>All services · {data.system_status.overall}</CardDescription>
                </div>
                <Badge className="bg-success/10 text-success hover:bg-success/10">
                  <span className="h-1.5 w-1.5 rounded-full bg-success mr-1.5 inline-block" />Operational
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="pt-2">
              <ul className="space-y-2.5">
                {data.system_status.services.map((s) => (
                  <li key={s.name} className="flex items-center justify-between text-[13px]">
                    <div className="flex items-center gap-2">
                      <Server className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium">{s.name}</span>
                    </div>
                    <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                      <span>{s.uptime}</span>
                      <span className="inline-flex items-center gap-1 text-success">
                        <span className="h-1.5 w-1.5 rounded-full bg-success" />operational
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {data.recent_notifications && data.recent_notifications.length > 0 && (
          <Card data-testid="recent-notifications" className="border-border">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="font-display text-[17px]">Recent notifications</CardTitle>
                  <CardDescription>Latest 5 across the workspace</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => nav("/notifications")} className="text-xs">Open inbox</Button>
              </div>
            </CardHeader>
            <CardContent className="pt-2">
              <ul className="space-y-3">
                {data.recent_notifications.slice(0, 5).map((n) => {
                  const Icon = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle }[n.kind] || Info;
                  const kindClass = { info: "bg-info/10 text-info", success: "bg-success/10 text-success", warning: "bg-warning/10 text-warning", error: "bg-destructive/10 text-destructive" }[n.kind] || "bg-info/10 text-info";
                  return (
                    <li key={n.id} className="flex items-start gap-3">
                      <div className={cn("h-8 w-8 rounded-md flex items-center justify-center shrink-0", kindClass)}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2">
                          <div className="text-[13px] font-medium truncate">{n.title}</div>
                          {!n.read && <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />}
                        </div>
                        <p className="text-[12px] text-muted-foreground line-clamp-1 mt-0.5">{n.body}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
