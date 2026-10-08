import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/AuthContext";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { todayLocal } from "@/components/crm/crmShared";
import { useOwnerOptions } from "@/components/crm/FollowupDialog";
import { CHANNEL_LABELS, OBJECTIVE_LABELS } from "./marketingShared";

const NONE = "none";

function blank(userId) {
  return {
    name: "", objective: "acquisition", channels: [], audience_segment_id: "", audience_note: "", city_targets: [],
    budget: "", spend: "0", start_date: todayLocal(), end_date: todayLocal(30), mode: "draft", coupon_codes: [],
    owner_id: userId || "", notes: "",
  };
}

function fromCampaign(c) {
  return {
    name: c.name, objective: c.objective, channels: c.channels || [], audience_segment_id: c.audience_segment_id || "",
    audience_note: c.audience_note || "", city_targets: c.city_targets || [], budget: String(c.budget ?? ""),
    spend: String(c.spend ?? 0), start_date: c.start_date, end_date: c.end_date, mode: c.mode,
    coupon_codes: c.coupon_codes || [], owner_id: c.owner_id || "", notes: c.notes || "",
  };
}

// Selected values no longer offered (renamed / deleted in Marketplace) stay visible so they can be removed.
function withStale(options, value) {
  const known = new Set(options.map((o) => o.value));
  return [...options, ...value.filter((v) => !known.has(v)).map((v) => ({ value: v, label: `${v} (removed)` }))];
}

