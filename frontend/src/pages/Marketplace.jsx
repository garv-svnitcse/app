import { useEffect, useMemo, useState } from "react";
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
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

function inr(n) {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return `₹${v.toLocaleString("en-IN")}`;
}

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
function CrudTable({ endpoint, columns, formFields, title, module, testid, defaults = {}, autoOpenTrigger = 0 }) {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(defaults);
  const [editing, setEditing] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    try {
      const { data } = await api.get(endpoint);
      setRows(data);
    } catch (e) { toast.error(formatApiError(e)); }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [endpoint]);

  useEffect(() => {
    if (autoOpenTrigger) {
      create();
    }
  }, [autoOpenTrigger]);

  const filtered = useMemo(() => {
    if (!q) return rows;
    const t = q.toLowerCase();
    return rows.filter(r => JSON.stringify(r).toLowerCase().includes(t));
  }, [rows, q]);

  async function submit() {
    setSubmitting(true);
    try {
      if (editing) await api.patch(`${endpoint}/${editing.id}`, form);
      else await api.post(endpoint, form);
      toast.success(editing ? `${title} updated` : `${title} created`);
      setOpen(false); setEditing(null); setForm(defaults);
      load();
    } catch (e) { toast.error(formatApiError(e)); } finally { setSubmitting(false); }
  }

  function edit(row) { setEditing(row); setForm({ ...defaults, ...row }); setOpen(true); }
  function create() { setEditing(null); setForm(defaults); setOpen(true); }

  return (
    <>
      <ToolbarRow q={q} setQ={setQ} onCreate={create} placeholder={`Search ${title.toLowerCase()}…`} />
      <Card className="border-border" data-testid={testid}>
        {filtered.length === 0 ? (
          <EmptyState icon={Search} title={`No ${title.toLowerCase()} yet`} description="Add the first one to get started." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map(c => <TableHead key={c.key} className="text-[11px] uppercase tracking-[0.1em]">{c.label}</TableHead>)}
                <TableHead className="w-[80px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(r => (
                <TableRow key={r.id} className="hover:bg-muted/40">
                  {columns.map(c => (
                    <TableCell key={c.key}>{c.render ? c.render(r) : (r[c.key] ?? "—")}</TableCell>
                  ))}
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => edit(r)} className="h-7 text-xs">Edit</Button>
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
                {f.type === "select" ? (
                  <Select value={form[f.key] || ""} onValueChange={(v) => setForm(s => ({ ...s, [f.key]: v }))} disabled={submitting}>
                    <SelectTrigger className="mt-1"><SelectValue placeholder={f.placeholder || "Select…"} /></SelectTrigger>
                    <SelectContent>{f.options.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                  </Select>
                ) : f.type === "textarea" ? (
                  <Textarea rows={3} className="mt-1" value={form[f.key] || ""} onChange={(e) => setForm(s => ({ ...s, [f.key]: e.target.value }))} disabled={submitting} />
                ) : (
                  <Input type={f.type || "text"} className="mt-1" value={form[f.key] ?? ""} disabled={submitting}
                         onChange={(e) => setForm(s => ({ ...s, [f.key]: f.type === "number" ? parseFloat(e.target.value) || 0 : e.target.value }))} />
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
  useEffect(() => {
    api.get("/marketplace/dashboard").then(({ data }) => setT(data.totals));
    api.get("/marketplace/analytics").then(({ data }) => setA(data));
  }, []);
  if (!t) return <div className="text-sm text-muted-foreground">Loading…</div>;
  const kpis = [
    { label: "Vehicles", value: t.vehicles, icon: Bike },
    { label: "Vendors", value: t.vendors, icon: Handshake },
    { label: "Customers", value: t.customers, icon: Users },
    { label: "Cities", value: t.cities, icon: MapPin },
    { label: "Bookings", value: t.bookings, icon: TrendingUp },
    { label: "Active", value: t.active_bookings, icon: ArrowUpRight, tone: "info" },
    { label: "Today", value: t.today_bookings, icon: ArrowUpRight, tone: "success" },
    { label: "Revenue (all-time)", value: inr(t.revenue), icon: Wallet, tone: "success" },
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
                    {(a?.by_status || []).map((_, i) => (
                      <Cell key={i} fill={["hsl(var(--chart-1))","hsl(var(--chart-2))","hsl(var(--chart-3))","hsl(var(--chart-4))","hsl(var(--chart-5))"][i % 5]} />
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
                    <span className="inline-flex items-center gap-1 text-warning font-medium"><Star className="h-3 w-3 fill-warning" /> {v.rating}</span>
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

/* -------- Bookings Tab (custom) -------- */
function BookingsTab({ cityOpts = [], customerOpts = [], vehicleOpts = [], autoOpenTrigger = 0 }) {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    customer_id: "",
    vehicle_id: "",
    city: "",
    start_time: new Date().toISOString(),
    end_time: new Date(Date.now() + 86400000).toISOString(),
    amount: 399,
    status: "pending"
  });

  async function load() { const { data } = await api.get("/marketplace/bookings?limit=200"); setRows(data); }
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (autoOpenTrigger) {
      setOpen(true);
    }
  }, [autoOpenTrigger]);

  const filtered = useMemo(() => {
    if (!q) return rows;
    const t = q.toLowerCase();
    return rows.filter(r => JSON.stringify(r).toLowerCase().includes(t));
  }, [rows, q]);

  async function setStatus(b, status) {
    try { await api.patch(`/marketplace/bookings/${b.id}/status`, { status }); toast.success(`Booking → ${status}`); load(); }
    catch (e) { toast.error(formatApiError(e)); }
  }

  async function submitBooking() {
    if (!form.customer_id) { toast.error("Please select a customer"); return; }
    if (!form.vehicle_id) { toast.error("Please select a vehicle"); return; }
    if (!form.city) { toast.error("Please select a city"); return; }
    setSubmitting(true);
    try {
      await api.post("/marketplace/bookings", form);
      toast.success("New Booking created!");
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <ToolbarRow q={q} setQ={setQ} onCreate={() => setOpen(true)} placeholder="Search bookings…" />
      <Card className="border-border" data-testid="marketplace-bookings-table">
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
                <TableCell className="text-muted-foreground text-[13px]">{r.vehicle_label}</TableCell>
                <TableCell>{r.city}</TableCell>
                <TableCell className="text-right">{inr(r.amount)}</TableCell>
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
              <Select value={form.vehicle_id} onValueChange={(v) => setForm(s => ({ ...s, vehicle_id: v }))}>
                <SelectTrigger className="mt-1"><SelectValue placeholder="Select vehicle…" /></SelectTrigger>
                <SelectContent>
                  {vehicleOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
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
              <Label className="text-[12px]">Amount (₹)</Label>
              <Input type="number" className="mt-1" value={form.amount} onChange={(e) => setForm(s => ({ ...s, amount: parseFloat(e.target.value) || 0 }))} />
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
function KycTab() {
  const [rows, setRows] = useState([]);
  async function load() { const { data } = await api.get("/marketplace/kyc"); setRows(data); }
  useEffect(() => { load(); }, []);
  async function setStatus(id, status) {
    try { await api.patch(`/marketplace/kyc/${id}`, { status }); toast.success(`KYC ${status}`); load(); }
    catch (e) { toast.error(formatApiError(e)); }
  }
  return (
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
  );
}

/* -------- Support Tab -------- */
function SupportTab() {
  const [rows, setRows] = useState([]);
  async function load() { const { data } = await api.get("/marketplace/support"); setRows(data); }
  useEffect(() => { load(); }, []);
  async function setStatus(id, status) {
    try { await api.patch(`/marketplace/support/${id}`, { status }); toast.success(`Ticket → ${status}`); load(); }
    catch (e) { toast.error(formatApiError(e)); }
  }
  return (
    <Card className="border-border">
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
                {r.status !== "resolved" && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setStatus(r.id, "in_progress")}>In progress</Button>}
                {r.status !== "resolved" && <Button size="sm" variant="outline" className="h-7 text-xs text-success border-success/40" onClick={() => setStatus(r.id, "resolved")}>Resolve</Button>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

/* -------- Main -------- */
export default function Marketplace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState("dashboard");
  const [bookingCreateTrigger, setBookingCreateTrigger] = useState(0);
  const [vendorCreateTrigger, setVendorCreateTrigger] = useState(0);

  const [cities, setCities] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [vehicles, setVehicles] = useState([]);

  useEffect(() => {
    api.get("/marketplace/cities").then(({ data }) => setCities(data));
    api.get("/marketplace/vendors").then(({ data }) => setVendors(data));
    api.get("/marketplace/customers").then(({ data }) => setCustomers(data));
    api.get("/marketplace/vehicles").then(({ data }) => setVehicles(data));
  }, []);

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (tabParam) {
      setActiveTab(tabParam);
    }
    const createParam = searchParams.get("create");
    if (createParam === "booking") {
      setActiveTab("bookings");
      setBookingCreateTrigger(t => t + 1);
      setSearchParams(params => { params.delete("create"); return params; }, { replace: true });
    } else if (createParam === "vendor") {
      setActiveTab("vendors");
      setVendorCreateTrigger(t => t + 1);
      setSearchParams(params => { params.delete("create"); return params; }, { replace: true });
    }
  }, [searchParams]);

  const cityOpts = cities.map(c => ({ value: c.name, label: c.name }));
  const vendorOpts = vendors.map(v => ({ value: v.id, label: v.name }));
  const customerOpts = customers.map(c => ({ value: c.id, label: c.name }));
  const vehicleOpts = vehicles.map(v => ({ value: v.id, label: `${v.model} (${v.plate})` }));

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
          <BookingsTab cityOpts={cityOpts} customerOpts={customerOpts} vehicleOpts={vehicleOpts} autoOpenTrigger={bookingCreateTrigger} />
        </TabsContent>

        <TabsContent value="customers" className="mt-6">
          <CrudTable
            title="Customer" module="Marketplace" endpoint="/marketplace/customers" testid="mp-customers-table"
            defaults={{ name: "", email: "", phone: "", city: "", kyc_status: "pending" }}
            columns={[
              { key: "name", label: "Name" },
              { key: "email", label: "Email" },
              { key: "phone", label: "Phone" },
              { key: "city", label: "City" },
              { key: "kyc_status", label: "KYC", render: r => <StatusPill status={r.kyc_status} /> },
            ]}
            formFields={[
              { key: "name", label: "Name" },
              { key: "email", label: "Email", type: "email" },
              { key: "phone", label: "Phone" },
              { key: "city", label: "City", type: "select", options: cityOpts },
              { key: "kyc_status", label: "KYC status", type: "select", options: [{value:"pending",label:"Pending"},{value:"approved",label:"Approved"},{value:"rejected",label:"Rejected"}] },
            ]}
          />
        </TabsContent>

        <TabsContent value="vendors" className="mt-6">
          <CrudTable
            title="Vendor" module="Marketplace" endpoint="/marketplace/vendors" testid="mp-vendors-table"
            autoOpenTrigger={vendorCreateTrigger}
            defaults={{ name: "", contact_name: "", email: "", phone: "", city: "", kyc_status: "pending", rating: 4.5, active: true }}
            columns={[
              { key: "name", label: "Vendor" },
              { key: "contact_name", label: "Contact" },
              { key: "city", label: "City" },
              { key: "rating", label: "Rating", render: r => <span className="inline-flex items-center gap-1 font-medium"><Star className="h-3 w-3 fill-warning text-warning" />{r.rating}</span> },
              { key: "kyc_status", label: "KYC", render: r => <StatusPill status={r.kyc_status} /> },
            ]}
            formFields={[
              { key: "name", label: "Vendor name" },
              { key: "contact_name", label: "Contact person" },
              { key: "email", label: "Email", type: "email" },
              { key: "phone", label: "Phone" },
              { key: "city", label: "City", type: "select", options: cityOpts },
              { key: "rating", label: "Rating (1-5)", type: "number" },
            ]}
          />
        </TabsContent>

        <TabsContent value="vehicles" className="mt-6">
          <CrudTable
            title="Vehicle" module="Marketplace" endpoint="/marketplace/vehicles" testid="mp-vehicles-table"
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
              { key: "model", label: "Model" },
              { key: "plate", label: "Plate" },
              { key: "kind", label: "Type", type: "select", options: [{value:"bike",label:"Bike"},{value:"scooter",label:"Scooter"},{value:"ebike",label:"E-Bike"}] },
              { key: "vendor_id", label: "Vendor", type: "select", options: vendorOpts },
              { key: "city", label: "City", type: "select", options: cityOpts },
              { key: "hourly_rate", label: "Hourly rate", type: "number" },
              { key: "daily_rate", label: "Daily rate", type: "number" },
              { key: "status", label: "Status", type: "select", options: [{value:"available",label:"Available"},{value:"booked",label:"Booked"},{value:"maintenance",label:"Maintenance"},{value:"retired",label:"Retired"}] },
            ]}
          />
        </TabsContent>

        <TabsContent value="cities" className="mt-6">
          <CrudTable
            title="City" module="Marketplace" endpoint="/marketplace/cities" testid="mp-cities-table"
            defaults={{ name: "", state: "Bihar", status: "active" }}
            columns={[
              { key: "name", label: "City" },
              { key: "state", label: "State" },
              { key: "status", label: "Status", render: r => <StatusPill status={r.status} /> },
            ]}
            formFields={[
              { key: "name", label: "City name" },
              { key: "state", label: "State" },
              { key: "status", label: "Status", type: "select", options: [{value:"active",label:"Active"},{value:"paused",label:"Paused"},{value:"planned",label:"Planned"}] },
            ]}
          />
        </TabsContent>

        <TabsContent value="pricing" className="mt-6">
          <CrudTable
            title="Pricing plan" module="Marketplace" endpoint="/marketplace/pricing" testid="mp-pricing-table"
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
              { key: "name", label: "Plan name" },
              { key: "city", label: "City", type: "select", options: cityOpts },
              { key: "hourly", label: "Hourly ₹", type: "number" },
              { key: "daily", label: "Daily ₹", type: "number" },
              { key: "weekly", label: "Weekly ₹", type: "number" },
              { key: "monthly", label: "Monthly ₹", type: "number" },
            ]}
          />
        </TabsContent>

        <TabsContent value="coupons" className="mt-6">
          <CrudTable
            title="Coupon" module="Marketplace" endpoint="/marketplace/coupons" testid="mp-coupons-table"
            defaults={{ code: "", discount_pct: 10, usage_limit: 100, used_count: 0, active: true }}
            columns={[
              { key: "code", label: "Code", render: r => <span className="font-mono font-semibold">{r.code}</span> },
              { key: "discount_pct", label: "Discount", render: r => `${r.discount_pct}%` },
              { key: "used_count", label: "Used", render: r => `${r.used_count} / ${r.usage_limit}` },
              { key: "active", label: "Active", render: r => <StatusPill status={r.active ? "active" : "paused"} /> },
            ]}
            formFields={[
              { key: "code", label: "Coupon code" },
              { key: "discount_pct", label: "Discount %", type: "number" },
              { key: "usage_limit", label: "Usage limit", type: "number" },
            ]}
          />
        </TabsContent>

        <TabsContent value="kyc" className="mt-6"><KycTab /></TabsContent>
        <TabsContent value="support" className="mt-6"><SupportTab /></TabsContent>

        <TabsContent value="reviews" className="mt-6">
          <CrudTable
            title="Review" module="Marketplace" endpoint="/marketplace/reviews" testid="mp-reviews-table"
            defaults={{ customer_name: "", vendor_name: "", rating: 5, comment: "" }}
            columns={[
              { key: "customer_name", label: "Customer" },
              { key: "vendor_name", label: "Vendor" },
              { key: "rating", label: "Rating", render: r => <span className="inline-flex items-center gap-1 font-medium"><Star className="h-3 w-3 fill-warning text-warning" />{r.rating}</span> },
              { key: "comment", label: "Comment", render: r => <span className="text-[13px] text-muted-foreground line-clamp-1">{r.comment}</span> },
            ]}
            formFields={[
              { key: "customer_name", label: "Customer name" },
              { key: "vendor_name", label: "Vendor name" },
              { key: "rating", label: "Rating (1-5)", type: "number" },
              { key: "comment", label: "Comment", type: "textarea" },
            ]}
          />
        </TabsContent>

        <TabsContent value="analytics" className="mt-6"><MarketplaceDashboardTab /></TabsContent>
      </Tabs>
    </div>
  );
}
