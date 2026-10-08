import { useState } from "react";
import { ArrowRight, Layers, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/module/ModulePrimitives";
import { Button } from "@/components/ui/button";
import { api, formatApiError } from "@/lib/api";
import { inr } from "./crmShared";
import { ErrorBlock, RowSkeletons } from "./StateBlocks";
import { describeFilters } from "./SegmentDialog";

export default function SegmentsPanel({ segments, error, reload, canEdit, onCreate, onEdit, onView, onDeleted }) {
  const [busy, setBusy] = useState(null);

  async function remove(s) {
    if (!window.confirm(`Delete the segment “${s.name}”? Customers are not affected.`)) return;
    setBusy(s.id);
    try {
      await api.delete(`/crm/segments/${s.id}`);
      toast.success("Segment deleted");
      onDeleted?.(s);
      reload();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setBusy(null);
    }
  }

  if (error && !segments) return <ErrorBlock title="Couldn't load segments" error={error} onRetry={reload} />;
  if (!segments) return <RowSkeletons rows={4} />;

  return (
    <div className="space-y-4" data-testid="crm-segments">
      {canEdit && segments.length > 0 && (
        <div className="flex justify-end">
          <Button size="sm" className="gap-1.5" onClick={onCreate} data-testid="crm-new-segment"><Plus className="h-4 w-4" /> New segment</Button>
        </div>
      )}
      {segments.length === 0 ? (
        <EmptyState icon={Layers} title="No segments yet"
                    description="Save a set of filters — for example at-risk customers in Patna — and track its size over time."
                    action={canEdit && <Button size="sm" className="gap-1.5" onClick={onCreate}><Plus className="h-4 w-4" /> New segment</Button>} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {segments.map((s) => (
            <div key={s.id} className="rounded-xl border border-border bg-card p-4 flex flex-col hover-lift" data-testid="crm-segment-card">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-display text-[15px] font-semibold truncate">{s.name}</div>
                  <div className="text-[12px] text-muted-foreground mt-0.5">{describeFilters(s.filters)}</div>
                </div>
                {canEdit && (
                  <div className="flex shrink-0 -mr-1.5 -mt-1">
                    <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Edit segment" onClick={() => onEdit(s)}><Pencil className="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" aria-label="Delete segment" disabled={busy === s.id} onClick={() => remove(s)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </div>
              {s.description && <p className="text-[12.5px] text-muted-foreground mt-2 line-clamp-2">{s.description}</p>}
              <div className="flex items-end justify-between mt-4 pt-3 border-t border-border">
                <div>
                  <div className="font-display text-[22px] font-semibold tabular-nums leading-none">{s.count.toLocaleString("en-IN")}</div>
                  <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground mt-1">customers · {inr(s.ltv)} LTV</div>
                </div>
                <Button variant="ghost" size="sm" className="gap-1 text-primary" onClick={() => onView(s)}>
                  View <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