function Chips({ options, value, onChange, testid }) {
  const toggle = (v) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <div className="flex flex-wrap gap-1.5" data-testid={testid}>
      {options.map((o) => {
        const on = value.includes(o.value);
        return (
          <button key={o.value} type="button" aria-pressed={on} onClick={() => toggle(o.value)}
                  className={cn("h-7 px-2.5 rounded-md border text-[12.5px] transition-colors",
                    on ? "border-primary bg-primary/10 text-primary font-medium" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30")}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export default function CampaignDialog({ open, onOpenChange, campaign, meta, onSaved }) {
  const { user } = useAuth();
  const owners = useOwnerOptions("marketing.view", open);
  const [form, setForm] = useState(blank(user?.id));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(campaign ? fromCampaign(campaign) : blank(user?.id));
    setErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, campaign, user?.id]);

  const set = (k) => (e) => {
    const v = e?.target ? e.target.value : e;
    setForm((f) => ({ ...f, [k]: v }));
    setErrors((er) => ({ ...er, [k]: undefined, ...(k === "start_date" ? { end_date: undefined } : {}) }));
  };

  function validate() {
    const er = {};
    if (!form.name.trim()) er.name = "Name the campaign";
    if (!form.channels.length) er.channels = "Pick at least one channel";
    const budget = Number(form.budget);
    if (form.budget === "" || Number.isNaN(budget) || budget < 0) er.budget = "Budget must be ₹0 or more";
    const spend = Number(form.spend || 0);
    if (Number.isNaN(spend) || spend < 0) er.spend = "Spend must be ₹0 or more";
    if (!form.start_date) er.start_date = "Pick a start date";
    if (!form.end_date) er.end_date = "Pick an end date";
    else if (form.start_date && form.end_date < form.start_date) er.end_date = "End date must be on or after the start date";
    setErrors(er);
    return Object.keys(er).length === 0;
  }

  async function submit(e) {
    e.preventDefault();
    if (!validate()) return;
    setSaving(true);
    const body = {
      ...form,
      name: form.name.trim(),
      budget: Number(form.budget),
      spend: Number(form.spend || 0),
      audience_segment_id: form.audience_segment_id || null,
      audience_note: form.audience_note.trim() || null,
      notes: form.notes.trim() || null,
      owner_id: form.owner_id || null,
    };
    try {
      const { data } = campaign
        ? await api.patch(`/marketing/campaigns/${campaign.id}`, body)
        : await api.post("/marketing/campaigns", body);
      toast.success(campaign ? "Campaign updated" : "Campaign created");
      onSaved?.(data);
      onOpenChange(false);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const err = (k) => errors[k] && <p className="text-[12px] text-destructive">{errors[k]}</p>;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[92vh] overflow-y-auto" data-testid="campaign-dialog">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle className="font-display">{campaign ? "Edit campaign" : "New campaign"}</DialogTitle>
            <DialogDescription>Dates are in IST and inclusive. Status follows the dates once the campaign is launched.</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="grid grid-cols-1 sm:grid-cols-[1fr_180px] gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="cmp-name">Name</Label>
                <Input id="cmp-name" value={form.name} onChange={set("name")} maxLength={120} placeholder="e.g. Patna monsoon riders" data-testid="campaign-name" />
                {err("name")}
              </div>
              <div className="space-y-1.5">
                <Label>Objective</Label>
                <Select value={form.objective} onValueChange={set("objective")}>
                  <SelectTrigger data-testid="campaign-objective"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(meta?.objectives || Object.keys(OBJECTIVE_LABELS)).map((o) => <SelectItem key={o} value={o}>{OBJECTIVE_LABELS[o] || o}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Channels</Label>
              <Chips options={(meta?.channels || Object.keys(CHANNEL_LABELS)).map((c) => ({ value: c, label: CHANNEL_LABELS[c] || c }))}
                     value={form.channels} onChange={set("channels")} testid="campaign-channels" />
              {err("channels")}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="cmp-start">Start date</Label>
                <Input id="cmp-start" type="date" value={form.start_date} onChange={set("start_date")} data-testid="campaign-start" />
                {err("start_date")}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cmp-end">End date</Label>
                <Input id="cmp-end" type="date" value={form.end_date} min={form.start_date || undefined} onChange={set("end_date")} data-testid="campaign-end" />
                {err("end_date")}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cmp-budget">Budget (₹)</Label>
                <Input id="cmp-budget" type="number" min="0" inputMode="decimal" value={form.budget} onChange={set("budget")} data-testid="campaign-budget" />
                {err("budget")}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cmp-spend">Spend to date (₹)</Label>
                <Input id="cmp-spend" type="number" min="0" inputMode="decimal" value={form.spend} onChange={set("spend")} data-testid="campaign-spend" />
                {err("spend")}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Audience (CRM segment)</Label>
                <Select value={form.audience_segment_id || NONE} onValueChange={(v) => set("audience_segment_id")(v === NONE ? "" : v)}>
                  <SelectTrigger data-testid="campaign-segment"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>No segment</SelectItem>
                    {(meta?.segments || []).map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                    {meta && form.audience_segment_id && !(meta.segments || []).some((s) => s.id === form.audience_segment_id) && (
                      <SelectItem value={form.audience_segment_id}>{campaign?.audience_segment_name || "Segment"} (removed)</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Owner</Label>
                <Select value={form.owner_id || undefined} onValueChange={set("owner_id")}>
                  <SelectTrigger data-testid="campaign-owner"><SelectValue placeholder="Me" /></SelectTrigger>
                  <SelectContent>
                    {owners.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}{o.id === user?.id ? " (me)" : ""} · {o.role}</SelectItem>)}
                    {owners.length > 0 && form.owner_id && !owners.some((o) => o.id === form.owner_id) && (
                      <SelectItem value={form.owner_id}>{campaign?.owner_name || "Previous owner"} (inactive)</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cmp-aud">Audience notes (optional)</Label>
              <Input id="cmp-aud" value={form.audience_note} onChange={set("audience_note")} maxLength={500} placeholder="e.g. College students near Boring Road" />
            </div>

            <div className="space-y-1.5">
              <Label>Target cities <span className="text-muted-foreground font-normal">(none = all cities)</span></Label>
              {meta?.cities?.length || form.city_targets.length ? (
                <Chips options={withStale((meta?.cities || []).map((c) => ({ value: c, label: c })), form.city_targets)} value={form.city_targets} onChange={set("city_targets")} testid="campaign-cities" />
              ) : <p className="text-[12.5px] text-muted-foreground">No cities set up in Marketplace yet.</p>}
            </div>

            <div className="space-y-1.5">
              <Label>Linked coupon codes</Label>
              {meta?.coupons?.length || form.coupon_codes.length ? (
                <Chips options={withStale((meta?.coupons || []).map((c) => ({ value: c.code, label: `${c.code} · ${c.discount_pct}%${c.active === false ? " (inactive)" : ""}` })), form.coupon_codes)}
                       value={form.coupon_codes} onChange={set("coupon_codes")} testid="campaign-coupons" />
              ) : <p className="text-[12.5px] text-muted-foreground">No coupons in Marketplace yet.</p>}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-3">
              <div className="space-y-1.5">
                <Label>State</Label>
                <Select value={form.mode} onValueChange={set("mode")}>
                  <SelectTrigger data-testid="campaign-mode"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="draft">Draft</SelectItem>
                    <SelectItem value="live">Launched (follows dates)</SelectItem>
                    <SelectItem value="paused">Paused</SelectItem>
                    <SelectItem value="completed">Ended</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cmp-notes">Notes (optional)</Label>
                <Textarea id="cmp-notes" value={form.notes} onChange={set("notes")} rows={2} maxLength={5000} />
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="campaign-save">
              {saving && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}{campaign ? "Save changes" : "Create campaign"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
