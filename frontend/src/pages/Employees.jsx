import { useCallback, useEffect, useMemo, useState } from "react";
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
import { Users, Plus, UserPlus, Building2, CalendarDays, Award, KeyRound, Mail, Copy, Check, Trash2, Pencil, Power, UserMinus, CheckCircle2, Loader2, Eye, EyeOff, Sparkles, Send, ShieldCheck, ArrowLeft, Clock, LogIn, LogOut, ClipboardList, Upload, FileText } from "lucide-react";
import { useLiveRefresh } from "@/hooks/useLiveRefresh";
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

const ROLE_OPTIONS = ["Admin", "Manager", "Employee", "Intern"];
const ALL_EMPLOYEES = "__all__";
const NO_DEPARTMENT = "__none__";

// Local calendar date (YYYY-MM-DD); toISOString() would give the UTC date.
// Attendance days are company-local (IST) dates on the server, whatever the browser's timezone.
function todayLocal() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function currentQuarter() {
  const d = new Date();
  return `Q${Math.floor(d.getMonth() / 3) + 1}-${d.getFullYear()}`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtDuration(minutes) {
  if (minutes === null || minutes === undefined || minutes < 0) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.floor(minutes % 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function DepartmentSelect({ value, onChange, departments, disabled }) {
  return (
    <Select value={value || NO_DEPARTMENT} onValueChange={(v) => onChange(v === NO_DEPARTMENT ? "" : v)} disabled={disabled}>
      <SelectTrigger><SelectValue placeholder="Select department" /></SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_DEPARTMENT}>No department</SelectItem>
        {departments.filter(d => d.registered !== false).map(d => <SelectItem key={d.id || d.name} value={d.name}>{d.name}</SelectItem>)}
        {value && !departments.some(d => d.name === value) && <SelectItem value={value}>{value}</SelectItem>}
      </SelectContent>
    </Select>
  );
}

// ============================================================
// EMPLOYEE DETAILS (submitted by the employee + provided by the company)
// ============================================================

// [key, label, type]  — type: text (default) | date | number | checkbox | textarea
const SUBMITTED_FIELDS = [
  ["phone", "Phone"],
  ["personal_email", "Personal email"],
  ["date_of_birth", "Date of birth", "date"],
  ["address", "Address", "textarea"],
  ["emergency_contact_name", "Emergency contact name"],
  ["emergency_contact_relation", "Emergency contact relation"],
  ["emergency_contact_phone", "Emergency contact phone"],
  ["college", "College"],
  ["degree", "Degree"],
  ["resume_url", "Resume link"],
  ["id_proof_url", "ID proof link"],
  ["bank_account_last4", "Bank account (last 4 digits)"],
];

const COMPANY_FIELDS = [
  ["employee_code", "Employee ID"],
  ["reporting_manager", "Reporting manager"],
  ["joining_date", "Joining date", "date"],
  ["employment_type", "Employment type"],
  ["stipend_or_salary", "Stipend / salary", "number"],
  ["offer_letter_url", "Offer letter link"],
  ["nda_signed", "NDA signed", "checkbox"],
  ["assigned_assets", "Assigned assets", "textarea"],
];

const normalizeValue = (v) => (v === "" || v === undefined ? null : v);

function DetailsSection({ title, subtitle, fields, values, editable, onSave }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(values);
  const [saving, setSaving] = useState(false);

  useEffect(() => { setForm(values); }, [values]);

  function display(key, type) {
    const v = values[key];
    if (type === "checkbox") return v ? "Yes" : "No";
    if (v === null || v === undefined || v === "") return "—";
    if (key.endsWith("_url")) {
      return <a href={v} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">Open link</a>;
    }
    return String(v);
  }

  async function save() {
    // Send only what changed, so untouched fields are never overwritten.
    const changes = {};
    fields.forEach(([key]) => {
      if (normalizeValue(form[key]) !== normalizeValue(values[key])) changes[key] = form[key];
    });
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(changes);
      toast.success(`${title} saved`);
      setEditing(false);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setForm(values);
    setEditing(false);
  }

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="font-display text-[14px]">{title}</CardTitle>
            <div className="text-[11.5px] text-muted-foreground mt-0.5">{subtitle}</div>
          </div>
          {editable && !editing && (
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setEditing(true)}>
              <Pencil className="h-3.5 w-3.5 mr-1" /> Edit
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
          {fields.map(([key, label, type]) => (
            <div key={key} className={type === "textarea" ? "sm:col-span-2" : ""}>
              <Label className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</Label>
              {editing ? (
                type === "checkbox" ? (
                  <div className="mt-1.5">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={!!form[key]}
                      onChange={(e) => setForm(s => ({ ...s, [key]: e.target.checked }))}
                      disabled={saving}
                    />
                  </div>
                ) : type === "textarea" ? (
                  <Textarea
                    rows={2}
                    className="mt-1"
                    value={form[key] ?? ""}
                    onChange={(e) => setForm(s => ({ ...s, [key]: e.target.value }))}
                    disabled={saving}
                  />
                ) : (
                  <Input
                    className="mt-1"
                    type={type === "date" ? "date" : type === "number" ? "number" : "text"}
                    min={type === "number" ? 0 : undefined}
                    value={form[key] ?? ""}
                    onChange={(e) => setForm(s => ({
                      ...s,
                      [key]: type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value,
                    }))}
                    disabled={saving}
                  />
                )
              ) : (
                <div className="mt-1 text-[13.5px] break-words whitespace-pre-wrap">{display(key, type)}</div>
              )}
            </div>
          ))}
        </div>
        {editing && (
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" size="sm" onClick={cancel} disabled={saving}>Cancel</Button>
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? <><Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> Saving...</> : "Save"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DocumentUpload({
  employeeId,
  section,
  documentType,
  label,
  multiple = false,
  editable,
  onUploaded,
}) {
  const [uploading, setUploading] = useState(false);

  async function handleUpload(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    setUploading(true);

    try {
      for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("section", section);
        formData.append("document_type", documentType);

        const { data } = await api.post(
          `/employees/${employeeId}/profile/document`,
          formData
        );

        onUploaded(data.profile);
      }

      toast.success(
        files.length === 1
          ? `${label} uploaded successfully`
          : `${files.length} documents uploaded successfully`
      );
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  if (!editable) return null;

  return (
    <div className="mt-3 rounded-lg border border-dashed border-border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
            {label}
          </div>
          {multiple && (
            <div className="text-[11px] text-muted-foreground mt-0.5">
              You can select multiple files.
            </div>
          )}
        </div>

        <label className="shrink-0">
          <input
            type="file"
            className="hidden"
            multiple={multiple}
            onChange={handleUpload}
            disabled={uploading}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 text-xs"
            disabled={uploading}
            asChild
          >
            <span>
              {uploading ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="h-3.5 w-3.5 mr-1.5" />
                  {multiple ? "Choose files" : "Upload"}
                </>
              )}
            </span>
          </Button>
        </label>
      </div>
    </div>
  );
}

function EmployeeDetailsDialog({ employee, onClose }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const employeeId = employee?.id;

  useEffect(() => {
    if (!employeeId) {
      setProfile(null);
      setError("");
      return undefined;
    }
    let alive = true;
    setLoading(true);
    setProfile(null);
    setError("");
    api.get(`/employees/${employeeId}/profile`)
      .then(({ data }) => { if (alive) setProfile(data); })
      .catch((e) => { if (alive) setError(formatApiError(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [employeeId]);

  async function saveSubmitted(changes) {
    const { data } = await api.put(`/employees/${employeeId}/profile/submitted`, changes);
    setProfile(data);
  }

  async function saveCompany(changes) {
    const { data } = await api.patch(`/employees/${employeeId}/profile/company`, changes);
    setProfile(data);
  }

  function handleDocumentUploaded(updatedProfile) {
    setProfile(updatedProfile);
  }

  return (
    <Dialog open={!!employee} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[88vh] overflow-y-auto" data-testid="employee-details-dialog">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <Avatar className="h-11 w-11">
              <AvatarImage src={employee?.photo || undefined} />
              <AvatarFallback className="bg-wavygo-100 text-wavygo-800 text-[11px] font-semibold">{initials(employee?.name)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <DialogTitle className="font-display">{employee?.name}</DialogTitle>
              <DialogDescription className="text-xs">
                {employee?.email}
                {employee?.role ? ` · ${employee.role}` : ""}
                {employee?.designation ? ` · ${employee.designation}` : ""}
                {employee?.department ? ` · ${employee.department}` : ""}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {loading && (
          <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading details...
          </div>
        )}
        {!loading && error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">{error}</div>}

        {profile && (
          <div className="space-y-4">
            <DetailsSection
              title="Submitted by employee"
              subtitle="Details the employee has filled in about themselves."
              fields={SUBMITTED_FIELDS}
              values={profile.submitted}
              editable={profile.can_edit_submitted}
              onSave={saveSubmitted}
            />

            {profile.can_edit_submitted && (
              <Card className="border-border">
                <CardHeader className="pb-3">
                  <CardTitle className="font-display text-[14px]">
                    Employee documents
                  </CardTitle>
                  <div className="text-[11.5px] text-muted-foreground mt-0.5">
                    Upload documents submitted by the employee.
                  </div>
                </CardHeader>
                <CardContent className="pt-0 space-y-2">
                  <DocumentUpload
                    employeeId={employeeId}
                    section="submitted"
                    documentType="resume"
                    label="Resume"
                    editable={profile.can_edit_submitted}
                    onUploaded={handleDocumentUploaded}
                  />
                  <DocumentUpload
                    employeeId={employeeId}
                    section="submitted"
                    documentType="id_proof"
                    label="ID Proof"
                    editable={profile.can_edit_submitted}
                    onUploaded={handleDocumentUploaded}
                  />
                  <DocumentUpload
                    employeeId={employeeId}
                    section="submitted"
                    documentType="other"
                    label="Other Documents"
                    multiple
                    editable={profile.can_edit_submitted}
                    onUploaded={handleDocumentUploaded}
                  />
                </CardContent>
              </Card>
            )}

            <DetailsSection
              title="Provided by company"
              subtitle="Details the company has recorded for this employee."
              fields={COMPANY_FIELDS}
              values={profile.company}
              editable={profile.can_edit_company}
              onSave={saveCompany}
            />

            {profile.can_edit_company && (
              <Card className="border-border">
                <CardHeader className="pb-3">
                  <CardTitle className="font-display text-[14px]">
                    Company documents
                  </CardTitle>
                  <div className="text-[11.5px] text-muted-foreground mt-0.5">
                    Upload documents provided by the company.
                  </div>
                </CardHeader>
                <CardContent className="pt-0 space-y-2">
                  <DocumentUpload
                    employeeId={employeeId}
                    section="company"
                    documentType="offer_letter"
                    label="Offer Letter"
                    editable={profile.can_edit_company}
                    onUploaded={handleDocumentUploaded}
                  />
                  <DocumentUpload
                    employeeId={employeeId}
                    section="company"
                    documentType="employment_agreement"
                    label="Employment Agreement"
                    editable={profile.can_edit_company}
                    onUploaded={handleDocumentUploaded}
                  />
                  <DocumentUpload
                    employeeId={employeeId}
                    section="company"
                    documentType="other"
                    label="Other Documents"
                    multiple
                    editable={profile.can_edit_company}
                    onUploaded={handleDocumentUploaded}
                  />
                </CardContent>
              </Card>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Directory({ onChange }) {
  const { user } = useAuth();
  const { can, role } = usePermission();
  const canInvite = can("employee.invite");
  const canEdit = can("employee.edit");
  const canReset = can("auth.reset_other_password");
  const canManageAccount = role === "Founder" || role === "Admin";
  // Roles this user may grant, mirroring the user.invite.* permission matrix.
  const assignableRoles = ROLE_OPTIONS.filter(r => can(`user.invite.${r.toLowerCase()}`));
  const [rows, setRows] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState(null);
  const [invitations, setInvitations] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", role: "Employee", designation: "", department: "", phone: "" });
  const [resetInfo, setResetInfo] = useState(null);
  const [resetTargetUser, setResetTargetUser] = useState(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [passwordCopied, setPasswordCopied] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [editForm, setEditForm] = useState({ name: "", role: "Employee", designation: "", department: "", phone: "" });
  const [detailsUser, setDetailsUser] = useState(null);

  const [createdInvite, setCreatedInvite] = useState(null);
  const [copied, setCopied] = useState(false);
  const [actionLoadingKey, setActionLoadingKey] = useState(null);

  const loadRows = (dept) => {
    const params = dept && dept !== ALL_EMPLOYEES ? { department: dept } : {};
    api.get("/employees", { params }).then(({ data }) => setRows(data)).catch((e) => toast.error(formatApiError(e)));
  };

  const loadMeta = () => {
    api.get("/employees/departments/list").then(({ data }) => setDepartments(data)).catch((e) => toast.error(formatApiError(e)));
    api.get("/employees/invitations").then(({ data }) => setInvitations(data)).catch((e) => toast.error(formatApiError(e)));
  };

  const load = () => {
    if (selectedDepartment) loadRows(selectedDepartment);
    loadMeta();
    onChange?.();
  };

  const [searchParams, setSearchParams] = useSearchParams();

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadMeta(); }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setQ("");
    if (!selectedDepartment) {
      setRows([]);
      return;
    }
    loadRows(selectedDepartment);
  }, [selectedDepartment]);

  // Managers only manage their own department, so only that card is offered to them.
  const visibleDepartments = useMemo(
    () => (role === "Manager"
      ? departments.filter(d => d.name.trim().toLowerCase() === (user?.department || "").trim().toLowerCase())
      : departments),
    [departments, role, user]
  );

  useEffect(() => {
    if (searchParams.get("create") === "invite" || searchParams.get("action") === "invite-teammate") {
      // Only roles that may invite get the dialog; for others the deep link is simply dropped.
      if (canInvite) {
        setCreatedInvite(null);
        setForm({ email: "", name: "", role: "Employee", designation: "", department: "", phone: "" });
        setOpen(true);
      }
      setSearchParams(params => {
        params.delete("create");
        params.delete("action");
        return params;
      }, { replace: true });
    }
  }, [searchParams, setSearchParams, canInvite]);

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
      toast.success(data.message || "Invitation created — share the link");
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingKey(null);
    }
  }

  async function copyInviteUrl(url) {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      toast.error("Couldn't copy automatically — select the link and copy it manually");
      return;
    }
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
      toast.success(data.message || "Invitation renewed");
      load();
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

  function openResetModal(u) {
    setResetTargetUser(u);
    setNewPassword("");
    setConfirmPassword("");
    setShowPassword(false);
    setPasswordCopied(false);
  }

  function generateRandomPassword() {
    const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*";
    let pwd = "Wg";
    for (let i = 0; i < 10; i++) {
      pwd += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    setNewPassword(pwd);
    setConfirmPassword(pwd);
    setShowPassword(true);
  }

  async function handleResetSubmit(e) {
    if (e) e.preventDefault();
    if (!resetTargetUser) return;
    const trimmed = newPassword.trim();
    if (!trimmed || trimmed.length < 8) {
      toast.error("Password must be at least 8 characters long");
      return;
    }
    if (trimmed !== confirmPassword.trim()) {
      toast.error("Passwords do not match");
      return;
    }

    const key = `reset-${resetTargetUser.id}`;
    setActionLoadingKey(key);
    try {
      const { data } = await api.post(`/employees/${resetTargetUser.id}/reset-password`, {
        new_password: trimmed,
      });
      toast.success(data.message || "Password updated");
      setResetInfo({
        email: resetTargetUser.email,
        name: resetTargetUser.name,
        password: trimmed,
        emailQueued: !!data.email_queued,
      });
      setResetTargetUser(null);
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setActionLoadingKey(null);
    }
  }

  async function resetPassword(u) {
    openResetModal(u);
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

  // Mirrors the backend edit rules: role/department are org-managed fields.
  const editingSelf = editingUser?.id === user?.id;
  const canChangeRole = !!editingUser && !editingSelf && (role === "Founder" || role === "Admin")
    && assignableRoles.includes(editingUser.role);
  const canChangeDepartment = !!editingUser && (role === "Founder" || (role === "Admin" && !editingSelf));
  const editRoles = canChangeRole ? assignableRoles : [editForm.role];

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
      {selectedDepartment === null ? (
        <>
          <div className="flex justify-end mb-4">
            {canInvite && <Button onClick={() => { setCreatedInvite(null); setForm({ email: "", name: "", role: "Employee", designation: "", department: "", phone: "" }); setOpen(true); }} data-testid="employee-invite-btn"><UserPlus className="h-4 w-4 mr-1.5" /> Invite teammate</Button>}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
            <Card className="border-border hover-lift cursor-pointer" onClick={() => setSelectedDepartment(ALL_EMPLOYEES)} data-testid="dept-card-all">
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center"><Users className="h-4.5 w-4.5" /></div>
                  <div>
                    <CardTitle className="font-display text-[15px]">{role === "Manager" ? "My team" : "All employees"}</CardTitle>
                    <div className="text-[11.5px] text-muted-foreground">Everyone{role === "Manager" ? " in your department" : ", including teammates without a department"}</div>
                  </div>
                </div>
              </CardHeader>
            </Card>
            {visibleDepartments.map(d => (
              <Card key={d.id || `unregistered-${d.name}`} className="border-border hover-lift cursor-pointer" onClick={() => setSelectedDepartment(d.name)}>
                <DepartmentCardBody d={d} />
              </Card>
            ))}
          </div>
        </>
      ) : (
        <div className="mb-4">
          <button type="button" onClick={() => setSelectedDepartment(null)} className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft className="h-4 w-4" /> Back to Departments
          </button>
          <div className="mb-2 font-display text-[15px] font-semibold">{selectedDepartment === ALL_EMPLOYEES ? (role === "Manager" ? "My team" : "All employees") : selectedDepartment}</div>
          <div className="flex flex-col sm:flex-row gap-2 items-start sm:items-center justify-between">
            <Input placeholder="Search by name, email, role…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-md" data-testid="employee-search" />
            {canInvite && <Button onClick={() => { setCreatedInvite(null); setForm({ email: "", name: "", role: "Employee", designation: "", department: "", phone: "" }); setOpen(true); }} data-testid="employee-invite-btn"><UserPlus className="h-4 w-4 mr-1.5" /> Invite teammate</Button>}
          </div>
        </div>
      )}

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
                  <div key={targetId} className="py-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 sm:gap-4 text-xs">
                    <div className="min-w-0 break-words">
                      <span className="font-medium text-foreground">{inv.name}</span>
                      <span className="text-muted-foreground ml-2">({inv.email})</span>
                      <Badge variant="outline" className="ml-2 text-[10px] uppercase">{inv.role}</Badge>
                      {inv.expired && <Badge variant="outline" className="ml-1 text-[10px] uppercase text-destructive border-destructive/40">Expired</Badge>}
                    </div>
                    {canInvite && <div className="flex flex-wrap items-center gap-2">
                      {inv.token && !inv.expired && (
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => copyInviteUrl(link)}>
                          <Copy className="h-3 w-3 mr-1" /> Copy Link
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs border-amber-500/30 text-amber-700 dark:text-amber-300 hover:bg-amber-500/10"
                        onClick={() => resendInvite(inv)}
                        disabled={isResending || !!actionLoadingKey}
                      >
                        {isResending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                        {inv.expired ? "Renew" : "Resend"}
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
                    </div>}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {selectedDepartment !== null && <Card className="border-border">
        {filtered.length === 0 ? <EmptyState icon={Users} title="No employees match" /> : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Employee</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Designation</TableHead>
                <TableHead>Contact</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Details</TableHead>
                {(canEdit || canReset || canManageAccount) && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(u => {
                const targetId = u.id || u._id || u.email;
                const isStatusLoading = actionLoadingKey === `status-${targetId}`;
                const isDeleteLoading = actionLoadingKey === `del-emp-${targetId}`;
                const isResetLoading = actionLoadingKey === `reset-${u.id}`;
                const isSelf = u.id === user?.id;
                const canEditRow = canEdit && u.role !== "Founder" && (
                  isSelf
                  || (role === "Manager" ? ["Employee", "Intern"].includes(u.role) : !(role === "Admin" && u.role === "Admin"))
                );
                const canManageRow = canManageAccount && u.role !== "Founder" && !isSelf && !(role === "Admin" && u.role === "Admin");

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
                    <TableCell className="text-[13px] text-muted-foreground">{u.phone || "—"}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <StatusPill status={u.status === "deactivated" || u.is_active === false ? "deactivated" : "active"} />
                        {u.online && <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" title="Online now" />}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setDetailsUser(u)} data-testid={`view-details-btn-${u.id}`}>
                        <ClipboardList className="h-3.5 w-3.5 mr-1" /> View
                      </Button>
                    </TableCell>
                    {(canEdit || canReset || canManageAccount) && (
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {canEditRow && (
                            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => startEdit(u)} disabled={!!actionLoadingKey} data-testid={`edit-employee-btn-${u.id}`}>
                              <Pencil className="h-3.5 w-3.5 mr-1" /> Edit
                            </Button>
                          )}
                          {canReset && u.role !== "Founder" && !(role === "Admin" && u.role === "Admin" && !isSelf) && (
                            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => resetPassword(u)} disabled={isResetLoading || !!actionLoadingKey} data-testid={`reset-password-btn-${u.id}`}>
                              {isResetLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <KeyRound className="h-3.5 w-3.5 mr-1" />}
                              Reset password
                            </Button>
                          )}
                          {canManageRow && (
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
      </Card>}

      <EmployeeDetailsDialog employee={detailsUser} onClose={() => setDetailsUser(null)} />

      <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setCreatedInvite(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="font-display">{createdInvite ? "Invitation Created" : "Invite teammate"}</DialogTitle>
            <DialogDescription>
              {createdInvite
                ? (createdInvite.email_queued
                  ? "The invitation email has been queued. You can also copy and share the direct invitation link below."
                  : "Invitation created — share the link below. Email is not configured, so no email was sent.")
                : "They will be added to the directory once they accept the invitation. The link is valid for 7 days."}
            </DialogDescription>
          </DialogHeader>

          {createdInvite ? (
            <div className="space-y-3 my-2">
              <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3.5 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-blue-700 dark:text-blue-400 uppercase tracking-wider">Invitation Link</span>
                  <Badge variant="outline" className="text-[10px] bg-blue-500/20 text-blue-700 dark:text-blue-300 border-blue-500/30">Active</Badge>
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
                    <SelectContent>{assignableRoles.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div><Label>Phone</Label><Input value={form.phone} onChange={(e) => setForm(s => ({ ...s, phone: e.target.value }))} /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Designation</Label><Input value={form.designation} onChange={(e) => setForm(s => ({ ...s, designation: e.target.value }))} /></div>
                <div><Label>Department</Label><DepartmentSelect value={form.department} onChange={(v) => setForm(s => ({ ...s, department: v }))} departments={departments} /></div>
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
                      <Loader2 className="h-4 w-4 animate-spin mr-2" /> Creating invitation...
                    </>
                  ) : (
                    "Create invitation"
                  )}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reset Password Form Modal */}
      <Dialog open={!!resetTargetUser} onOpenChange={(v) => !v && setResetTargetUser(null)}>
        <DialogContent className="sm:max-w-md" data-testid="reset-password-form-dialog">
          <DialogHeader>
            <div className="flex items-center gap-2 mb-1">
              <div className="h-9 w-9 rounded-lg bg-amber-500/10 text-amber-500 flex items-center justify-center">
                <KeyRound className="h-5 w-5" />
              </div>
              <div>
                <DialogTitle className="text-lg font-display">Reset Employee Password</DialogTitle>
                <DialogDescription className="text-xs">
                  Set a new password for <span className="font-semibold text-foreground">{resetTargetUser?.name}</span>
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {/* Brevo Notification Info Callout */}
          <div className="rounded-lg bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900/60 p-3 text-xs text-blue-900 dark:text-blue-200 flex items-start gap-2.5">
            <Mail className="h-4 w-4 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
            <div className="space-y-0.5 leading-relaxed">
              <span className="font-semibold">Email Notification:</span>
              <p className="text-muted-foreground text-[11px] leading-normal">
                If email is configured, the updated login credentials are emailed to{" "}
                <span className="font-mono font-medium text-foreground">{resetTargetUser?.email}</span>. Otherwise share them securely yourself.
              </p>
            </div>
          </div>

          <form onSubmit={handleResetSubmit} className="space-y-4 pt-1">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-medium">New Password</Label>
                <button
                  type="button"
                  onClick={generateRandomPassword}
                  className="text-[11px] font-medium text-primary hover:underline flex items-center gap-1 cursor-pointer transition-colors"
                >
                  <Sparkles className="h-3 w-3" /> Auto-generate strong
                </button>
              </div>
              <div className="relative">
                <Input
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter new password (min 8 characters)"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="pr-10 text-sm font-mono tracking-wide"
                  autoFocus
                  data-testid="reset-new-password-input"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors p-1"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Confirm New Password</Label>
              <div className="relative">
                <Input
                  type={showPassword ? "text" : "password"}
                  placeholder="Re-enter new password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className={`pr-10 text-sm font-mono tracking-wide ${
                    confirmPassword && confirmPassword !== newPassword ? "border-rose-500 focus-visible:ring-rose-500" : ""
                  }`}
                  data-testid="reset-confirm-password-input"
                />
              </div>
              {confirmPassword && confirmPassword !== newPassword && (
                <p className="text-[11px] text-rose-500 font-medium">Passwords do not match</p>
              )}
            </div>

            <DialogFooter className="gap-2 sm:gap-0 pt-2">
              <Button type="button" variant="outline" onClick={() => setResetTargetUser(null)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={actionLoadingKey === `reset-${resetTargetUser?.id}` || !newPassword || newPassword.length < 8 || newPassword !== confirmPassword}
                data-testid="reset-submit-btn"
              >
                {actionLoadingKey === `reset-${resetTargetUser?.id}` ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    Updating password...
                  </>
                ) : (
                  <>
                    <Send className="h-3.5 w-3.5 mr-1.5" />
                    Update password
                  </>
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Password Reset Confirmation Dialog */}
      <Dialog open={!!resetInfo} onOpenChange={(v) => !v && setResetInfo(null)}>
        <DialogContent data-testid="reset-password-dialog" className="sm:max-w-md">
          <DialogHeader>
            <div className="flex items-center gap-2 mb-1">
              <div className="h-9 w-9 rounded-lg bg-emerald-500/10 text-emerald-500 flex items-center justify-center">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <DialogTitle className="text-lg font-display">Password Updated Successfully</DialogTitle>
                <DialogDescription className="text-xs">
                  {resetInfo?.emailQueued
                    ? <>Email queued to <span className="font-semibold text-foreground">{resetInfo?.email}</span></>
                    : "Email is not configured — share the new password securely"}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="space-y-3 my-2">
            <div className="flex items-center gap-2 text-xs bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/60 text-emerald-800 dark:text-emerald-300 p-2.5 rounded-lg">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              <span>
                {resetInfo?.emailQueued
                  ? <>The employee's password has been updated and an email with the new credentials is on its way to <strong>{resetInfo?.email}</strong>.</>
                  : "The employee's password has been updated. No email was sent, so share it with them directly."}
              </span>
            </div>

            <div className="p-3.5 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Updated Password</span>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(resetInfo?.password || "");
                    } catch {
                      toast.error("Couldn't copy automatically — select the password and copy it manually");
                      return;
                    }
                    setPasswordCopied(true);
                    toast.success("Password copied to clipboard");
                    setTimeout(() => setPasswordCopied(false), 2000);
                  }}
                  className="flex items-center gap-1 text-slate-300 hover:text-white transition-colors"
                >
                  {passwordCopied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                  {passwordCopied ? "Copied" : "Copy"}
                </button>
              </div>
              <div className="font-mono text-base font-bold text-amber-400 select-all tracking-wider break-all">
                {resetInfo?.password}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button onClick={() => setResetInfo(null)} className="w-full sm:w-auto">
              Done
            </Button>
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
                <Select value={editForm.role} onValueChange={(v) => setEditForm(s => ({ ...s, role: v }))} disabled={!canChangeRole}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{editRoles.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div><Label>Phone</Label><Input value={editForm.phone} onChange={(e) => setEditForm(s => ({ ...s, phone: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Designation</Label><Input value={editForm.designation} onChange={(e) => setEditForm(s => ({ ...s, designation: e.target.value }))} /></div>
              <div><Label>Department</Label><DepartmentSelect value={editForm.department} onChange={(v) => setEditForm(s => ({ ...s, department: v }))} departments={departments} disabled={!canChangeDepartment} /></div>
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

function Attendance({ onChange }) {
  const { user } = useAuth();
  const { can } = usePermission();
  const canDir = can("employee.view_directory");
  const canMarkOthers = can("attendance.mark_others");
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [punching, setPunching] = useState(false);
  const [, setTick] = useState(0);
  const [form, setForm] = useState({ employee_id: "", date: todayLocal(), status: "present" });
  const [dateFilter, setDateFilter] = useState("");

  useEffect(() => { if (user) setForm(s => ({ ...s, employee_id: s.employee_id || user.id })); }, [user]);

  // Re-render every minute so the running worked time stays current.
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 60000);
    return () => clearInterval(t);
  }, []);

  async function load({ background = false } = {}) {
    try {
      const empReq = canDir ? api.get("/employees") : Promise.resolve({ data: [] });
      const [{ data: att }, { data: emps }] = await Promise.all([api.get("/employees/attendance/records"), empReq]);
      const list = canDir ? emps : (user ? [{ id: user.id, name: user.name }] : []);
      const nameMap = Object.fromEntries(list.map(e => [e.id, e.name]));
      if (user) nameMap[user.id] = user.name;
      setRows(att.map(a => ({ ...a, employee_name: a.employee_name || nameMap[a.employee_id] || "Unknown employee" })));
      setUsers(list);
    } catch (e) {
      if (!background) toast.error(formatApiError(e));
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, 60000);

  const today = todayLocal();
  const shownRows = dateFilter ? rows.filter(r => r.date === dateFilter) : rows;
  const mine = rows.find(r => r.employee_id === user?.id && r.date === today);
  const checkedIn = !!mine?.check_in;
  const checkedOut = !!mine?.check_out;
  const workedMinutes = checkedIn && !checkedOut
    ? Math.max(0, Math.floor((Date.now() - new Date(mine.check_in).getTime()) / 60000))
    : mine?.duration_minutes;
  const todayText = !checkedIn
    ? (mine?.status === "leave" ? "On leave today" : "Not checked in yet")
    : checkedOut
      ? `Checked in ${fmtTime(mine.check_in)} · out ${fmtTime(mine.check_out)} · worked ${fmtDuration(workedMinutes)}`
      : `Checked in at ${fmtTime(mine.check_in)} · worked ${fmtDuration(workedMinutes)} so far`;

  async function punch() {
    setPunching(true);
    try {
      await api.post(checkedIn ? "/employees/attendance/check-out" : "/employees/attendance/check-in");
      toast.success(checkedIn ? "Checked out" : "Checked in");
      load();
      onChange?.();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setPunching(false);
    }
  }

  async function submit() {
    if (!form.employee_id) {
      toast.error("Please select an employee");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/employees/attendance/records", form);
      toast.success("Attendance recorded");
      setOpen(false);
      load();
      onChange?.();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  const markingSelf = form.employee_id === user?.id;
  // Leave is recorded through an approved leave request, never self-marked.
  const statusOptions = ["present", "absent", "leave", "half_day", "wfh"].filter(s => !(markingSelf && s === "leave"));

  return (
    <>
      <Card className="border-border mb-4" data-testid="attendance-today-card">
        <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center"><Clock className="h-4.5 w-4.5" /></div>
            <div>
              <div className="text-[13.5px] font-medium">Today</div>
              <div className="text-[12.5px] text-muted-foreground" data-testid="attendance-today-status">{todayText}</div>
            </div>
          </div>
          <Button onClick={punch} disabled={punching || !user} data-testid="attendance-punch-btn">
            {punching ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : checkedIn ? <LogOut className="h-4 w-4 mr-1.5" /> : <LogIn className="h-4 w-4 mr-1.5" />}
            {checkedIn ? (checkedOut ? "Check out again" : "Check out") : "Check in"}
          </Button>
        </CardContent>
      </Card>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <Input type="date" value={dateFilter} onChange={(e) => setDateFilter(e.target.value)} className="w-[170px]" aria-label="Filter by date" data-testid="attendance-date-filter" />
          {dateFilter && <Button variant="ghost" size="sm" onClick={() => setDateFilter("")} data-testid="attendance-date-clear">All dates</Button>}
        </div>
        <Button onClick={() => { setForm(s => ({ ...s, date: todayLocal(), employee_id: s.employee_id || user?.id || "" })); setOpen(true); }} data-testid="attendance-mark-btn"><Plus className="h-4 w-4 mr-1.5" /> Mark attendance</Button>
      </div>
      <Card className="border-border">
        {shownRows.length === 0 ? <EmptyState icon={CalendarDays} title={dateFilter ? "No attendance on this date" : "No attendance yet"} description="Attendance records will appear here." /> : (
          <Table>
            <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Date</TableHead><TableHead>Status</TableHead><TableHead>Check-in</TableHead><TableHead>Check-out</TableHead><TableHead>Worked</TableHead></TableRow></TableHeader>
            <TableBody>{shownRows.map(r => (
              <TableRow key={r.id}>
                <TableCell className="font-medium">{r.employee_name}</TableCell>
                <TableCell>{r.date}</TableCell>
                <TableCell><StatusPill status={r.status} /></TableCell>
                <TableCell className="text-[13px] text-muted-foreground">{fmtTime(r.check_in)}</TableCell>
                <TableCell className="text-[13px] text-muted-foreground">{fmtTime(r.check_out)}</TableCell>
                <TableCell className="text-[13px] text-muted-foreground">{fmtDuration(r.duration_minutes)}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">Mark attendance</DialogTitle><DialogDescription>Record today's status. Existing check-in and check-out times are kept.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Employee</Label>
              <Select
                value={form.employee_id}
                onValueChange={(v) => setForm(s => ({ ...s, employee_id: v, status: v === user?.id && s.status === "leave" ? "present" : s.status }))}
                disabled={!canMarkOthers || !canDir || submitting}
              >
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
                  <SelectContent>{statusOptions.map(s => <SelectItem key={s} value={s} className="capitalize">{s.replace("_"," ")}</SelectItem>)}</SelectContent>
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

function Leave({ onChange }) {
  const { user } = useAuth();
  const { can } = usePermission();
  const canDir = can("employee.view_directory");
  const canApprove = can("leave.approve");
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionId, setActionId] = useState(null);
  const [form, setForm] = useState({ employee_id: "", from_date: "", to_date: "", kind: "casual", reason: "" });

  useEffect(() => { if (user) setForm(s => ({ ...s, employee_id: s.employee_id || user.id })); }, [user]);

  async function load({ background = false } = {}) {
    try {
      const empReq = canDir ? api.get("/employees") : Promise.resolve({ data: [] });
      const [{ data: lv }, { data: emps }] = await Promise.all([api.get("/employees/leave/requests"), empReq]);
      setRows(lv); setUsers(canDir ? emps : (user ? [{ id: user.id, name: user.name }] : []));
    } catch (e) {
      if (!background) toast.error(formatApiError(e));
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, 60000);

  async function submit() {
    if (!form.from_date || !form.to_date || form.from_date > form.to_date) {
      toast.error("Please pick a valid date range");
      return;
    }
    if (!form.reason.trim()) {
      toast.error("Please add a reason");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/employees/leave/requests", form);
      toast.success("Leave requested");
      setOpen(false);
      setForm({ employee_id: user?.id || "", from_date: "", to_date: "", kind: "casual", reason: "" });
      load();
      onChange?.();
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
      onChange?.();
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
                <TableCell className="font-medium">{r.employee_name || "Unknown employee"}</TableCell>
                <TableCell className="capitalize">{r.kind}</TableCell>
                <TableCell className="text-[13px]">{r.from_date} → {r.to_date}</TableCell>
                <TableCell className="text-[13px] text-muted-foreground line-clamp-1">{r.reason}</TableCell>
                <TableCell><StatusPill status={r.status} /></TableCell>
                <TableCell className="text-right space-x-1">
                  {canApprove && r.status === "pending" && r.employee_id !== user?.id && <>
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
  const [form, setForm] = useState({ employee_id: "", period: currentQuarter(), score: 4.0, highlights: "", growth_areas: "" });

  async function load({ background = false } = {}) {
    try {
      const empReq = canDir ? api.get("/employees") : Promise.resolve({ data: [] });
      const [{ data: pr }, { data: emps }] = await Promise.all([api.get("/employees/performance/reviews"), empReq]);
      // Nobody reviews themselves.
      setRows(pr); setUsers(canDir ? emps.filter(e => e.id !== user?.id) : []);
    } catch (e) {
      if (!background) toast.error(formatApiError(e));
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, 60000);

  async function submit() {
    if (!form.employee_id) {
      toast.error("Please select an employee");
      return;
    }
    if (!(form.score >= 1 && form.score <= 5)) {
      toast.error("Score must be between 1 and 5");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/employees/performance/reviews", form);
      toast.success("Review saved");
      setOpen(false);
      setForm({ employee_id: "", period: currentQuarter(), score: 4.0, highlights: "", growth_areas: "" });
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
                    <div className="font-medium text-[14px]">{r.employee_name || "Unknown employee"}</div>
                    <Badge variant="secondary" className="text-[10px]">{r.period}</Badge>
                    <span className="ml-auto inline-flex items-center gap-1 text-warning font-semibold">★ {r.score}</span>
                  </div>
                  {r.employee_designation && <div className="text-[11.5px] text-muted-foreground">{r.employee_designation}</div>}
                  {r.highlights && <div className="mt-2 text-[13px]"><span className="text-muted-foreground text-[11px] uppercase tracking-wide">Highlights · </span>{r.highlights}</div>}
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
              <div><Label>Score (1-5)</Label><Input type="number" step="0.1" min="1" max="5" value={form.score} onChange={(e) => setForm(s => ({ ...s, score: parseFloat(e.target.value) }))} disabled={submitting} /></div>
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

const NO_HEAD = "__none__";

function DepartmentCardBody({ d }) {
  return (
    <>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0"><Building2 className="h-4.5 w-4.5" /></div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <CardTitle className="font-display text-[15px]">{d.name}</CardTitle>
              {d.registered === false && <Badge variant="outline" className="text-[10.5px] border-warning/40 text-warning">Not set up</Badge>}
            </div>
            <div className="text-[11.5px] text-muted-foreground">
              {d.headcount} teammate{d.headcount === 1 ? "" : "s"} · {d.head_name ? `Head: ${d.head_name}` : "No head assigned"}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0 text-[13px] text-muted-foreground">
        {d.description || (d.registered === false
          ? "Some teammates have this department, but it hasn't been created yet."
          : "No description yet.")}
      </CardContent>
    </>
  );
}

function Departments() {
  const { can } = usePermission();
  const canCreate = can("department.create");
  const [rows, setRows] = useState([]);
  const [people, setPeople] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", head_id: NO_HEAD });
  async function load({ background = false } = {}) {
    try {
      const { data } = await api.get("/employees/departments/list");
      setRows(data);
    } catch (e) {
      if (!background) toast.error(formatApiError(e));
    }
  }
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, 60000);
  useEffect(() => {
    if (!canCreate) return;
    api.get("/users/directory").then(({ data }) => setPeople(data || [])).catch(() => setPeople([]));
  }, [canCreate]);

  function startCreate(name = "") {
    setEditing(null);
    setForm({ name, description: "", head_id: NO_HEAD });
    setOpen(true);
  }

  function startEdit(d) {
    setEditing(d);
    setForm({ name: d.name, description: d.description || "", head_id: d.head_id || NO_HEAD });
    setOpen(true);
  }

  async function submit() {
    const name = form.name.trim();
    if (!name) {
      toast.error("Please enter a department name");
      return;
    }
    const body = { name, description: form.description.trim(), head_id: form.head_id === NO_HEAD ? null : form.head_id };
    setSubmitting(true);
    try {
      if (editing) {
        await api.patch(`/employees/departments/${editing.id}`, body);
        toast.success("Department updated");
      } else {
        await api.post("/employees/departments/list", { ...body, head_id: body.head_id || undefined });
        toast.success("Department created");
      }
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  const unregistered = rows.filter((d) => d.registered === false);

  return (
    <>
      {canCreate && <div className="flex justify-end mb-4"><Button onClick={() => startCreate()} data-testid="department-create-btn"><Plus className="h-4 w-4 mr-1.5" /> New department</Button></div>}
      {canCreate && unregistered.length > 0 && (
        <div className="mb-4 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-[13px] text-foreground">
          {unregistered.length} department name{unregistered.length === 1 ? " is" : "s are"} used by teammates but not set up yet. Set them up to give them a head and a description, or edit those teammates to move them into an existing department.
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {rows.map(d => (
          <Card key={d.id || `unregistered-${d.name}`} className="border-border hover-lift flex flex-col">
            <DepartmentCardBody d={d} />
            {canCreate && (
              <div className="mt-auto px-6 pb-4">
                {d.registered === false ? (
                  <Button size="sm" variant="outline" onClick={() => startCreate(d.name)} data-testid="department-setup-btn">
                    <Plus className="h-3.5 w-3.5 mr-1" /> Set up department
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => startEdit(d)} data-testid="department-edit-btn">
                    <Pencil className="h-3.5 w-3.5 mr-1" /> Edit
                  </Button>
                )}
              </div>
            )}
          </Card>
        ))}
      </div>
      <Dialog open={open} onOpenChange={(o) => !submitting && setOpen(o)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? "Edit department" : "New department"}</DialogTitle>
            <DialogDescription>
              {editing ? "Renaming also moves everyone in this department to the new name." : "The department head is optional and can be set later."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm(s => ({ ...s, name: e.target.value }))} disabled={submitting} maxLength={80} /></div>
            <div>
              <Label>Head</Label>
              <Select value={form.head_id} onValueChange={(v) => setForm(s => ({ ...s, head_id: v }))} disabled={submitting}>
                <SelectTrigger className="mt-1"><SelectValue placeholder="No head" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_HEAD}>No head</SelectItem>
                  {people.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}{p.department ? ` · ${p.department}` : ""}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div><Label>Description</Label><Textarea rows={2} value={form.description} onChange={(e) => setForm(s => ({ ...s, description: e.target.value }))} disabled={submitting} maxLength={1000} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {submitting ? "Saving..." : editing ? "Save" : "Create"}
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
  const [tab, setTab] = useState(canDir ? "directory" : "attendance");
  const [searchParams] = useSearchParams();
  const loadStats = useCallback(({ quiet = false } = {}) => {
    api.get("/employees/stats/overview").then(({ data }) => setStats(data)).catch((e) => { if (!quiet) toast.error(formatApiError(e)); });
  }, []);
  const refreshStats = useCallback(() => loadStats({ quiet: true }), [loadStats]);
  useEffect(() => { loadStats(); }, [loadStats]);
  // Quick-create "Invite teammate" may arrive while another tab is open: show the Directory,
  // whose own effect then opens the invite dialog and clears the parameter.
  const wantsInvite = searchParams.get("create") === "invite" || searchParams.get("action") === "invite-teammate";
  useEffect(() => { if (wantsInvite && canDir) setTab("directory"); }, [wantsInvite, canDir]);
  return (
    <div data-testid="employees-page">
      <PageHeader
        eyebrow={personal ? "Personal" : "Module"}
        title={personal ? "My Workspace" : "Employees"}
        description={personal
          ? "Your attendance, leave and performance in one place."
          : "Directory, attendance, leave, performance and departments — the human core of WavyGo."}
      />
      {stats && stats.scope === "self" && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="Days present this month" value={stats.present_this_month} icon={CalendarDays} />
          <StatCard label="Checked in today" value={stats.checked_in_today ? "Yes" : "Not yet"} icon={Clock} tone="success" />
          <StatCard label="Pending leave" value={stats.pending_leave} icon={CalendarDays} tone="warning" />
          <StatCard label="Approved leave" value={stats.approved_leave} icon={CheckCircle2} tone="info" />
        </div>
      )}
      {stats && stats.scope !== "self" && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label={stats.scope === "department" ? "Team members" : "Total teammates"} value={stats.total} icon={Users} />
          <StatCard label="Online now" value={stats.online} icon={Users} tone="success" />
          {stats.scope === "department"
            ? <StatCard label="Department" value={stats.department || "—"} icon={Building2} tone="info" />
            : <StatCard label="Departments" value={stats.departments} icon={Building2} tone="info" />}
          <StatCard label="Pending leave" value={stats.pending_leave} icon={CalendarDays} tone="warning" />
        </div>
      )}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex flex-wrap h-auto gap-1 justify-start">
          {canDir && <TabsTrigger value="directory" data-testid="emp-tab-directory">Directory</TabsTrigger>}
          <TabsTrigger value="attendance" data-testid="emp-tab-attendance">Attendance</TabsTrigger>
          <TabsTrigger value="leave" data-testid="emp-tab-leave">Leave</TabsTrigger>
          {showPerformance && <TabsTrigger value="performance" data-testid="emp-tab-performance">Performance</TabsTrigger>}
          {canDepts && <TabsTrigger value="departments" data-testid="emp-tab-departments">Departments</TabsTrigger>}
        </TabsList>
        {canDir && <TabsContent value="directory" className="mt-6"><Directory onChange={refreshStats} /></TabsContent>}
        <TabsContent value="attendance" className="mt-6"><Attendance onChange={refreshStats} /></TabsContent>
        <TabsContent value="leave" className="mt-6"><Leave onChange={refreshStats} /></TabsContent>
        {showPerformance && <TabsContent value="performance" className="mt-6"><Performance /></TabsContent>}
        {canDepts && <TabsContent value="departments" className="mt-6"><Departments /></TabsContent>}
      </Tabs>
    </div>
  );
}