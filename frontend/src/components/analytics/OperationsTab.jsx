import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import {
  AlarmClock, CalendarDays, CheckCircle2, ClipboardList, Palmtree, Target, Timer, TrendingUp, UserCheck,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import {
  AXIS_TICK, GRID_STROKE, ChartCard, ChartTooltip, ErrorPanel, ExportButton, KpiGrid, Legend,
  formatNumber, formatPct, titleCase, useAnalyticsData,
} from "./shared";

const KPI_ICONS = {
  tasks_created: ClipboardList, tasks_completed: CheckCircle2, cycle: Timer, overdue: AlarmClock,
  pipeline: Target, win_rate: TrendingUp, attendance: UserCheck, leave: Palmtree,
};

function lakhs(v) {
  return `₹${(Number(v) || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
}

function RankList({ rows, labelKey, valueKey, sub, format = formatNumber, max, tone = "bg-primary" }) {
  const top = max ?? Math.max(1, ...rows.map((r) => r[valueKey] || 0));
  return (
    <div className="space-y-3">
      {rows.map((r) => {
        const v = r[valueKey];
        const width = v === null || v === undefined ? 0 : Math.min(100, (v / top) * 100);
        return (
          <div key={r[labelKey]}>
            <div className="flex items-baseline justify-between gap-2 text-[13px]">
              <span className="font-medium text-foreground truncate">{titleCase(r[labelKey])}</span>
              <span className="tabular-nums text-foreground">{format(v)}</span>
            </div>
            <div className="mt-1 h-2 rounded-full bg-muted overflow-hidden">
              <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
            </div>
            {sub && <div className="text-[11px] text-muted-foreground mt-1 truncate">{sub(r)}</div>}
          </div>
        );
      })}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground mb-2">{title}</div>
      {children}
    </div>
  );
}

export default function OperationsTab({ range, department, canExport }) {
  const params = { days: range.days, from: range.from, to: range.to, ...(department ? { department } : {}) };
  const { data, loading, error, reload } = useAnalyticsData("/analytics/operations", params);
  const exp = (dataset) => <ExportButton dataset={dataset} params={params} canExport={canExport} />;

  if (error && !data) {
    return <Card className="border-border"><ErrorPanel error={error} onRetry={reload} /></Card>;
  }

  const t = data?.tasks;
  const o = data?.opportunities;
  const a = data?.attendance;
  const l = data?.leave;
  const c = data?.calendar;

  const kpis = data ? [
    { key: "tasks_created", label: "Tasks created", value: t.created, format: "number" },
    { key: "tasks_completed", label: "Tasks completed", value: t.completed, format: "number" },
    { key: "cycle", label: "Avg cycle time", value: t.avg_cycle_days === null ? "—" : `${t.avg_cycle_days} d`, format: "raw", hint: "created → completed" },
    { key: "overdue", label: "Overdue now", value: t.overdue_total, format: "number", hint: "open tasks past due" },
    { key: "pipeline", label: "Open pipeline", value: lakhs(o.open_value_lakhs), format: "raw", hint: `${formatNumber(o.open_count)} open opportunities` },
    { key: "win_rate", label: "Win rate", value: o.win_rate, format: "pct", hint: `${o.won} won · ${o.lost} lost in range` },
    { key: "attendance", label: "Attendance rate", value: a.rate, format: "pct", hint: "present + WFH + ½ half-days" },
    { key: "leave", label: "Leave taken", value: `${formatNumber(l.days)} d`, format: "raw", hint: `${formatNumber(l.requests)} approved requests` },
  ] : null;

  const taskSeries = t?.series || [];
  const noTasks = !taskSeries.some((s) => s.created || s.completed);
  const calSeries = c?.series || [];
  const stageRows = (o?.pipeline || []).filter((p) => p.count);

  return (
    <div className="space-y-4 sm:space-y-6">
      {data?.scope?.department && (
        <div className="text-xs text-muted-foreground -mb-2">
          Showing <span className="font-medium text-foreground">{data.scope.department}</span> department
          {data.scope.locked ? " · Managers see their own department only" : ""}
        </div>
      )}
      <KpiGrid kpis={kpis} loading={loading && !data} icons={KPI_ICONS} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard
          className="lg:col-span-2" testId="analytics-tasks-throughput"
          title="Task throughput" description={`Created vs completed per ${t?.granularity || "day"} · by assignee`}
          actions={exp("tasks")} loading={loading && !data}
          empty={noTasks} emptyIcon={ClipboardList} emptyTitle="No task activity in this range"
        >
          <div className="h-[240px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={taskSeries} margin={{ top: 10, right: 8, left: -18, bottom: 0 }} barGap={2}>
                <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={12} />
                <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted) / 0.5)" }} />
                <Bar dataKey="created" fill="hsl(var(--chart-2))" radius={[4, 4, 0, 0]} maxBarSize={20} />
                <Bar dataKey="completed" fill="hsl(var(--chart-1))" radius={[4, 4, 0, 0]} maxBarSize={20} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2">
            <Legend items={[{ label: "Created", color: "hsl(var(--chart-2))" }, { label: "Completed", color: "hsl(var(--chart-1))" }]} />
          </div>
        </ChartCard>

        <ChartCard
          title="Overdue tasks" description={t ? `Open tasks past their due date · as of ${t.as_of}` : "Open tasks past their due date"}
          actions={exp("overdue")} loading={loading && !data}
          empty={!t?.overdue_total} emptyIcon={AlarmClock} emptyTitle="Nothing overdue" emptyDescription="Every open task is within its due date."
        >
          {t && (
            <div className="space-y-5">
              <Section title="By department">
                <RankList rows={t.overdue_by_department} labelKey="department" valueKey="overdue" tone="bg-destructive" />
              </Section>
              <Section title="By assignee">
                <RankList rows={t.overdue_by_assignee.slice(0, 6)} labelKey="assignee" valueKey="overdue" tone="bg-destructive"
                  sub={(r) => r.department} />
              </Section>
            </div>
          )}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard
          title="Opportunity pipeline" description="Current value by stage · ₹ lakhs"
          actions={exp("pipeline")} loading={loading && !data}
          empty={!stageRows.length} emptyIcon={Target} emptyTitle="No opportunities yet"
        >
          {o && (
            <>
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={stageRows.map((p) => ({ ...p, label: titleCase(p.stage) }))} layout="vertical" margin={{ top: 0, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} width={82} />
                    <Tooltip
                      content={<ChartTooltip names={{ value_lakhs: "Value" }} formatters={{ value_lakhs: lakhs }} />}
                      cursor={{ fill: "hsl(var(--muted) / 0.5)" }}
                    />
                    <Bar dataKey="value_lakhs" fill="hsl(var(--chart-1))" radius={[0, 4, 4, 0]} maxBarSize={18} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 text-[11px] text-muted-foreground">
                Win rate {formatPct(o.win_rate)} · decided in range (won ÷ won + lost) · won value {lakhs(o.won_value_lakhs)}
              </div>
            </>
          )}
        </ChartCard>

        <ChartCard
          title="Attendance by department" description="Present + WFH + ½ half-days ÷ working records"
          actions={exp("attendance")} loading={loading && !data}
          empty={!a?.departments?.length} emptyIcon={UserCheck} emptyTitle="No attendance records in this range"
        >
          {a && (
            <RankList rows={a.departments} labelKey="department" valueKey="rate" max={100} format={formatPct}
              sub={(d) => `${formatNumber(d.employees)} people · ${formatNumber(d.absent)} absent · ${formatNumber(d.leave)} on leave`} />
          )}
        </ChartCard>

        <ChartCard
          title="Leave taken" description="Approved leave days falling in this range"
          actions={exp("leave")} loading={loading && !data}
          empty={!l?.days} emptyIcon={Palmtree} emptyTitle="No approved leave in this range"
        >
          {l && (
            <div className="space-y-5">
              <Section title="By type">
                <RankList rows={l.by_kind} labelKey="kind" valueKey="days" format={(v) => `${formatNumber(v)} d`} />
              </Section>
              <Section title="By department">
                <RankList rows={l.by_department} labelKey="department" valueKey="days" format={(v) => `${formatNumber(v)} d`} />
              </Section>
            </div>
          )}
        </ChartCard>
      </div>

      <ChartCard
        title="Calendar load" description={`Events scheduled per ${c?.granularity || "day"} · cancelled excluded`}
        actions={exp("calendar")} loading={loading && !data}
        empty={!c?.total} emptyIcon={CalendarDays} emptyTitle="No events in this range"
      >
        {c && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="h-[220px] lg:col-span-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={calSeries} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={12} />
                  <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted) / 0.5)" }} />
                  <Bar dataKey="events" fill="hsl(var(--chart-2))" radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <Section title="By category">
              <RankList rows={c.by_category} labelKey="category" valueKey="events" tone="bg-info" />
            </Section>
          </div>
        )}
      </ChartCard>

    </div>
  );
}
