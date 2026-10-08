import { useEffect, useState } from "react";
import { CalendarClock, Plus } from "lucide-react";
import { EmptyState } from "@/components/module/ModulePrimitives";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useResource } from "./crmShared";
import { ErrorBlock, RowSkeletons } from "./StateBlocks";
import { FollowupItem, useFollowupActions } from "./Customer360Sheet";
import FollowupDialog from "./FollowupDialog";

export default function FollowupsPanel({ canEdit, onOpenCustomer, refreshKey, onChanged }) {
  const [status, setStatus] = useState("open");
  const [mine, setMine] = useState(false);
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const { data, error, loading, reload } = useResource("/crm/followups", { status, mine: mine || undefined });
  useEffect(() => { if (refreshKey) reload({ background: true }); }, [refreshKey, reload]);
  // Completing / deleting / editing here also changes the overview's open & overdue counts.
  const changed = () => { reload({ background: true }); onChanged?.(); };
  const actions = useFollowupActions(changed);

  const overdue = data ? data.filter((f) => f.overdue).length : 0;

  return (
    <div className="space-y-4" data-testid="crm-followups">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <Tabs value={status} onValueChange={setStatus}>
          <TabsList className="bg-muted/60 p-1">
            <TabsTrigger value="open">Open</TabsTrigger>
            <TabsTrigger value="done">Done</TabsTrigger>
            <TabsTrigger value="all">All</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-2">
          {canEdit && (
            <Button size="sm" className="gap-1.5 mr-2" onClick={() => setCreating(true)} data-testid="crm-new-followup">
              <Plus className="h-4 w-4" /> New follow-up
            </Button>
          )}
          <Label htmlFor="fu-mine" className="text-[13px] cursor-pointer">Only mine</Label>
          <Switch id="fu-mine" checked={mine} onCheckedChange={setMine} data-testid="crm-followups-mine" />
        </div>
      </div>
      {status === "open" && overdue > 0 && (
        <div className="text-[12.5px] text-destructive font-medium">{overdue} overdue follow-up{overdue === 1 ? "" : "s"}</div>
      )}
      {error && !data ? (
        <ErrorBlock title="Couldn't load follow-ups" error={error} onRetry={reload} />
      ) : !data || (loading && !data) ? (
        <RowSkeletons rows={4} />
      ) : data.length === 0 ? (
        <EmptyState icon={CalendarClock} title={status === "done" ? "Nothing completed yet" : "No open follow-ups"}
                    description="Schedule a follow-up here or from a customer's profile; owners are notified."
                    action={canEdit && status !== "done" && (
                      <Button size="sm" className="gap-1.5" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New follow-up</Button>
                    )} />
      ) : (
        <ul className="space-y-2">
          {data.map((f) => (
            <FollowupItem key={f.id} f={f} canEdit={canEdit} busy={actions.busy} showCustomer onOpenCustomer={onOpenCustomer}
                          onToggle={actions.toggle} onDelete={actions.remove} onEdit={setEditing} />
          ))}
        </ul>
      )}
      <FollowupDialog open={Boolean(editing)} onOpenChange={(o) => !o && setEditing(null)} followup={editing}
                      customerName={editing?.customer_name} onSaved={changed} />
      <FollowupDialog open={creating} onOpenChange={setCreating} onSaved={changed} />
    </div>
  );
}
