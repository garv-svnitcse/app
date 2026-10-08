import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Receipt, Plus, Search, Loader2, Download, CheckCircle2, Ban, Pencil, Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { EmptyState } from "@/components/module/ModulePrimitives";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import {
  inr, formatDate, todayIST, monthLabel, useFinanceResource, LoadError, TableSkeleton, MonthSelect,
  downloadCsv, TH, VENDOR_CATEGORIES, categoryLabel, BillStatus, VendorSelect,
} from "@/components/finance/financeShared";

const PAGE = 50;
const METHODS = [
  { value: "bank_transfer", label: "Bank transfer" }, { value: "upi", label: "UPI" }, { value: "card", label: "Card" },
  { value: "cash", label: "Cash" }, { value: "cheque", label: "Cheque" }, { value: "other", label: "Other" },
];

function emptyBill(vendorId) {
  return { vendor_id: vendorId || "", bill_number: "", bill_date: todayIST(), due_date: "", description: "",
           category: "", amount: "", gst_amount: "", notes: "" };
}

/* -------- Create / edit a bill (also used from the vendor detail panel) -------- */
export function BillDialog({ open, onOpenChange, bill, defaultVendorId, vendors, onDone }) {
  const [form, setForm] = useState(emptyBill());
  const [busy, setBusy] = useState(false);
  const editing = !!bill;

  useEffect(() => {
    if (!open) return;
    setForm(bill ? {
      vendor_id: bill.vendor_id, bill_number: bill.bill_number || "", bill_date: bill.bill_date,
      due_date: bill.due_date || "", description: bill.description || "", category: bill.category || "",
      amount: String(bill.amount ?? ""), gst_amount: bill.gst_amount ? String(bill.gst_amount) : "", notes: bill.notes || "",
    } : emptyBill(defaultVendorId));
  }, [open, bill, defaultVendorId]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target ? e.target.value : e }));
  const vendor = (vendors || []).find((v) => v.id === form.vendor_id);
  const amount = Number(form.amount) || 0;
  const gst = Number(form.gst_amount) || 0;
  const valid = form.vendor_id && form.bill_date && form.description.trim().length >= 2 && amount > 0 && gst >= 0
    && (!form.due_date || form.due_date >= form.bill_date);
  // Only active vendors can receive new bills; keep the current one selectable while editing.
  const options = (vendors || []).filter((v) => v.status === "active" || v.id === form.vendor_id);

  async function submit() {
    setBusy(true);
    const body = { ...form, amount, gst_amount: gst };
    try {
      if (editing) await api.put(`/finance/bills/${bill.id}`, body);
      else await api.post("/finance/bills", body);
      toast.success(editing ? "Bill updated" : `Bill recorded · ${inr(amount + gst)}`);
      onOpenChange(false); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display">{editing ? "Edit bill" : "Record vendor bill"}</DialogTitle>
          <DialogDescription>A bill or expense owed to a vendor. It stays pending until you mark it paid.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <Label className="text-[12px]">Vendor</Label>
            <VendorSelect vendors={vendors ? options : null} value={form.vendor_id} onChange={set("vendor_id")}
                          className="sm:w-full mt-1" disabled={busy} testid="finance-bill-vendor" />
            {vendors && options.length === 0 && (
              <div className="text-[11.5px] text-muted-foreground mt-1">Add an active vendor in the Vendors tab first.</div>
            )}
          </div>
          <div>
            <Label className="text-[12px]">Bill date</Label>
            <Input type="date" className="mt-1" max={todayIST()} value={form.bill_date} onChange={set("bill_date")} disabled={busy} data-testid="finance-bill-date" />
          </div>
          <div>
            <Label className="text-[12px]">Due date <span className="text-muted-foreground">(optional)</span></Label>
            <Input type="date" className="mt-1" min={form.bill_date} value={form.due_date} onChange={set("due_date")} disabled={busy} />
            {!form.due_date && vendor?.payment_terms_days != null && (
              <div className="text-[11px] text-muted-foreground mt-1">Defaults to {vendor.payment_terms_days} day terms</div>
            )}
          </div>
          <div className="sm:col-span-2">
            <Label className="text-[12px]">Description</Label>
            <Input className="mt-1" maxLength={300} value={form.description} onChange={set("description")} disabled={busy}
                   placeholder="e.g. Brake pad replacement, 12 scooters" data-testid="finance-bill-description" />
          </div>
          <div>
            <Label className="text-[12px]">Bill / invoice number</Label>
            <Input className="mt-1" maxLength={60} value={form.bill_number} onChange={set("bill_number")} disabled={busy} />
          </div>
          <div>
            <Label className="text-[12px]">Category</Label>
            <Select value={form.category || "vendor"} onValueChange={(v) => set("category")(v === "vendor" ? "" : v)} disabled={busy}>
              <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="vendor">Vendor default{vendor ? ` (${categoryLabel(vendor.category)})` : ""}</SelectItem>
                {VENDOR_CATEGORIES.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">Amount (before GST, ₹)</Label>
            <Input type="number" min="0" step="0.01" className="mt-1" value={form.amount} onChange={set("amount")} disabled={busy} data-testid="finance-bill-amount" />
          </div>
          <div>
            <Label className="text-[12px]">GST (₹)</Label>
            <Input type="number" min="0" step="0.01" className="mt-1" value={form.gst_amount} onChange={set("gst_amount")} disabled={busy} />
          </div>
          <div className="sm:col-span-2">
            <Label className="text-[12px]">Notes</Label>
            <Textarea className="mt-1" rows={2} maxLength={500} value={form.notes} onChange={set("notes")} disabled={busy} />
          </div>
        </div>
        <div className="text-[13px] text-muted-foreground">Total <span className="font-medium text-foreground">{inr(amount + gst)}</span></div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !valid} data-testid="finance-bill-submit">
            {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}{editing ? "Save" : "Record bill"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function PayBillDialog({ bill, onClose, onDone }) {
  const [method, setMethod] = useState("bank_transfer");
  const [paidOn, setPaidOn] = useState(todayIST());
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (bill) { setMethod("bank_transfer"); setPaidOn(todayIST()); setReference(""); } }, [bill]);

  async function submit() {
    setBusy(true);
    try {
      await api.post(`/finance/bills/${bill.id}/pay`, { method, paid_on: paidOn, reference });
      toast.success(`Bill for ${bill.vendor_name} marked paid`);
      onClose(); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={!!bill} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">Mark bill paid</DialogTitle>
          <DialogDescription>{bill?.vendor_name} · {inr(bill?.total)}{bill?.bill_number ? ` · ${bill.bill_number}` : ""}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[12px]">Method</Label>
            <Select value={method} onValueChange={setMethod} disabled={busy}>
              <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>{METHODS.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">Paid on</Label>
            <Input type="date" className="mt-1" min={bill?.bill_date} max={todayIST()} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} disabled={busy} />
          </div>
          <div>
            <Label className="text-[12px]">Reference (UTR / cheque no.)</Label>
            <Input className="mt-1" maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} disabled={busy} data-testid="finance-bill-reference" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !paidOn} data-testid="finance-bill-pay-submit">
            {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Mark paid
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CancelBillDialog({ bill, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (bill) setReason(""); }, [bill]);

  async function submit() {
    setBusy(true);
    try {
      await api.post(`/finance/bills/${bill.id}/cancel`, { reason });
      toast.success("Bill cancelled"); onClose(); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={!!bill} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">Cancel bill</DialogTitle>
          <DialogDescription>
            {bill?.vendor_name} · {inr(bill?.total)}. The bill is kept for the record but no longer counts towards spend or outstanding.
          </DialogDescription>
        </DialogHeader>
        <div>
          <Label className="text-[12px]">Reason</Label>
          <Textarea className="mt-1" rows={2} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} data-testid="finance-bill-cancel-reason" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Keep bill</Button>
          <Button variant="destructive" onClick={submit} disabled={busy || reason.trim().length < 3} data-testid="finance-bill-cancel-submit">
            {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Cancel bill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------- Tab -------- */
export default function BillsTab({ canManage }) {
  const [params, setParams] = useSearchParams();
  const vendorId = params.get("vendor") || "";
  const setVendorId = (v) => setParams((p) => { if (v) p.set("vendor", v); else p.delete("vendor"); return p; }, { replace: true });
  const [status, setStatus] = useState("");
  const [month, setMonth] = useState("");
  const [category, setCategory] = useState("");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState(null); // null closed, {} new, bill edit
  const [paying, setPaying] = useState(null);
  const [cancelling, setCancelling] = useState(null);
  const [toDelete, setToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [exporting, setExporting] = useState(false);

  const vendors = useFinanceResource("/finance/vendors");
  useEffect(() => { const t = setTimeout(() => setQ(qInput.trim()), 300); return () => clearTimeout(t); }, [qInput]);
  useEffect(() => { setPage(0); }, [vendorId, status, month, category, q]);

  const filters = {
    ...(vendorId ? { vendor_id: vendorId } : {}), ...(status ? { status } : {}), ...(month ? { month } : {}),
    ...(category ? { category } : {}), ...(q ? { q } : {}),
  };
  const { data, error, loading, reload } = useFinanceResource("/finance/bills", { ...filters, limit: PAGE, skip: page * PAGE });
  const vendorList = vendors.data?.items;
  function reloadAll() { reload(); vendors.reload(); }

  async function exportCsv() {
    setExporting(true);
    try { await downloadCsv("/finance/bills/export", filters, `wavygo-vendor-bills-${month || "all"}.csv`); }
    catch (e) { toast.error(formatApiError(e)); } finally { setExporting(false); }
  }

  async function remove() {
    setDeleting(true);
    try {
      await api.delete(`/finance/bills/${toDelete.id}`);
      toast.success("Bill deleted"); setToDelete(null); reloadAll();
    } catch (e) { toast.error(formatApiError(e)); } finally { setDeleting(false); }
  }

  const s = data?.summary;
  const filtered = Object.keys(filters).length > 0;

  return (
    <div data-testid="finance-bills">
      <div className="flex flex-col xl:flex-row gap-2 xl:items-center justify-between mb-4">
        <div className="flex flex-col sm:flex-row sm:flex-wrap gap-2 flex-1">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search bill no., description…" value={qInput} onChange={(e) => setQInput(e.target.value)} className="pl-9 h-9" data-testid="finance-bill-search" />
          </div>
          <VendorSelect vendors={vendorList} value={vendorId} onChange={setVendorId} allLabel="All vendors" testid="finance-bill-vendor-filter" />
          <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : v)}>
            <SelectTrigger className="h-9 w-full sm:w-[130px]" data-testid="finance-bill-status"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {["pending", "overdue", "paid", "cancelled"].map((x) => <SelectItem key={x} value={x} className="capitalize">{x}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={category || "all"} onValueChange={(v) => setCategory(v === "all" ? "" : v)}>
            <SelectTrigger className="h-9 w-full sm:w-[170px]" data-testid="finance-bill-category"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {VENDOR_CATEGORIES.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <MonthSelect value={month} onChange={setMonth} allowAll testid="finance-bill-month" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" className="h-9" onClick={exportCsv} disabled={exporting} data-testid="finance-bill-export">
            {exporting ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Download className="h-4 w-4 mr-1.5" />}CSV
          </Button>
          {canManage && (
            <Button size="sm" className="h-9" onClick={() => setEditing({})} data-testid="finance-bill-create-btn">
              <Plus className="h-4 w-4 mr-1.5" />Record bill
            </Button>
          )}
        </div>
      </div>

      {s && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-muted-foreground mb-3">
          <span>Pending <b className="text-foreground">{s.pending.count}</b> · {inr(s.pending.total)}</span>
          <span className={s.overdue.count ? "text-destructive" : undefined}>Overdue <b>{s.overdue.count}</b> · {inr(s.overdue.total)}</span>
          <span>Paid <b className="text-foreground">{s.paid.count}</b> · {inr(s.paid.total)}</span>
          <span>Cancelled <b className="text-foreground">{s.cancelled.count}</b></span>
          {month && <span>for {monthLabel(month)}</span>}
        </div>
      )}

      {!data && error ? (
        <LoadError error={error} onRetry={reload} loading={loading} what="vendor bills" />
      ) : (
        <Card className="border-border">
          {!data ? <TableSkeleton /> : data.items.length === 0 ? (
            <EmptyState icon={Receipt} title={filtered ? "No bills match these filters" : "No vendor bills yet"}
                        description={filtered ? "Try another vendor, status, month or search." : "Record bills and expenses from your vendors to track spend and what you owe."}
                        action={!filtered && canManage ? <Button size="sm" onClick={() => setEditing({})}><Plus className="h-4 w-4 mr-1.5" />Record bill</Button> : null} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={TH}>Date</TableHead>
                  <TableHead className={TH}>Vendor</TableHead>
                  <TableHead className={TH}>Description</TableHead>
                  <TableHead className={`${TH} text-right`}>GST</TableHead>
                  <TableHead className={`${TH} text-right`}>Total</TableHead>
                  <TableHead className={TH}>Status</TableHead>
                  <TableHead className="w-[1%]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((b) => (
                  <TableRow key={b.id} className="hover:bg-muted/40" data-testid="finance-bill-row">
                    <TableCell className="whitespace-nowrap">
                      {formatDate(b.bill_date)}
                      {b.due_date && <div className="text-[11px] text-muted-foreground">Due {formatDate(b.due_date)}</div>}
                    </TableCell>
                    <TableCell className="min-w-[130px]">
                      <button type="button" className="font-medium text-foreground hover:text-primary text-left" onClick={() => setVendorId(b.vendor_id)}>{b.vendor_name}</button>
                      <div className="text-[11.5px] text-muted-foreground">{categoryLabel(b.category)}</div>
                    </TableCell>
                    <TableCell className="min-w-[180px]">
                      <div className="text-foreground">{b.description}</div>
                      {b.bill_number && <div className="text-[11.5px] text-muted-foreground">#{b.bill_number}</div>}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">{inr(b.gst_amount)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap font-medium">{inr(b.total)}</TableCell>
                    <TableCell>
                      <BillStatus status={b.status} overdue={b.overdue} />
                      {b.status === "paid" && b.payment && <div className="text-[11px] text-muted-foreground mt-0.5 whitespace-nowrap">{formatDate(b.payment.paid_on)}</div>}
                      {b.status === "cancelled" && b.cancel_reason && <div className="text-[11px] text-muted-foreground mt-0.5 max-w-[160px] truncate" title={b.cancel_reason}>{b.cancel_reason}</div>}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap space-x-1">
                      {canManage && b.status === "pending" && (
                        <>
                          <Button variant="ghost" size="sm" className="h-7 text-xs text-success" onClick={() => setPaying(b)} data-testid="finance-bill-pay-btn">
                            <CheckCircle2 className="h-3.5 w-3.5 mr-1" />Paid
                          </Button>
                          <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => setEditing(b)} aria-label="Edit bill"><Pencil className="h-3.5 w-3.5" /></Button>
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-destructive" onClick={() => setToDelete(b)} aria-label="Delete bill"><Trash2 className="h-3.5 w-3.5" /></Button>
                        </>
                      )}
                      {canManage && b.status === "paid" && (
                        <Button variant="ghost" size="sm" className="h-7 text-xs text-destructive" onClick={() => setCancelling(b)} data-testid="finance-bill-cancel-btn">
                          <Ban className="h-3.5 w-3.5 mr-1" />Cancel
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {data && data.total > PAGE && (
            <div className="flex items-center justify-between border-t border-border px-4 py-2 text-[12.5px] text-muted-foreground">
              <span>{page * PAGE + 1}–{Math.min((page + 1) * PAGE, data.total)} of {data.total}</span>
              <div className="space-x-2">
                <Button variant="outline" size="sm" className="h-7" disabled={page === 0 || loading} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button variant="outline" size="sm" className="h-7" disabled={(page + 1) * PAGE >= data.total || loading} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </Card>
      )}

      <BillDialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)} bill={editing?.id ? editing : null}
                  defaultVendorId={vendorId} vendors={vendorList} onDone={reloadAll} />
      <PayBillDialog bill={paying} onClose={() => setPaying(null)} onDone={reloadAll} />
      <CancelBillDialog bill={cancelling} onClose={() => setCancelling(null)} onDone={reloadAll} />
      <AlertDialog open={!!toDelete} onOpenChange={(v) => !v && !deleting && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this bill?</AlertDialogTitle>
            <AlertDialogDescription>
              {toDelete?.vendor_name} · {inr(toDelete?.total)} · {toDelete?.description}. Use this only for bills entered by mistake.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Keep bill</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); remove(); }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              data-testid="finance-bill-delete-confirm"
            >
              {deleting && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}Delete bill
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
