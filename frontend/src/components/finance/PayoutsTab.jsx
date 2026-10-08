import { useEffect, useState } from "react";
import { Wallet, Plus, Loader2, CheckCircle2, X, Handshake } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { EmptyState, StatusPill } from "@/components/module/ModulePrimitives";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import {
  inr, formatDate, todayIST, useFinanceResource, LoadError, TableSkeleton, TH, VendorSelect,
} from "@/components/finance/financeShared";

function previousMonthRange() {
  const [y, m] = todayIST().split("-").map(Number);
  const start = new Date(Date.UTC(y, m - 2, 1));
  const end = new Date(Date.UTC(y, m - 1, 0));
  return [start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)];
}

function CreatePayoutDialog({ open, onOpenChange, onDone, commissionPct }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { const [s, e] = previousMonthRange(); setStart(s); setEnd(e); } }, [open]);

  async function submit() {
    setBusy(true);
    try {
      const { data } = await api.post("/finance/payouts", { period_start: start, period_end: end });
      toast.success(`${data.payouts.length} vendor payout(s) created · ${inr(data.totals.net)} to transfer`);
      onOpenChange(false); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">Create payout batch</DialogTitle>
          <DialogDescription>
            Groups every completed booking created in the period (IST) that is not yet in a payout, one payout per vendor.
            Vendors receive {100 - (commissionPct ?? 0)}% (commission {commissionPct ?? "—"}%).
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <Label className="text-[12px]">From</Label>
            <Input type="date" className="mt-1" value={start} max={todayIST()} onChange={(e) => setStart(e.target.value)} disabled={busy} data-testid="finance-payout-start" />
          </div>
          <div>
            <Label className="text-[12px]">To</Label>
            <Input type="date" className="mt-1" value={end} min={start} onChange={(e) => setEnd(e.target.value)} disabled={busy} data-testid="finance-payout-end" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !start || !end || end < start} data-testid="finance-payout-submit">
            {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Create batch
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PayPayoutDialog({ payout, onClose, onDone }) {
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(todayIST());
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (payout) { setReference(""); setPaidOn(todayIST()); } }, [payout]);

  async function submit() {
    setBusy(true);
    try {
      await api.post(`/finance/payouts/${payout.id}/pay`, { reference, paid_on: paidOn });
      toast.success(`Payout to ${payout.vendor_name} marked paid`);
      onClose(); onDone?.();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  return (
    <Dialog open={!!payout} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display">Mark payout paid</DialogTitle>
          <DialogDescription>{payout?.vendor_name} · {inr(payout?.net)} · {payout?.bookings_count} booking(s)</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[12px]">Transfer reference (UTR / NEFT id)</Label>
            <Input className="mt-1" maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} disabled={busy} data-testid="finance-payout-reference" />
          </div>
          <div>
            <Label className="text-[12px]">Paid on</Label>
            <Input type="date" className="mt-1" max={todayIST()} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} disabled={busy} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !reference.trim() || !paidOn} data-testid="finance-payout-pay-submit">
            {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Mark paid
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function PayoutsTab({ canManage }) {
  const outstanding = useFinanceResource("/finance/payouts/outstanding");
  const [status, setStatus] = useState("");
  const [vendorId, setVendorId] = useState("");
  const payouts = useFinanceResource("/finance/payouts", { ...(status ? { status } : {}), ...(vendorId ? { vendor_id: vendorId } : {}) });
  const payoutVendors = (outstanding.data?.vendors || []).map((v) => ({ id: v.vendor_id, name: v.vendor_name }));
  const [createOpen, setCreateOpen] = useState(false);
  const [paying, setPaying] = useState(null);
  const [toCancel, setToCancel] = useState(null);
  const [cancelling, setCancelling] = useState(null);

  function reloadAll() { outstanding.reload(); payouts.reload(); }

  async function cancel() {
    const p = toCancel;
    setCancelling(p.id);
    try {
      await api.delete(`/finance/payouts/${p.id}`);
      toast.success("Payout cancelled"); setToCancel(null); reloadAll();
    } catch (e) { toast.error(formatApiError(e)); } finally { setCancelling(null); }
  }

  const o = outstanding.data;
  return (
    <div className="space-y-6" data-testid="finance-payouts">
      {/* Outstanding per vendor */}
      {!o && outstanding.error ? (
        <LoadError error={outstanding.error} onRetry={outstanding.reload} loading={outstanding.loading} what="vendor earnings" />
      ) : (
        <Card className="border-border">
          <CardHeader className="pb-2">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
              <div>
                <CardTitle className="font-display text-[17px]">Vendor earnings</CardTitle>
                <CardDescription>
                  Booking revenue × (1 − {o?.commission_pct ?? "—"}% commission). Completed bookings are payable;
                  confirmed and active ones are earned but not yet payable.
                </CardDescription>
              </div>
              {canManage && (
                <Button size="sm" className="h-9 shrink-0" onClick={() => setCreateOpen(true)} data-testid="finance-payout-create-btn">
                  <Plus className="h-4 w-4 mr-1.5" />Create payout batch
                </Button>
              )}
            </div>
          </CardHeader>
          {!o ? <TableSkeleton rows={4} /> : o.vendors.length === 0 ? (
            <div className="p-4 pt-0"><EmptyState icon={Handshake} title="No vendor earnings yet" description="Vendor earnings appear once their vehicles have confirmed, active or completed bookings." /></div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={TH}>Vendor</TableHead>
                    <TableHead className={`${TH} text-right`}>Earned, unbatched</TableHead>
                    <TableHead className={`${TH} text-right`}>Payable now</TableHead>
                    <TableHead className={`${TH} text-right`}>In pending payouts</TableHead>
                    <TableHead className={`${TH} text-right`}>Paid to date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {o.vendors.map((v) => (
                    <TableRow key={v.vendor_id} className="hover:bg-muted/40">
                      <TableCell className="font-medium min-w-[140px]">{v.vendor_name}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {inr(v.earned_net)}
                        <div className="text-[11px] text-muted-foreground">{v.earned_bookings} booking(s) · gross {inr(v.earned_gross)}</div>
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap font-medium">
                        {inr(v.payable_net)}
                        <div className="text-[11px] text-muted-foreground font-normal">{v.payable_bookings} completed</div>
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">{inr(v.pending_net)}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{inr(v.paid_net)}</TableCell>
                    </TableRow>
                  ))}
                  <TableRow className="bg-muted/30 font-medium">
                    <TableCell>Total</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{inr(o.totals.earned_net)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{inr(o.totals.payable_net)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{inr(o.totals.pending_net)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{inr(o.totals.paid_net)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
              {o.unassigned.bookings > 0 && (
                <div className="px-4 py-2 text-[12px] text-muted-foreground border-t border-border">
                  {o.unassigned.bookings} revenue booking(s) ({inr(o.unassigned.gross)}) have no vendor and are not part of payouts.
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {/* Payout batches */}
      <Card className="border-border">
        <CardHeader className="pb-2">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <CardTitle className="font-display text-[17px]">Payouts</CardTitle>
              <CardDescription>Each booking is paid out at most once.</CardDescription>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <VendorSelect vendors={outstanding.data ? payoutVendors : null} value={vendorId} onChange={setVendorId} allLabel="All vendors" testid="finance-payout-vendor" />
              <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : v)}>
                <SelectTrigger className="h-9 w-full sm:w-[140px]" data-testid="finance-payout-status"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All payouts</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="paid">Paid</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        {!payouts.data && payouts.error ? (
          <div className="p-4 pt-0"><LoadError error={payouts.error} onRetry={payouts.reload} loading={payouts.loading} what="payouts" /></div>
        ) : !payouts.data ? <TableSkeleton rows={4} /> : payouts.data.length === 0 ? (
          <div className="p-4 pt-0"><EmptyState icon={Wallet} title={status || vendorId ? `No ${status ? `${status} ` : ""}payouts${vendorId ? " for this vendor" : ""}` : "No payouts yet"} description="Create a payout batch to settle vendors for completed bookings." /></div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className={TH}>Vendor</TableHead>
                <TableHead className={TH}>Period</TableHead>
                <TableHead className={`${TH} text-right`}>Gross</TableHead>
                <TableHead className={`${TH} text-right`}>Commission</TableHead>
                <TableHead className={`${TH} text-right`}>Net</TableHead>
                <TableHead className={TH}>Status</TableHead>
                <TableHead className="w-[1%]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {payouts.data.map((p) => (
                <TableRow key={p.id} className="hover:bg-muted/40" data-testid="finance-payout-row">
                  <TableCell className="font-medium min-w-[130px]">
                    {p.vendor_name}
                    <div className="text-[11px] text-muted-foreground font-normal">{p.bookings_count} booking(s) · batch {p.batch_id}</div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-[13px]">{formatDate(p.period_start)} – {formatDate(p.period_end)}</TableCell>
                  <TableCell className="text-right whitespace-nowrap">{inr(p.gross)}</TableCell>
                  <TableCell className="text-right whitespace-nowrap">{inr(p.commission)} <span className="text-[11px] text-muted-foreground">({p.commission_pct}%)</span></TableCell>
                  <TableCell className="text-right whitespace-nowrap font-medium">{inr(p.net)}</TableCell>
                  <TableCell>
                    <StatusPill status={p.status} className={p.status === "paid" ? "bg-success/10 text-success" : undefined} />
                    {p.status === "paid" && <div className="text-[11px] text-muted-foreground mt-0.5 whitespace-nowrap">{formatDate(p.paid_on)} · {p.reference}</div>}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap space-x-1">
                    {canManage && p.status === "pending" && (
                      <>
                        <Button variant="ghost" size="sm" className="h-7 text-xs text-success" onClick={() => setPaying(p)} data-testid="finance-payout-pay-btn">
                          <CheckCircle2 className="h-3.5 w-3.5 mr-1" />Paid
                        </Button>
                        <Button variant="ghost" size="sm" className="h-7 text-xs text-destructive" onClick={() => setToCancel(p)} disabled={cancelling === p.id} data-testid="finance-payout-cancel-btn">
                          <X className="h-3.5 w-3.5 mr-1" />Cancel
                        </Button>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <CreatePayoutDialog open={createOpen} onOpenChange={setCreateOpen} onDone={reloadAll} commissionPct={o?.commission_pct} />
      <PayPayoutDialog payout={paying} onClose={() => setPaying(null)} onDone={reloadAll} />
      <AlertDialog open={!!toCancel} onOpenChange={(v) => !v && !cancelling && setToCancel(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel payout to {toCancel?.vendor_name}?</AlertDialogTitle>
            <AlertDialogDescription>
              The pending payout of {inr(toCancel?.net)} is removed and its {toCancel?.bookings_count} booking(s) return to outstanding.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={!!cancelling}>Keep payout</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); cancel(); }}
              disabled={!!cancelling}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              data-testid="finance-payout-cancel-confirm"
            >
              {cancelling && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
              Cancel payout
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
