import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/AuthContext";
import { can } from "@/constants/permissions";
import { api, formatApiError } from "@/lib/api";
import { todayLocal } from "./crmShared";

/** Active users who may own a record in `module` (by the module's view action). */
export function useOwnerOptions(action, open = true) {
  const [people, setPeople] = useState([]);
  useEffect(() => {
    if (!open) return;
    api.get("/users/directory").then(({ data }) => setPeople(data)).catch(() => setPeople([]));
  }, [open]);
  return useMemo(() => people.filter((p) => can(p.role, action)), [people, action]);
}

/** Customers matching a search, for picking who a new follow-up is with. */
function useCustomerOptions(q, enabled) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    const id = setTimeout(() => {
      api.get("/crm/customers", { params: { q: q.trim() || undefined, sort: "name", order: "asc", page_size: 50 }, signal: controller.signal })
        .then(({ data }) => setItems(data.items))
        .catch(() => { if (!controller.signal.aborted) setItems([]); });
    }, 250);
    return () => { clearTimeout(id); controller.abort(); };
  }, [q, enabled]);
  return items;
}

/** Create (customerId, or pick a customer when none is given) or edit (followup) a CRM follow-up. */
export default function FollowupDialog({ open, onOpenChange, customerId, customerName, followup, onSaved }) {
  const { user } = useAuth();
  const owners = useOwnerOptions("crm.view", open);
  const [form, setForm] = useState({ title: "", due_date: todayLocal(1), owner_id: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const pickCustomer = open && !followup && !customerId;
  const [customerQ, setCustomerQ] = useState("");
  const [picked, setPicked] = useState(null);
  const found = useCustomerOptions(customerQ, pickCustomer);
  // Keep the chosen customer selectable even when a new search no longer lists it.
  const customerOptions = picked && !found.some((c) => c.id === picked.id) ? [picked, ...found] : found;
  const pickedId = picked?.id || "";

  useEffect(() => {
    if (!open) return;
    setCustomerQ("");
    setPicked(null);
    setForm(followup
      ? { title: followup.title, due_date: followup.due_date, owner_id: followup.owner_id, notes: followup.notes || "" }
      : { title: "", due_date: todayLocal(1), owner_id: user?.id || "", notes: "" });
  }, [open, followup, user]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target ? e.target.value : e }));

  async function submit(e) {
    e.preventDefault();
    const targetId = customerId || pickedId;
    if (!followup && !targetId) return toast.error("Pick the customer this follow-up is with");
    if (!form.title.trim()) return toast.error("Give the follow-up a title");
    if (!form.due_date) return toast.error("Pick a due date");
    setSaving(true);
    try {
      const body = { title: form.title.trim(), due_date: form.due_date, owner_id: form.owner_id || null, notes: form.notes.trim() || null };
      const { data } = followup
        ? await api.patch(`/crm/followups/${followup.id}`, body)
        : await api.post(`/crm/customers/${targetId}/followups`, body);
      toast.success(followup ? "Follow-up updated" : "Follow-up scheduled");
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
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle className="font-display">{followup ? "Edit follow-up" : "Schedule follow-up"}</DialogTitle>
            <DialogDescription>
              {customerName ? `With ${customerName}. ` : ""}The owner is notified when someone else assigns it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            {pickCustomer && (
              <div className="space-y-1.5">
                <Label htmlFor="fu-customer-q">Customer</Label>
                <Input id="fu-customer-q" value={customerQ} onChange={(e) => setCustomerQ(e.target.value)}
                       placeholder="Search name, email or phone…" className="h-9" data-testid="crm-followup-customer-search" />
                <Select value={pickedId || undefined} onValueChange={(id) => setPicked(customerOptions.find((c) => c.id === id) || null)}>
                  <SelectTrigger data-testid="crm-followup-customer"><SelectValue placeholder="Select a customer" /></SelectTrigger>
                  <SelectContent>
                    {customerOptions.length === 0 && <div className="px-2 py-1.5 text-[12.5px] text-muted-foreground">No customers found</div>}
                    {customerOptions.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}{c.city ? ` · ${c.city}` : ""}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="fu-title">What needs to happen</Label>
              <Input id="fu-title" value={form.title} onChange={set("title")} maxLength={200} placeholder="e.g. Call about monthly plan renewal" data-testid="crm-followup-title" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="fu-due">Due date</Label>
                <Input id="fu-due" type="date" value={form.due_date} onChange={set("due_date")} data-testid="crm-followup-due" />
              </div>
              <div className="space-y-1.5">
                <Label>Owner</Label>
                <Select value={form.owner_id || undefined} onValueChange={set("owner_id")}>
                  <SelectTrigger data-testid="crm-followup-owner"><SelectValue placeholder="Me" /></SelectTrigger>
                  <SelectContent>
                    {owners.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}{o.id === user?.id ? " (me)" : ""} · {o.role}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fu-notes">Notes (optional)</Label>
              <Textarea id="fu-notes" value={form.notes} onChange={set("notes")} rows={3} maxLength={2000} />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="crm-followup-save">
              {saving && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}{followup ? "Save" : "Schedule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
