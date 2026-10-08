import { useEffect, useState } from "react";
import { CalendarRange, Megaphone, Search, Target, User } from "lucide-react";
import { EmptyState } from "@/components/module/ModulePrimitives";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { fmtDate, inr, useResource } from "@/components/crm/crmShared";
import { ErrorBlock, RowSkeletons } from "@/components/crm/StateBlocks";
import { CHANNEL_LABELS, CampaignStatus, STATUS_KEYS, STATUS_META, channelList, roiText } from "./marketingShared";

const ALL = "all";

export default function CampaignList({ onOpenCampaign, onCreate, refreshKey, paused }) {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [mine, setMine] = useState(false);
  useEffect(() => { const id = setTimeout(() => setQ(search.trim()), 300); return () => clearTimeout(id); }, [search]);

  const params = { q: q || undefined, status: status || undefined, channel: channel || undefined, owner: mine ? "me" : undefined, _k: refreshKey };
  const { data, error, loading, reload } = useResource("/marketing/campaigns", params, { paused });
  const filtered = Boolean(q || status || channel || mine);

  return (
    <div className="space-y-4" data-testid="marketing-campaigns">
      <div className="flex flex-col lg:flex-row gap-2 lg:items-center">
        <div className="relative flex-1 min-w-0 lg:max-w-sm">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search campaigns…" className="pl-9 h-9" data-testid="campaign-search" />
        </div>
        <div className="grid grid-cols-2 sm:flex gap-2 sm:items-center">
          <Select value={status || ALL} onValueChange={(v) => setStatus(v === ALL ? "" : v)}>
            <SelectTrigger className="h-9 sm:w-[150px] text-[13px]" data-testid="campaign-filter-status"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              {STATUS_KEYS.map((s) => <SelectItem key={s} value={s}>{STATUS_META[s].label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={channel || ALL} onValueChange={(v) => setChannel(v === ALL ? "" : v)}>
            <SelectTrigger className="h-9 sm:w-[150px] text-[13px]" data-testid="campaign-filter-channel"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All channels</SelectItem>
              {Object.entries(CHANNEL_LABELS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
            </SelectContent>
          </Select>
          <div className="col-span-2 flex items-center gap-2 sm:ml-2">
            <Switch id="cmp-mine" checked={mine} onCheckedChange={setMine} />
            <Label htmlFor="cmp-mine" className="text-[13px] cursor-pointer">Owned by me</Label>
          </div>
        </div>
      </div>

      {error && !data ? (
        <ErrorBlock title="Couldn't load campaigns" error={error} onRetry={reload} />
      ) : !data ? (
        <RowSkeletons rows={5} />
      ) : data.length === 0 ? (
        <EmptyState icon={Megaphone} title={filtered ? "No campaigns match" : "No campaigns yet"}
                    description={filtered ? "Try other filters." : "Plan a campaign with a budget, channels, target cities and linked coupons."}
                    action={!filtered && onCreate} />
      ) : (
        <div className={cn("grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 transition-opacity", loading && "opacity-60")}>
          {data.map((c) => (
            <button key={c.id} type="button" onClick={() => onOpenCampaign(c.id)} data-testid="campaign-card"
                    className="text-left rounded-xl border border-border bg-card p-4 hover-lift flex flex-col focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-display text-[15px] font-semibold truncate">{c.name}</div>
                  <div className="text-[12px] text-muted-foreground truncate">{channelList(c.channels)}</div>
                </div>
                <CampaignStatus status={c.status} />
              </div>
              <div className="mt-3 space-y-1 text-[12px] text-muted-foreground">
                <div className="flex items-center gap-1.5"><CalendarRange className="h-3.5 w-3.5" />{fmtDate(c.start_date)} – {fmtDate(c.end_date)}</div>
                <div className="flex items-center gap-1.5 min-w-0"><Target className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{c.city_targets?.length ? c.city_targets.join(", ") : "All cities"}{c.audience_segment_name ? ` · ${c.audience_segment_name}` : ""}</span></div>
                <div className="flex items-center gap-1.5"><User className="h-3.5 w-3.5" />{c.owner_name || "—"}</div>
              </div>
              <div className="mt-4 pt-3 border-t border-border space-y-2">
                <div className="flex items-baseline justify-between text-[12.5px]">
                  <span className={cn("font-display font-semibold text-[15px] tabular-nums", c.over_budget && "text-destructive")}>{inr(c.spend)}</span>
                  <span className="text-muted-foreground">of {inr(c.budget)}</span>
                </div>
                <Progress value={Math.min(100, c.budget_used_pct ?? 0)} className="h-1.5" />
                {c.attribution.supported && (
                  <div className="flex justify-between text-[11.5px] text-muted-foreground pt-1">
                    <span>{c.attribution.bookings} bookings · {inr(c.attribution.revenue)}</span>
                    <span>ROI {roiText(c.attribution.roi)}</span>
                  </div>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
