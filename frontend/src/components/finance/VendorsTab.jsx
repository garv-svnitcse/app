import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Building2, Plus, Search, Loader2, Pencil, Trash2, Receipt, Mail, Phone, MapPin, User, Link2, IndianRupee,
  Clock, AlertTriangle, Users, ArrowRight, History, FileText, ArrowUp, ArrowDown, ArrowUpDown,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { EmptyState, StatCard, StatusPill } from "@/components/module/ModulePrimitives";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import {
  inr, formatDate, useFinanceResource, LoadError, TableSkeleton, SkeletonBlocks, TH, VENDOR_CATEGORIES,
  categoryLabel, BillStatus,
} from "@/components/finance/financeShared";
import { BillDialog, PayBillDialog } from "@/components/finance/BillsTab";
import VendorStatementPanel from "@/components/finance/VendorStatement";

const EMPTY = {
  name: "", contact_person: "", email: "", phone: "", tax_id: "", category: "other", address: "", notes: "",
  status: "active", payment_terms_days: "", marketplace_vendor_id: "",
};

/* -------- Create / edit vendor -------- */
function VendorDialog({ open, onOpenChange, vendor, onDone }) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [mpVendors, setMpVendors] = useState(null);
  const editing = !!vendor;

  useEffect(() => {
    if (!open) return;
    setForm(vendor ? Object.fromEntries(Object.keys(EMPTY).map((k) => [k, vendor[k] == null ? "" : String(vendor[k])])) : EMPTY);
    api.get("/finance/vendors/marketplace-options").then(({ data }) => setMpVendors(data)).catch(() => setMpVendors([]));
  }, [open, vendor]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target ? e.target.value : e }));
  const linkable = (mpVendors || []).filter((m) => !m.finance_vendor_id || m.finance_vendor_id === vendor?.id);
  const valid = form.name.trim().length >= 2;

  async function submit() {
    setBusy(true);
    const body = { ...form, payment_terms_days: form.payment_terms_days === "" ? null : Number(form.payment_terms_days) };
    try {
      const { data } = editing ? await api.put(`/finance/vendors/${vendor.id}`, body) : await api.post("/finance/vendors", body);
      toast.success(editing ? "Vendor updated" : `${data.name} added`);
      onOpenChange(false); onDone?.(data);
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display">{editing ? "Edit vendor" : "Add vendor"}</DialogTitle>
          <DialogDescription>Suppliers and payees WavyGo pays: workshops, insurers, agencies, landlords, fleet partners.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <Label className="text-[12px]">Vendor name</Label>
            <Input className="mt-1" maxLength={120} value={form.name} onChange={set("name")} disabled={busy} data-testid="finance-vendor-name" />
          </div>
          <div>
            <Label className="text-[12px]">Contact person</Label>
            <Input className="mt-1" maxLength={120} value={form.contact_person} onChange={set("contact_person")} disabled={busy} />
          </div>
          <div>
            <Label className="text-[12px]">Category</Label>
            <Select value={form.category} onValueChange={set("category")} disabled={busy}>
              <SelectTrigger className="mt-1" data-testid="finance-vendor-category"><SelectValue /></SelectTrigger>
              <SelectContent>{VENDOR_CATEGORIES.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">Email</Label>
            <Input type="email" className="mt-1" maxLength={200} value={form.email} onChange={set("email")} disabled={busy} />
          </div>
          <div>
            <Label className="text-[12px]">Phone</Label>
            <Input className="mt-1" maxLength={20} value={form.phone} onChange={set("phone")} disabled={busy} />
          </div>
          <div>
            <Label className="text-[12px]">GSTIN / tax id</Label>
            <Input className="mt-1 uppercase" maxLength={20} value={form.tax_id} onChange={set("tax_id")} disabled={busy} placeholder="10ABCDE1234F1Z5" />
          </div>
          <div>
            <Label className="text-[12px]">Payment terms (days)</Label>
            <Input type="number" min="0" max="365" className="mt-1" value={form.payment_terms_days} onChange={set("payment_terms_days")} disabled={busy} placeholder="e.g. 30" />
          </div>
          <div className="sm:col-span-2">
            <Label className="text-[12px]">Address</Label>
            <Textarea className="mt-1" rows={2} maxLength={500} value={form.address} onChange={set("address")} disabled={busy} />
          </div>
          <div>
            <Label className="text-[12px]">Status</Label>
            <Select value={form.status} onValueChange={set("status")} disabled={busy}>
              <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="inactive">Inactive</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">Marketplace vendor link</Label>
            <Select value={form.marketplace_vendor_id || "none"} onValueChange={(v) => set("marketplace_vendor_id")(v === "none" ? "" : v)} disabled={busy || !mpVendors}>
              <SelectTrigger className="mt-1" data-testid="finance-vendor-mp-link"><SelectValue placeholder="Loading…" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Not linked</SelectItem>
                {linkable.map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <div className="text-[11px] text-muted-foreground mt-1">Linked fleet vendors include booking payouts in spend.</div>
          </div>
          <div className="sm:col-span-2">
            <Label className="text-[12px]">Notes</Label>
            <Textarea className="mt-1" rows={2} maxLength={1000} value={form.notes} onChange={set("notes")} disabled={busy} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !valid} data-testid="finance-vendor-submit">
            {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}{editing ? "Save" : "Add vendor"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function InfoRow({ icon: Icon, children }) {
  if (!children) return null;
  return (
    <div className="flex items-start gap-2 text-[13px] text-foreground/90">
      <Icon className="h-3.5 w-3.5 mt-0.5 text-muted-foreground shrink-0" />
      <span className="break-words min-w-0">{children}</span>
    </div>
  );
}

function Figure({ label, value, sub, tone }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted-foreground">{label}</div>
      <div className={`font-display text-[17px] font-semibold mt-0.5 ${tone || "text-foreground"}`}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

/* -------- Per-vendor detail: totals + transaction history -------- */
function VendorDetail({ vendorId, version, onClose, canManage, vendors, onEdit, onDelete, onViewBills, onChanged }) {
  const [v, setV] = useState(null);
  const [error, setError] = useState(null);
  const [billOpen, setBillOpen] = useState(false);
  const [paying, setPaying] = useState(null);

  useEffect(() => { setV(null); }, [vendorId]);
  // Reloads when another vendor opens and whenever the parent list refreshes (`version`).
  useEffect(() => {
    if (!vendorId) return undefined;
    let live = true;
    setError(null);
    api.get(`/finance/vendors/${vendorId}`)
      .then(({ data }) => { if (live) setV(data); })
      .catch((e) => { if (live) setError(formatApiError(e)); });
    return () => { live = false; };
  }, [vendorId, version]);

  const changed = () => onChanged?.();

  return (
    <Sheet open={!!vendorId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-xl overflow-y-auto" data-testid="finance-vendor-detail">
        {error ? (
          <div className="pt-8 text-center text-sm text-destructive">{error}</div>
        ) : !v ? (
          <div className="pt-8 space-y-3"><SkeletonBlocks count={4} className="h-16" /><TableSkeleton rows={4} /></div>
        ) : (
          <div className="space-y-5">
            <SheetHeader className="text-left">
              <div className="flex items-center gap-2 flex-wrap pr-6">
                <SheetTitle className="font-display text-[20px]">{v.name}</SheetTitle>
                <StatusPill status={v.status} />
              </div>
              <SheetDescription>
                {categoryLabel(v.category)}{v.payment_terms_days != null ? ` · ${v.payment_terms_days} day terms` : ""}
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-1.5">
              <InfoRow icon={User}>{v.contact_person}</InfoRow>
              <InfoRow icon={Mail}>{v.email && <a href={`mailto:${v.email}`} className="hover:text-primary">{v.email}</a>}</InfoRow>
              <InfoRow icon={Phone}>{v.phone && <a href={`tel:${v.phone}`} className="hover:text-primary">{v.phone}</a>}</InfoRow>
              <InfoRow icon={Receipt}>{v.tax_id && <>GSTIN / tax id <span className="font-mono">{v.tax_id}</span></>}</InfoRow>
              <InfoRow icon={MapPin}>{v.address}</InfoRow>
              <InfoRow icon={Link2}>{v.marketplace_vendor_id && <>Linked to marketplace vendor <b>{v.marketplace_vendor_name}</b></>}</InfoRow>
              {v.notes && <div className="text-[12.5px] text-muted-foreground whitespace-pre-wrap border-l-2 border-border pl-3 mt-2">{v.notes}</div>}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Figure label="Total spent" value={inr(v.total_spent)}
                      sub={v.marketplace_vendor_id ? `Bills ${inr(v.bills_paid)} · payouts ${inr(v.payouts_paid)}` : `${v.bills_count} bill(s)`} />
              <Figure label="Outstanding" value={inr(v.outstanding)} tone={v.outstanding ? "text-warning" : undefined}
                      sub={v.marketplace_vendor_id ? `Bills ${inr(v.bills_pending)} · payouts ${inr(v.payouts_pending)}` : `${v.pending_bills} pending bill(s)`} />
              <Figure label="Overdue" value={inr(v.overdue)} tone={v.overdue ? "text-destructive" : undefined} />
              <Figure label="Last bill" value={v.last_bill_date ? formatDate(v.last_bill_date) : "—"} />
            </div>

            <div className="flex flex-wrap gap-2">
              {canManage && v.status === "active" && (
                <Button size="sm" className="h-8" onClick={() => setBillOpen(true)} data-testid="finance-vendor-add-bill">
                  <Plus className="h-3.5 w-3.5 mr-1" />Record bill
                </Button>
              )}
              <Button variant="outline" size="sm" className="h-8" onClick={() => onViewBills(v.id)}>
                All bills<ArrowRight className="h-3.5 w-3.5 ml-1" />
              </Button>
              {canManage && (
                <>
                  <Button variant="outline" size="sm" className="h-8" onClick={() => onEdit(v)}><Pencil className="h-3.5 w-3.5 mr-1" />Edit</Button>
                  <Button variant="outline" size="sm" className="h-8 text-destructive" onClick={() => onDelete(v)}><Trash2 className="h-3.5 w-3.5 mr-1" />Delete</Button>
                </>
              )}
            </div>

            <Tabs defaultValue="history" className="w-full">
              <TabsList className="mb-3">
                <TabsTrigger value="history" data-testid="finance-vendor-tab-history"><History className="h-3.5 w-3.5 mr-1.5" />Transaction history</TabsTrigger>
                <TabsTrigger value="statement" data-testid="finance-vendor-tab-statement"><FileText className="h-3.5 w-3.5 mr-1.5" />Statement</TabsTrigger>
              </TabsList>
              <TabsContent value="history" className="mt-0">
                {v.history.length === 0 ? (
                  <div className="text-[13px] text-muted-foreground border border-dashed border-border rounded-lg p-6 text-center">No bills or payouts yet.</div>
                ) : (
                  <div className="rounded-lg border border-border overflow-hidden">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className={TH}>Date</TableHead>
                          <TableHead className={TH}>Details</TableHead>
                          <TableHead className={`${TH} text-right`}>Amount</TableHead>
                          <TableHead className={TH}>Status</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {v.history.map((h) => (
                          <TableRow key={`${h.type}-${h.id}`} data-testid="finance-vendor-history-row">
                            <TableCell className="whitespace-nowrap text-[12.5px]">{formatDate(h.date)}</TableCell>
                            <TableCell className="text-[12.5px] min-w-[150px]">
                              <div className="text-foreground">{h.description}</div>
                              <div className="text-[11px] text-muted-foreground">
                                {h.type === "payout" ? "Booking payout" : "Bill"}{h.reference ? ` · ${h.reference}` : ""}
                                {h.due_date && h.status === "pending" ? ` · due ${formatDate(h.due_date)}` : ""}
                              </div>
                            </TableCell>
                            <TableCell className="text-right whitespace-nowrap text-[12.5px] font-medium">{inr(h.amount)}</TableCell>
                            <TableCell>
                              <BillStatus status={h.status} overdue={h.overdue} />
                              {canManage && h.type === "bill" && h.status === "pending" && (
                                <button type="button" className="block text-[11px] text-success hover:underline mt-0.5"
                                        onClick={() => setPaying({ id: h.id, vendor_name: v.name, total: h.amount, bill_number: h.reference, bill_date: h.date })}>
                                  Mark paid
                                </button>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </TabsContent>
              <TabsContent value="statement" className="mt-0">
                <VendorStatementPanel vendorId={v.id} version={version} />
              </TabsContent>
            </Tabs>
          </div>
        )}
        <BillDialog open={billOpen} onOpenChange={setBillOpen} defaultVendorId={v?.id} vendors={vendors} onDone={changed} />
        <PayBillDialog bill={paying} onClose={() => setPaying(null)} onDone={changed} />
      </SheetContent>
    </Sheet>
  );
}

/* -------- Sortable list -------- */
const SORT_VALUE = {
  name: (v) => (v.name || "").toLowerCase(),
  total_spent: (v) => v.total_spent || 0,
  outstanding: (v) => v.outstanding || 0,
  overdue: (v) => v.overdue || 0,
  bills_count: (v) => v.bills_count || 0,
  last_bill_date: (v) => v.last_bill_date || "",
};

function sortVendors(items, { key, dir }) {
  const get = SORT_VALUE[key] || SORT_VALUE.name;
  const sign = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const x = get(a), y = get(b);
    if (x < y) return -sign;
    if (x > y) return sign;
    return SORT_VALUE.name(a).localeCompare(SORT_VALUE.name(b));
  });
}

function SortHead({ label, column, sort, onSort, right }) {
  const active = sort.key === column;
  const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead className={`${TH} ${right ? "text-right" : ""}`}
               aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => onSort(column)} data-testid={`finance-vendor-sort-${column}`}
              className={`inline-flex items-center gap-1 uppercase tracking-[0.1em] hover:text-foreground ${active ? "text-foreground" : ""} ${right ? "flex-row-reverse" : ""}`}>
        {label}<Icon className={`h-3 w-3 ${active ? "" : "opacity-40"}`} />
      </button>
    </TableHead>
  );
}

/* -------- Tab -------- */
export default function VendorsTab({ canManage, onViewBills }) {
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [editing, setEditing] = useState(null); // null closed, {} new, vendor edit
  // The open vendor panel lives in the URL (?tab=vendors&vendor=<id>) so it can be deep-linked.
  const [params, setParams] = useSearchParams();
  const detailId = params.get("vendor");
  const setDetailId = (id) => setParams((p) => { if (id) p.set("vendor", id); else p.delete("vendor"); return p; }, { replace: true });
  const [sort, setSort] = useState({ key: "name", dir: "asc" });
  const [toDelete, setToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => { const t = setTimeout(() => setQ(qInput.trim()), 300); return () => clearTimeout(t); }, [qInput]);
  const filters = { ...(q ? { q } : {}), ...(status ? { status } : {}), ...(category ? { category } : {}) };
  const { data, error, loading, reload } = useFinanceResource("/finance/vendors", filters);
  // Unfiltered list for the bill form's vendor selector.
  const all = useFinanceResource("/finance/vendors");
  function reloadAll() { reload(); all.reload(); setVersion((n) => n + 1); }

  async function remove() {
    setDeleting(true);
    try {
      await api.delete(`/finance/vendors/${toDelete.id}`);
      toast.success(`${toDelete.name} deleted`);
      if (detailId === toDelete.id) setDetailId(null);
      setToDelete(null); reloadAll();
    } catch (e) { toast.error(formatApiError(e)); } finally { setDeleting(false); }
  }

  const onSort = (key) => setSort((s) => (s.key === key
    ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
    : { key, dir: key === "name" ? "asc" : "desc" }));
  const rows = useMemo(() => (data ? sortVendors(data.items, sort) : []), [data, sort]);

  const t = all.data?.totals;
  const filtered = Object.keys(filters).length > 0;

  return (
    <div className="space-y-5" data-testid="finance-vendors">
      {!t ? <SkeletonBlocks count={4} /> : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <StatCard label="Vendors" value={t.vendors.toLocaleString("en-IN")} icon={Users} sub={`${t.active} active`} />
          <StatCard label="Total spent" value={inr(t.total_spent)} icon={IndianRupee} tone="info" sub="Paid bills + linked payouts" />
          <StatCard label="Outstanding" value={inr(t.outstanding)} icon={Clock} tone="warning" sub="Pending bills + payouts" />
          <StatCard label="Overdue bills" value={inr(t.overdue)} icon={AlertTriangle} tone={t.overdue ? "danger" : "default"} sub="Past due date" />
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-2 lg:items-center justify-between">
        <div className="flex flex-col sm:flex-row gap-2 flex-1">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search name, contact, GSTIN…" value={qInput} onChange={(e) => setQInput(e.target.value)} className="pl-9 h-9" data-testid="finance-vendor-search" />
          </div>
          <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : v)}>
            <SelectTrigger className="h-9 w-full sm:w-[130px]" data-testid="finance-vendor-status"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="inactive">Inactive</SelectItem>
            </SelectContent>
          </Select>
          <Select value={category || "all"} onValueChange={(v) => setCategory(v === "all" ? "" : v)}>
            <SelectTrigger className="h-9 w-full sm:w-[180px]" data-testid="finance-vendor-category-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {VENDOR_CATEGORIES.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        {canManage && (
          <Button size="sm" className="h-9" onClick={() => setEditing({})} data-testid="finance-vendor-create-btn">
            <Plus className="h-4 w-4 mr-1.5" />Add vendor
          </Button>
        )}
      </div>

      {!data && error ? (
        <LoadError error={error} onRetry={reload} loading={loading} what="vendors" />
      ) : (
        <Card className="border-border">
          {!data ? <TableSkeleton /> : data.items.length === 0 ? (
            <EmptyState icon={Building2} title={filtered ? "No vendors match these filters" : "No vendors yet"}
                        description={filtered ? "Try another search, status or category." : "Add the suppliers and payees WavyGo pays to track spend and outstanding bills per vendor."}
                        action={!filtered && canManage ? <Button size="sm" onClick={() => setEditing({})}><Plus className="h-4 w-4 mr-1.5" />Add vendor</Button> : null} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <SortHead label="Vendor" column="name" sort={sort} onSort={onSort} />
                  <TableHead className={TH}>Category</TableHead>
                  <SortHead label="Total spent" column="total_spent" sort={sort} onSort={onSort} right />
                  <SortHead label="Outstanding" column="outstanding" sort={sort} onSort={onSort} right />
                  <SortHead label="Overdue" column="overdue" sort={sort} onSort={onSort} right />
                  <SortHead label="Bills" column="bills_count" sort={sort} onSort={onSort} right />
                  <SortHead label="Last bill" column="last_bill_date" sort={sort} onSort={onSort} />
                  <TableHead className={TH}>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((v) => (
                  <TableRow key={v.id} className="hover:bg-muted/40 cursor-pointer" onClick={() => setDetailId(v.id)} data-testid="finance-vendor-row">
                    <TableCell className="min-w-[170px]">
                      <div className="font-medium text-foreground">{v.name}</div>
                      <div className="text-[11.5px] text-muted-foreground">
                        {[v.contact_person, v.phone || v.email].filter(Boolean).join(" · ") || "No contact details"}
                      </div>
                    </TableCell>
                    <TableCell className="text-[13px] whitespace-nowrap">
                      {categoryLabel(v.category)}
                      {v.marketplace_vendor_id && <div className="text-[11px] text-muted-foreground flex items-center gap-1"><Link2 className="h-3 w-3" />Marketplace</div>}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      {inr(v.total_spent)}
                      {v.payouts_count > 0 && <div className="text-[11px] text-muted-foreground">incl. {v.payouts_count} payout(s)</div>}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap font-medium">
                      {inr(v.outstanding)}
                      {v.pending_bills > 0 && <div className="text-[11px] text-muted-foreground font-normal">{v.pending_bills} pending bill(s)</div>}
                    </TableCell>
                    <TableCell className={`text-right whitespace-nowrap ${v.overdue > 0 ? "text-destructive font-medium" : "text-muted-foreground"}`}>
                      {inr(v.overdue)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{(v.bills_count || 0).toLocaleString("en-IN")}</TableCell>
                    <TableCell className="whitespace-nowrap text-[13px]">{formatDate(v.last_bill_date)}</TableCell>
                    <TableCell><StatusPill status={v.status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
      )}

      <VendorDialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)} vendor={editing?.id ? editing : null}
                    onDone={reloadAll} />
      <VendorDetail vendorId={detailId} version={version} onClose={() => setDetailId(null)} canManage={canManage} vendors={all.data?.items}
                    onEdit={(v) => setEditing(v)} onDelete={(v) => setToDelete(v)} onChanged={reloadAll}
                    onViewBills={(id) => onViewBills?.(id)} />
      <AlertDialog open={!!toDelete} onOpenChange={(o) => !o && !deleting && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {toDelete?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Vendors with bills cannot be deleted; mark them inactive instead to keep their history.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Keep vendor</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); remove(); }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              data-testid="finance-vendor-delete-confirm"
            >
              {deleting && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}Delete vendor
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
