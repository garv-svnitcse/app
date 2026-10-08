import { useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { useFinanceResource, LoadError, SkeletonBlocks, formatDate, todayIST } from "@/components/finance/financeShared";

// Same rule as the API: 2-digit state code + 13 alphanumerics.
const GSTIN_RE = /^[0-9]{2}[A-Z0-9]{10}[0-9A-Z]{3}$/;

const FIELDS = ["commission_pct", "gst_pct", "invoice_prefix", "prices_include_gst", "company_name",
  "company_gstin", "company_state", "billing_address"];

function fyNow() {
  const [y, m] = todayIST().split("-").map(Number);
  const start = m >= 4 ? y : y - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

export default function FinanceSettingsTab({ canManage }) {
  const { data, error, loading, reload } = useFinanceResource("/finance/settings");
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);

  // Sync the form from the server unless the user has unsaved edits.
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (data && !dirty) setForm(Object.fromEntries(FIELDS.map((k) => [k, data[k] ?? ""])));
  }, [data, dirty]);

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })); setDirty(true); }

  async function save() {
    setBusy(true);
    try {
      await api.put("/finance/settings", {
        ...form,
        commission_pct: Number(form.commission_pct),
        gst_pct: Number(form.gst_pct),
      });
      toast.success("Finance settings saved");
      setDirty(false); reload();
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  if (!data && error) return <LoadError error={error} onRetry={reload} loading={loading} what="finance settings" />;
  if (!form) return <SkeletonBlocks count={2} className="h-64" />;

  const ro = !canManage || busy;
  const pct = (v) => v !== "" && Number(v) >= 0 && Number(v) <= 100;
  const prefixOk = /^[A-Za-z0-9][A-Za-z0-9-]{0,15}$/.test((form.invoice_prefix || "").trim());
  const gstin = (form.company_gstin || "").trim();
  const gstinOk = !gstin || GSTIN_RE.test(gstin);
  const valid = pct(form.commission_pct) && pct(form.gst_pct) && prefixOk && gstinOk && (form.company_name || "").trim();

  return (
    <div className="space-y-4 max-w-4xl" data-testid="finance-settings">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[17px]">Commission & tax</CardTitle>
            <CardDescription>Editable defaults. Changes apply to new invoices and to bookings not yet in a payout.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <Label className="text-[12px]">Platform commission (%)</Label>
              <Input type="number" min={0} max={100} step="0.01" className="mt-1" value={form.commission_pct} disabled={ro}
                     onChange={(e) => set("commission_pct", e.target.value)} data-testid="finance-settings-commission" />
              {pct(form.commission_pct)
                ? <p className="text-[11.5px] text-muted-foreground mt-1">Vendors receive {(100 - Number(form.commission_pct)).toFixed(2).replace(/\.00$/, "")}% of booking revenue.</p>
                : <p className="text-[11.5px] text-destructive mt-1">Enter a percentage from 0 to 100.</p>}
            </div>
            <div>
              <Label className="text-[12px]">GST on invoices (%)</Label>
              <Input type="number" min={0} max={100} step="0.01" className="mt-1" value={form.gst_pct} disabled={ro}
                     onChange={(e) => set("gst_pct", e.target.value)} data-testid="finance-settings-gst" />
              {!pct(form.gst_pct) && <p className="text-[11.5px] text-destructive mt-1">Enter a percentage from 0 to 100.</p>}
            </div>
            <label className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
              <span>
                <span className="block text-[13px] font-medium text-foreground">Booking amounts include GST</span>
                <span className="block text-[12px] text-muted-foreground">
                  {form.prices_include_gst ? "Invoice total = booking amount; GST is carved out." : "GST is added on top of the booking amount."}
                </span>
              </span>
              <Switch checked={!!form.prices_include_gst} onCheckedChange={(v) => set("prices_include_gst", v)} disabled={ro} />
            </label>
            <div>
              <Label className="text-[12px]">Invoice prefix</Label>
              <Input className="mt-1" maxLength={16} value={form.invoice_prefix} disabled={ro}
                     onChange={(e) => set("invoice_prefix", e.target.value)} data-testid="finance-settings-prefix" />
              {prefixOk
                ? <p className="text-[11.5px] text-muted-foreground mt-1">Next numbers look like {form.invoice_prefix.trim()}/{fyNow()}/0001 · sequence restarts every April.</p>
                : <p className="text-[11.5px] text-destructive mt-1">Use letters, digits and hyphens only, starting with a letter or digit (max 16).</p>}
            </div>
          </CardContent>
        </Card>

        <Card className="border-border">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-[17px]">Billing details</CardTitle>
            <CardDescription>Printed on every invoice.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <Label className="text-[12px]">Legal name</Label>
              <Input className="mt-1" maxLength={200} value={form.company_name} disabled={ro} onChange={(e) => set("company_name", e.target.value)} />
            </div>
            <div>
              <Label className="text-[12px]">GSTIN (optional)</Label>
              <Input className="mt-1 uppercase" maxLength={15} value={form.company_gstin} disabled={ro} placeholder="15-character GSTIN"
                     onChange={(e) => set("company_gstin", e.target.value.toUpperCase())} aria-invalid={!gstinOk}
                     data-testid="finance-settings-gstin" />
              {!gstinOk && <p className="text-[11.5px] text-destructive mt-1">GSTIN must be 15 characters, e.g. 10ABCDE1234F1Z5.</p>}
            </div>
            <div>
              <Label className="text-[12px]">Registered state (optional)</Label>
              <Input className="mt-1" maxLength={60} value={form.company_state} disabled={ro} placeholder="e.g. Bihar"
                     onChange={(e) => set("company_state", e.target.value)} />
              <p className="text-[11.5px] text-muted-foreground mt-1">Bookings in another state are billed with IGST; same state (or unset) with CGST + SGST.</p>
            </div>
            <div>
              <Label className="text-[12px]">Billing address (optional)</Label>
              <Textarea rows={3} className="mt-1" maxLength={500} value={form.billing_address} disabled={ro} onChange={(e) => set("billing_address", e.target.value)} />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="text-[12px] text-muted-foreground">
          {data.updated_at ? `Last updated by ${data.updated_by || "—"} on ${formatDate(data.updated_at)}.` : "Using default settings — nothing saved yet."}
        </div>
        {canManage && (
          <div className="flex gap-2">
            {dirty && <Button variant="outline" onClick={() => setDirty(false)} disabled={busy}>Discard</Button>}
            <Button onClick={save} disabled={busy || !dirty || !valid} data-testid="finance-settings-save">
              {busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}Save settings
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
