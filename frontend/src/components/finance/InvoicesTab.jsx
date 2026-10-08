import { useCallback, useEffect, useState } from "react";
import { FileText, Plus, Layers, Download, Search, Loader2, Printer, Eye, CheckCircle2, Ban, Send } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/module/ModulePrimitives";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import {
  inr, formatDate, todayIST, monthLabel, useFinanceResource, LoadError, TableSkeleton, MonthSelect,
  FinanceStatus, downloadCsv, TH, VendorSelect,
} from "@/components/finance/financeShared";
import InvoicePrint, { InvoiceDocument } from "@/components/finance/InvoicePrint";

const PAGE = 50;
const METHODS = [
  { value: "upi", label: "UPI" }, { value: "card", label: "Card" }, { value: "cash", label: "Cash" },
  { value: "bank_transfer", label: "Bank transfer" }, { value: "cheque", label: "Cheque" }, { value: "other", label: "Other" },
];

function SubmitButton({ busy, children, ...props }) {
  return (
    <Button disabled={busy} {...props}>
      {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}{children}
    </Button>
  );
}

/* -------- Generate one invoice -------- */
function GenerateDialog({ open, onOpenChange, onDone }) {
  const [eligible, setEligible] = useState(null);
  const [bookingId, setBookingId] = useState("");
  const [date, setDate] = useState(todayIST());
  const [draft, setDraft] = useState(false);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let live = true;
    setEligible(null); setBookingId(""); setDate(todayIST()); setDraft(false); setNotes("");
    api.get("/finance/invoices/eligible", { params: { limit: 500 } })
      .then(({ data }) => { if (live) setEligible(data); })
      .catch((e) => { if (live) { toast.error(formatApiError(e)); setEligible({ items: [], total: 0 }); } });
    return () => { live = false; };
  }, [open]);

  async function submit() {
    setBusy(true);
    try {
      const { data } = await api.post("/finance/invoices", { booking_id: bookingId, invoice_date: date, issue: !draft, notes: notes || null });
      toast.success(data.created ? `${data.number || "Draft invoice"} created` : `Booking already has ${data.number || "a draft invoice"}`);
      onOpenChange(false); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display">Generate invoice</DialogTitle>
          <DialogDescription>Customer invoice for a confirmed, active or completed booking. One live invoice per booking.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[12px]">Booking</Label>
            {eligible === null ? (
              <div className="mt-1 h-9 rounded-md bg-muted animate-pulse" />
            ) : eligible.items.length === 0 ? (
              <div className="mt-1 text-[13px] text-muted-foreground">Every eligible booking already has an invoice.</div>
            ) : (
              <Select value={bookingId} onValueChange={setBookingId} disabled={busy}>
                <SelectTrigger className="mt-1" data-testid="finance-generate-booking"><SelectValue placeholder={`Select from ${eligible.total} uninvoiced booking(s)`} /></SelectTrigger>
                <SelectContent>
                  {eligible.items.map((b) => (
                    <SelectItem key={b.id} value={b.id}>
                      {b.customer_name} · {inr(b.amount)} · {formatDate(b.created_at)} · {b.status}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <div>
            <Label className="text-[12px]">Invoice date</Label>
            <Input type="date" className="mt-1" max={todayIST()} value={date} onChange={(e) => setDate(e.target.value)} disabled={busy} data-testid="finance-generate-date" />
            <p className="text-[11.5px] text-muted-foreground mt-1">Sets the financial year of the invoice number (April–March).</p>
          </div>
          <div>
            <Label className="text-[12px]">Notes (optional)</Label>
            <Textarea rows={2} className="mt-1" value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} disabled={busy} />
          </div>
          <label className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
            <span>
              <span className="block text-[13px] font-medium text-foreground">Save as draft</span>
              <span className="block text-[12px] text-muted-foreground">Drafts get a number only when issued.</span>
            </span>
            <Switch checked={draft} onCheckedChange={setDraft} disabled={busy} />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <SubmitButton busy={busy} onClick={submit} disabled={busy || !bookingId || !date} data-testid="finance-generate-submit">
            {draft ? "Save draft" : "Generate & issue"}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------- Bulk generate -------- */
function BulkDialog({ open, onOpenChange, onDone }) {
  const [month, setMonth] = useState("");
  const [preview, setPreview] = useState(null);
  const [date, setDate] = useState(todayIST());
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) { setMonth(""); setDate(todayIST()); } }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    // Ignore the response for a month the user has already switched away from.
    let live = true;
    setPreview(null);
    api.get("/finance/invoices/eligible", { params: { limit: 1, ...(month ? { month } : {}) } })
      .then(({ data }) => { if (live) setPreview(data); })
      .catch((e) => { if (live) toast.error(formatApiError(e)); });
    return () => { live = false; };
  }, [open, month]);

  async function submit() {
    setBusy(true);
    try {
      const { data } = await api.post("/finance/invoices/bulk", { month: month || null, invoice_date: date, issue: true });
      toast.success(data.created ? `${data.created} invoice(s) generated · ${inr(data.total)}` : "No invoices needed");
      if (data.remaining) toast.info(`${data.remaining} more booking(s) remain — run again to continue.`);
      onOpenChange(false); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">Generate all missing invoices</DialogTitle>
          <DialogDescription>Issues an invoice for every confirmed, active or completed booking that has none, oldest first.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[12px]">Bookings created in</Label>
            <MonthSelect value={month} onChange={setMonth} allowAll className="sm:w-full mt-1" disabled={busy} testid="finance-bulk-month" />
          </div>
          <div>
            <Label className="text-[12px]">Invoice date</Label>
            <Input type="date" className="mt-1" max={todayIST()} value={date} onChange={(e) => setDate(e.target.value)} disabled={busy} />
          </div>
          <div className="rounded-md bg-muted/50 p-3 text-[13px]">
            {preview === null ? "Checking eligible bookings…" : preview.total === 0
              ? "Nothing to invoice — every eligible booking already has an invoice."
              : <><span className="font-semibold text-foreground">{preview.total}</span> booking(s) · {inr(preview.amount)} will be invoiced.</>}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <SubmitButton busy={busy} onClick={submit} disabled={busy || !preview?.total || !date} data-testid="finance-bulk-submit">Generate</SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------- Mark paid -------- */
function PayDialog({ invoice, onClose, onDone }) {
  const [method, setMethod] = useState("upi");
  const [paidOn, setPaidOn] = useState(todayIST());
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (invoice) { setMethod("upi"); setPaidOn(todayIST()); setReference(""); } }, [invoice]);

  async function submit() {
    setBusy(true);
    try {
      await api.post(`/finance/invoices/${invoice.id}/pay`, { method, paid_on: paidOn, reference: reference || null });
      toast.success(`${invoice.number} marked paid`);
      onClose(); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={!!invoice} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">Record payment</DialogTitle>
          <DialogDescription>{invoice?.number} · {invoice?.customer_name} · {inr(invoice?.total)}</DialogDescription>
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
            <Label className="text-[12px]">Received on</Label>
            <Input type="date" className="mt-1" max={todayIST()} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} disabled={busy} />
          </div>
          <div>
            <Label className="text-[12px]">Reference (UTR / txn id, optional)</Label>
            <Input className="mt-1" maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} disabled={busy} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <SubmitButton busy={busy} onClick={submit} disabled={busy || !paidOn} data-testid="finance-pay-submit">Mark paid</SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------- Void -------- */
function VoidDialog({ invoice, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (invoice) setReason(""); }, [invoice]);

  async function submit() {
    setBusy(true);
    try {
      await api.post(`/finance/invoices/${invoice.id}/void`, { reason });
      toast.success(`${invoice.number || "Draft invoice"} voided`);
      onClose(); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={!!invoice} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">Void invoice</DialogTitle>
          <DialogDescription>
            {invoice?.number || "Draft"} · {inr(invoice?.total)}. The number stays used; the booking can be invoiced again.
            {invoice?.status === "paid" && " This invoice is paid — voiding records it as refunded."}
          </DialogDescription>
        </DialogHeader>
        <div>
          <Label className="text-[12px]">Reason</Label>
          <Textarea rows={3} className="mt-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy}
                    placeholder="e.g. Booking cancelled, wrong customer details" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <SubmitButton busy={busy} variant="destructive" onClick={submit} disabled={busy || reason.trim().length < 3} data-testid="finance-void-submit">Void invoice</SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------- Detail -------- */
function DetailDialog({ invoiceId, onClose, onPrint }) {
  const [inv, setInv] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!invoiceId) return undefined;
    let live = true;
    setInv(null); setError(null);
    api.get(`/finance/invoices/${invoiceId}`)
      .then(({ data }) => { if (live) setInv(data); })
      .catch((e) => { if (live) setError(formatApiError(e)); });
    return () => { live = false; };
  }, [invoiceId]);

  const bookingChanged = inv && inv.status !== "void" && inv.current_booking_status && !["confirmed", "active", "completed"].includes(inv.current_booking_status);
  return (
    <Dialog open={!!invoiceId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            {inv?.number || "Invoice"} {inv && <FinanceStatus status={inv.status} />}
          </DialogTitle>
          <DialogDescription>{inv ? `Created by ${inv.created_by || "—"} · ${formatDate(inv.created_at)}` : "Loading…"}</DialogDescription>
        </DialogHeader>
        {error && <div className="text-sm text-destructive">{error}</div>}
        {!inv && !error && <div className="h-64 rounded-md bg-muted animate-pulse" />}
        {inv && (
          <>
            {bookingChanged && (
              <div className="rounded-md bg-warning/10 text-warning text-[13px] p-3">
                The booking is now <b>{inv.current_booking_status}</b>. Consider voiding this invoice.
              </div>
            )}
            <div className="rounded-lg border border-border bg-white text-black p-4 sm:p-6 overflow-x-auto">
              <InvoiceDocument invoice={inv} />
            </div>
          </>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
          <Button onClick={() => onPrint(inv)} disabled={!inv} data-testid="finance-invoice-print"><Printer className="h-4 w-4 mr-1.5" />Print</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------- Tab -------- */
export default function InvoicesTab({ canManage }) {
  const [status, setStatus] = useState("");
  const [month, setMonth] = useState("");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [vendorId, setVendorId] = useState("");
  const [page, setPage] = useState(0);
  const [genOpen, setGenOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [paying, setPaying] = useState(null);
  const [voiding, setVoiding] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [printing, setPrinting] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [issuing, setIssuing] = useState(null);

  useEffect(() => { const t = setTimeout(() => setQ(qInput.trim()), 300); return () => clearTimeout(t); }, [qInput]);
  useEffect(() => { setPage(0); }, [status, month, q, vendorId]);

  const filters = { ...(status ? { status } : {}), ...(month ? { month } : {}), ...(q ? { q } : {}), ...(vendorId ? { vendor_id: vendorId } : {}) };
  const mpVendors = useFinanceResource("/finance/vendors/marketplace-options");
  const { data, error, loading, reload } = useFinanceResource("/finance/invoices", { ...filters, limit: PAGE, skip: page * PAGE });
  const donePrint = useCallback(() => setPrinting(null), []);

  async function exportCsv() {
    setExporting(true);
    try { await downloadCsv("/finance/invoices/export", filters, `wavygo-invoices-${month || "all"}.csv`); }
    catch (e) { toast.error(formatApiError(e)); } finally { setExporting(false); }
  }

  async function issue(inv) {
    setIssuing(inv.id);
    try {
      const { data } = await api.post(`/finance/invoices/${inv.id}/issue`);
      toast.success(`${data.number} issued`); reload();
    } catch (e) { toast.error(formatApiError(e)); } finally { setIssuing(null); }
  }

  async function printInvoice(inv) {
    try {
      const full = inv.line_items ? inv : (await api.get(`/finance/invoices/${inv.id}`)).data;
      setPrinting(full);
    } catch (e) { toast.error(formatApiError(e)); }
  }

  const s = data?.summary;
  const filtered = Object.keys(filters).length > 0;

  return (
    <div data-testid="finance-invoices">
      <div className="flex flex-col lg:flex-row gap-2 lg:items-center justify-between mb-4">
        <div className="flex flex-col sm:flex-row gap-2 flex-1">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search number, customer…" value={qInput} onChange={(e) => setQInput(e.target.value)} className="pl-9 h-9" data-testid="finance-invoice-search" />
          </div>
          <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : v)}>
            <SelectTrigger className="h-9 w-full sm:w-[130px]" data-testid="finance-invoice-status"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {["draft", "issued", "paid", "void"].map((x) => <SelectItem key={x} value={x} className="capitalize">{x}</SelectItem>)}
            </SelectContent>
          </Select>
          <MonthSelect value={month} onChange={setMonth} allowAll testid="finance-invoice-month" />
          <VendorSelect vendors={mpVendors.data} value={vendorId} onChange={setVendorId} allLabel="All fleet vendors" testid="finance-invoice-vendor" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" className="h-9" onClick={exportCsv} disabled={exporting} data-testid="finance-invoice-export">
            {exporting ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Download className="h-4 w-4 mr-1.5" />}CSV
          </Button>
          {canManage && (
            <>
              <Button variant="outline" size="sm" className="h-9" onClick={() => setBulkOpen(true)} data-testid="finance-bulk-btn">
                <Layers className="h-4 w-4 mr-1.5" />Generate all
              </Button>
              <Button size="sm" className="h-9" onClick={() => setGenOpen(true)} data-testid="finance-generate-btn">
                <Plus className="h-4 w-4 mr-1.5" />New invoice
              </Button>
            </>
          )}
        </div>
      </div>

      {s && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-muted-foreground mb-3">
          <span>Issued <b className="text-foreground">{s.issued.count}</b> · {inr(s.issued.total)}</span>
          <span>Paid <b className="text-foreground">{s.paid.count}</b> · {inr(s.paid.total)}</span>
          <span>Draft <b className="text-foreground">{s.draft.count}</b></span>
          <span>Void <b className="text-foreground">{s.void.count}</b></span>
          {month && <span>for {monthLabel(month)}</span>}
        </div>
      )}

      {!data && error ? (
        <LoadError error={error} onRetry={reload} loading={loading} what="invoices" />
      ) : (
        <Card className="border-border">
          {!data ? <TableSkeleton /> : data.items.length === 0 ? (
            <EmptyState icon={FileText} title={filtered ? "No invoices match these filters" : "No invoices yet"}
                        description={filtered ? "Try another status, month, vendor or search." : "Generate invoices for confirmed, active or completed bookings."}
                        action={!filtered && canManage ? <Button size="sm" onClick={() => setGenOpen(true)}><Plus className="h-4 w-4 mr-1.5" />New invoice</Button> : null} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={TH}>Number</TableHead>
                  <TableHead className={TH}>Date</TableHead>
                  <TableHead className={TH}>Customer</TableHead>
                  <TableHead className={`${TH} text-right`}>GST</TableHead>
                  <TableHead className={`${TH} text-right`}>Total</TableHead>
                  <TableHead className={TH}>Status</TableHead>
                  <TableHead className="w-[1%]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((inv) => (
                  <TableRow key={inv.id} className="hover:bg-muted/40" data-testid="finance-invoice-row">
                    <TableCell className="font-medium whitespace-nowrap">
                      <button type="button" className="hover:text-primary" onClick={() => setViewing(inv.id)}>{inv.number || <span className="text-muted-foreground">Draft</span>}</button>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{formatDate(inv.invoice_date)}</TableCell>
                    <TableCell className="min-w-[140px]">
                      <div className="text-foreground">{inv.customer_name}</div>
                      <div className="text-[11.5px] text-muted-foreground">{inv.city}</div>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">{inr(inv.gst_total)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap font-medium">{inr(inv.total)}</TableCell>
                    <TableCell>
                      <FinanceStatus status={inv.status} />
                      {inv.status === "paid" && inv.payment && <div className="text-[11px] text-muted-foreground mt-0.5 whitespace-nowrap">{formatDate(inv.payment.paid_on)}</div>}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap space-x-1">
                      <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => setViewing(inv.id)} aria-label="View"><Eye className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => printInvoice(inv)} aria-label="Print"><Printer className="h-3.5 w-3.5" /></Button>
                      {canManage && inv.status === "draft" && (
                        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => issue(inv)} disabled={issuing === inv.id}>
                          <Send className="h-3.5 w-3.5 mr-1" />Issue
                        </Button>
                      )}
                      {canManage && inv.status === "issued" && (
                        <Button variant="ghost" size="sm" className="h-7 text-xs text-success" onClick={() => setPaying(inv)} data-testid="finance-pay-btn">
                          <CheckCircle2 className="h-3.5 w-3.5 mr-1" />Paid
                        </Button>
                      )}
                      {canManage && inv.status !== "void" && (
                        <Button variant="ghost" size="sm" className="h-7 text-xs text-destructive" onClick={() => setVoiding(inv)} data-testid="finance-void-btn">
                          <Ban className="h-3.5 w-3.5 mr-1" />Void
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

      <GenerateDialog open={genOpen} onOpenChange={setGenOpen} onDone={reload} />
      <BulkDialog open={bulkOpen} onOpenChange={setBulkOpen} onDone={reload} />
      <PayDialog invoice={paying} onClose={() => setPaying(null)} onDone={reload} />
      <VoidDialog invoice={voiding} onClose={() => setVoiding(null)} onDone={reload} />
      <DetailDialog invoiceId={viewing} onClose={() => setViewing(null)} onPrint={(inv) => { setViewing(null); setPrinting(inv); }} />
      <InvoicePrint invoice={printing} onDone={donePrint} />
    </div>
  );
}
