import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, Loader2, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatApiError } from "@/lib/api";
import { toast } from "sonner";
import {
  inr, formatDate, todayIST, currentMonthIST, recentMonths, monthLabel, useFinanceResource, downloadCsv,
  TableSkeleton, TH, categoryLabel,
} from "@/components/finance/financeShared";

export const LEDGER_KINDS = {
  bill: "Bill",
  bill_payment: "Bill payment",
  payout: "Booking payout",
  payout_payment: "Payout transfer",
};

// While mounted, printing shows only the statement (same approach as InvoicePrint).
const PRINT_ID = "wg-vendor-statement-print";
const PRINT_CSS = `
#${PRINT_ID} { display: none; }
@media print {
  body > *:not(#${PRINT_ID}) { display: none !important; }
  #${PRINT_ID} { display: block !important; color: #111; background: #fff; font-family: Inter, system-ui, sans-serif; }
  @page { size: A4; margin: 14mm; }
}
`;

function SumRow({ label, value, strong }) {
  return (
    <tr>
      <td style={{ padding: "4px 0", color: strong ? "#111" : "#555", fontWeight: strong ? 600 : 400 }}>{label}</td>
      <td style={{ padding: "4px 0", textAlign: "right", fontWeight: strong ? 700 : 500 }}>{value}</td>
    </tr>
  );
}

export function VendorStatementDocument({ statement: st }) {
  const co = st.company || {};
  const v = st.vendor || {};
  const cell = { padding: "6px 6px", borderBottom: "1px solid #e5e7eb", fontSize: 11.5, verticalAlign: "top" };
  const num = { ...cell, textAlign: "right", whiteSpace: "nowrap" };
  return (
    <div style={{ maxWidth: 760, margin: "0 auto", fontSize: 12, lineHeight: 1.45 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 24, borderBottom: "2px solid #0F8D52", paddingBottom: 12 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0F8D52" }}>{co.company_name}</div>
          {co.billing_address && <div style={{ whiteSpace: "pre-line", color: "#444" }}>{co.billing_address}</div>}
          {co.company_gstin && <div style={{ color: "#444" }}>GSTIN: {co.company_gstin}</div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: 1 }}>VENDOR STATEMENT</div>
          <div style={{ marginTop: 4 }}><b>Period</b> {formatDate(st.from)} – {formatDate(st.to)}</div>
          <div style={{ color: "#666" }}>Generated {formatDate(st.generated_at)}</div>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 24, marginTop: 14 }}>
        <div>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 1, color: "#666" }}>Vendor</div>
          <div style={{ fontWeight: 600 }}>{v.name}</div>
          {v.contact_person && <div>{v.contact_person}</div>}
          {v.address && <div style={{ whiteSpace: "pre-line" }}>{v.address}</div>}
          {v.email && <div>{v.email}</div>}
          {v.phone && <div>{v.phone}</div>}
          {v.tax_id && <div>GSTIN / tax id: {v.tax_id}</div>}
        </div>
        <table style={{ width: 260 }}>
          <tbody>
            <SumRow label={`Opening outstanding (${formatDate(st.from)})`} value={inr(st.opening_balance)} />
            <SumRow label={`Charges (${st.charges_count})`} value={inr(st.charges)} />
            <SumRow label={`Payments (${st.payments_count})`} value={`− ${inr(st.payments)}`} />
            <SumRow label={`Closing outstanding (${formatDate(st.to)})`} value={inr(st.closing_balance)} strong />
          </tbody>
        </table>
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 16 }}>
        <thead>
          <tr style={{ background: "#f3f4f6" }}>
            <th style={{ ...cell, textAlign: "left" }}>Date</th>
            <th style={{ ...cell, textAlign: "left" }}>Details</th>
            <th style={{ ...num }}>Charges</th>
            <th style={{ ...num }}>Payments</th>
            <th style={{ ...num }}>Balance</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={cell}>{formatDate(st.from)}</td>
            <td style={{ ...cell, fontWeight: 600 }}>Opening balance</td>
            <td style={num} /><td style={num} />
            <td style={{ ...num, fontWeight: 600 }}>{inr(st.opening_balance)}</td>
          </tr>
          {st.lines.map((ln) => (
            <tr key={`${ln.kind}-${ln.id}`}>
              <td style={{ ...cell, whiteSpace: "nowrap" }}>{formatDate(ln.date)}</td>
              <td style={cell}>
                <div style={{ fontWeight: 500 }}>{ln.description}</div>
                <div style={{ color: "#666" }}>{LEDGER_KINDS[ln.kind]}{ln.reference ? ` · ${ln.reference}` : ""}</div>
              </td>
              <td style={num}>{ln.charge ? inr(ln.charge) : ""}</td>
              <td style={num}>{ln.payment ? inr(ln.payment) : ""}</td>
              <td style={num}>{inr(ln.balance)}</td>
            </tr>
          ))}
          <tr style={{ background: "#f9fafb" }}>
            <td style={cell}>{formatDate(st.to)}</td>
            <td style={{ ...cell, fontWeight: 600 }}>Closing balance</td>
            <td style={{ ...num, fontWeight: 600 }}>{inr(st.charges)}</td>
            <td style={{ ...num, fontWeight: 600 }}>{inr(st.payments)}</td>
            <td style={{ ...num, fontWeight: 700 }}>{inr(st.closing_balance)}</td>
          </tr>
        </tbody>
      </table>
      <div style={{ marginTop: 28, color: "#888", fontSize: 10 }}>
        Charges are vendor bills (by bill date) and linked booking payouts; cancelled bills are excluded.
        This is a computer-generated statement.
      </div>
    </div>
  );
}

