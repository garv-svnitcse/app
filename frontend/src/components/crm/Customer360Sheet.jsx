import { useState } from "react";
import {
  Bike, CalendarClock, CheckCircle2, Circle, LifeBuoy, Loader2, Mail, MapPin, MessageSquare, Pencil, Phone, Pin, PinOff,
  Plus, ShieldCheck, Star, Tag, Trash2, X,
} from "lucide-react";
import { toast } from "sonner";
import { StatusPill } from "@/components/module/ModulePrimitives";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/contexts/AuthContext";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtDate, inr, initials, relativeDays, useResource } from "./crmShared";
import { ErrorBlock, LifecyclePill } from "./StateBlocks";
import FollowupDialog from "./FollowupDialog";
import CustomerDialog from "./CustomerDialog";

const TIMELINE_ICONS = {
  booking: { icon: Bike, cls: "bg-primary/10 text-primary" },
  ticket: { icon: LifeBuoy, cls: "bg-warning/10 text-warning" },
  kyc: { icon: ShieldCheck, cls: "bg-info/10 text-info" },
  review: { icon: Star, cls: "bg-warning/10 text-warning" },
  note: { icon: MessageSquare, cls: "bg-muted text-foreground/70" },
  followup: { icon: CalendarClock, cls: "bg-info/10 text-info" },
};

function Kpi({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5 min-w-0">
      <div className="text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground truncate">{label}</div>
      <div className="font-display text-[17px] font-semibold mt-0.5 truncate tabular-nums">{value}</div>
    </div>
  );
}

function TagEditor({ customerId, tags, suggestions, canEdit, onChanged }) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(next) {
    setSaving(true);
    try {
      const { data } = await api.put(`/crm/customers/${customerId}/tags`, { tags: next });
      onChanged(data.tags);
      setDraft("");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSaving(false);
    }
  }
  const add = (e) => {
    e.preventDefault();
    const t = draft.trim();
    if (!t) return;
    if (tags.some((x) => x.toLowerCase() === t.toLowerCase())) { setDraft(""); return; }
    save([...tags, t]);
  };
  const unused = (suggestions || []).filter((s) => !tags.some((t) => t.toLowerCase() === s.toLowerCase())).slice(0, 6);

  return (
    <div className="space-y-2" data-testid="crm-tags">
      <div className="flex flex-wrap items-center gap-1.5">
        <Tag className="h-3.5 w-3.5 text-muted-foreground" />
        {tags.length === 0 && <span className="text-[12.5px] text-muted-foreground">No tags</span>}
        {tags.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-md bg-primary/10 text-primary text-[12px] font-medium">
            {t}
            {canEdit && (
              <button type="button" aria-label={`Remove tag ${t}`} disabled={saving} onClick={() => save(tags.filter((x) => x !== t))}
                      className="rounded hover:bg-primary/20 p-0.5"><X className="h-3 w-3" /></button>
            )}
          </span>
        ))}
      </div>
      {canEdit && (
        <form onSubmit={add} className="flex flex-wrap items-center gap-1.5">
          <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a tag" maxLength={32}
                 className="h-8 w-40 text-[12.5px]" data-testid="crm-tag-input" />
          <Button type="submit" size="sm" variant="outline" className="h-8" disabled={saving || !draft.trim()}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Add"}
          </Button>
          {unused.map((s) => (
            <button key={s} type="button" disabled={saving} onClick={() => save([...tags, s])}
                    className="h-6 px-2 rounded-md border border-dashed border-border text-[11.5px] text-muted-foreground hover:text-foreground hover:border-foreground/40">
              + {s}
            </button>
          ))}
        </form>
      )}
    </div>
  );
}

