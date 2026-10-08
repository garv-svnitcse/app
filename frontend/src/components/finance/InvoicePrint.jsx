import { useEffect } from "react";
import { createPortal } from "react-dom";
import { inr, formatDate } from "@/components/finance/financeShared";

// While mounted, printing shows only the invoice: every other child of <body> (app root, dialogs) is hidden.
const PRINT_CSS = `
#wg-invoice-print { display: none; }
@media print {
  body > *:not(#wg-invoice-print) { display: none !important; }
  #wg-invoice-print { display: block !important; color: #111; background: #fff; font-family: Inter, system-ui, sans-serif; }
  @page { size: A4; margin: 14mm; }
}
`;

function Row({ label, value, strong }) {
  return (
    <tr>
      <td style={{ padding: "4px 0", color: strong ? "#111" : "#555", fontWeight: strong ? 600 : 400 }}>{label}</td>
      <td style={{ padding: "4px 0", textAlign: "right", fontWeight: strong ? 700 : 500 }}>{value}</td>
    </tr>
  );
}

export function InvoiceDocument({ invoice: inv }) {
  const co = inv.company || {};
  const cell = { padding: "8px 6px", borderBottom: "1px solid #e5e7eb", fontSize: 12, verticalAlign: "top" };
  return (
    <div style={{ maxWidth: 760, margin: "0 auto", fontSize: 12, lineHeight: 1.45 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 24, borderBottom: "2px solid #0F8D52", paddingBottom: 12 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0F8D52" }}>{co.company_name}</div>
          {co.billing_address && <div style={{ whiteSpace: "pre-line", color: "#444" }}>{co.billing_address}</div>}
          {co.company_state && <div style={{ color: "#444" }}>State: {co.company_state}</div>}
          {co.company_gstin && <div style={{ color: "#444" }}>GSTIN: {co.company_gstin}</div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: 1 }}>{inv.status === "draft" ? "DRAFT INVOICE" : "TAX INVOICE"}</div>
          <div style={{ marginTop: 4 }}><b>No.</b> {inv.number || "Not issued"}</div>
          <div><b>Date</b> {formatDate(inv.invoice_date)}</div>
          {inv.status === "void" && <div style={{ color: "#b91c1c", fontWeight: 700 }}>VOID — {inv.void_reason}</div>}
          {inv.status === "paid" && <div style={{ color: "#0F8D52", fontWeight: 700 }}>PAID</div>}
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 24, marginTop: 14 }}>
        <div>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 1, color: "#666" }}>Bill to</div>
          <div style={{ fontWeight: 600 }}>{inv.customer_name}</div>
          {inv.customer_email && <div>{inv.customer_email}</div>}
          {inv.customer_phone && <div>{inv.customer_phone}</div>}
          {inv.customer_city && <div>{inv.customer_city}</div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 1, color: "#666" }}>Place of supply</div>
          <div>{inv.place_of_supply || inv.city || "—"}</div>
          <div style={{ color: "#666", marginTop: 4 }}>Booking ref {inv.booking_id}</div>
        </div>
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 16 }}>
        <thead>
          <tr style={{ background: "#f3f4f6" }}>
            <th style={{ ...cell, textAlign: "left" }}>Description</th>
            <th style={{ ...cell, textAlign: "left" }}>SAC</th>
            <th style={{ ...cell, textAlign: "right" }}>Qty</th>
            <th style={{ ...cell, textAlign: "right" }}>Rate</th>
            <th style={{ ...cell, textAlign: "right" }}>Taxable value</th>
          </tr>
        </thead>
        <tbody>
          {(inv.line_items || []).map((li, i) => (
            <tr key={i}>
              <td style={cell}>
                <div style={{ fontWeight: 500 }}>{li.description}</div>
                {li.detail && <div style={{ color: "#666" }}>{li.detail}</div>}
              </td>
              <td style={cell}>{li.sac}</td>
              <td style={{ ...cell, textAlign: "right" }}>{li.quantity}</td>
              <td style={{ ...cell, textAlign: "right" }}>{inr(li.unit_price)}</td>
              <td style={{ ...cell, textAlign: "right" }}>{inr(li.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
        <table style={{ width: 280 }}>
          <tbody>
            <Row label="Taxable value" value={inr(inv.subtotal)} />
            {inv.gst_type === "igst"
              ? <Row label={`IGST @ ${inv.gst_pct}%`} value={inr(inv.igst)} />
              : <>
                  <Row label={`CGST @ ${inv.gst_pct / 2}%`} value={inr(inv.cgst)} />
                  <Row label={`SGST @ ${inv.gst_pct / 2}%`} value={inr(inv.sgst)} />
                </>}
            <Row label="Total" value={inr(inv.total)} strong />
          </tbody>
        </table>
      </div>

      {inv.payment && (
        <div style={{ marginTop: 12, color: "#444" }}>
          Received on {formatDate(inv.payment.paid_on)} via {inv.payment.method.replace(/_/g, " ")}
          {inv.payment.reference ? ` (ref ${inv.payment.reference})` : ""}.
        </div>
      )}
      {inv.notes && <div style={{ marginTop: 8, color: "#444" }}>Note: {inv.notes}</div>}
      <div style={{ marginTop: 28, color: "#888", fontSize: 10 }}>
        {inv.prices_include_gst ? "Booking amount is inclusive of GST. " : ""}This is a computer-generated invoice.
      </div>
    </div>
  );
}

/** Mount with an invoice to print it; calls onDone after the print dialog closes. */
export default function InvoicePrint({ invoice, onDone }) {
  useEffect(() => {
    if (!invoice) return undefined;
    const after = () => onDone?.();
    window.addEventListener("afterprint", after);
    const t = setTimeout(() => window.print(), 50);
    return () => { clearTimeout(t); window.removeEventListener("afterprint", after); };
  }, [invoice, onDone]);

  if (!invoice) return null;
  return createPortal(
    <div id="wg-invoice-print">
      <style>{PRINT_CSS}</style>
      <InvoiceDocument invoice={invoice} />
    </div>,
    document.body,
  );
}
