import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader, StatCard, EmptyState, StatusPill } from "@/components/module/ModulePrimitives";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Bike, Users, Handshake, Building2, MapPin, Wallet, Tag, ShieldCheck, LifeBuoy, Star,
  Plus, Search, TrendingUp, ArrowUpRight, Loader2,
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, PieChart, Pie, Cell,
} from "recharts";
import { useLiveRefresh } from "@/hooks/useLiveRefresh";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

function inr(n) {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

// Client-side search over a row's values (not its keys, so "city" doesn't match every row).
function rowMatches(row, t) {
  return Object.values(row).some(v => v != null && typeof v !== "object" && String(v).toLowerCase().includes(t));
}

function fmtWhen(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

// 422 details name the offending field by its form label ("Email: value is not a valid email…").
function formError(e, fields = []) {
  const d = e?.response?.data?.detail;
  if (!Array.isArray(d)) return formatApiError(e);
  return d.map(x => {
    const key = Array.isArray(x?.loc) ? x.loc[x.loc.length - 1] : null;
    const label = fields.find(f => f.key === key)?.label || (typeof key === "string" ? key.replace(/_/g, " ") : "");
    return label ? `${label}: ${x.msg}` : x?.msg;
  }).join(" · ");
}

// Booking statuses keep the same colour in every chart, whatever order the API returns them in.
const STATUS_COLORS = {
  pending: "hsl(var(--chart-3))", confirmed: "hsl(var(--chart-2))", active: "hsl(var(--chart-1))",
  completed: "hsl(var(--chart-4))", cancelled: "hsl(var(--chart-5))",
};
const statusColor = (s, i) => STATUS_COLORS[s] || ["hsl(var(--chart-1))","hsl(var(--chart-2))","hsl(var(--chart-3))","hsl(var(--chart-4))","hsl(var(--chart-5))"][i % 5];

const TABS = ["dashboard", "bookings", "customers", "vendors", "vehicles", "cities", "pricing", "coupons", "kyc", "support", "reviews", "analytics"];

function ToolbarRow({ q, setQ, onCreate, placeholder = "Search…" }) {
  return (
    <div className="flex flex-col sm:flex-row gap-2 sm:items-center justify-between mb-4">
      <div className="relative flex-1 max-w-md">
        <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} className="pl-9 h-9" />
      </div>
      {onCreate && (
        <Button onClick={onCreate} size="sm" className="h-9" data-testid="marketplace-create-btn">
          <Plus className="h-4 w-4 mr-1.5" /> New
        </Button>
      )}
    </div>
  );
}

/* -------- Generic CRUD table -------- */
function CrudTable({ endpoint, columns, formFields, title, module, testid, defaults = {}, autoOpenTrigger = 0, onAutoOpened, onChanged, onOpen }) {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(defaults);
  const [editing, setEditing] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function load({ background = false } = {}) {
    try {
      const { data } = await api.get(endpoint);
      setRows(data);
    } catch (e) { if (!background) toast.error(formatApiError(e)); }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [endpoint]);
  useLiveRefresh(load, 60000);

  useEffect(() => {
    if (autoOpenTrigger) {
      create();
      onAutoOpened?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpenTrigger]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return rows;
    return rows.filter(r => rowMatches(r, t));
  }, [rows, q]);

  async function submit() {
    const missing = formFields.find(f => f.required && String(form[f.key] ?? "").trim() === "");
    if (missing) { toast.error(`${missing.label} is required`); return; }
    setSubmitting(true);
    try {
      if (editing) await api.patch(`${endpoint}/${editing.id}`, form);
      else await api.post(endpoint, form);
      toast.success(editing ? `${title} updated` : `${title} created`);
      setOpen(false); setEditing(null); setForm(defaults);
      load(); onChanged?.();
    } catch (e) { toast.error(formError(e, formFields)); } finally { setSubmitting(false); }
  }

  async function remove(row) {
    const label = row[columns[0].key] || title.toLowerCase();
    if (!window.confirm(`Delete ${title.toLowerCase()} "${label}"? This cannot be undone.`)) return;
    try {
      await api.delete(`${endpoint}/${row.id}`);
      toast.success(`${title} deleted`);
      load(); onChanged?.();
    } catch (e) { toast.error(formatApiError(e)); }
  }

  function edit(row) { setEditing(row); setForm({ ...defaults, ...row }); setOpen(true); onOpen?.(); }
  function create() { setEditing(null); setForm(defaults); setOpen(true); onOpen?.(); }

  return (
    <>
      <ToolbarRow q={q} setQ={setQ} onCreate={create} placeholder={`Search ${title.toLowerCase()}…`} />
      <Card className="border-border" data-testid={testid}>
        {filtered.length === 0 ? (
          rows.length > 0
            ? <EmptyState icon={Search} title="No matches" description={`No ${title.toLowerCase()} matches "${q.trim()}".`} />
            : <EmptyState icon={Search} title={`No ${title.toLowerCase()} yet`} description="Add the first one to get started." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map(c => <TableHead key={c.key} className="text-[11px] uppercase tracking-[0.1em]">{c.label}</TableHead>)}
                <TableHead className="w-[140px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(r => (
                <TableRow key={r.id} className="hover:bg-muted/40">
                  {columns.map(c => (
                    <TableCell key={c.key}>{c.render ? c.render(r) : (r[c.key] ?? "—")}</TableCell>
                  ))}
                  <TableCell className="text-right space-x-1">
                    <Button variant="ghost" size="sm" onClick={() => edit(r)} className="h-7 text-xs">Edit</Button>
                    <Button variant="ghost" size="sm" onClick={() => remove(r)} className="h-7 text-xs text-destructive" data-testid={`${testid}-delete-btn`}>Delete</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? `Edit ${title}` : `New ${title}`}</DialogTitle>
            <DialogDescription>Fill in the details below.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {formFields.map(f => (
              <div key={f.key}>
                <Label className="text-[12px]">{f.label}</Label>
                {f.type === "bool" ? (
                  <Select value={form[f.key] === false ? "false" : "true"} onValueChange={(v) => setForm(s => ({ ...s, [f.key]: v === "true" }))} disabled={submitting}>
                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="true">{f.trueLabel || "Active"}</SelectItem>
                      <SelectItem value="false">{f.falseLabel || "Inactive"}</SelectItem>
                    </SelectContent>
                  </Select>
                ) : f.type === "select" ? (
                  <Select value={form[f.key] || ""} onValueChange={(v) => setForm(s => ({ ...s, [f.key]: v }))} disabled={submitting}>
                    <SelectTrigger className="mt-1"><SelectValue placeholder={f.placeholder || "Select…"} /></SelectTrigger>
                    <SelectContent>{f.options.map(o => <SelectItem key={o.value} value={o.value} disabled={o.disabled}>{o.label}</SelectItem>)}</SelectContent>
                  </Select>
                ) : f.type === "textarea" ? (
                  <Textarea rows={3} className="mt-1" value={form[f.key] || ""} onChange={(e) => setForm(s => ({ ...s, [f.key]: e.target.value }))} disabled={submitting} />
                ) : (
                  <Input type={f.type || "text"} className="mt-1" value={form[f.key] ?? ""} disabled={submitting}
                         min={f.min} max={f.max} step={f.step}
                         onChange={(e) => setForm(s => ({ ...s, [f.key]: f.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value }))} />
                )}
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {editing ? "Save changes" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/* -------- Marketplace Dashboard -------- */
function MarketplaceDashboardTab() {
  const [t, setT] = useState(null);
  const [a, setA] = useState(null);
  // Background refreshes are silent; the tab only mounts while it is open, so polling stops elsewhere.
  const load = useCallback(({ background = false } = {}) => {
    api.get("/marketplace/dashboard").then(({ data }) => setT(data.totals)).catch(e => { if (!background) toast.error(formatApiError(e)); });
    api.get("/marketplace/analytics").then(({ data }) => setA(data)).catch(e => { if (!background) toast.error(formatApiError(e)); });
  }, []);
  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load, 30000);
  if (!t) return <div className="text-sm text-muted-foreground">Loading…</div>;
  const kpis = [
    { label: "Vehicles", value: t.vehicles, icon: Bike },
    { label: "Vendors", value: t.vendors, icon: Handshake },
    { label: "Customers", value: t.customers, icon: Users },
    { label: "Cities", value: t.cities, icon: MapPin },
    { label: "Bookings", value: t.bookings, icon: TrendingUp },
    { label: "Active", value: t.active_bookings, icon: ArrowUpRight, tone: "info" },
    { label: "Today", value: t.today_bookings, icon: ArrowUpRight, tone: "success" },
    { label: "Revenue (all-time)", value: inr(t.revenue), sub: "Confirmed, active & completed", icon: Wallet, tone: "success" },
  ];
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {kpis.map(k => <StatCard key={k.label} {...k} />)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-border">
          <CardHeader className="pb-2"><CardTitle className="font-display text-[16px]">Bookings by city</CardTitle></CardHeader>
          <CardContent>
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={a?.by_city || []} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="city" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))" }} />
                  <Bar dataKey="bookings" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} maxBarSize={30} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border">
          <CardHeader className="pb-2"><CardTitle className="font-display text-[16px]">Bookings by status</CardTitle></CardHeader>
          <CardContent>
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={a?.by_status || []} dataKey="count" nameKey="status" innerRadius={55} outerRadius={95} paddingAngle={3}>
                    {(a?.by_status || []).map((s, i) => (
                      <Cell key={s.status || i} fill={statusColor(s.status, i)} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))" }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-wrap gap-2 mt-2">
              {(a?.by_status || []).map(s => (
                <div key={s.status} className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
                  <StatusPill status={s.status} />
                  <span className="font-medium text-foreground">{s.count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      <Card className="border-border">
        <CardHeader className="pb-2"><CardTitle className="font-display text-[16px]">Top vendors</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-[11px] uppercase tracking-[0.1em]">Vendor</TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.1em]">City</TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Vehicles</TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Rating</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(a?.top_vendors || []).map(v => (
                <TableRow key={v.name}>
                  <TableCell className="font-medium">{v.name}</TableCell>
                  <TableCell>{v.city}</TableCell>
                  <TableCell className="text-right">{v.vehicles}</TableCell>
                  <TableCell className="text-right">
                    {v.rating == null ? <span className="text-muted-foreground">—</span>
                      : <span className="inline-flex items-center gap-1 text-warning font-medium"><Star className="h-3 w-3 fill-warning" /> {v.rating}</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------- Analytics Tab -------- */
const TOOLTIP_STYLE = { background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))" };
const AXIS_TICK = { fill: "hsl(var(--muted-foreground))", fontSize: 11 };

function MarketplaceAnalyticsTab() {
  const [a, setA] = useState(null);
  useEffect(() => {
    api.get("/marketplace/analytics").then(({ data }) => setA(data)).catch(e => toast.error(formatApiError(e)));
  }, []);
  const stats = useMemo(() => {
    if (!a) return null;
    const total = a.by_status.reduce((s, x) => s + x.count, 0);
    const of = (st) => a.by_status.find(x => x.status === st)?.count || 0;
    const pct = (n) => (total ? `${Math.round((n / total) * 100)}%` : "—");
    return {
      total,
      revenue: a.by_city.reduce((s, c) => s + (c.revenue || 0), 0),
      completion: pct(of("completed")),
      cancellation: pct(of("cancelled")),
    };
  }, [a]);
  if (!a) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (stats.total === 0) return <Card className="border-border"><EmptyState icon={TrendingUp} title="No bookings yet" description="Analytics appear once bookings come in." /></Card>;
  const kpis = [
    { label: "Bookings", value: stats.total, icon: TrendingUp },
    { label: "Completion rate", value: stats.completion, icon: ArrowUpRight, tone: "success" },
    { label: "Cancellation rate", value: stats.cancellation, icon: ArrowUpRight, tone: "danger" },
    { label: "Revenue · top cities", value: inr(stats.revenue), sub: "Confirmed, active & completed", icon: Wallet, tone: "success" },
  ];
  return (
    <div className="space-y-6" data-testid="mp-analytics">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {kpis.map(k => <StatCard key={k.label} {...k} />)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[16px]">Revenue by city</CardTitle>
            <CardDescription>Confirmed, active and completed bookings</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={a.by_city} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="city" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} tickFormatter={inr} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => inr(v)} />
                  <Bar dataKey="revenue" name="Revenue" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} maxBarSize={30} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[16px]">Bookings by status</CardTitle>
            <CardDescription>All bookings, every status</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={a.by_status} layout="vertical" margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="status" tick={AXIS_TICK} axisLine={false} tickLine={false} width={80} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="count" name="Bookings" radius={[0, 6, 6, 0]} maxBarSize={24}>
                    {a.by_status.map((s, i) => <Cell key={s.status || i} fill={statusColor(s.status, i)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-border">
          <CardHeader className="pb-2"><CardTitle className="font-display text-[16px]">City breakdown</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[11px] uppercase tracking-[0.1em]">City</TableHead>
                  <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Bookings</TableHead>
                  <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Revenue</TableHead>
                  <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Share</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {a.by_city.map(c => (
                  <TableRow key={c.city || "—"}>
                    <TableCell className="font-medium">{c.city || "—"}</TableCell>
                    <TableCell className="text-right">{c.bookings}</TableCell>
                    <TableCell className="text-right">{inr(c.revenue)}</TableCell>
                    <TableCell className="text-right text-muted-foreground">{stats.revenue ? `${Math.round((c.revenue / stats.revenue) * 100)}%` : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card className="border-border">
          <CardHeader className="pb-2"><CardTitle className="font-display text-[16px]">Top vendors by fleet</CardTitle></CardHeader>
          <CardContent>
            {a.top_vendors.length === 0 ? <EmptyState icon={Handshake} title="No vendor fleet yet" /> : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em]">Vendor</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Vehicles</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Rating</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {a.top_vendors.map(v => (
                    <TableRow key={v.name}>
                      <TableCell><div className="font-medium">{v.name}</div><div className="text-[12px] text-muted-foreground">{v.city}</div></TableCell>
                      <TableCell className="text-right">{v.vehicles}</TableCell>
                      <TableCell className="text-right">
                        {v.rating == null ? <span className="text-muted-foreground">No ratings yet</span>
                          : <span className="inline-flex items-center gap-1 text-warning font-medium"><Star className="h-3 w-3 fill-warning" /> {v.rating}</span>}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* -------- Bookings Tab (custom) -------- */
// <input type="datetime-local"> value (local time, minutes precision)
function toLocalInput(d) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function emptyBooking() {
  const now = new Date();
  return {
    customer_id: "",
    vehicle_id: "",
    city: "",
    start_local: toLocalInput(now),
    end_local: toLocalInput(new Date(now.getTime() + 86400000)),
    amount: 399,
    coupon_code: "",
    status: "pending"
  };
}

function BookingsTab({ cityOpts = [], customerOpts = [], vehicleOpts = [], autoOpenTrigger = 0, onAutoOpened, onChanged, onOpen }) {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState(emptyBooking);
  const availableVehicles = vehicleOpts.filter(o => o.status === "available");

  async function load({ background = false } = {}) {
    try { const { data } = await api.get("/marketplace/bookings?limit=200"); setRows(data); }
    catch (e) { if (!background) toast.error(formatApiError(e)); }
  }
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, 60000);

  function openCreate() { setForm(emptyBooking()); setOpen(true); onOpen?.(); }

  useEffect(() => {
    if (autoOpenTrigger) {
      openCreate();
      onAutoOpened?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpenTrigger]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return rows;
    return rows.filter(r => rowMatches(r, t));
  }, [rows, q]);

  async function setStatus(b, status) {
    try { await api.patch(`/marketplace/bookings/${b.id}/status`, { status }); toast.success(`Booking → ${status}`); load(); onChanged?.(); }
    catch (e) { toast.error(formatApiError(e)); }
  }

  async function submitBooking() {
    if (!form.customer_id) { toast.error("Please select a customer"); return; }
    if (!form.vehicle_id) { toast.error("Please select a vehicle"); return; }
    if (!form.city) { toast.error("Please select a city"); return; }
    const start = new Date(form.start_local), end = new Date(form.end_local);
    if (isNaN(start) || isNaN(end)) { toast.error("Please set start and end times"); return; }
    if (end <= start) { toast.error("End must be after start"); return; }
    setSubmitting(true);
    try {
      const { start_local, end_local, coupon_code, ...rest } = form;
      await api.post("/marketplace/bookings", {
        ...rest,
        ...(coupon_code.trim() ? { coupon_code: coupon_code.trim() } : {}),
        start_time: start.toISOString(),
        end_time: end.toISOString(),
      });
      toast.success("New Booking created!");
      setOpen(false);
      setForm(emptyBooking());
      load(); onChanged?.();
    } catch (e) {
      toast.error(formError(e, [{ key: "amount", label: "Amount" }, { key: "coupon_code", label: "Coupon code" }]));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <ToolbarRow q={q} setQ={setQ} onCreate={openCreate} placeholder="Search bookings…" />
      <Card className="border-border" data-testid="marketplace-bookings-table">
        {filtered.length === 0 ? (
          <EmptyState icon={Search} title={rows.length ? "No matches" : "No bookings yet"}
                      description={rows.length ? `No booking matches "${q.trim()}".` : "Create the first booking to get started."} />
        ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-[11px] uppercase tracking-[0.1em]">Customer</TableHead>
              <TableHead className="text-[11px] uppercase tracking-[0.1em]">Vehicle</TableHead>
              <TableHead className="text-[11px] uppercase tracking-[0.1em]">City</TableHead>
              <TableHead className="text-[11px] uppercase tracking-[0.1em] text-right">Amount</TableHead>
              <TableHead className="text-[11px] uppercase tracking-[0.1em]">Status</TableHead>
              <TableHead className="w-[220px] text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map(r => (
              <TableRow key={r.id}>
                <TableCell className="font-medium">{r.customer_name}</TableCell>
                <TableCell className="text-muted-foreground text-[13px]">
                  <div>{r.vehicle_label}</div>
                  {r.start_time && <div className="text-[11.5px]">{fmtWhen(r.start_time)} → {fmtWhen(r.end_time)}</div>}
                </TableCell>
                <TableCell>{r.city}</TableCell>
                <TableCell className="text-right">
                  {inr(r.amount)}
                  {r.discount_amount > 0 && (
                    <div className="text-[11px] text-muted-foreground">{r.coupon_code} · −{inr(r.discount_amount)}</div>
                  )}
                </TableCell>
                <TableCell><StatusPill status={r.status} /></TableCell>
                <TableCell className="text-right space-x-1">
                  {r.status === "pending"   && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setStatus(r, "confirmed")}>Confirm</Button>}
                  {r.status === "confirmed" && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setStatus(r, "active")}>Start</Button>}
                  {r.status === "active"    && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setStatus(r, "completed")}>Complete</Button>}
                  {["pending","confirmed"].includes(r.status) && <Button size="sm" variant="ghost" className="h-7 text-xs text-destructive" onClick={() => setStatus(r, "cancelled")}>Cancel</Button>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        )}
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-display">New Booking</DialogTitle>
            <DialogDescription>Reserve a vehicle for a customer.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-[12px]">Customer</Label>
              <Select value={form.customer_id} onValueChange={(v) => setForm(s => ({ ...s, customer_id: v }))}>
                <SelectTrigger className="mt-1"><SelectValue placeholder="Select customer…" /></SelectTrigger>
                <SelectContent>
                  {customerOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[12px]">Vehicle</Label>
              <Select value={form.vehicle_id}
                      onValueChange={(v) => setForm(s => ({ ...s, vehicle_id: v, city: vehicleOpts.find(o => o.value === v)?.city || s.city }))}>
                <SelectTrigger className="mt-1"><SelectValue placeholder={availableVehicles.length ? "Select vehicle…" : "No vehicles available"} /></SelectTrigger>
                <SelectContent>
                  {availableVehicles.map(o => <SelectItem key={o.value} value={o.value}>{o.label} · {o.city}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[12px]">Start</Label>
                <Input type="datetime-local" className="mt-1" value={form.start_local} onChange={(e) => setForm(s => ({ ...s, start_local: e.target.value }))} data-testid="mp-booking-start" />
              </div>
              <div>
                <Label className="text-[12px]">End</Label>
                <Input type="datetime-local" className="mt-1" value={form.end_local} onChange={(e) => setForm(s => ({ ...s, end_local: e.target.value }))} data-testid="mp-booking-end" />
              </div>
            </div>
            <div>
              <Label className="text-[12px]">City</Label>
              <Select value={form.city} onValueChange={(v) => setForm(s => ({ ...s, city: v }))}>
                <SelectTrigger className="mt-1"><SelectValue placeholder="Select city…" /></SelectTrigger>
                <SelectContent>
                  {cityOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[12px]">{form.coupon_code?.trim() ? "Price before discount (₹)" : "Amount (₹)"}</Label>
              <Input type="number" className="mt-1" value={form.amount} onChange={(e) => setForm(s => ({ ...s, amount: parseFloat(e.target.value) || 0 }))} />
            </div>
            <div>
              <Label className="text-[12px]">Coupon code (optional)</Label>
              <Input className="mt-1 uppercase" maxLength={40} placeholder="e.g. PATNA10" value={form.coupon_code}
                     onChange={(e) => setForm(s => ({ ...s, coupon_code: e.target.value }))} data-testid="booking-coupon-input" />
              {form.coupon_code?.trim() && (
                <p className="text-[11.5px] text-muted-foreground mt-1">The coupon's discount is taken off the price when the booking is saved.</p>
              )}
            </div>
            <div>
              <Label className="text-[12px]">Initial Status</Label>
              <Select value={form.status} onValueChange={(v) => setForm(s => ({ ...s, status: v }))}>
                <SelectTrigger className="mt-1"><SelectValue placeholder="Select status…" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="confirmed">Confirmed</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submitBooking} disabled={submitting}>
              {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Create Booking
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/* -------- KYC Tab -------- */
const KYC_DOC_TYPES = [
  { value: "aadhaar", label: "Aadhaar" }, { value: "pan", label: "PAN" }, { value: "dl", label: "Driving licence" },
  { value: "gst", label: "GST" }, { value: "cin", label: "CIN" }, { value: "other", label: "Other" },
];
const EMPTY_KYC = { subject_type: "customer", subject_id: "", doc_type: "aadhaar", notes: "" };

function KycTab({ vendorOpts = [], customerOpts = [], onChanged, onOpen }) {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState(EMPTY_KYC);
  const subjectOpts = form.subject_type === "vendor" ? vendorOpts : customerOpts;

  async function load({ background = false } = {}) {
    try { const { data } = await api.get("/marketplace/kyc"); setRows(data); }
    catch (e) { if (!background) toast.error(formatApiError(e)); }
  }
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, 60000);
  async function setStatus(id, status) {
    try { await api.patch(`/marketplace/kyc/${id}`, { status }); toast.success(`KYC ${status}`); load(); onChanged?.(); }
    catch (e) { toast.error(formatApiError(e)); }
  }
  function openCreate() { setForm(EMPTY_KYC); setOpen(true); onOpen?.(); }
  async function submit() {
    const subject = subjectOpts.find(o => o.value === form.subject_id);
    if (!subject) { toast.error(`Please select a ${form.subject_type}`); return; }
    setSubmitting(true);
    try {
      await api.post("/marketplace/kyc", { ...form, subject_name: subject.label });
      toast.success("KYC request created");
      setOpen(false); setForm(EMPTY_KYC);
      load();
    } catch (e) { toast.error(formatApiError(e)); } finally { setSubmitting(false); }
  }
  return (
    <>
    <div className="flex justify-end mb-4">
      <Button onClick={openCreate} size="sm" className="h-9" data-testid="mp-kyc-create-btn"><Plus className="h-4 w-4 mr-1.5" /> New KYC request</Button>
    </div>
    <Card className="border-border">
      {rows.length === 0 ? <EmptyState icon={ShieldCheck} title="No KYC requests" /> : (
        <Table>
          <TableHeader><TableRow>
            <TableHead>Subject</TableHead><TableHead>Type</TableHead>
            <TableHead>Document</TableHead><TableHead>Status</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows.map(r => (
              <TableRow key={r.id}>
                <TableCell className="font-medium">{r.subject_name}</TableCell>
                <TableCell className="capitalize">{r.subject_type}</TableCell>
                <TableCell className="uppercase text-[12px]">{r.doc_type}</TableCell>
                <TableCell><StatusPill status={r.status} /></TableCell>
                <TableCell className="text-right space-x-1">
                  {r.status === "pending" && <>
                    <Button size="sm" variant="outline" className="h-7 text-xs text-success border-success/40" onClick={() => setStatus(r.id, "approved")}>Approve</Button>
                    <Button size="sm" variant="outline" className="h-7 text-xs text-destructive border-destructive/40" onClick={() => setStatus(r.id, "rejected")}>Reject</Button>
                  </>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>

    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display">New KYC request</DialogTitle>
          <DialogDescription>Submit a document for verification. Approving it updates the subject's KYC status.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[12px]">Subject type</Label>
            <Select value={form.subject_type} onValueChange={(v) => setForm(s => ({ ...s, subject_type: v, subject_id: "" }))}>
              <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="customer">Customer</SelectItem>
                <SelectItem value="vendor">Vendor</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">{form.subject_type === "vendor" ? "Vendor" : "Customer"}</Label>
            <Select value={form.subject_id} onValueChange={(v) => setForm(s => ({ ...s, subject_id: v }))}>
              <SelectTrigger className="mt-1"><SelectValue placeholder={`Select ${form.subject_type}…`} /></SelectTrigger>
              <SelectContent>{subjectOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">Document</Label>
            <Select value={form.doc_type} onValueChange={(v) => setForm(s => ({ ...s, doc_type: v }))}>
              <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>{KYC_DOC_TYPES.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">Notes</Label>
            <Textarea rows={2} className="mt-1" value={form.notes} onChange={(e) => setForm(s => ({ ...s, notes: e.target.value }))} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
          <Button onClick={submit} disabled={submitting}>
            {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  );
}

/* -------- Support Tab -------- */
const NO_CUSTOMER = "none";
const EMPTY_TICKET = { subject: "", description: "", customer_id: NO_CUSTOMER, priority: "medium" };

function SupportTab({ customerOpts = [], onOpen }) {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState(EMPTY_TICKET);

  async function load({ background = false } = {}) {
    try { const { data } = await api.get("/marketplace/support"); setRows(data); }
    catch (e) { if (!background) toast.error(formatApiError(e)); }
  }
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, 60000);
  async function setStatus(id, status) {
    try { await api.patch(`/marketplace/support/${id}`, { status }); toast.success(`Ticket → ${status}`); load(); }
    catch (e) { toast.error(formatApiError(e)); }
  }
  function openCreate() { setForm(EMPTY_TICKET); setOpen(true); onOpen?.(); }
  async function submit() {
    if (!form.subject.trim() || !form.description.trim()) { toast.error("Subject and description are required"); return; }
    setSubmitting(true);
    try {
      const { customer_id, ...rest } = form;
      await api.post("/marketplace/support", { ...rest, ...(customer_id !== NO_CUSTOMER && { customer_id }) });
      toast.success("Support ticket opened");
      setOpen(false); setForm(EMPTY_TICKET);
      load();
    } catch (e) { toast.error(formatApiError(e)); } finally { setSubmitting(false); }
  }
  return (
    <>
    <div className="flex justify-end mb-4">
      <Button onClick={openCreate} size="sm" className="h-9" data-testid="mp-support-create-btn"><Plus className="h-4 w-4 mr-1.5" /> New support ticket</Button>
    </div>
    <Card className="border-border">
      {rows.length === 0 ? <EmptyState icon={LifeBuoy} title="No support tickets" description="Tickets raised by customers show up here." /> : (
      <Table>
        <TableHeader><TableRow>
          <TableHead>Ticket</TableHead><TableHead>Customer</TableHead>
          <TableHead>Priority</TableHead><TableHead>Status</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.map(r => (
            <TableRow key={r.id}>
              <TableCell><div className="font-medium">{r.subject}</div><div className="text-[12px] text-muted-foreground line-clamp-1">{r.description}</div></TableCell>
              <TableCell>{r.customer_name || "—"}</TableCell>
              <TableCell><StatusPill status={r.priority} /></TableCell>
              <TableCell><StatusPill status={r.status} /></TableCell>
              <TableCell className="text-right space-x-1">
                {r.status === "open" && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setStatus(r.id, "in_progress")}>In progress</Button>}
                {["open", "in_progress"].includes(r.status) && <Button size="sm" variant="outline" className="h-7 text-xs text-success border-success/40" onClick={() => setStatus(r.id, "resolved")}>Resolve</Button>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      )}
    </Card>

    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display">New support ticket</DialogTitle>
          <DialogDescription>Log an issue on behalf of a customer.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[12px]">Subject</Label>
            <Input className="mt-1" value={form.subject} onChange={(e) => setForm(s => ({ ...s, subject: e.target.value }))} />
          </div>
          <div>
            <Label className="text-[12px]">Description</Label>
            <Textarea rows={3} className="mt-1" value={form.description} onChange={(e) => setForm(s => ({ ...s, description: e.target.value }))} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[12px]">Customer</Label>
              <Select value={form.customer_id} onValueChange={(v) => setForm(s => ({ ...s, customer_id: v }))}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CUSTOMER}>No customer</SelectItem>
                  {customerOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[12px]">Priority</Label>
              <Select value={form.priority} onValueChange={(v) => setForm(s => ({ ...s, priority: v }))}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="urgent">Urgent</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
          <Button onClick={submit} disabled={submitting}>
            {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  );
}

/* -------- Main -------- */
export default function Marketplace() {
  const [searchParams, setSearchParams] = useSearchParams();
  // The open tab lives in ?tab= so it survives reloads and deep links; unknown values fall back.
  const tabParam = searchParams.get("tab");
  const activeTab = TABS.includes(tabParam) ? tabParam : "dashboard";
  const setActiveTab = (tab) => setSearchParams(params => {
    const next = new URLSearchParams(params);
    if (tab === "dashboard") next.delete("tab"); else next.set("tab", tab);
    return next;
  }, { replace: true });
  const [bookingCreateTrigger, setBookingCreateTrigger] = useState(0);
  const [vendorCreateTrigger, setVendorCreateTrigger] = useState(0);

  const [cities, setCities] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [vehicles, setVehicles] = useState([]);

  // Dropdown sources; reloaded whenever their data changes or a form opens.
  async function reloadOptions() {
    try {
      const [c, v, cu, ve] = await Promise.all([
        api.get("/marketplace/cities"), api.get("/marketplace/vendors"),
        api.get("/marketplace/customers"), api.get("/marketplace/vehicles"),
      ]);
      setCities(c.data); setVendors(v.data); setCustomers(cu.data); setVehicles(ve.data);
    } catch (e) { toast.error(formatApiError(e)); }
  }
  useEffect(() => { reloadOptions(); }, []);

  // ?create=booking / ?create=vendor open that tab's create dialog once; the trigger is cleared after
  // the dialog opens so revisiting the tab later doesn't reopen it.
  useEffect(() => {
    const createParam = searchParams.get("create");
    const tab = { booking: "bookings", vendor: "vendors" }[createParam];
    if (!createParam) return;
    if (tab === "bookings") setBookingCreateTrigger(t => t + 1);
    if (tab === "vendors") setVendorCreateTrigger(t => t + 1);
    setSearchParams(params => {
      const next = new URLSearchParams(params);
      next.delete("create");
      if (tab) next.set("tab", tab);
      return next;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const cityOpts = cities.map(c => ({ value: c.name, label: c.name }));
  const vendorOpts = vendors.map(v => ({ value: v.id, label: v.name }));
  const customerOpts = customers.map(c => ({ value: c.id, label: c.name }));
  const vehicleOpts = vehicles.map(v => ({ value: v.id, label: `${v.model} (${v.plate})`, city: v.city, status: v.status }));
  const optionHooks = { onChanged: reloadOptions, onOpen: reloadOptions };

  return (
    <div data-testid="marketplace-page">
      <PageHeader
        eyebrow="Module"
        title="Marketplace"
        description="Vehicles, vendors, bookings, customers, pricing, coupons and everything that keeps the WavyGo fleet moving."
        badge="Live"
      />

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="flex flex-wrap h-auto gap-1">
          <TabsTrigger value="dashboard" data-testid="mp-tab-dashboard">Dashboard</TabsTrigger>
          <TabsTrigger value="bookings"  data-testid="mp-tab-bookings">Bookings</TabsTrigger>
          <TabsTrigger value="customers" data-testid="mp-tab-customers">Customers</TabsTrigger>
          <TabsTrigger value="vendors"   data-testid="mp-tab-vendors">Vendors</TabsTrigger>
          <TabsTrigger value="vehicles"  data-testid="mp-tab-vehicles">Vehicles</TabsTrigger>
          <TabsTrigger value="cities"    data-testid="mp-tab-cities">Cities</TabsTrigger>
          <TabsTrigger value="pricing"   data-testid="mp-tab-pricing">Pricing</TabsTrigger>
          <TabsTrigger value="coupons"   data-testid="mp-tab-coupons">Coupons</TabsTrigger>
          <TabsTrigger value="kyc"       data-testid="mp-tab-kyc">KYC</TabsTrigger>
          <TabsTrigger value="support"   data-testid="mp-tab-support">Support</TabsTrigger>
          <TabsTrigger value="reviews"   data-testid="mp-tab-reviews">Reviews</TabsTrigger>
          <TabsTrigger value="analytics" data-testid="mp-tab-analytics">Analytics</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard" className="mt-6"><MarketplaceDashboardTab /></TabsContent>
        <TabsContent value="bookings" className="mt-6">
          <BookingsTab cityOpts={cityOpts} customerOpts={customerOpts} vehicleOpts={vehicleOpts} autoOpenTrigger={bookingCreateTrigger} onAutoOpened={() => setBookingCreateTrigger(0)} {...optionHooks} />
        </TabsContent>

        <TabsContent value="customers" className="mt-6">
          <CrudTable
            title="Customer" module="Marketplace" endpoint="/marketplace/customers" testid="mp-customers-table" {...optionHooks}
            defaults={{ name: "", email: "", phone: "", city: "" }}
            columns={[
              { key: "name", label: "Name" },
              { key: "email", label: "Email" },
              { key: "phone", label: "Phone" },
              { key: "city", label: "City" },
              { key: "kyc_status", label: "KYC", render: r => <StatusPill status={r.kyc_status} /> },
            ]}
            formFields={[
              { key: "name", label: "Name", required: true },
              { key: "email", label: "Email", type: "email", required: true },
              { key: "phone", label: "Phone" },
              { key: "city", label: "City", type: "select", options: cityOpts, required: true },
            ]}
          />
        </TabsContent>

        <TabsContent value="vendors" className="mt-6">
          <CrudTable
            title="Vendor" module="Marketplace" endpoint="/marketplace/vendors" testid="mp-vendors-table"
            autoOpenTrigger={vendorCreateTrigger} onAutoOpened={() => setVendorCreateTrigger(0)} {...optionHooks}
            defaults={{ name: "", contact_name: "", email: "", phone: "", city: "", active: true }}
            columns={[
              { key: "name", label: "Vendor" },
              { key: "contact_name", label: "Contact" },
              { key: "city", label: "City" },
              { key: "rating", label: "Rating", render: r => r.rating == null
                ? <span className="text-[13px] text-muted-foreground">No ratings yet</span>
                : <span className="inline-flex items-center gap-1 font-medium"><Star className="h-3 w-3 fill-warning text-warning" />{r.rating}</span> },
              { key: "kyc_status", label: "KYC", render: r => <StatusPill status={r.kyc_status} /> },
            ]}
            formFields={[
              { key: "name", label: "Vendor name", required: true },
              { key: "contact_name", label: "Contact person" },
              { key: "email", label: "Email", type: "email" },
              { key: "phone", label: "Phone" },
              { key: "city", label: "City", type: "select", options: cityOpts, required: true },
              { key: "active", label: "Status", type: "bool" },
            ]}
          />
        </TabsContent>

        <TabsContent value="vehicles" className="mt-6">
          <CrudTable
            title="Vehicle" module="Marketplace" endpoint="/marketplace/vehicles" testid="mp-vehicles-table" {...optionHooks}
            defaults={{ model: "", kind: "scooter", plate: "", city: "", hourly_rate: 40, daily_rate: 399, status: "available" }}
            columns={[
              { key: "model", label: "Model" },
              { key: "plate", label: "Plate" },
              { key: "kind", label: "Type", render: r => <span className="capitalize">{r.kind}</span> },
              { key: "city", label: "City" },
              { key: "daily_rate", label: "Daily", render: r => inr(r.daily_rate) },
              { key: "status", label: "Status", render: r => <StatusPill status={r.status} /> },
            ]}
            formFields={[
              { key: "model", label: "Model", required: true },
              { key: "plate", label: "Plate", required: true },
              { key: "kind", label: "Type", type: "select", options: [{value:"bike",label:"Bike"},{value:"scooter",label:"Scooter"},{value:"ebike",label:"E-Bike"}] },
              { key: "vendor_id", label: "Vendor", type: "select", options: vendorOpts },
              { key: "city", label: "City", type: "select", options: cityOpts, required: true },
              { key: "hourly_rate", label: "Hourly rate ₹", type: "number", min: 0 },
              { key: "daily_rate", label: "Daily rate ₹", type: "number", min: 0 },
              // "Booked" is set by bookings, not by hand.
              { key: "status", label: "Status", type: "select", options: [{value:"available",label:"Available"},{value:"booked",label:"Booked (set by bookings)",disabled:true},{value:"maintenance",label:"Maintenance"},{value:"retired",label:"Retired"}] },
            ]}
          />
        </TabsContent>

        <TabsContent value="cities" className="mt-6">
          <CrudTable
            title="City" module="Marketplace" endpoint="/marketplace/cities" testid="mp-cities-table" {...optionHooks}
            defaults={{ name: "", state: "Bihar", status: "active" }}
            columns={[
              { key: "name", label: "City" },
              { key: "state", label: "State" },
              { key: "status", label: "Status", render: r => <StatusPill status={r.status} /> },
            ]}
            formFields={[
              { key: "name", label: "City name", required: true },
              { key: "state", label: "State", required: true },
              { key: "status", label: "Status", type: "select", options: [{value:"active",label:"Active"},{value:"paused",label:"Paused"},{value:"planned",label:"Planned"}] },
            ]}
          />
        </TabsContent>

        <TabsContent value="pricing" className="mt-6">
          <CrudTable
            title="Pricing plan" module="Marketplace" endpoint="/marketplace/pricing" testid="mp-pricing-table" onOpen={reloadOptions}
            defaults={{ name: "", city: "", hourly: 40, daily: 399, weekly: 1999, monthly: 6499, active: true }}
            columns={[
              { key: "name", label: "Plan" },
              { key: "city", label: "City" },
              { key: "hourly", label: "Hourly", render: r => inr(r.hourly) },
              { key: "daily", label: "Daily", render: r => inr(r.daily) },
              { key: "weekly", label: "Weekly", render: r => inr(r.weekly) },
              { key: "monthly", label: "Monthly", render: r => inr(r.monthly) },
            ]}
            formFields={[
              { key: "name", label: "Plan name", required: true },
              { key: "city", label: "City", type: "select", options: cityOpts, required: true },
              { key: "hourly", label: "Hourly ₹", type: "number", min: 0 },
              { key: "daily", label: "Daily ₹", type: "number", min: 0 },
              { key: "weekly", label: "Weekly ₹", type: "number", min: 0 },
              { key: "monthly", label: "Monthly ₹", type: "number", min: 0 },
              { key: "active", label: "Status", type: "bool" },
            ]}
          />
        </TabsContent>

        <TabsContent value="coupons" className="mt-6">
          <CrudTable
            title="Coupon" module="Marketplace" endpoint="/marketplace/coupons" testid="mp-coupons-table"
            defaults={{ code: "", discount_pct: 10, usage_limit: 100, active: true }}
            columns={[
              { key: "code", label: "Code", render: r => <span className="font-mono font-semibold">{r.code}</span> },
              { key: "discount_pct", label: "Discount", render: r => `${r.discount_pct}%` },
              { key: "used_count", label: "Used", render: r => `${r.used_count ?? 0} / ${r.usage_limit ? r.usage_limit : "∞"}` },
              { key: "valid_till", label: "Valid", render: r => (r.valid_from || r.valid_till)
                ? <span className="text-[13px]">{r.valid_from || "…"} → {r.valid_till || "…"}</span>
                : <span className="text-[13px] text-muted-foreground">Always</span> },
              { key: "active", label: "Active", render: r => <StatusPill status={r.active ? "active" : "paused"} /> },
            ]}
            formFields={[
              { key: "code", label: "Coupon code", required: true },
              { key: "discount_pct", label: "Discount %", type: "number", min: 1, max: 100 },
              { key: "usage_limit", label: "Usage limit (0 = unlimited)", type: "number", min: 0, step: 1 },
              { key: "valid_from", label: "Valid from (optional)", type: "date" },
              { key: "valid_till", label: "Valid till (optional)", type: "date" },
              { key: "active", label: "Status", type: "bool" },
            ]}
          />
        </TabsContent>

        <TabsContent value="kyc" className="mt-6"><KycTab vendorOpts={vendorOpts} customerOpts={customerOpts} {...optionHooks} /></TabsContent>
        <TabsContent value="support" className="mt-6"><SupportTab customerOpts={customerOpts} onOpen={reloadOptions} /></TabsContent>

        <TabsContent value="reviews" className="mt-6">
          <CrudTable
            title="Review" module="Marketplace" endpoint="/marketplace/reviews" testid="mp-reviews-table" {...optionHooks}
            defaults={{ customer_name: "", vendor_id: "", rating: 5, comment: "" }}
            columns={[
              { key: "customer_name", label: "Customer" },
              { key: "vendor_name", label: "Vendor", render: r => r.vendor_name || "—" },
              { key: "rating", label: "Rating", render: r => <span className="inline-flex items-center gap-1 font-medium"><Star className="h-3 w-3 fill-warning text-warning" />{r.rating}</span> },
              { key: "comment", label: "Comment", render: r => <span className="text-[13px] text-muted-foreground line-clamp-1">{r.comment}</span> },
            ]}
            formFields={[
              { key: "customer_name", label: "Customer name", required: true },
              // Picked by id so the review always counts towards that vendor's rating.
              { key: "vendor_id", label: "Vendor", type: "select", options: vendorOpts, required: true },
              { key: "rating", label: "Rating (1-5)", type: "number", min: 1, max: 5, step: 0.5 },
              { key: "comment", label: "Comment", type: "textarea" },
            ]}
          />
        </TabsContent>

        <TabsContent value="analytics" className="mt-6"><MarketplaceAnalyticsTab /></TabsContent>
      </Tabs>
    </div>
  );
}
