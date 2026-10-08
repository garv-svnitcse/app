import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader, StatCard, StatusPill, EmptyState } from "@/components/module/ModulePrimitives";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Target, Plus, Trophy, Calendar as CalendarIcon, ExternalLink, Trash2, User, Loader2 } from "lucide-react";
import { useLiveRefresh } from "@/hooks/useLiveRefresh";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { usePermission } from "@/hooks/usePermission";
import { useAuth } from "@/contexts/AuthContext";

const OPP_TYPES = ["Grant", "Investor", "Accelerator", "Incubator", "Competition", "Government Scheme", "Tender", "CSR", "Partnership", "Workshop", "Conference"];
const STATUSES = ["open", "assigned", "in_progress", "won", "lost", "closed"];
const EMPTY_FORM = { title: "", type: "Grant", description: "", organisation: "", deadline: "", value_lakhs: 0, status: "open", assignee_id: "", link: "", notes: "", documents: "" };
// Fields the PATCH endpoint accepts; Employees (assignees) may only send the last three.
const EDIT_FIELDS = ["title", "type", "description", "organisation", "deadline", "value_lakhs", "link", "assignee_id", "status", "notes", "documents"];
const EMPLOYEE_FIELDS = ["status", "notes", "documents"];
const UNASSIGNED = "none";

// Server row -> controlled form values (never null in inputs); documents are edited one link per line.
function toForm(o) {
  return {
    title: o.title || "", type: o.type || "Grant", description: o.description || "", organisation: o.organisation || "",
    deadline: o.deadline || "", value_lakhs: typeof o.value_lakhs === "number" ? o.value_lakhs : 0, status: o.status || "open",
    assignee_id: o.assignee_id || "", link: o.link || "", notes: o.notes || "", documents: (o.documents || []).join("\n"),
  };
}