function NotesPanel({ customerId, notes, canEdit, onChanged }) {
  const { user } = useAuth();
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(null);
  const [editBody, setEditBody] = useState("");
  const mayChange = (n) => canEdit && (n.author_id === user?.id || ["Founder", "Admin"].includes(user?.role));

  async function run(fn, ok) {
    setSaving(true);
    try { await fn(); if (ok) toast.success(ok); onChanged(); } catch (e) { toast.error(formatApiError(e)); } finally { setSaving(false); }
  }
  const add = (e) => {
    e.preventDefault();
    if (!body.trim()) return;
    run(async () => { await api.post(`/crm/customers/${customerId}/notes`, { body: body.trim() }); setBody(""); }, "Note added");
  };

  return (
    <div className="space-y-3">
      {canEdit && (
        <form onSubmit={add} className="space-y-2">
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} maxLength={5000}
                    placeholder="Log a call, preference or anything the team should know…" data-testid="crm-note-input" />
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={saving || !body.trim()} data-testid="crm-note-save">
              {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />} Add note
            </Button>
          </div>
        </form>
      )}
      {notes.length === 0 ? (
        <div className="text-[13px] text-muted-foreground text-center py-6">No notes yet.</div>
      ) : (
        <ul className="space-y-2">
          {notes.map((n) => (
            <li key={n.id} className={cn("rounded-lg border p-3", n.pinned ? "border-primary/40 bg-primary/5" : "border-border bg-card")}>
              <div className="flex items-start justify-between gap-2">
                <div className="text-[11.5px] text-muted-foreground">
                  <span className="font-medium text-foreground">{n.author_name}</span> · {fmtDate(n.created_at, true)}
                  {n.updated_at !== n.created_at && " · edited"}
                  {n.pinned && <span className="ml-1.5 text-primary font-medium">Pinned</span>}
                </div>
                {mayChange(n) && editing !== n.id && (
                  <div className="flex shrink-0 -mr-1 -mt-1">
                    <Button variant="ghost" size="icon" className="h-7 w-7" aria-label={n.pinned ? "Unpin" : "Pin"} disabled={saving}
                            onClick={() => run(() => api.patch(`/crm/notes/${n.id}`, { pinned: !n.pinned }))}>
                      {n.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Edit note"
                            onClick={() => { setEditing(n.id); setEditBody(n.body); }}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" aria-label="Delete note" disabled={saving}
                            onClick={() => { if (window.confirm("Delete this note?")) run(() => api.delete(`/crm/notes/${n.id}`), "Note deleted"); }}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </div>
              {editing === n.id ? (
                <div className="mt-2 space-y-2">
                  <Textarea value={editBody} onChange={(e) => setEditBody(e.target.value)} rows={3} maxLength={5000} />
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                    <Button size="sm" disabled={saving || !editBody.trim()}
                            onClick={() => run(async () => { await api.patch(`/crm/notes/${n.id}`, { body: editBody.trim() }); setEditing(null); }, "Note updated")}>
                      Save
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="text-[13px] mt-1.5 whitespace-pre-wrap break-words">{n.body}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FollowupItem({ f, canEdit, onToggle, onEdit, onDelete, showCustomer, onOpenCustomer, busy }) {
  return (
    <li className="flex items-start gap-3 rounded-lg border border-border bg-card p-3" data-testid="crm-followup-item">
      <button type="button" disabled={!canEdit || busy} onClick={() => onToggle(f)} aria-label={f.done ? "Mark as open" : "Mark as done"}
              className={cn("mt-0.5 shrink-0", f.done ? "text-success" : "text-muted-foreground hover:text-foreground", !canEdit && "cursor-default")}>
        {f.done ? <CheckCircle2 className="h-[18px] w-[18px]" /> : <Circle className="h-[18px] w-[18px]" />}
      </button>
      <div className="min-w-0 flex-1">
        <div className={cn("text-[13.5px] font-medium break-words", f.done && "line-through text-muted-foreground")}>{f.title}</div>
        <div className="text-[11.5px] text-muted-foreground mt-0.5 flex flex-wrap gap-x-2">
          {showCustomer && (
            <button type="button" className="text-primary hover:underline" onClick={() => onOpenCustomer(f.customer_id)}>{f.customer_name}</button>
          )}
          <span className={cn(f.overdue && "text-destructive font-medium")}>
            {f.done ? `Done ${fmtDate(f.done_at)}` : `${f.overdue ? "Overdue · was due" : "Due"} ${fmtDate(f.due_date)}`}
          </span>
          <span>· {f.owner_name}</span>
        </div>
        {f.notes && <p className="text-[12.5px] text-muted-foreground mt-1 whitespace-pre-wrap break-words">{f.notes}</p>}
      </div>
      {canEdit && (
        <div className="flex shrink-0 -mr-1 -mt-1">
          {!f.done && (
            <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Edit follow-up" onClick={() => onEdit(f)}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" aria-label="Delete follow-up" disabled={busy} onClick={() => onDelete(f)}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </li>
  );
}

export function useFollowupActions(onChanged) {
  const [busy, setBusy] = useState(false);
  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); onChanged(); } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  };
  return {
    busy,
    toggle: (f) => run(() => api.patch(`/crm/followups/${f.id}`, { done: !f.done }), f.done ? "Follow-up reopened" : "Follow-up completed"),
    remove: (f) => { if (window.confirm("Delete this follow-up?")) run(() => api.delete(`/crm/followups/${f.id}`), "Follow-up deleted"); },
  };
}

function Timeline({ items }) {
  if (items.length === 0) return <div className="text-[13px] text-muted-foreground text-center py-6">No activity yet.</div>;
  return (
    <ol className="relative space-y-4 before:absolute before:left-[15px] before:top-2 before:bottom-2 before:w-px before:bg-border" data-testid="crm-timeline">
      {items.map((i, idx) => {
        const meta = TIMELINE_ICONS[i.type] || TIMELINE_ICONS.note;
        const Icon = meta.icon;
        return (
          <li key={`${i.type}-${i.ref_id}-${idx}`} className="relative flex gap-3">
            <div className={cn("relative z-10 h-8 w-8 shrink-0 rounded-full flex items-center justify-center ring-4 ring-background", meta.cls)}>
              <Icon className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[13px] font-medium break-words">{i.title}</span>
                {i.status && <StatusPill status={i.status} />}
                {i.priority && <StatusPill status={i.priority} />}
              </div>
              <div className="text-[11.5px] text-muted-foreground mt-0.5">
                {fmtDate(i.at, true)}
                {i.amount !== undefined && i.amount !== null && ` · ${inr(i.amount)}`}
                {i.city && ` · ${i.city}`}
                {i.rating !== undefined && i.rating !== null && ` · ${i.rating}★`}
              </div>
              {i.detail && <p className="text-[12.5px] text-muted-foreground mt-1 whitespace-pre-wrap break-words line-clamp-4">{i.detail}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function Customer360Sheet({ customerId, open, onOpenChange, canEdit, tagSuggestions, cities, onChanged, onDeleted }) {
  const { data, error, loading, reload, setData } = useResource(customerId ? `/crm/customers/${customerId}` : null, null,
    { enabled: Boolean(open && customerId) });
  const [fuOpen, setFuOpen] = useState(false);
  const [fuEditing, setFuEditing] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const changed = () => { reload({ background: true }); onChanged?.(); };
  const actions = useFollowupActions(changed);
  const ready = data && data.customer?.id === customerId;
  const c = ready ? data.customer : null;
  const m = ready ? data.metrics : null;

  async function removeCustomer() {
    if (!window.confirm(`Delete ${c.name}? Their CRM notes, tags and follow-ups are deleted too. Customers with bookings or tickets can't be deleted.`)) return;
    setDeleting(true);
    try {
      await api.delete(`/crm/customers/${customerId}`);
      toast.success("Customer deleted");
      onDeleted?.();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl p-0 overflow-y-auto" data-testid="crm-customer-sheet">
        {error && !ready ? (
          <div className="p-6 pt-12"><ErrorBlock title="Couldn't load this customer" error={error} onRetry={reload} /></div>
        ) : !ready ? (
          <div className="p-6 space-y-4">
            <SheetHeader className="sr-only"><SheetTitle>Loading customer</SheetTitle><SheetDescription>Loading</SheetDescription></SheetHeader>
            <div className="flex gap-3 items-center"><Skeleton className="h-12 w-12 rounded-full" /><Skeleton className="h-6 w-48" /></div>
            <div className="grid grid-cols-3 gap-2">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>
            <Skeleton className="h-64" />
          </div>
        ) : (
          <div className={cn("transition-opacity", loading && "opacity-70")}>
            <div className="p-5 sm:p-6 border-b border-border space-y-4">
              <SheetHeader className="text-left space-y-0">
                <div className="flex items-start gap-3 pr-8">
                  <div className="h-12 w-12 rounded-full bg-primary/10 text-primary flex items-center justify-center font-display font-semibold shrink-0">
                    {initials(c.name)}
                  </div>
                  <div className="min-w-0">
                    <SheetTitle className="font-display text-xl tracking-tight break-words">{c.name}</SheetTitle>
                    <SheetDescription asChild>
                      <div className="flex flex-wrap items-center gap-1.5 mt-1">
                        <LifecyclePill stage={m.lifecycle} />
                        <StatusPill status={`kyc ${m.kyc_status}`} className={m.kyc_status === "approved" ? "bg-success/10 text-success" : m.kyc_status === "rejected" ? "bg-destructive/10 text-destructive" : "bg-warning/10 text-warning"} />
                        <span className="text-[12px] text-muted-foreground">Customer since {fmtDate(m.created_at)}</span>
                      </div>
                    </SheetDescription>
                  </div>
                </div>
              </SheetHeader>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px] text-muted-foreground">
                {c.email && <a href={`mailto:${c.email}`} className="inline-flex items-center gap-1.5 hover:text-foreground min-w-0"><Mail className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{c.email}</span></a>}
                {c.phone && <a href={`tel:${c.phone.replace(/\s/g, "")}`} className="inline-flex items-center gap-1.5 hover:text-foreground"><Phone className="h-3.5 w-3.5" />{c.phone}</a>}
                {c.city && <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" />{c.city}</span>}
              </div>
              {canEdit && (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={() => setEditOpen(true)} data-testid="crm-edit-customer">
                    <Pencil className="h-3.5 w-3.5" /> Edit details
                  </Button>
                  <Button size="sm" variant="ghost" className="h-8 gap-1.5 text-destructive" disabled={deleting} onClick={removeCustomer}
                          data-testid="crm-delete-customer">
                    {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />} Delete
                  </Button>
                </div>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <Kpi label="Lifetime value" value={inr(data.kpis.ltv)} />
                <Kpi label="Bookings" value={data.kpis.bookings} />
                <Kpi label="Avg booking" value={inr(data.kpis.avg_booking_value)} />
                <Kpi label="Last booking" value={relativeDays(m.days_since_last_booking)} />
                <Kpi label="Avg rating given" value={data.kpis.avg_rating === null ? "—" : `${data.kpis.avg_rating}★`} />
                <Kpi label="Open tickets" value={`${data.kpis.open_tickets} / ${data.kpis.total_tickets}`} />
              </div>
              <div className="text-[11.5px] text-muted-foreground">
                First booking {fmtDate(m.first_booking)} · {data.kpis.cancelled_bookings} cancelled booking{data.kpis.cancelled_bookings === 1 ? "" : "s"} (excluded)
              </div>
              <TagEditor customerId={customerId} tags={data.tags} suggestions={tagSuggestions} canEdit={canEdit}
                         onChanged={(tags) => { setData((d) => ({ ...d, tags, metrics: { ...d.metrics, tags } })); onChanged?.(); }} />
            </div>

            <Tabs defaultValue="timeline" className="p-5 sm:p-6">
              <TabsList className="bg-muted/60 p-1 w-full sm:w-auto grid grid-cols-3 sm:inline-flex">
                <TabsTrigger value="timeline" data-testid="crm-tab-timeline">Timeline</TabsTrigger>
                <TabsTrigger value="notes" data-testid="crm-tab-notes">Notes ({data.notes.length})</TabsTrigger>
                <TabsTrigger value="followups" data-testid="crm-tab-followups">
                  Follow-ups ({data.followups.filter((f) => !f.done).length})
                </TabsTrigger>
              </TabsList>
              <TabsContent value="timeline" className="mt-4"><Timeline items={data.timeline} /></TabsContent>
              <TabsContent value="notes" className="mt-4">
                <NotesPanel customerId={customerId} notes={data.notes} canEdit={canEdit} onChanged={changed} />
              </TabsContent>
              <TabsContent value="followups" className="mt-4 space-y-3">
                {canEdit && (
                  <Button size="sm" className="gap-1.5" onClick={() => { setFuEditing(null); setFuOpen(true); }} data-testid="crm-schedule-followup">
                    <Plus className="h-4 w-4" /> Schedule follow-up
                  </Button>
                )}
                {data.followups.length === 0 ? (
                  <div className="text-[13px] text-muted-foreground text-center py-6">No follow-ups scheduled.</div>
                ) : (
                  <ul className="space-y-2">
                    {data.followups.map((f) => (
                      <FollowupItem key={f.id} f={f} canEdit={canEdit} busy={actions.busy} onToggle={actions.toggle} onDelete={actions.remove}
                                    onEdit={(x) => { setFuEditing(x); setFuOpen(true); }} />
                    ))}
                  </ul>
                )}
              </TabsContent>
            </Tabs>
          </div>
        )}
        <FollowupDialog open={fuOpen} onOpenChange={setFuOpen} customerId={customerId} customerName={c?.name}
                        followup={fuEditing} onSaved={changed} />
        <CustomerDialog open={editOpen} onOpenChange={setEditOpen} customer={c} cities={cities} onSaved={changed} />
      </SheetContent>
    </Sheet>
  );
}
