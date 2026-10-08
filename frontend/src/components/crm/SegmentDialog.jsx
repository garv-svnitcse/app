import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, formatApiError } from "@/lib/api";
import { LIFECYCLE, LIFECYCLE_KEYS } from "./crmShared";

const ANY = "any";
const FILTER_KEYS = ["q", "city", "kyc_status", "lifecycle", "tag", "min_ltv", "min_bookings"];

function toForm(seg, initialFilters) {
  const f = seg?.filters || initialFilters || {};
  return {
    name: seg?.name || "",
    description: seg?.description || "",
    ...Object.fromEntries(FILTER_KEYS.map((k) => [k, f[k] === undefined || f[k] === null ? "" : String(f[k])])),
  };
}

export function describeFilters(f = {}) {
  const parts = [];
  if (f.lifecycle) parts.push(LIFECYCLE[f.lifecycle]?.label || f.lifecycle);
  if (f.city) parts.push(f.city);
  if (f.kyc_status) parts.push(`KYC ${f.kyc_status}`);
  if (f.tag) parts.push(`#${f.tag}`);
  if (f.min_ltv) parts.push(`LTV ≥ ₹${Number(f.min_ltv).toLocaleString("en-IN")}`);
  if (f.min_bookings) parts.push(`≥ ${f.min_bookings} bookings`);
  if (f.q) parts.push(`“${f.q}”`);
  return parts.join(" · ") || "All customers";
}

export default function SegmentDialog({ open, onOpenChange, segment, initialFilters, meta, onSaved }) {
  const [form, setForm] = useState(toForm(null));
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (open) setForm(toForm(segment, initialFilters)); }, [open, segment, initialFilters]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target ? e.target.value : e === ANY ? "" : e }));
  const pick = (k, placeholder, options) => (
    <Select value={form[k] || ANY} onValueChange={set(k)}>
      <SelectTrigger className="h-9"><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        <SelectItem value={ANY}>{placeholder}</SelectItem>
        {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );

  async function submit(e) {
    e.preventDefault();
    const filters = {};
    for (const k of FILTER_KEYS) {
      const v = form[k].trim();
      if (!v) continue;
      filters[k] = k === "min_ltv" ? Number(v) : k === "min_bookings" ? parseInt(v, 10) : v;
      if ((k === "min_ltv" || k === "min_bookings") && (Number.isNaN(filters[k]) || filters[k] < 0)) {
        return toast.error(`${k === "min_ltv" ? "Minimum LTV" : "Minimum bookings"} must be a positive number`);
      }
    }
    if (!form.name.trim()) return toast.error("Name the segment");
    if (!Object.keys(filters).length) return toast.error("Pick at least one filter");
    setSaving(true);
    try {
      const body = { name: form.name.trim(), description: form.description.trim() || null, filters };
      const { data } = segment ? await api.patch(`/crm/segments/${segment.id}`, body) : await api.post("/crm/segments", body);
      toast.success(segment ? "Segment updated" : `Segment saved · ${data.count} customers`);
      onSaved?.(data);
      onOpenChange(false);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[92vh] overflow-y-auto">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle className="font-display">{segment ? "Edit segment" : "New segment"}</DialogTitle>
            <DialogDescription>A saved filter. Its customer count updates live as bookings come in.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="seg-name">Name</Label>
              <Input id="seg-name" value={form.name} onChange={set("name")} maxLength={80} placeholder="e.g. Patna repeat riders" data-testid="crm-segment-name" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="seg-desc">Description (optional)</Label>
              <Input id="seg-desc" value={form.description} onChange={set("description")} maxLength={500} />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Lifecycle stage</Label>
                {pick("lifecycle", "Any stage", LIFECYCLE_KEYS.map((k) => ({ value: k, label: LIFECYCLE[k].label })))}</div>
              <div className="space-y-1.5"><Label>City</Label>
                {pick("city", "Any city", (meta?.cities || []).map((c) => ({ value: c, label: c })))}</div>
              <div className="space-y-1.5"><Label>KYC</Label>
                {pick("kyc_status", "Any KYC", ["pending", "approved", "rejected"].map((k) => ({ value: k, label: k[0].toUpperCase() + k.slice(1) })))}</div>
              <div className="space-y-1.5"><Label>Tag</Label>
                {pick("tag", "Any tag", (meta?.tags || []).map((t) => ({ value: t, label: t })))}</div>
              <div className="space-y-1.5"><Label htmlFor="seg-ltv">Minimum LTV (₹)</Label>
                <Input id="seg-ltv" type="number" min="0" step="any" inputMode="decimal" value={form.min_ltv} onChange={set("min_ltv")} /></div>
              <div className="space-y-1.5"><Label htmlFor="seg-bk">Minimum bookings</Label>
                <Input id="seg-bk" type="number" min="0" step="1" inputMode="numeric" value={form.min_bookings} onChange={set("min_bookings")} /></div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="seg-q">Name / email / phone contains (optional)</Label>
              <Input id="seg-q" value={form.q} onChange={set("q")} maxLength={100} />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="crm-segment-save">
              {saving && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}{segment ? "Save" : "Create segment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
