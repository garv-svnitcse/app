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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Users, Plus, UserPlus, Building2, CalendarDays, Award, KeyRound, Mail, Copy, Check, Trash2, Pencil, Power, UserMinus, CheckCircle2, Loader2 } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { toast } from "sonner";

function initials(name) {
  return (name || "?").split(" ").map(s => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

function getInviteLink(token) {
  if (!token) return "";
  const origin = typeof window !== "undefined" && window.location.origin ? window.location.origin : "https://app-eta-flax-97.vercel.app";
  return `${origin}/accept-invite?token=${token}`;
}

function Directory() {
  const { can, role } = usePermission();
  const canInvite = can("employee.invite");
  const canEdit = can("employee.edit");
  const canReset = can("auth.reset_other_password");
  const canManageAccount = role === "Founder" || role === "Admin";
  const [rows, setRows] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", role: "Employee", designation: "", department: "", phone: "" });
  const [resetInfo, setResetInfo] = useState(null);
  const [editingUser, setEditingUser] = useState(null);
  const [editForm, setEditForm] = useState({ name: "", role: "Employee", designation: "", department: "", phone: "" });

  const [createdInvite, setCreatedInvite] = useState(null);
  const [copied, setCopied] = useState(false);
  const [actionLoadingKey, setActionLoadingKey] = useState(null);

  const load = () => {
    api.get("/employees").then(({ data }) => setRows(data)).catch(() => {});
    api.get("/employees/invitations").then(({ data }) => setInvitations(data)).catch(() => {});
  };

  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (searchParams.get("create") === "invite" || searchParams.get("action") === "invite-teammate") {
      setCreatedInvite(null);
      setForm({ email: "", name: "", role: "Employee", designation: "", department: "", phone: "" });
      setOpen(true);
      setSearchParams(params => {
        params.delete("create");
        params.delete("action");
        return params;
      }, { replace: true });
    }
  }, [searchParams]);

  const filtered = useMemo(() => {
    if (!q) return rows;
    const t = q.toLowerCase();
    return rows.filter(r => (r.name + r.email + (r.designation || "") + (r.department || "")).toLowerCase().includes(t));
  }, [rows, q]);

  const pendingInvs = useMemo(() => invitations.filter(i => i.status === "pending"), [invitations]);

  async function invite() {
    if (!form.name || !form.name.trim()) {
      toast.error("Please enter the teammate's full name");
      return;
    }
    if (!form.email || !form.email.trim() || !form.email.includes("@")) {
      toast.error("Please enter a valid email address");
      return;
    }
    setActionLoadingKey("invite");
    try {
      const { data } = await api.post("/employees/invite", form);
      const url = getInviteLink(data.token);
      setCreatedInvite({ ...data, invite_url: url });
      toast.success(data.message || `Invitation email sent to ${form.email}`);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  function copyInviteUrl(url) {
    navigator.clipboard.writeText(url);
    setCopied(true);
    toast.success("Invitation link copied to clipboard!");
    setTimeout(() => setCopied(false), 2500);
  }

  async function resendInvite(inv) {
    const targetId = inv.id || inv._id || inv.token;
    const key = `resend-${targetId}`;
    setActionLoadingKey(key);
    try {
      const { data } = await api.post(`/employees/invitations/${targetId}/resend`);
      toast.success(data.message || `Invitation email resent to ${inv.email}`);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  async function deleteInvite(inv) {
    if (!window.confirm(`Are you sure you want to delete the pending invitation for ${inv.email}?`)) return;
    const targetId = inv.id || inv._id || inv.token;
    const key = `del-inv-${targetId}`;
    setActionLoadingKey(key);
    try {
      const { data } = await api.delete(`/employees/invitations/${targetId}`);
      toast.success(data.message || "Pending invitation deleted");
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  async function resetPassword(u) {
    const key = `reset-${u.id}`;
    setActionLoadingKey(key);
    try {
      const { data } = await api.post(`/employees/${u.id}/reset-password`);
      setResetInfo({ email: u.email, password: data.temp_password });
      toast.success("Password reset");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  async function toggleEmployeeStatus(u) {
    const targetId = u.id || u._id || u.email;
    const isCurrentlyDeactivated = u.status === "deactivated" || u.is_active === false;
    const actionText = isCurrentlyDeactivated ? "activate" : "deactivate";
    if (!window.confirm(`Are you sure you want to ${actionText} ${u.name}? ${!isCurrentlyDeactivated ? "They will be unable to log in until reactivated." : ""}`)) return;

    const key = `status-${targetId}`;
    setActionLoadingKey(key);
    try {
      const newStatus = isCurrentlyDeactivated ? "active" : "deactivated";
      const { data } = await api.patch(`/employees/${targetId}/status`, { status: newStatus });
      toast.success(data.message || `Employee ${u.name} status updated.`);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  async function deleteEmployee(u) {
    const targetId = u.id || u._id || u.email;
    if (!window.confirm(`Are you sure you want to remove ${u.name}?\n\nNote: Only their login ID & password credentials will be removed. All assigned tasks, submitted data, and activity logs will remain intact.`)) return;

    const key = `del-emp-${targetId}`;
    setActionLoadingKey(key);
    try {
      const { data } = await api.delete(`/employees/${targetId}`);
      toast.success(data.message || `Removed employee ${u.name}.`);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  function startEdit(u) {
    setEditingUser(u);
    setEditForm({
      name: u.name || "",
      role: u.role || "Employee",
      designation: u.designation || "",
      department: u.department || "",
      phone: u.phone || ""
    });
  }

  async function saveEdit() {
    if (!editingUser) return;
    setActionLoadingKey("save-edit");
    try {
      const { data } = await api.patch(`/employees/${editingUser.id}`, editForm);
      toast.success(`Updated profile for ${data.name || editingUser.name}`);
      setEditingUser(null);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  return (
    <>
      <div className="flex flex-col sm:flex-row gap-2 items-start sm:items-center justify-between mb-4">
        <Input placeholder="Search by name, email, role, department…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-md" data-testid="employee-search" />
        {canInvite && <Button onClick={() => { setCreatedInvite(null); setForm({ email: "", name: "", role: "Employee", designation: "", department: "", phone: "" }); setOpen(true); }} data-testid="employee-invite-btn"><UserPlus className="h-4 w-4 mr-1.5" /> Invite teammate</Button>}
      </div>

      {pendingInvs.length > 0 && (
        <Card className="border-amber-500/20 bg-amber-500/5 mb-6">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-amber-700 dark:text-amber-400 flex items-center gap-2">
              <Mail className="h-4 w-4" /> Pending Invitations ({pendingInvs.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="divide-y divide-amber-500/10">
              {pendingInvs.map(inv => {
                const link = getInviteLink(inv.token);
                const targetId = inv.id || inv._id || inv.token;
                const isResending = actionLoadingKey === `resend-${targetId}`;
                const isDeleting = actionLoadingKey === `del-inv-${targetId}`;

                return (
                  <div key={targetId} className="py-2.5 flex items-center justify-between gap-4 text-xs">
                    <div>
                      <span className="font-medium text-foreground">{inv.name}</span>
                      <span className="text-muted-foreground ml-2">({inv.email})</span>
                      <Badge variant="outline" className="ml-2 text-[10px] uppercase">{inv.role}</Badge>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => copyInviteUrl(link)}>
                        <Copy className="h-3 w-3 mr-1" /> Copy Link
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs border-amber-500/30 text-amber-700 dark:text-amber-300 hover:bg-amber-500/10"
                        onClick={() => resendInvite(inv)}
                        disabled={isResending || !!actionLoadingKey}
                      >
                        {isResending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                        Resend Email
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-500/10"
                        onClick={() => deleteInvite(inv)}
                        disabled={isDeleting || !!actionLoadingKey}
                      >
                        {isDeleting ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Trash2 className="h-3 w-3 mr-1" />}
                        Delete
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="border-border">
        {filtered.length === 0 ? <EmptyState icon={Users} title="No employees match" /> : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Employee</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Designation</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Contact</TableHead>
                <TableHead>Status</TableHead>
                {(canEdit || canReset || canManageAccount) && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(u => {
                const targetId = u.id || u._id || u.email;
                const isStatusLoading = actionLoadingKey === `status-${targetId}`;
                const isDeleteLoading = actionLoadingKey === `del-emp-${targetId}`;
                const isResetLoading = actionLoadingKey === `reset-${u.id}`;

                return (
                  <TableRow key={u.id}>
                    <TableCell>
                      <div className="flex items-center gap-2.5">
                        <Avatar className="h-8 w-8"><AvatarImage src={u.photo || undefined} /><AvatarFallback className="bg-wavygo-100 text-wavygo-800 text-[10px] font-semibold">{initials(u.name)}</AvatarFallback></Avatar>
                        <div><div className="text-[13.5px] font-medium">{u.name}</div><div className="text-[11.5px] text-muted-foreground">{u.email}</div></div>
                      </div>
                    </TableCell>
                    <TableCell><Badge variant="secondary">{u.role}</Badge></TableCell>
                    <TableCell className="text-[13px]">{u.designation || "—"}</TableCell>
                    <TableCell className="text-[13px]">{u.department || "—"}</TableCell>
                    <TableCell className="text-[13px] text-muted-foreground">{u.phone || "—"}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <StatusPill status={u.status === "deactivated" || u.is_active === false ? "deactivated" : "active"} />
                        {u.online && <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" title="Online now" />}
                      </div>
                    </TableCell>
                    {(canEdit || canReset || canManageAccount) && (
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {canEdit && u.role !== "Founder" && (
                            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => startEdit(u)} disabled={!!actionLoadingKey} data-testid={`edit-employee-btn-${u.id}`}>
                              <Pencil className="h-3.5 w-3.5 mr-1" /> Edit
                            </Button>
                          )}
                          {canReset && u.role !== "Founder" && (
                            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => resetPassword(u)} disabled={isResetLoading || !!actionLoadingKey} data-testid={`reset-password-btn-${u.id}`}>
                              {isResetLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <KeyRound className="h-3.5 w-3.5 mr-1" />}
                              Reset password
                            </Button>
                          )}
                          {canManageAccount && u.role !== "Founder" && (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                className={`h-7 text-xs ${
                                  u.status === "deactivated" || u.is_active === false
                                    ? "border-emerald-500/30 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10"
                                    : "border-amber-500/30 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10"
                                }`}
                                onClick={() => toggleEmployeeStatus(u)}
                                disabled={isStatusLoading || !!actionLoadingKey}
                                data-testid={`toggle-status-btn-${u.id}`}
                              >
                                {isStatusLoading ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                                ) : u.status === "deactivated" || u.is_active === false ? (
                                  <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                                ) : (
                                  <Power className="h-3.5 w-3.5 mr-1" />
                                )}
                                {u.status === "deactivated" || u.is_active === false ? "Activate" : "Deactivate"}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 text-xs border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-500/10"
                                onClick={() => deleteEmployee(u)}
                                disabled={isDeleteLoading || !!actionLoadingKey}
                                data-testid={`delete-employee-btn-${u.id}`}
                              >
                                {isDeleteLoading ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                                ) : (
                                  <UserMinus className="h-3.5 w-3.5 mr-1" />
                                )}
                                Remove
                              </Button>
                            </>
                          )}
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setCreatedInvite(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="font-display">{createdInvite ? "Invitation Sent & Link Generated" : "Invite teammate"}</DialogTitle>
            <DialogDescription>
              {createdInvite
                ? "An email was dispatched via Brevo. You can also copy and share the direct invitation link below."
                : "An invitation email will be sent to the employee. They will be added to the directory once they accept."}
            </DialogDescription>
          </DialogHeader>

          {createdInvite ? (
            <div className="space-y-3 my-2">
              <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3.5 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">Invitation Link</span>
                  <Badge variant="outline" className="text-[10px] bg-blue-500/20 text-blue-300 border-blue-500/30">Active</Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  Share this link directly with <strong className="text-foreground">{createdInvite.name}</strong> to let them set their password & accept:
                </div>
                <div className="p-2.5 rounded bg-background border border-border font-mono text-[11px] break-all text-foreground select-all">
                  {createdInvite.invite_url}
                </div>
                <Button className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium h-9 text-xs" onClick={() => copyInviteUrl(createdInvite.invite_url)}>
                  {copied ? <Check className="h-4 w-4 mr-2" /> : <Copy className="h-4 w-4 mr-2" />}
                  {copied ? "Link Copied!" : "Copy Invitation Link"}
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div><Label>Full name</Label><Input value={form.name} onChange={(e) => setForm(s => ({ ...s, name: e.target.value }))} data-testid="invite-name-input" /></div>
              <div><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm(s => ({ ...s, email: e.target.value }))} data-testid="invite-email-input" /></div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Role</Label>
                  <Select value={form.role} onValueChange={(v) => setForm(s => ({ ...s, role: v }))}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{["Admin","Manager","Employee","Intern"].map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div><Label>Phone</Label><Input value={form.phone} onChange={(e) => setForm(s => ({ ...s, phone: e.target.value }))} /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Designation</Label><Input value={form.designation} onChange={(e) => setForm(s => ({ ...s, designation: e.target.value }))} /></div>
                <div><Label>Department</Label><Input value={form.department} onChange={(e) => setForm(s => ({ ...s, department: e.target.value }))} /></div>
              </div>
            </div>
          )}

          <DialogFooter>
            {createdInvite ? (
              <Button onClick={() => { setOpen(false); setCreatedInvite(null); }}>Done</Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setOpen(false)} disabled={actionLoadingKey === "invite"}>Cancel</Button>
                <Button onClick={invite} disabled={actionLoadingKey === "invite"} data-testid="invite-submit-btn">
                  {actionLoadingKey === "invite" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" /> Sending invitation...
                    </>
                  ) : (
                    "Send invitation email"
                  )}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!resetInfo} onOpenChange={(v) => !v && setResetInfo(null)}>
        <DialogContent data-testid="reset-password-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">Temporary Password Generated</DialogTitle>
            <DialogDescription>Share this temporary password with {resetInfo?.email}. They should sign in and update their password if permitted.</DialogDescription>
          </DialogHeader>
          <div className="p-4 rounded-lg bg-slate-900 border border-slate-800 text-center font-mono text-lg tracking-wider font-bold text-amber-400 select-all my-2">
            {resetInfo?.password}
          </div>
          <DialogFooter>
            <Button onClick={() => setResetInfo(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!editingUser} onOpenChange={(v) => !v && setEditingUser(null)}>
        <DialogContent data-testid="edit-employee-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">Edit Teammate Profile</DialogTitle>
            <DialogDescription>Update role, designation, department, and contact information for {editingUser?.name}.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label>Full name</Label><Input value={editForm.name} onChange={(e) => setEditForm(s => ({ ...s, name: e.target.value }))} data-testid="edit-name-input" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Role</Label>
                <Select value={editForm.role} onValueChange={(v) => setEditForm(s => ({ ...s, role: v }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{["Admin","Manager","Employee","Intern"].map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div><Label>Phone</Label><Input value={editForm.phone} onChange={(e) => setEditForm(s => ({ ...s, phone: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Designation</Label><Input value={editForm.designation} onChange={(e) => setEditForm(s => ({ ...s, designation: e.target.value }))} /></div>
              <div><Label>Department</Label><Input value={editForm.department} onChange={(e) => setEditForm(s => ({ ...s, department: e.target.value }))} /></div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingUser(null)} disabled={actionLoadingKey === "save-edit"}>Cancel</Button>
            <Button onClick={saveEdit} disabled={actionLoadingKey === "save-edit"} data-testid="edit-employee-save-btn">
              {actionLoadingKey === "save-edit" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" /> Saving...
                </>
              ) : (
                "Save Changes"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Attendance() {
  const { user } = useAuth();
  const { can } = usePermission();
  const canDir = can("employee.view_directory");
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ employee_id: "", date: new Date().toISOString().slice(0, 10), status: "present" });

  useEffect(() => { if (!canDir && user) setForm(s => ({ ...s, employee_id: user.id })); }, [canDir, user]);

  async function load() {
    const empReq = canDir ? api.get("/employees") : Promise.resolve({ data: [] });
    const [{ data: att }, { data: emps }] = await Promise.all([api.get("/employees/attendance/records"), empReq]);
    const list = canDir ? emps : (user ? [{ id: user.id, name: user.name }] : []);
    const nameMap = Object.fromEntries(list.map(e => [e.id, e.name]));
    if (user) nameMap[user.id] = user.name;
    setRows(att.map(a => ({ ...a, employee_name: nameMap[a.employee_id] || (user ? user.name : "—") })));
    setUsers(list);
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  async function submit() {
    setSubmitting(true);
    try {
      await api.post("/employees/attendance/records", form);
      toast.success("Attendance recorded");
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="flex justify-end mb-4">
        <Button onClick={() => { setForm(s => ({ ...s, date: new Date().toISOString().slice(0, 10) })); setOpen(true); }} data-testid="attendance-mark-btn"><Plus className="h-4 w-4 mr-1.5" /> Mark attendance</Button>
      </div>
      <Card className="border-border">
        {rows.length === 0 ? <EmptyState icon={CalendarDays} title="No attendance yet" description="Attendance records will appear here." /> : (
          <Table>
            <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Date</TableHead><TableHead>Status</TableHead><TableHead>Check-in</TableHead><TableHead>Check-out</TableHead></TableRow></TableHeader>
            <TableBody>{rows.map(r => (
              <TableRow key={r.id}>
                <TableCell className="font-medium">{r.employee_name}</TableCell>
                <TableCell>{r.date}</TableCell>
                <TableCell><StatusPill status={r.status} /></TableCell>
                <TableCell className="text-[13px] text-muted-foreground">{r.check_in || "—"}</TableCell>
                <TableCell className="text-[13px] text-muted-foreground">{r.check_out || "—"}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">Mark attendance</DialogTitle><DialogDescription>Record for a specific date and employee.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Employee</Label>
              <Select value={form.employee_id} onValueChange={(v) => setForm(s => ({ ...s, employee_id: v }))} disabled={!canDir || submitting}>
                <SelectTrigger><SelectValue placeholder={canDir ? "Select employee" : (user?.name || "You")} /></SelectTrigger>
                <SelectContent>{users.map(u => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Date</Label><Input type="date" value={form.date} disabled data-testid="attendance-date" /></div>
              <div>
                <Label>Status</Label>
                <Select value={form.status} onValueChange={(v) => setForm(s => ({ ...s, status: v }))} disabled={submitting}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{["present","absent","leave","half_day","wfh"].map(s => <SelectItem key={s} value={s} className="capitalize">{s.replace("_"," ")}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {submitting ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Leave() {
  const { user } = useAuth();
  const { can } = usePermission();
  const canDir = can("employee.view_directory");
  const canApprove = can("leave.approve");
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionId, setActionId] = useState(null);
  const [form, setForm] = useState({ employee_id: "", from_date: "", to_date: "", kind: "casual", reason: "", status: "pending" });

  useEffect(() => { if (!canDir && user) setForm(s => ({ ...s, employee_id: user.id })); }, [canDir, user]);

  async function load() {
    const empReq = canDir ? api.get("/employees") : Promise.resolve({ data: [] });
    const [{ data: lv }, { data: emps }] = await Promise.all([api.get("/employees/leave/requests"), empReq]);
    setRows(lv); setUsers(canDir ? emps : (user ? [{ id: user.id, name: user.name }] : []));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  async function submit() {
    setSubmitting(true);
    try {
      await api.post("/employees/leave/requests", form);
      toast.success("Leave requested");
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function decide(id, status) {
    setActionId(`${id}-${status}`);
    try {
      await api.patch(`/employees/leave/requests/${id}`, { status });
      toast.success(`Leave ${status}`);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionId(null);
    }
  }

  return (
    <>
      <div className="flex justify-end mb-4"><Button onClick={() => setOpen(true)}><Plus className="h-4 w-4 mr-1.5" /> Request leave</Button></div>
      <Card className="border-border">
        {rows.length === 0 ? <EmptyState icon={CalendarDays} title="No leave requests" /> : (
          <Table>
            <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Type</TableHead><TableHead>From → To</TableHead><TableHead>Reason</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>{rows.map(r => (
              <TableRow key={r.id}>
                <TableCell className="font-medium">{r.employee_name}</TableCell>
                <TableCell className="capitalize">{r.kind}</TableCell>
                <TableCell className="text-[13px]">{r.from_date} → {r.to_date}</TableCell>
                <TableCell className="text-[13px] text-muted-foreground line-clamp-1">{r.reason}</TableCell>
                <TableCell><StatusPill status={r.status} /></TableCell>
                <TableCell className="text-right space-x-1">
                  {canApprove && r.status === "pending" && <>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs text-success border-success/40"
                      onClick={() => decide(r.id, "approved")}
                      disabled={actionId === `${r.id}-approved` || !!actionId}
                    >
                      {actionId === `${r.id}-approved` ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs text-destructive border-destructive/40"
                      onClick={() => decide(r.id, "rejected")}
                      disabled={actionId === `${r.id}-rejected` || !!actionId}
                    >
                      {actionId === `${r.id}-rejected` ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                      Reject
                    </Button>
                  </>}
                </TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">Request leave</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Employee</Label>
              <Select value={form.employee_id} onValueChange={(v) => setForm(s => ({ ...s, employee_id: v }))} disabled={!canDir || submitting}><SelectTrigger><SelectValue placeholder={canDir ? "Select employee" : (user?.name || "You")} /></SelectTrigger>
                <SelectContent>{users.map(u => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>From</Label><Input type="date" value={form.from_date} onChange={(e) => setForm(s => ({ ...s, from_date: e.target.value }))} disabled={submitting} /></div>
              <div><Label>To</Label><Input type="date" value={form.to_date} onChange={(e) => setForm(s => ({ ...s, to_date: e.target.value }))} disabled={submitting} /></div>
            </div>
            <div>
              <Label>Type</Label>
              <Select value={form.kind} onValueChange={(v) => setForm(s => ({ ...s, kind: v }))} disabled={submitting}><SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{["casual","sick","earned","unpaid"].map(k => <SelectItem key={k} value={k} className="capitalize">{k}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Reason</Label><Textarea rows={3} value={form.reason} onChange={(e) => setForm(s => ({ ...s, reason: e.target.value }))} disabled={submitting} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {submitting ? "Submitting..." : "Submit"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Performance() {
  const { user } = useAuth();
  const { can } = usePermission();
  const canDir = can("employee.view_directory");
  const canReview = can("performance.create");
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ employee_id: "", period: "Q1-2026", score: 4.0, highlights: "", growth_areas: "" });

  async function load() {
    const empReq = canDir ? api.get("/employees") : Promise.resolve({ data: [] });
    const [{ data: pr }, { data: emps }] = await Promise.all([api.get("/employees/performance/reviews"), empReq]);
    setRows(pr); setUsers(canDir ? emps : (user ? [{ id: user.id, name: user.name }] : []));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  async function submit() {
    setSubmitting(true);
    try {
      await api.post("/employees/performance/reviews", form);
      toast.success("Review saved");
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      {canReview && <div className="flex justify-end mb-4"><Button onClick={() => setOpen(true)}><Plus className="h-4 w-4 mr-1.5" /> Log review</Button></div>}
      <Card className="border-border">
        {rows.length === 0 ? <EmptyState icon={Award} title="No reviews yet" /> : (
          <div className="divide-y divide-border">
            {rows.map(r => (
              <div key={r.id} className="p-4 flex gap-4">
                <Avatar className="h-10 w-10"><AvatarImage src={r.employee_photo || undefined} /><AvatarFallback className="bg-wavygo-100 text-wavygo-800 text-[11px] font-semibold">{initials(r.employee_name)}</AvatarFallback></Avatar>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="font-medium text-[14px]">{r.employee_name}</div>
                    <Badge variant="secondary" className="text-[10px]">{r.period}</Badge>
                    <span className="ml-auto inline-flex items-center gap-1 text-warning font-semibold">★ {r.score}</span>
                  </div>
                  {r.employee_designation && <div className="text-[11.5px] text-muted-foreground">{r.employee_designation}</div>}
                  <div className="mt-2 text-[13px]"><span className="text-muted-foreground text-[11px] uppercase tracking-wide">Highlights · </span>{r.highlights}</div>
                  {r.growth_areas && <div className="text-[13px] mt-1"><span className="text-muted-foreground text-[11px] uppercase tracking-wide">Growth · </span>{r.growth_areas}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">Log performance review</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Employee</Label>
              <Select value={form.employee_id} onValueChange={(v) => setForm(s => ({ ...s, employee_id: v }))} disabled={submitting}><SelectTrigger><SelectValue placeholder="Select" /></SelectTrigger>
                <SelectContent>{users.map(u => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Period</Label><Input value={form.period} onChange={(e) => setForm(s => ({ ...s, period: e.target.value }))} disabled={submitting} /></div>
              <div><Label>Score (1-5)</Label><Input type="number" step="0.1" value={form.score} onChange={(e) => setForm(s => ({ ...s, score: parseFloat(e.target.value) }))} disabled={submitting} /></div>
            </div>
            <div><Label>Highlights</Label><Textarea rows={2} value={form.highlights} onChange={(e) => setForm(s => ({ ...s, highlights: e.target.value }))} disabled={submitting} /></div>
            <div><Label>Growth areas</Label><Textarea rows={2} value={form.growth_areas} onChange={(e) => setForm(s => ({ ...s, growth_areas: e.target.value }))} disabled={submitting} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {submitting ? "Saving review..." : "Save review"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Departments() {
  const { can } = usePermission();
  const canCreate = can("department.create");
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  async function load() { const { data } = await api.get("/employees/departments/list"); setRows(data); }
  useEffect(() => { load(); }, []);

  async function submit() {
    setSubmitting(true);
    try {
      await api.post("/employees/departments/list", form);
      toast.success("Department created");
      setOpen(false);
      setForm({ name: "", description: "" });
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      {canCreate && <div className="flex justify-end mb-4"><Button onClick={() => setOpen(true)} data-testid="department-create-btn"><Plus className="h-4 w-4 mr-1.5" /> New department</Button></div>}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {rows.map(d => (
          <Card key={d.id} className="border-border hover-lift">
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2">
                <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center"><Building2 className="h-4.5 w-4.5" /></div>
                <div>
                  <CardTitle className="font-display text-[15px]">{d.name}</CardTitle>
                  <div className="text-[11.5px] text-muted-foreground">{d.headcount} teammate{d.headcount === 1 ? "" : "s"}{d.head_name ? ` · ${d.head_name}` : ""}</div>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0 text-[13px] text-muted-foreground">{d.description || "—"}</CardContent>
          </Card>
        ))}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">New department</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm(s => ({ ...s, name: e.target.value }))} disabled={submitting} /></div>
            <div><Label>Description</Label><Textarea rows={2} value={form.description} onChange={(e) => setForm(s => ({ ...s, description: e.target.value }))} disabled={submitting} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {submitting ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function Employees() {
  const { can, role } = usePermission();
  const canDir = can("employee.view_directory");
  const canDepts = role === "Founder" || role === "Admin" || role === "Manager";
  const showPerformance = role !== "Intern";
  const personal = role === "Employee" || role === "Intern";
  const [stats, setStats] = useState(null);
  useEffect(() => { api.get("/employees/stats/overview").then(({ data }) => setStats(data)); }, []);
  return (
    <div data-testid="employees-page">
      <PageHeader
        eyebrow={personal ? "Personal" : "Module"}
        title={personal ? "My Workspace" : "Employees"}
        description={personal
          ? "Your attendance, leave and performance in one place."
          : "Directory, attendance, leave, performance and departments — the human core of WavyGo."}
      />
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="Total teammates" value={stats.total} icon={Users} />
          <StatCard label="Online now" value={stats.online} icon={Users} tone="success" />
          <StatCard label="Departments" value={stats.departments} icon={Building2} tone="info" />
          <StatCard label="Pending leave" value={stats.pending_leave} icon={CalendarDays} tone="warning" />
        </div>
      )}
      <Tabs defaultValue={canDir ? "directory" : "attendance"}>
        <TabsList>
          {canDir && <TabsTrigger value="directory" data-testid="emp-tab-directory">Directory</TabsTrigger>}
          <TabsTrigger value="attendance" data-testid="emp-tab-attendance">Attendance</TabsTrigger>
          <TabsTrigger value="leave" data-testid="emp-tab-leave">Leave</TabsTrigger>
          {showPerformance && <TabsTrigger value="performance" data-testid="emp-tab-performance">Performance</TabsTrigger>}
          {canDepts && <TabsTrigger value="departments" data-testid="emp-tab-departments">Departments</TabsTrigger>}
        </TabsList>
        {canDir && <TabsContent value="directory" className="mt-6"><Directory /></TabsContent>}
        <TabsContent value="attendance" className="mt-6"><Attendance /></TabsContent>
        <TabsContent value="leave" className="mt-6"><Leave /></TabsContent>
        {showPerformance && <TabsContent value="performance" className="mt-6"><Performance /></TabsContent>}
        {canDepts && <TabsContent value="departments" className="mt-6"><Departments /></TabsContent>}
      </Tabs>
    </div>
  );
}