// "YYYY-MM-DD" deadlines are calendar days: parse them as local dates, not UTC midnight.
function parseDate(s) {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function initials(name) { return (name || "?").split(" ").map(s => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase(); }

export default function OpportunityHub() {
  const { can, role } = usePermission();
  const { user: me } = useAuth();
  const canCreate = can("opportunity.create");
  const canAssign = can("opportunity.assign");
  const canDelete = can("opportunity.delete");
  const oppTitle = role === "Employee" ? "My Opportunities" : role === "Intern" ? "Assigned Opportunities" : "Opportunity Hub";
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [stats, setStats] = useState(null);
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [highlightId, setHighlightId] = useState(null);

  async function load({ background = false } = {}) {
    try {
      const [{ data: o }, { data: u }, { data: s }] = await Promise.all([
        api.get("/opportunities?limit=300"),
        api.get("/users/directory").catch(() => ({ data: [] })),
        api.get("/opportunities/stats/overview").catch(() => ({ data: null })),
      ]);
      setRows(o || []); setUsers(u || []); setStats(s || null);
    } catch (e) {
      if (!background) toast.error(formatApiError(e));
    }
  }
  const [searchParams, setSearchParams] = useSearchParams();
  useLiveRefresh(load, 60000);

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (searchParams.get("create") === "opportunity" || searchParams.get("action") === "create-opportunity") {
      if (canCreate) {
        setEditing(null);
        setForm(EMPTY_FORM);
        setOpen(true);
      }
      setSearchParams(params => {
        params.delete("create");
        params.delete("action");
        return params;
      }, { replace: true });
    }
  }, [searchParams, setSearchParams, canCreate]);

  // ?opp=<id> (notification / email links) opens that opportunity and highlights its card.
  useEffect(() => {
    const oppId = searchParams.get("opp");
    if (!oppId) return;
    (async () => {
      try {
        const { data } = await api.get(`/opportunities/${oppId}`);
        setTypeFilter("all"); setStatusFilter("all"); setQ("");
        setHighlightId(data.id);
        if (data.can_edit !== false) edit(data);
      } catch (e) {
        toast.error(formatApiError(e) || "Could not open this opportunity.");
      } finally {
        // Remove the param (also on failure) so it is not retried on every URL change.
        setSearchParams(params => { params.delete("opp"); return params; }, { replace: true });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, setSearchParams]);

  // Scroll the highlighted card into view once it is rendered; the highlight fades after a few seconds.
  useEffect(() => {
    if (!highlightId || !rows.some(r => r.id === highlightId)) return undefined;
    document.getElementById(`opp-${highlightId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = setTimeout(() => setHighlightId(null), 4000);
    return () => clearTimeout(t);
  }, [highlightId, rows]);

  // Managers may only assign within their own department (the server enforces the same rule).
  const assignees = useMemo(
    () => (role === "Manager" ? users.filter(u => u.id === me?.id || (me?.department && u.department === me.department)) : users),
    [users, role, me]
  );

  const filtered = useMemo(() => {
    return rows.filter(r => {
      if (typeFilter !== "all" && r.type !== typeFilter) return false;
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (q && !JSON.stringify(r).toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
  }, [rows, q, typeFilter, statusFilter]);

  async function submit() {
    if (!fieldsLocked && !form.title.trim()) {
      toast.error("Please enter a title");
      return;
    }
    setSubmitting(true);
    try {
      const values = {
        ...form,
        title: form.title.trim(),
        assignee_id: form.assignee_id || null,
        deadline: form.deadline || null,
        documents: form.documents.split("\n").map(s => s.trim()).filter(Boolean),
      };
      if (editing) {
        // Send only editable fields (never id / assignee_name / created_by / timestamps).
        const allowed = fieldsLocked ? EMPLOYEE_FIELDS : EDIT_FIELDS.filter(k => canAssign || k !== "assignee_id");
        await api.patch(`/opportunities/${editing.id}`, Object.fromEntries(allowed.map(k => [k, values[k]])));
      } else {
        const { notes, documents, ...create } = values;
        await api.post("/opportunities", create);
      }
      toast.success(editing ? "Opportunity updated" : "Opportunity logged");
      setOpen(false); setEditing(null);
      setForm(EMPTY_FORM);
      load();
    } catch (e) { toast.error(formatApiError(e)); } finally { setSubmitting(false); }
  }

  async function setStatus(id, status) {
    setActionLoadingId(`status-${id}-${status}`);
    try { await api.patch(`/opportunities/${id}/status`, { status }); toast.success(`Opportunity → ${status.replace("_", " ")}`); load(); }
    catch (e) { toast.error(formatApiError(e)); } finally { setActionLoadingId(null); }
  }

  async function assign(id, assignee_id) {
    setActionLoadingId(`assign-${id}`);
    try { await api.post(`/opportunities/${id}/assign`, { assignee_id }); toast.success("Assigned"); load(); }
    catch (e) { toast.error(formatApiError(e)); } finally { setActionLoadingId(null); }
  }

  async function del(id) {
    if (!confirm("Delete this opportunity?")) return;
    setActionLoadingId(`del-${id}`);
    try { await api.delete(`/opportunities/${id}`); toast.success("Deleted"); load(); }
    catch (e) { toast.error(formatApiError(e)); } finally { setActionLoadingId(null); }
  }

  function edit(o) { setEditing(o); setForm(toForm(o)); setOpen(true); }

  const fieldsLocked = !!editing && role === "Employee";

  return (
    <div data-testid="opportunity-page">
      <PageHeader
        eyebrow="Module"
        title={oppTitle}
        description="Track every grant, investor conversation, tender, partnership and CSR deal in one place."
        actions={canCreate && <Button onClick={() => { setEditing(null); setForm(EMPTY_FORM); setOpen(true); }} data-testid="opp-create-btn"><Plus className="h-4 w-4 mr-1.5" /> Log opportunity</Button>}
      />

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-6">
          <StatCard label="Open" value={stats.open} icon={Target} tone="info" />
          <StatCard label="Assigned" value={stats.assigned} icon={User} tone="info" />
          <StatCard label="In progress" value={stats.in_progress} icon={Target} tone="warning" />
          <StatCard label="Won" value={stats.won} icon={Trophy} tone="success" />
          <StatCard label="Lost" value={stats.lost} icon={Target} tone="danger" />
          <StatCard label="Closed" value={stats.closed ?? 0} icon={Target} />
          <StatCard label="Assigned to me" value={stats.mine} icon={User} />
          <StatCard label="Pipeline value" value={`₹${stats.pipeline_lakhs ?? 0}L`} sub="Active" icon={Target} tone="info" />
          <StatCard label="Won value" value={`₹${stats.won_lakhs ?? 0}L`} icon={Trophy} tone="success" />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <Input placeholder="Search opportunities…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-sm" data-testid="opp-search" />
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-[180px]"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All types</SelectItem>{OPP_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[160px]"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All statuses</SelectItem>{STATUSES.map(s => <SelectItem key={s} value={s} className="capitalize">{s.replace("_", " ")}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={Target} title="No opportunities match" description="Log the first opportunity or clear filters." />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map(o => (
            <Card key={o.id} id={`opp-${o.id}`} className={`border-border hover-lift ${highlightId === o.id ? "ring-2 ring-primary" : ""}`}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Badge variant="secondary" className="text-[10px] mb-2">{o.type}</Badge>
                    <CardTitle className="font-display text-[15.5px] leading-snug">{o.title}</CardTitle>
                    {o.organisation && <div className="text-[11.5px] text-muted-foreground mt-1">{o.organisation}</div>}
                  </div>
                  <StatusPill status={o.status} />
                </div>
              </CardHeader>
              <CardContent className="pt-0 space-y-3">
                {o.description && <p className="text-[12.5px] text-muted-foreground line-clamp-2">{o.description}</p>}
                <div className="flex items-center justify-between text-[12px]">
                  {o.deadline && <div className="inline-flex items-center gap-1.5 text-muted-foreground"><CalendarIcon className="h-3 w-3" /> {parseDate(o.deadline)?.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</div>}
                  {o.value_lakhs ? <div className="font-semibold text-primary">₹{o.value_lakhs}L</div> : <div />}
                </div>
                <div className="flex items-center justify-between border-t border-border pt-3">
                  <div className="flex items-center gap-2">
                    {o.assignee_name ? (
                      <><Avatar className="h-6 w-6"><AvatarImage src={o.assignee_photo || undefined} /><AvatarFallback className="text-[9px] bg-wavygo-100 text-wavygo-800">{initials(o.assignee_name)}</AvatarFallback></Avatar>
                        <span className="text-[12px]">{o.assignee_name}</span></>
                    ) : !canAssign || o.can_edit === false ? (
                      <span className="text-[12px] text-muted-foreground">Unassigned</span>
                    ) : (
                      <Select value="" onValueChange={(v) => assign(o.id, v)} disabled={actionLoadingId === `assign-${o.id}`}>
                        <SelectTrigger className="h-7 text-[11px] w-[140px]"><SelectValue placeholder="Assign…" /></SelectTrigger>
                        <SelectContent>{assignees.map(u => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}</SelectContent>
                      </Select>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    {o.link ? (
                      <a href={o.link.startsWith("http") ? o.link : `https://${o.link}`} target="_blank" rel="noreferrer" className="text-muted-foreground hover:text-foreground p-1.5 rounded hover:bg-muted" title="Open opportunity link">
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    ) : (
                      <button type="button" onClick={() => toast.info("No external link provided for this opportunity")} className="text-muted-foreground/40 hover:text-muted-foreground p-1.5 rounded hover:bg-muted" title="No external link">
                        <ExternalLink className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {o.can_edit !== false && <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => edit(o)}>{role === "Employee" ? "Update" : "Edit"}</Button>}
                    {canDelete && (
                      <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive" onClick={() => del(o.id)} disabled={actionLoadingId === `del-${o.id}`}>
                        {actionLoadingId === `del-${o.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                      </Button>
                    )}
                  </div>
                </div>
                {o.can_edit !== false && <div className="flex flex-wrap gap-1 pt-1">
                  {STATUSES.filter(s => s !== o.status).map(s => {
                    const isStatusLoading = actionLoadingId === `status-${o.id}-${s}`;
                    return (
                      <Button key={s} size="sm" variant="outline" className="h-6 text-[10.5px] px-1.5 capitalize" onClick={() => setStatus(o.id, s)} disabled={isStatusLoading || !!actionLoadingId}>
                        {isStatusLoading ? <Loader2 className="h-2.5 w-2.5 animate-spin mr-1" /> : null}
                        {s.replace("_", " ")}
                      </Button>
                    );
                  })}
                </div>}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? "Edit opportunity" : "Log new opportunity"}</DialogTitle>
            <DialogDescription>Every opportunity you log publishes to Activity Logs and notifies the assignee.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {fieldsLocked && <div className="rounded-md border border-border bg-muted/40 p-2.5 text-[12px] text-muted-foreground">As the assignee, you can update the status, notes and documents.</div>}
            <div><Label>Title</Label><Input disabled={fieldsLocked || submitting} value={form.title} onChange={(e) => setForm(s => ({ ...s, title: e.target.value }))} data-testid="opp-title-input" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Type</Label>
                <Select value={form.type} onValueChange={(v) => setForm(s => ({ ...s, type: v }))} disabled={fieldsLocked || submitting}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{OPP_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div><Label>Organisation</Label><Input disabled={fieldsLocked || submitting} value={form.organisation} onChange={(e) => setForm(s => ({ ...s, organisation: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Deadline</Label><Input disabled={fieldsLocked || submitting} type="date" value={form.deadline || ""} onChange={(e) => setForm(s => ({ ...s, deadline: e.target.value }))} /></div>
              <div><Label>Value (₹ Lakhs)</Label><Input disabled={fieldsLocked || submitting} type="number" step="0.5" value={form.value_lakhs} onChange={(e) => setForm(s => ({ ...s, value_lakhs: parseFloat(e.target.value) || 0 }))} /></div>
            </div>
            <div><Label>External Link / Portal</Label><Input disabled={fieldsLocked || submitting} value={form.link} onChange={(e) => setForm(s => ({ ...s, link: e.target.value }))} placeholder="https://..." /></div>
            <div><Label>Description</Label><Textarea disabled={fieldsLocked || submitting} rows={3} value={form.description} onChange={(e) => setForm(s => ({ ...s, description: e.target.value }))} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Status</Label>
                <Select value={form.status} onValueChange={(v) => setForm(s => ({ ...s, status: v }))} disabled={submitting}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{STATUSES.map(s => <SelectItem key={s} value={s} className="capitalize">{s.replace("_", " ")}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Assignee</Label>
                <Select value={form.assignee_id || UNASSIGNED} onValueChange={(v) => setForm(s => ({ ...s, assignee_id: v === UNASSIGNED ? "" : v }))} disabled={fieldsLocked || !canAssign || submitting}>
                  <SelectTrigger><SelectValue placeholder="Optional" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNASSIGNED}>Unassigned</SelectItem>
                    {assignees.map(u => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {editing && (
              <>
                <div><Label>Notes</Label><Textarea disabled={submitting} rows={2} value={form.notes} onChange={(e) => setForm(s => ({ ...s, notes: e.target.value }))} data-testid="opp-notes-input" /></div>
                <div><Label>Documents (one link per line)</Label><Textarea disabled={submitting} rows={2} value={form.documents} onChange={(e) => setForm(s => ({ ...s, documents: e.target.value }))} placeholder="https://..." data-testid="opp-documents-input" /></div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submit} disabled={submitting} data-testid="opp-submit-btn">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {editing ? "Save changes" : "Log opportunity"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