/** Mount with a statement to print it; calls onDone after the print dialog closes. */
export function VendorStatementPrint({ statement, onDone }) {
  useEffect(() => {
    if (!statement) return undefined;
    const after = () => onDone?.();
    window.addEventListener("afterprint", after);
    const t = setTimeout(() => window.print(), 50);
    return () => { clearTimeout(t); window.removeEventListener("afterprint", after); };
  }, [statement, onDone]);

  if (!statement) return null;
  return createPortal(
    <div id={PRINT_ID}>
      <style>{PRINT_CSS}</style>
      <VendorStatementDocument statement={statement} />
    </div>,
    document.body,
  );
}

function Figure({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted-foreground">{label}</div>
      <div className={`font-display text-[16px] font-semibold mt-0.5 tabular-nums ${tone || "text-foreground"}`}>{value}</div>
    </div>
  );
}

/**
 * Per-vendor statement for a month or a custom from/to range: opening and closing outstanding,
 * charges and payments in the period, running ledger, CSV export and print.
 * `version` changes whenever the parent data changes (e.g. a bill was paid) to trigger a reload.
 */
export default function VendorStatementPanel({ vendorId, version }) {
  const [applied, setApplied] = useState({ month: currentMonthIST() });
  const [custom, setCustom] = useState(null); // { from, to } while editing a custom range
  const [exporting, setExporting] = useState(false);
  const [printing, setPrinting] = useState(null);
  const donePrint = useCallback(() => setPrinting(null), []);
  const { data, error, loading, reload } = useFinanceResource(`/finance/vendors/${vendorId}/statement`, applied);

  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    reload();
  }, [version]); // eslint-disable-line react-hooks/exhaustive-deps

  const today = todayIST();
  const customValid = custom && custom.from && custom.to && custom.from <= custom.to;
  const mode = custom || !applied.month ? "custom" : applied.month;

  function pickMode(value) {
    if (value === "custom") {
      setCustom({ from: data?.from || `${currentMonthIST()}-01`, to: data?.to || today });
    } else {
      setCustom(null);
      setApplied({ month: value });
    }
  }

  function applyCustom() {
    if (!customValid) return;
    setApplied({ from: custom.from, to: custom.to });
    setCustom(null);
  }

  async function exportCsv() {
    setExporting(true);
    const name = (data?.vendor?.name || "vendor").replace(/[^A-Za-z0-9]+/g, "-").toLowerCase();
    try {
      await downloadCsv(`/finance/vendors/${vendorId}/statement/export`, applied,
        `wavygo-vendor-statement-${name}-${data?.from || ""}-to-${data?.to || ""}.csv`);
    } catch (e) { toast.error(formatApiError(e)); } finally { setExporting(false); }
  }

  return (
    <div className="space-y-3" data-testid="finance-vendor-statement">
      <div className="flex flex-col sm:flex-row gap-2 sm:items-center justify-between">
        <Select value={mode} onValueChange={pickMode}>
          <SelectTrigger className="h-9 w-full sm:w-[170px]" data-testid="finance-vendor-statement-period"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="custom">{!custom && !applied.month && data ? data.label : "Custom range…"}</SelectItem>
            {recentMonths(24).map((m) => <SelectItem key={m} value={m}>{monthLabel(m)}</SelectItem>)}
          </SelectContent>
        </Select>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-9" onClick={exportCsv} disabled={!data || exporting}
                  data-testid="finance-vendor-statement-export">
            {exporting ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Download className="h-4 w-4 mr-1.5" />}CSV
          </Button>
          <Button variant="outline" size="sm" className="h-9" onClick={() => setPrinting(data)} disabled={!data}
                  data-testid="finance-vendor-statement-print">
            <Printer className="h-4 w-4 mr-1.5" />Print
          </Button>
        </div>
      </div>

      {custom && (
        <div className="flex flex-col sm:flex-row gap-2 sm:items-end rounded-lg border border-border p-3">
          <label className="flex-1 text-[11.5px] text-muted-foreground">
            From
            <Input type="date" value={custom.from} max={today} className="h-9 mt-1"
                   onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} data-testid="finance-vendor-statement-from" />
          </label>
          <label className="flex-1 text-[11.5px] text-muted-foreground">
            To
            <Input type="date" value={custom.to} min={custom.from || undefined} className="h-9 mt-1"
                   onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} data-testid="finance-vendor-statement-to" />
          </label>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" className="h-9" onClick={() => setCustom(null)}>Cancel</Button>
            <Button size="sm" className="h-9" onClick={applyCustom} disabled={!customValid} data-testid="finance-vendor-statement-apply">Apply</Button>
          </div>
        </div>
      )}

      {!data && error ? (
        <div className="text-[13px] text-destructive border border-dashed border-border rounded-lg p-6 text-center">
          {error}
          <div><Button variant="outline" size="sm" className="h-8 mt-3 text-xs" onClick={reload} disabled={loading}>Retry</Button></div>
        </div>
      ) : !data ? (
        <TableSkeleton rows={4} />
      ) : (
        <>
          <div className="text-[12px] text-muted-foreground">
            {data.label} · {formatDate(data.from)} – {formatDate(data.to)}
            {error && <span className="text-destructive"> · Refresh failed: {error}</span>}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Figure label="Opening outstanding" value={inr(data.opening_balance)} />
            <Figure label={`Charges · ${data.charges_count}`} value={inr(data.charges)} />
            <Figure label={`Payments · ${data.payments_count}`} value={inr(data.payments)} tone="text-success" />
            <Figure label="Closing outstanding" value={inr(data.closing_balance)}
                    tone={data.closing_balance > 0 ? "text-warning" : undefined} />
          </div>
          {data.lines.length === 0 ? (
            <div className="text-[13px] text-muted-foreground border border-dashed border-border rounded-lg p-6 text-center">
              No bills, payouts or payments in this period.
            </div>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={TH}>Date</TableHead>
                    <TableHead className={TH}>Details</TableHead>
                    <TableHead className={`${TH} text-right`}>Amount</TableHead>
                    <TableHead className={`${TH} text-right`}>Balance</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.lines.map((ln) => (
                    <TableRow key={`${ln.kind}-${ln.id}`} data-testid="finance-vendor-statement-line">
                      <TableCell className="whitespace-nowrap text-[12.5px]">{formatDate(ln.date)}</TableCell>
                      <TableCell className="text-[12.5px] min-w-[150px]">
                        <div className="text-foreground">{ln.description}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {LEDGER_KINDS[ln.kind]}{ln.reference ? ` · ${ln.reference}` : ""}
                          {ln.kind === "bill" && ln.category ? ` · ${categoryLabel(ln.category)}` : ""}
                          {ln.overdue ? <span className="text-destructive"> · overdue</span> : null}
                        </div>
                      </TableCell>
                      <TableCell className={`text-right whitespace-nowrap text-[12.5px] font-medium ${ln.payment ? "text-success" : ""}`}>
                        {ln.payment ? `− ${inr(ln.payment)}` : inr(ln.charge)}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap text-[12.5px]">{inr(ln.balance)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}
      <VendorStatementPrint statement={printing} onDone={donePrint} />
    </div>
  );
}
