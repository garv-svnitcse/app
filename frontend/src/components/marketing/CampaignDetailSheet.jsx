import { useState } from "react";
import { Info, Loader2, Pause, Pencil, Play, Rocket, Square, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtDate, inr, useResource } from "@/components/crm/crmShared";
import { ErrorBlock } from "@/components/crm/StateBlocks";
import { CampaignStatus, OBJECTIVE_LABELS, channelList, roiText } from "./marketingShared";

function Metric({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5 min-w-0">
      <div className="text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground truncate">{label}</div>
      <div className={cn("font-display text-[17px] font-semibold mt-0.5 truncate tabular-nums", tone)}>{value}</div>
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-3 py-2 text-[13px] border-b border-border last:border-0">
      <div className="text-muted-foreground">{label}</div>
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}

export default function CampaignDetailSheet({ campaignId, open, onOpenChange, canManage, onEdit, onChanged, refreshKey }) {
  const { data, error, loading, reload } = useResource(campaignId ? `/marketing/campaigns/${campaignId}` : null, { _k: refreshKey },
    { enabled: Boolean(open && campaignId) });
  const [busy, setBusy] = useState(false);
  const [spend, setSpend] = useState(null);
  const ready = data && data.id === campaignId;

  async function patch(body, ok) {
    setBusy(true);
    try {
      await api.patch(`/marketing/campaigns/${campaignId}`, body);
      toast.success(ok);
      reload({ background: true });
      onChanged?.();
      return true;
    } catch (e) {
      toast.error(formatApiError(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete “${data.name}”? This can't be undone.`)) return;
    setBusy(true);
    try {
      await api.delete(`/marketing/campaigns/${campaignId}`);
      toast.success("Campaign deleted");
      onChanged?.();
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveSpend(e) {
    e.preventDefault();
    const v = Number(spend);
    if (spend === "" || Number.isNaN(v) || v < 0) return toast.error("Spend must be ₹0 or more");
    if (await patch({ spend: v }, "Spend updated")) setSpend(null);
  }

  const a = ready ? data.attribution : null;
  const actions = ready && canManage ? [
    data.mode === "draft" && { label: "Launch", icon: Rocket, body: { mode: "live" }, ok: "Campaign launched" },
    data.mode === "live" && data.status !== "completed" && { label: "Pause", icon: Pause, body: { mode: "paused" }, ok: "Campaign paused" },
    data.mode === "paused" && { label: "Resume", icon: Play, body: { mode: "live" }, ok: "Campaign resumed" },
    ["live", "paused"].includes(data.mode) && data.status !== "completed" && { label: "End now", icon: Square, body: { mode: "completed" }, ok: "Campaign ended" },
  ].filter(Boolean) : [];

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) setSpend(null); onOpenChange(o); }}>
      <SheetContent side="right" className="w-full sm:max-w-xl p-0 overflow-y-auto" data-testid="campaign-sheet">
        {error && !ready ? (
          <div className="p-6 pt-12"><ErrorBlock title="Couldn't load this campaign" error={error} onRetry={reload} /></div>
        ) : !ready ? (
          <div className="p-6 space-y-4">
            <SheetHeader className="sr-only"><SheetTitle>Loading campaign</SheetTitle><SheetDescription>Loading</SheetDescription></SheetHeader>
            <Skeleton className="h-7 w-2/3" />
            <div className="grid grid-cols-2 gap-2">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>
            <Skeleton className="h-48" />
          </div>
        ) : (
          <div className={cn("p-5 sm:p-6 space-y-5 transition-opacity", loading && "opacity-70")}>
            <SheetHeader className="text-left space-y-1.5 pr-8">
              <div className="flex flex-wrap items-center gap-2">
                <CampaignStatus status={data.status} />
                <span className="text-[12px] text-muted-foreground">{OBJECTIVE_LABELS[data.objective] || data.objective}</span>
              </div>
              <SheetTitle className="font-display text-xl tracking-tight break-words">{data.name}</SheetTitle>
              <SheetDescription>{fmtDate(data.start_date)} – {fmtDate(data.end_date)} · {channelList(data.channels)}</SheetDescription>
            </SheetHeader>

            {canManage && (
              <div className="flex flex-wrap gap-2">
                {actions.map((x) => (
                  <Button key={x.label} size="sm" variant={x.label === "Launch" ? "default" : "outline"} className="gap-1.5" disabled={busy}
                          onClick={() => patch(x.body, x.ok)} data-testid={`campaign-action-${x.label.toLowerCase().replace(/\s/g, "-")}`}>
                    <x.icon className="h-3.5 w-3.5" /> {x.label}
                  </Button>
                ))}
                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => onEdit(data)} data-testid="campaign-edit">
                  <Pencil className="h-3.5 w-3.5" /> Edit
                </Button>
                <Button size="sm" variant="ghost" className="gap-1.5 text-destructive" disabled={busy} onClick={remove} data-testid="campaign-delete">
                  <Trash2 className="h-3.5 w-3.5" /> Delete
                </Button>
              </div>
            )}

            <div className="rounded-xl border border-border bg-card p-4 space-y-3">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Spend to date</div>
                  <div className={cn("font-display text-[22px] font-semibold tabular-nums", data.over_budget && "text-destructive")}>{inr(data.spend)}</div>
                </div>
                <div className="text-right text-[12.5px] text-muted-foreground">
                  of {inr(data.budget)} budget
                  {data.budget_used_pct !== null && <div className={cn("font-medium", data.over_budget ? "text-destructive" : "text-foreground")}>{data.budget_used_pct}% used</div>}
                </div>
              </div>
              <Progress value={Math.min(100, data.budget_used_pct ?? 0)} className="h-2" />
              {canManage && (spend === null ? (
                <Button size="sm" variant="ghost" className="h-7 px-2 -ml-2 text-primary" onClick={() => setSpend(String(data.spend ?? 0))} data-testid="campaign-update-spend">
                  Update spend
                </Button>
              ) : (
                <form onSubmit={saveSpend} className="flex gap-2">
                  <Input type="number" min="0" inputMode="decimal" value={spend} onChange={(e) => setSpend(e.target.value)} className="h-8" autoFocus aria-label="Spend to date in rupees" />
                  <Button type="submit" size="sm" className="h-8" disabled={busy}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}</Button>
                  <Button type="button" size="sm" variant="ghost" className="h-8" onClick={() => setSpend(null)}>Cancel</Button>
                </form>
              ))}
            </div>

            <section className="space-y-2">
              <h3 className="font-display text-[15px] font-semibold">Attribution</h3>
              {a.supported ? (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <Metric label="Attributed bookings" value={a.bookings} />
                    <Metric label="Attributed revenue" value={inr(a.revenue)} />
                    <Metric label="Cost per booking" value={inr(a.cost_per_booking)} />
                    <Metric label="ROI" value={roiText(a.roi)} tone={a.roi === null ? "" : a.roi >= 0 ? "text-success" : "text-destructive"} />
                  </div>
                  <p className="text-[12px] text-muted-foreground">
                    Bookings created between the start and end dates that used a linked coupon. Revenue counts confirmed, active and completed bookings.
                    {!data.coupon_codes?.length && " Link a coupon code to attribute bookings."}
                  </p>
                </>
              ) : (
                <div className="flex gap-2.5 rounded-lg border border-info/30 bg-info/5 p-3 text-[12.5px]" data-testid="campaign-attribution-unsupported">
                  <Info className="h-4 w-4 text-info shrink-0 mt-0.5" />
                  <span>{a.reason}</span>
                </div>
              )}
            </section>

            <section className="space-y-2">
              <h3 className="font-display text-[15px] font-semibold">
                Context{" "}
                <span className="text-[12px] font-normal text-muted-foreground">
                  (not attributed{data.market_context.cities.length ? " · target cities only" : ""})
                </span>
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <Metric label="Bookings in window" value={data.market_context.bookings} />
                <Metric label="Their revenue" value={inr(data.market_context.revenue)} />
              </div>
              {data.coupons.length > 0 && (
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {data.coupons.map((c) => (
                    <li key={c.code} className="flex items-center justify-between gap-3 px-3 py-2 text-[12.5px]">
                      <span className="font-mono font-medium">{c.code}</span>
                      <span className="text-muted-foreground text-right">
                        {c.discount_pct}% off · {c.used_count}{c.usage_limit ? ` / ${c.usage_limit}` : ""} redeemed (all-time){c.active === false ? " · inactive" : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-xl border border-border bg-card px-4 py-1">
              <Row label="Owner">{data.owner_name || "—"}</Row>
              <Row label="Audience">
                {data.audience_segment_name ? `${data.audience_segment_name}${data.audience_size !== undefined && data.audience_size !== null ? ` · ${data.audience_size} customers now` : ""}` : "No CRM segment"}
                {data.audience_note && <div className="text-muted-foreground text-[12.5px] mt-0.5">{data.audience_note}</div>}
              </Row>
              <Row label="Cities">{data.city_targets?.length ? data.city_targets.join(", ") : "All cities"}</Row>
              <Row label="Coupons">{data.coupon_codes?.length ? data.coupon_codes.join(", ") : "None linked"}</Row>
              {data.notes && <Row label="Notes"><span className="whitespace-pre-wrap">{data.notes}</span></Row>}
              <Row label="Created">{fmtDate(data.created_at, true)} · {data.created_by_name}</Row>
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
