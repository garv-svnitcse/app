import { useEffect, useMemo, useRef, useState } from "react";
import { PageHeader, EmptyState } from "@/components/module/ModulePrimitives";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { MessagesSquare, Hash, Users2, Megaphone, Plus, Send, Search, Lock, Building2, ShieldCheck, ShieldPlus, ShieldMinus, UserPlus, UserMinus, LogOut, Crown, Settings2, MoreHorizontal, Pencil, Trash2, Copy, Ban, Check, X, Paperclip, FileText } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { formatChatTime, formatChatTimeFull, formatDateSeparator } from "@/lib/chatTime";

const KIND_ICON = { channel: Hash, dm: MessagesSquare, group: Users2, announcement: Megaphone };
const KIND_LABEL = { channel: "Channel", group: "Group", announcement: "Announcement channel" };

const HIGH_ROLES = ["Founder", "Admin", "Manager"];
const HIGH_DESIG_KEYWORDS = [
  "founder", "ceo", "cto", "coo", "cfo", "chief", "director", "head",
  "president", "vp", "vice president", "manager", "lead", "general manager"
];

function isHighDesignation(u) {
  if (!u) return false;
  if (HIGH_ROLES.includes(u.role)) return true;
  const d = (u.designation || "").toLowerCase();
  return HIGH_DESIG_KEYWORDS.some(k => d.includes(k));
}

function initials(name) { return (name || "?").split(" ").map(s => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase(); }

const NO_IDS = [];

/* Checkbox list of DM-eligible users (from /connect/users) for picking group members. */
function MemberPicker({ users, selected, onChange, exclude = NO_IDS }) {
  const [search, setSearch] = useState("");
  const list = useMemo(() => {
    const t = search.trim().toLowerCase();
    return users.filter(u => !exclude.includes(u.id) && (!t ||
      [u.name, u.email, u.role, u.designation, u.department].some(v => (v || "").toLowerCase().includes(t))));
  }, [users, exclude, search]);
  const toggle = (id) => onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id]);
  return (
    <div>
      <Label>Members{selected.length > 0 && <span className="text-muted-foreground font-normal"> · {selected.length} selected</span>}</Label>
      <div className="relative mt-1">
        <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="Search people…" value={search} onChange={(e) => setSearch(e.target.value)} className="h-8 pl-8 text-[13px]" />
      </div>
      <div className="mt-2 max-h-[220px] overflow-y-auto scrollbar-thin rounded-md border border-border divide-y divide-border" data-testid="connect-member-picker">
        {list.length === 0 ? (
          <div className="text-center py-6 text-sm text-muted-foreground">No matching members found.</div>
        ) : list.map(u => (
          <label key={u.id} className="flex items-center gap-3 px-3 py-2 hover:bg-muted/70 cursor-pointer">
            <Checkbox checked={selected.includes(u.id)} onCheckedChange={() => toggle(u.id)} />
            <Avatar className="h-7 w-7">
              <AvatarImage src={u.photo || undefined} />
              <AvatarFallback className="text-[9px] bg-wavygo-100 text-wavygo-800">{initials(u.name)}</AvatarFallback>
            </Avatar>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-medium truncate">{u.name}</div>
              <div className="text-[11px] text-muted-foreground truncate">{u.designation || u.role}{u.department ? ` · ${u.department}` : ""}</div>
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}

/* Checkbox list of departments (from /connect/departments); picking one adds all its current members. */
function DepartmentPicker({ departments, selected, onChange }) {
  if (departments.length === 0) return null;
  const toggle = (name) => onChange(selected.includes(name) ? selected.filter(x => x !== name) : [...selected, name]);
  return (
    <div>
      <Label>Whole departments{selected.length > 0 && <span className="text-muted-foreground font-normal"> · {selected.length} selected</span>}</Label>
      <div className="mt-1 max-h-[140px] overflow-y-auto scrollbar-thin rounded-md border border-border divide-y divide-border" data-testid="connect-department-picker">
        {departments.map(d => (
          <label key={d.name} className="flex items-center gap-3 px-3 py-2 hover:bg-muted/70 cursor-pointer">
            <Checkbox checked={selected.includes(d.name)} onCheckedChange={() => toggle(d.name)} />
            <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="flex-1 text-[13px] font-medium truncate">{d.name}</span>
            <span className="text-[11px] text-muted-foreground">{d.member_count} {d.member_count === 1 ? "person" : "people"}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

const IMG_RE = /\.(png|jpe?g|gif|webp|avif|svg)(\?.*)?$/i;
const isImageUrl = (u) => IMG_RE.test(u || "");
const fileNameFromUrl = (u) => decodeURIComponent((u || "").split("/").pop().split("?")[0]) || "file";

export default function WavygoConnect() {
  const { user } = useAuth();
  const { can } = usePermission();
  const canCreateChannel = can("connect.create_channel");
  const canCreateAnnouncement = can("connect.create_announcement");
  const canPostAnnouncement = can("connect.post_announcement");
  const [channels, setChannels] = useState([]);
  const [users, setUsers] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [editingId, setEditingId] = useState(null);   // message being edited inline
  const [editText, setEditText] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [deleting, setDeleting] = useState(null);     // message awaiting delete confirmation
  // Re-render every 30s so Edit/Delete disappear once a message's edit window closes.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  // Senders may edit/delete for a limited time (server-enforced; `editable_until` null = no limit).
  const withinWindow = (m) => !m.editable_until || new Date(m.editable_until).getTime() > now;
  const minutesLeft = (m) => (m.editable_until ? Math.max(1, Math.ceil((new Date(m.editable_until).getTime() - now) / 60000)) : null);
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  function pickFile(e) {
    const f = e.target.files?.[0];
    e.target.value = ""; // lets you pick the same file again
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) {
      toast.error("File too large (max 10 MB)");
      return;
    }
    setFile(f);
  }
  const [createOpen, setCreateOpen] = useState(false);
  const [dmOpen, setDmOpen] = useState(false);
  const [dmSearch, setDmSearch] = useState("");
  const [form, setForm] = useState({ name: "", kind: "channel", description: "", members: [], departments: [] });
  const [departments, setDepartments] = useState([]);
  const [addOpen, setAddOpen] = useState(false);
  const [addSel, setAddSel] = useState([]);
  const [addDepts, setAddDepts] = useState([]);
  const [membersOpen, setMembersOpen] = useState(false);
  const [members, setMembers] = useState([]);
  // Channel whose members are shown / managed: the open channel, or (Founder/Admin) any row from
  // "Manage channels", including channels they are not in. Membership only, never messages.
  const [target, setTarget] = useState(null);
  const [addExclude, setAddExclude] = useState(NO_IDS);
  const [manageOpen, setManageOpen] = useState(false);
  const [manageRows, setManageRows] = useState([]);
  const [manageQ, setManageQ] = useState("");
  const [fromManage, setFromManage] = useState(false);  // reopen "Manage channels" when the members dialog closes
  const [convertRow, setConvertRow] = useState(null);
  const [convertDepts, setConvertDepts] = useState([]);
  const targetIdRef = useRef(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);   // a create / add-members request is in flight
  const sendingRef = useRef(false);          // blocks double sends (Enter pressed twice)
  const scrollRef = useRef(null);
  const paneRef = useRef(null);
  const revealRef = useRef(false);      // bring the pane into view once the picked channel's messages render
  const activeIdRef = useRef(null);
  const msgSigRef = useRef("");        // "<channel>:<count>:<last id>" of the rendered messages
  const scrollNextRef = useRef(false); // scroll to bottom after the next messages render

  // Open a channel; on the stacked (mobile) layout bring the message pane + composer into view.
  function revealPane() {
    paneRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }
  function selectChannel(id) {
    setActiveId(id);
    if (window.matchMedia("(max-width: 1023px)").matches) {
      revealRef.current = id !== activeIdRef.current;  // same channel: no re-render to wait for
      requestAnimationFrame(revealPane);  // immediate feedback; repeated after the messages render
    }
  }

  async function loadChannels(selectId = null, silent = false) {
    try {
      const { data } = await api.get("/connect/channels");
      const openId = selectId || activeIdRef.current;
      // the open channel is marked read as messages arrive, so never badge it
      setChannels(data.map(c => (c.id === openId ? { ...c, unread: 0 } : c)));
      if (selectId) selectChannel(selectId);
      // keep the open channel only while it is still visible (e.g. not after being removed from it)
      else setActiveId(prev => (prev && data.some(c => c.id === prev) ? prev : data[0]?.id || null));
    } catch (e) { if (!silent) toast.error(formatApiError(e)); }
  }

  async function loadUsers() {
    try {
      const { data } = await api.get("/connect/users");
      setUsers(data || []);
    } catch (e) { toast.error(formatApiError(e)); }
  }

  // Load once on mount, then refresh the channel list every 15 s.
  useEffect(() => {
    loadChannels(); loadUsers();
    const t = setInterval(() => loadChannels(null, true), 15000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (dmOpen) {
      loadUsers();
      setDmSearch("");
    }
  }, [dmOpen]);

  async function loadDepartments() {
    if (!canCreateChannel) return;
    try {
      const { data } = await api.get("/connect/departments");
      setDepartments(data || []);
    } catch { /* department picking is optional; individual members still work */ }
  }

  async function loadMembers(id) {
    try {
      const { data } = await api.get(`/connect/channels/${id}/members`);
      if (id === targetIdRef.current) setMembers(data || []);
    } catch (e) { toast.error(formatApiError(e)); }
  }

  async function loadManageRows() {
    try {
      const { data } = await api.get("/connect/manage/channels");
      setManageRows(data || []);
    } catch (e) { toast.error(formatApiError(e)); }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (createOpen || addOpen || convertRow) { loadUsers(); loadDepartments(); } }, [createOpen, addOpen, convertRow]);

  const targetId = target?.id || null;
  useEffect(() => {
    targetIdRef.current = targetId;
    setMembers([]);
    if (membersOpen && targetId) loadMembers(targetId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [membersOpen, targetId]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (manageOpen) { setManageQ(""); loadManageRows(); } }, [manageOpen]);

  function openMembers(ch, viaManage = false) {
    setTarget(ch); setFromManage(viaManage);
    if (viaManage) setManageOpen(false);
    setMembersOpen(true);
  }
  function onMembersOpenChange(open) {
    setMembersOpen(open);
    if (!open && fromManage) { setFromManage(false); setManageOpen(true); }
  }
  function onAddOpenChange(open) {
    setAddOpen(open);
    if (!open && fromManage) { setFromManage(false); setManageOpen(true); }
  }
  function openAdd(ch, exclude) {
    setTarget(ch); setAddExclude(exclude || NO_IDS);
    setAddSel([]); setAddDepts([]); setAddOpen(true);
  }
  // A membership change returns the updated channel: refresh the target and the lists that show it.
  function afterMembershipChange(data) {
    if (data) setTarget(t => (t && t.id === data.id ? { ...t, ...data } : t));
    loadChannels(null, true);
    if (fromManage || manageOpen) loadManageRows();
  }

  function markRead(id) {
    api.post(`/connect/channels/${id}/read`).catch(() => { /* retried on the next change */ });
    setChannels(cs => cs.map(c => (c.id === id && c.unread ? { ...c, unread: 0 } : c)));
  }

  function isNearBottom() {
    const el = scrollRef.current;
    return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  // Only re-render when the channel's messages changed; follow new messages only when the reader
  // is already near the bottom (or just opened the channel / sent a message).
  async function loadMessages(id, { scroll = false, silent = false } = {}) {
    try {
      const { data } = await api.get(`/connect/channels/${id}/messages`);
      if (id !== activeIdRef.current) return;
      // Include the latest edit/delete time so changes to existing messages re-render too.
      const changed = data.reduce((max, m) => (m.updated_at && m.updated_at > max ? m.updated_at : max), "");
      const sig = `${id}:${data.length}:${data[data.length - 1]?.id || ""}:${changed}`;
      if (sig === msgSigRef.current) return;
      msgSigRef.current = sig;
      scrollNextRef.current = scroll || isNearBottom();
      setMessages(data);
      markRead(id);
    } catch (e) { if (!silent) toast.error(formatApiError(e)); }
  }
  useEffect(() => {
    activeIdRef.current = activeId;
    msgSigRef.current = "";
    setEditingId(null);
    if (activeId) {
      loadMessages(activeId, { scroll: true });
      const t = setInterval(() => loadMessages(activeId, { silent: true }), 5000);
      return () => clearInterval(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  useEffect(() => {
    if (scrollNextRef.current && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    scrollNextRef.current = false;
    if (revealRef.current) { revealRef.current = false; revealPane(); }
  }, [messages]);

  async function createChannel() {
    if (!form.name.trim() || busy) return;
    setBusy(true);
    try {
      const pick = form.kind !== "announcement";
      const { data } = await api.post("/connect/channels", {
        name: form.name.trim(), kind: form.kind, description: form.description.trim(),
        members: pick ? form.members : [], departments: pick ? form.departments : [],
      });
      toast.success(`${KIND_LABEL[form.kind] || "Channel"} created`);
      setCreateOpen(false); setForm({ name: "", kind: "channel", description: "", members: [], departments: [] });
      loadChannels(data.id);
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  async function addMembers() {
    if (!target || (addSel.length === 0 && addDepts.length === 0) || busy) return;
    setBusy(true);
    try {
      const before = target.member_count ?? target.members?.length ?? 0;
      const { data } = await api.post(`/connect/channels/${target.id}/members`, { member_ids: addSel, departments: addDepts });
      const n = (data.member_count ?? data.members?.length ?? 0) - before;
      toast.success(n > 0 ? `${n} member${n > 1 ? "s" : ""} added` : "Everyone selected is already a member");
      onAddOpenChange(false); setAddSel([]); setAddDepts([]);
      afterMembershipChange(data);
      if (membersOpen) loadMembers(target.id);
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  async function removeMember(member) {
    if (!target || busy) return;
    const leaving = member.id === user?.id;
    if (!window.confirm(leaving ? `Leave ${target.name}?` : `Remove ${member.name} from ${target.name}?`)) return;
    setBusy(true);
    try {
      const { data } = await api.delete(`/connect/channels/${target.id}/members/${member.id}`);
      if (leaving) {
        toast.success(`You left ${target.name}`);
        onMembersOpenChange(false);
        if (target.id === activeId) setActiveId(null);
        afterMembershipChange(data);
      } else {
        toast.success(`${member.name} removed`);
        loadMembers(target.id); afterMembershipChange(data);
      }
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  async function setAdmin(member, makeAdmin) {
    if (!target || busy) return;
    if (!makeAdmin && member.id === user?.id && !window.confirm(`Step down as admin of ${target.name}?`)) return;
    setBusy(true);
    try {
      const url = `/connect/channels/${target.id}/admins/${member.id}`;
      const { data } = makeAdmin ? await api.post(url) : await api.delete(url);
      toast.success(makeAdmin ? `${member.name} is now an admin` : `${member.name} is no longer an admin`);
      loadMembers(target.id); afterMembershipChange(data);
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  function closeConvert() {
    setConvertRow(null); setManageOpen(true);  // back to the list it was opened from
  }

  async function convertToMembersOnly() {
    if (!convertRow || busy) return;
    setBusy(true);
    try {
      await api.post(`/connect/channels/${convertRow.id}/members-only`, { departments: convertDepts });
      toast.success(`${convertRow.name} is now members-only`);
      closeConvert(); setConvertDepts([]);
      loadChannels(null, true);  // reopening "Manage channels" reloads its rows
    } catch (e) { toast.error(formatApiError(e)); } finally { setBusy(false); }
  }

  async function openDm(peerId) {
    try {
      const { data } = await api.post(`/connect/dm/${peerId}`);
      setDmOpen(false);
      loadChannels(data.id);
    } catch (e) { toast.error(formatApiError(e)); }
  }

  // ------------------------- edit / delete -------------------------

  function startEdit(m) {
    setEditingId(m.id);
    setEditText(m.body);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditText("");
  }

  async function saveEdit(m) {
    const body = editText.trim();
    if (!body || savingEdit) return;
    if (body === m.body) { cancelEdit(); return; }
    setSavingEdit(true);
    try {
      const { data } = await api.patch(`/connect/channels/${activeId}/messages/${m.id}`, { body });
      setMessages((list) => list.map((x) => (x.id === m.id ? data : x)));
      cancelEdit();
      loadChannels(null, true);
    } catch (e) { toast.error(formatApiError(e)); } finally { setSavingEdit(false); }
  }

  async function confirmDeleteMessage() {
    const m = deleting;
    if (!m) return;
    try {
      const { data } = await api.delete(`/connect/channels/${activeId}/messages/${m.id}`);
      setMessages((list) => list.map((x) => (x.id === m.id ? data : x)));
      if (editingId === m.id) cancelEdit();
      toast.success("Message deleted");
      loadChannels(null, true);
    } catch (e) { toast.error(formatApiError(e)); } finally { setDeleting(null); }
  }

  async function copyMessage(m) {
    try { await navigator.clipboard.writeText(m.body); toast.success("Copied"); } catch { toast.error("Couldn't copy"); }
  }

  async function send() {
    if ((!text.trim() && !file) || !activeId || sendingRef.current) return;
    sendingRef.current = true;
    setUploading(Boolean(file));
    try {
      let attachments = [];
      if (file) {
        const fd = new FormData();
        fd.append("file", file); // must match the backend parameter name "file"
        const { data: up } = await api.post("/connect/upload", fd);
        attachments = [up.url];
      }
      await api.post(`/connect/channels/${activeId}/messages`, {
        body: text.trim() || (file ? `📎 ${file.name}` : ""),
        attachments,
      });
      setText("");
      setFile(null);
      loadMessages(activeId, { scroll: true });
      loadChannels(null, true);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      sendingRef.current = false;
      setUploading(false);
    }
  }

  const active = channels.find(c => c.id === activeId);
  const canAddMembers = Boolean(active?.can_manage);
  const isPrivate = Boolean(active?.members_only) && active?.kind !== "dm" && active?.kind !== "announcement";
  const isOrgAdmin = user?.role === "Founder" || user?.role === "Admin";
  // Members dialog rules (mirror the API): target is the channel being managed.
  const targetManage = Boolean(target?.can_manage);
  const adminCount = members.filter(m => m.is_admin).length;
  const canLeave = members.some(m => m.id === user?.id) && (!target?.department || isOrgAdmin);
  const canRemove = (m) => targetManage && m.id !== user?.id && (!m.is_creator || isOrgAdmin);
  const canPromote = (m) => targetManage && !m.is_admin && m.active !== false;
  // never demote the last admin (department groups have none by default); creator only by Founder/Admin
  const canDemote = (m) => targetManage && m.is_admin && (!m.is_creator || isOrgAdmin)
    && (adminCount > 1 || Boolean(target?.department));

  const manageList = useMemo(() => {
    const t = manageQ.trim().toLowerCase();
    return manageRows.filter(r => !t || [r.name, r.description, r.department, r.kind].some(v => (v || "").toLowerCase().includes(t)));
  }, [manageRows, manageQ]);

  const grouped = useMemo(() => {
    const g = { announcement: [], channel: [], group: [], dm: [] };
    for (const c of channels) {
      if (q && !((c.display_name || c.name) + " " + (c.description || "")).toLowerCase().includes(q.toLowerCase())) continue;
      (g[c.kind] || (g[c.kind] = [])).push(c);
    }
    return g;
  }, [channels, q]);

  const { deptMembers, leadershipMembers, otherMembers } = useMemo(() => {
    const qLower = dmSearch.trim().toLowerCase();
    const currDept = (user?.department || "").trim().toLowerCase();
    const isFounderOrAdmin = user?.role === "Founder" || user?.role === "Admin";

    const base = users.filter(u => u.id !== user?.id && u.status !== "deactivated" && u.is_active !== false);

    const matchesSearch = (u) => {
      if (!qLower) return true;
      return (
        (u.name || "").toLowerCase().includes(qLower) ||
        (u.role || "").toLowerCase().includes(qLower) ||
        (u.designation || "").toLowerCase().includes(qLower) ||
        (u.department || "").toLowerCase().includes(qLower) ||
        (u.email || "").toLowerCase().includes(qLower)
      );
    };

    const dept = [];
    const leadership = [];
    const others = [];

    for (const u of base) {
      if (!matchesSearch(u)) continue;
      const uDept = (u.department || "").trim().toLowerCase();
      const isSameDept = Boolean(currDept) && Boolean(uDept) && uDept === currDept;
      const isHighDesig = isHighDesignation(u);

      if (isSameDept) {
        dept.push(u);
      } else if (isHighDesig) {
        leadership.push(u);
      } else if (isFounderOrAdmin) {
        others.push(u);
      }
    }

    return { deptMembers: dept, leadershipMembers: leadership, otherMembers: others };
  }, [users, user, dmSearch]);

  function renderUserRow(u) {
    const isLeadership = isHighDesignation(u);
    return (
      <li key={u.id}>
        <button
          onClick={() => openDm(u.id)}
          className="w-full flex items-center gap-3 py-2.5 px-2 hover:bg-muted/70 rounded-md text-left transition-colors group"
        >
          <div className="relative shrink-0">
            <Avatar className="h-8 w-8">
              <AvatarImage src={u.photo || undefined} />
              <AvatarFallback className="text-[10px] bg-wavygo-100 text-wavygo-800">
                {initials(u.name)}
              </AvatarFallback>
            </Avatar>
            <span
              className={cn(
                "absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-background",
                u.online ? "bg-emerald-500" : "bg-slate-300"
              )}
            />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[13px] font-medium text-foreground truncate group-hover:text-primary transition-colors">
                {u.name}
              </span>
              {isLeadership && (
                <Badge variant="secondary" className="text-[9.5px] px-1.5 py-0 h-4 bg-amber-500/10 text-amber-700 dark:text-amber-400 font-normal border-amber-500/20">
                  Leadership
                </Badge>
              )}
            </div>
            <div className="text-[11px] text-muted-foreground truncate">
              {u.designation || u.role}
              {u.department ? ` · ${u.department}` : ""}
            </div>
          </div>

          <Badge variant="outline" className="text-[10.5px] shrink-0 font-normal text-muted-foreground">
            {u.role}
          </Badge>
        </button>
      </li>
    );
  }

  return (
    <div data-testid="connect-page">
      <PageHeader
        eyebrow="Module"
        title="WavyGo Connect"
        description="Internal channels, announcements, groups and direct messages — all your team communication in one place."
        actions={
          <>
            {isOrgAdmin && (
              <Button variant="outline" onClick={() => setManageOpen(true)} data-testid="connect-manage-btn"><Settings2 className="h-4 w-4 mr-1.5" /> Manage channels</Button>
            )}
            <Button variant="outline" onClick={() => setDmOpen(true)}><MessagesSquare className="h-4 w-4 mr-1.5" /> New DM</Button>
            {canCreateChannel && (
              <Button onClick={() => setCreateOpen(true)} data-testid="connect-create-btn"><Plus className="h-4 w-4 mr-1.5" /> New channel</Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4 min-h-[560px]">
        {/* Channel list */}
        <Card className="border-border p-3 flex flex-col">
          <div className="relative">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 pl-8 text-[13px]" />
          </div>
          {/* Radix renders the viewport content as display:table, which lets long previews widen the list
              past the card and push unread badges out of view; force a block so rows truncate. */}
          <ScrollArea className="mt-3 flex-1 [&_[data-radix-scroll-area-viewport]>div]:!block">
            {["announcement", "channel", "group", "dm"].map(kind => (
              (grouped[kind] || []).length > 0 && (
                <div key={kind} className="mb-4">
                  <div className="text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground px-2 mb-1.5">
                    {kind === "dm" ? "Direct Messages" : kind === "announcement" ? "Announcements" : kind === "group" ? "Groups" : "Channels"}
                  </div>
                  <ul className="space-y-0.5">
                    {(grouped[kind] || []).map(c => {
                      const Icon = KIND_ICON[c.kind] || Hash;
                      const isActive = c.id === activeId;
                      const displayName = c.display_name || c.name;
                      return (
                        <li key={c.id}>
                          <button onClick={() => selectChannel(c.id)}
                                  className={cn(
                                    "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-[13px] transition-colors",
                                    isActive ? "bg-primary/10 text-foreground font-medium" : "text-foreground/80 hover:bg-muted"
                                  )}>
                            {c.kind === "dm" ? (
                              <Avatar className="h-5 w-5">
                                <AvatarImage src={c.peer_photo || undefined} />
                                <AvatarFallback className="text-[8px] bg-wavygo-100 text-wavygo-800">{initials(displayName)}</AvatarFallback>
                              </Avatar>
                            ) : <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                            <span className="flex-1 min-w-0 text-left">
                              <span className={cn("block truncate", c.unread > 0 && "font-semibold text-foreground")}>{displayName}</span>
                              {c.last_body && <span className="block truncate text-[11px] font-normal text-muted-foreground">{c.last_body}</span>}
                            </span>
                            {c.unread > 0 && !isActive && (
                              <Badge className="h-4 min-w-4 px-1 text-[10px] rounded-full justify-center shrink-0" data-testid="connect-unread-badge">
                                {c.unread > 99 ? "99+" : c.unread}
                              </Badge>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )
            ))}
          </ScrollArea>
        </Card>

        {/* Message pane */}
        <Card ref={paneRef} className="border-border flex flex-col overflow-hidden scroll-mt-20">
          {!active ? (
            <EmptyState icon={MessagesSquare} title="Select a channel" description="Pick a channel from the list to start chatting." />
          ) : (
            <>
              <div className="px-5 py-3 border-b border-border flex items-center gap-3">
                {active.kind === "dm" ? (
                  <>
                    <Avatar className="h-8 w-8"><AvatarImage src={active.peer_photo || undefined} /><AvatarFallback className="text-[10px] bg-wavygo-100 text-wavygo-800">{initials(active.display_name || active.name)}</AvatarFallback></Avatar>
                    <div className="flex-1">
                      <div className="font-display text-[15px] font-semibold">{active.display_name || active.name}</div>
                      <div className="text-[11px] text-muted-foreground flex items-center gap-1.5">
                        <span className={cn("h-1.5 w-1.5 rounded-full", active.peer_online ? "bg-emerald-500" : "bg-slate-400")} />
                        {active.peer_online ? "Online" : "Offline"} · {active.peer_role}
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="h-8 w-8 rounded-md bg-primary/10 text-primary flex items-center justify-center">
                      {(() => { const Icon = KIND_ICON[active.kind] || Hash; return <Icon className="h-4 w-4" />; })()}
                    </div>
                    <div className="flex-1">
                      <div className="font-display text-[15px] font-semibold flex items-center gap-2">
                        {active.name}
                        {isPrivate && <Badge variant="secondary" className="text-[10px]"><Lock className="h-2.5 w-2.5 mr-1" />{active.department ? "Department" : "Private"}</Badge>}
                        {active.kind === "announcement" && <Badge className="bg-info/10 text-info hover:bg-info/10 text-[10px]">Announcement</Badge>}
                      </div>
                      {active.description && <div className="text-[11.5px] text-muted-foreground">{active.description}</div>}
                    </div>
                    {isPrivate && (
                      <Button variant="ghost" size="sm" onClick={() => openMembers(active)} data-testid="connect-members-btn">
                        <Users2 className="h-4 w-4 mr-1.5" /> {active.member_count ?? active.members?.length ?? 0}
                      </Button>
                    )}
                    {canAddMembers && (
                      <Button variant="outline" size="sm" onClick={() => openAdd(active, active.members)} data-testid="connect-add-members-btn">
                        <UserPlus className="h-4 w-4 mr-1.5" /> Add members
                      </Button>
                    )}
                  </>
                )}
              </div>

              <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 space-y-4 min-h-[300px] max-h-[520px]">
                {messages.length === 0 && <div className="text-center text-sm text-muted-foreground py-16">No messages yet. Say hello 👋</div>}
                {messages.map((m, idx) => {
                  const mine = m.sender_id === user?.id;
                  const open = withinWindow(m);
                  const canEditMsg = mine && !m.deleted && open;
                  const canDeleteMsg = !m.deleted && (isOrgAdmin || (mine && open));
                  const left = mine && open ? minutesLeft(m) : null;
                  const editing = editingId === m.id;
                  // Day separator: show when the date changes between consecutive messages
                  const prevMsg = idx > 0 ? messages[idx - 1] : null;
                  const curDay = m.created_at ? new Date(m.created_at).toDateString() : "";
                  const prevDay = prevMsg?.created_at ? new Date(prevMsg.created_at).toDateString() : "";
                  const showSep = curDay && curDay !== prevDay;
                  return (
                    <div key={m.id}>
                      {showSep && (
                        <div className="flex items-center gap-3 my-3">
                          <div className="flex-1 h-px bg-border" />
                          <span className="text-[10.5px] font-medium text-muted-foreground uppercase tracking-wide select-none">{formatDateSeparator(m.created_at)}</span>
                          <div className="flex-1 h-px bg-border" />
                        </div>
                      )}
                      <div className={cn("group flex gap-2.5", mine && "flex-row-reverse")} data-testid="connect-message">
                        <Avatar className="h-7 w-7 shrink-0"><AvatarImage src={m.sender_photo || undefined} /><AvatarFallback className="text-[9px] bg-wavygo-100 text-wavygo-800">{initials(m.sender_name)}</AvatarFallback></Avatar>
                        <div className={cn("max-w-[70%] min-w-0", mine && "text-right", editing && "w-full")}>
                          <div className={cn("flex items-baseline gap-2 mb-0.5", mine && "flex-row-reverse")}>
                            <span className="text-[12px] font-medium">{m.sender_name}</span>
                            <span className="text-[10.5px] text-muted-foreground cursor-default" title={formatChatTimeFull(m.created_at)}>{formatChatTime(m.created_at)}</span>
                            {m.edited_at && !m.deleted && <span className="text-[10.5px] text-muted-foreground italic" title={`Edited ${formatChatTimeFull(m.edited_at)}`}>(edited)</span>}
                          </div>
                          <div className={cn("flex items-center gap-1", mine && "flex-row-reverse")}>
                            {editing ? (
                              <div className="w-full text-left space-y-1.5">
                                <Textarea
                                  autoFocus
                                  rows={2}
                                  maxLength={4000}
                                  value={editText}
                                  onChange={(e) => setEditText(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveEdit(m); }
                                    if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
                                  }}
                                  className="text-[13.5px] min-h-[60px]"
                                  data-testid="connect-edit-input"
                                />
                                <div className="flex items-center justify-end gap-1.5">
                                  <span className="text-[10.5px] text-muted-foreground mr-auto">Enter to save · Esc to cancel</span>
                                  <Button size="sm" variant="ghost" className="h-7 gap-1" onClick={cancelEdit}><X className="h-3.5 w-3.5" />Cancel</Button>
                                  <Button size="sm" className="h-7 gap-1" onClick={() => saveEdit(m)} disabled={!editText.trim() || savingEdit} data-testid="connect-edit-save">
                                    <Check className="h-3.5 w-3.5" />Save
                                  </Button>
                                </div>
                              </div>
                            ) : m.deleted ? (
                              <div className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[13px] italic text-muted-foreground border border-dashed border-border">
                                <Ban className="h-3.5 w-3.5" /> This message was deleted
                              </div>
                            ) : (
                              <div className={cn("inline-block rounded-lg px-3 py-2 text-[13.5px] leading-relaxed break-words text-left", mine ? "bg-primary text-primary-foreground" : "bg-muted text-foreground")}>
                                {m.body && <div className="whitespace-pre-wrap">{m.body}</div>}
                                {(m.attachments || []).map((url, i) => (
                                  isImageUrl(url) ? (
                                    <a key={i} href={url} target="_blank" rel="noreferrer" className="block mt-1.5">
                                      <img src={url} alt="attachment" className="max-h-60 max-w-full rounded-md object-cover" />
                                    </a>
                                  ) : (
                                    <a key={i} href={url} target="_blank" rel="noreferrer"
                                       className="mt-1.5 flex items-center gap-2 rounded-md bg-black/10 px-2.5 py-1.5 text-[12.5px] underline-offset-2 hover:underline">
                                      <FileText className="h-4 w-4 shrink-0" />
                                      <span className="truncate">{fileNameFromUrl(url)}</span>
                                    </a>
                                  )
                                ))}
                              </div>
                            )}
                            {!editing && !m.deleted && (
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <button type="button" aria-label="Message options" data-testid="connect-message-menu"
                                          className="shrink-0 h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 hover:bg-muted transition-opacity">
                                    <MoreHorizontal className="h-4 w-4" />
                                  </button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align={mine ? "end" : "start"} className="w-40">
                                  <DropdownMenuItem onSelect={() => copyMessage(m)}><Copy className="h-4 w-4 mr-2" />Copy text</DropdownMenuItem>
                                  {canEditMsg && <DropdownMenuItem onSelect={() => startEdit(m)} data-testid="connect-message-edit"><Pencil className="h-4 w-4 mr-2" />Edit</DropdownMenuItem>}
                                  {mine && !open && !isOrgAdmin && (
                                    <div className="px-2 py-1.5 text-[11px] text-muted-foreground">Edit and delete are only possible for 15 minutes after sending.</div>
                                  )}
                                  {left !== null && (
                                    <div className="px-2 py-1 text-[11px] text-muted-foreground">Editable for {left} more min</div>
                                  )}
                                  {canDeleteMsg && (
                                    <>
                                      <DropdownMenuSeparator />
                                      <DropdownMenuItem onSelect={() => setDeleting(m)} className="text-destructive focus:text-destructive" data-testid="connect-message-delete">
                                        <Trash2 className="h-4 w-4 mr-2" />{mine ? "Delete" : "Delete (moderate)"}
                                      </DropdownMenuItem>
                                    </>
                                  )}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {(active.kind !== "announcement" || canPostAnnouncement) && (
                <div className="border-t border-border px-4 py-3">
                  {file && (
                    <div className="mb-2 flex items-center gap-2 rounded-md border border-border bg-muted/60 px-3 py-1.5 text-[12.5px]">
                      <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="flex-1 truncate">{file.name}</span>
                      <button type="button" onClick={() => setFile(null)} aria-label="Remove file" className="text-muted-foreground hover:text-destructive">
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <input ref={fileRef} type="file" hidden onChange={pickFile}
                           accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip" data-testid="connect-file-input" />
                    <Button type="button" variant="outline" size="icon" className="h-10 w-10 shrink-0"
                            onClick={() => fileRef.current?.click()} disabled={uploading} title="Attach file" data-testid="connect-attach-btn">
                      <Paperclip className="h-4 w-4" />
                    </Button>
                    <Input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => {
                             if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                             else if (e.key === "ArrowUp" && !text) {
                               const last = [...messages].reverse().find((m) => m.sender_id === user?.id && !m.deleted && withinWindow(m));
                               if (last) { e.preventDefault(); startEdit(last); }
                             }
                           }}
                           placeholder={`Message ${active.kind === "dm" ? active.display_name || active.name : "#" + active.name}`}
                           className="h-10" data-testid="connect-message-input" />
                    <Button onClick={send} disabled={(!text.trim() && !file) || uploading} data-testid="connect-send-btn">
                      <Send className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      <AlertDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this message?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleting && deleting.sender_id !== user?.id
                ? `This removes ${deleting.sender_name}'s message for everyone. It will show as "This message was deleted".`
                : `It will be removed for everyone and show as "This message was deleted". This can't be undone.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleting?.body && (
            <div className="rounded-md bg-muted px-3 py-2 text-[13px] text-muted-foreground line-clamp-3 whitespace-pre-wrap">{deleting.body}</div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDeleteMessage} className="bg-destructive text-destructive-foreground hover:bg-destructive/90" data-testid="connect-confirm-delete">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* New channel dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">New channel</DialogTitle><DialogDescription>Only the people and departments you add can see, read and post in channels and groups. Announcements reach everyone.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm(s => ({ ...s, name: e.target.value }))} placeholder="e.g. patna-ops" /></div>
            <div>
              <Label>Kind</Label>
              <Select value={form.kind} onValueChange={(v) => setForm(s => ({ ...s, kind: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="channel">Channel — members only</SelectItem>
                  <SelectItem value="group">Group — members only</SelectItem>
                  {canCreateAnnouncement && <SelectItem value="announcement">Announcement — broadcast</SelectItem>}
                </SelectContent>
              </Select>
            </div>
            <div><Label>Description</Label><Textarea rows={2} value={form.description} onChange={(e) => setForm(s => ({ ...s, description: e.target.value }))} /></div>
            {form.kind !== "announcement" && (
              <>
                <DepartmentPicker departments={departments} selected={form.departments} onChange={(departments) => setForm(s => ({ ...s, departments }))} />
                <MemberPicker users={users} selected={form.members} onChange={(members) => setForm(s => ({ ...s, members }))} />
                <p className="text-[11.5px] text-muted-foreground">You are added as the admin. Departments add everyone currently in them.</p>
              </>
            )}
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button><Button onClick={createChannel} disabled={!form.name.trim() || busy} data-testid="connect-create-submit">Create</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add group members dialog */}
      <Dialog open={addOpen} onOpenChange={onAddOpenChange}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display">Add members</DialogTitle>
            <DialogDescription>{target ? `Add people to ${target.name}.` : ""}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <DepartmentPicker departments={departments} selected={addDepts} onChange={setAddDepts} />
            <MemberPicker users={users} selected={addSel} onChange={setAddSel} exclude={addExclude} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => onAddOpenChange(false)}>Cancel</Button>
            <Button onClick={addMembers} disabled={(addSel.length === 0 && addDepts.length === 0) || busy} data-testid="connect-add-members-submit">Add</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Channel members dialog */}
      <Dialog open={membersOpen} onOpenChange={onMembersOpenChange}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display">Members</DialogTitle>
            <DialogDescription>
              {target ? `${members.length || target.member_count || 0} people can see and post in ${target.name}.` : ""}
              {target && fromManage && !members.some(m => m.id === user?.id) && " You manage membership only; messages stay private to members."}
            </DialogDescription>
          </DialogHeader>
          <ul className="max-h-[360px] overflow-y-auto scrollbar-thin divide-y divide-border rounded-md border border-border" data-testid="connect-members-list">
            {members.map(m => (
              <li key={m.id} className="flex items-center gap-3 px-3 py-2">
                <Avatar className="h-8 w-8">
                  <AvatarImage src={m.photo || undefined} />
                  <AvatarFallback className="text-[10px] bg-wavygo-100 text-wavygo-800">{initials(m.name)}</AvatarFallback>
                </Avatar>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium truncate flex items-center gap-1.5">
                    {m.name}{m.id === user?.id && <span className="text-muted-foreground font-normal">(you)</span>}
                    {m.is_admin && (
                      <Badge variant="secondary" className="text-[9.5px] px-1.5 py-0 h-4 font-normal"><Crown className="h-2.5 w-2.5 mr-1" />Admin</Badge>
                    )}
                  </div>
                  <div className="text-[11px] text-muted-foreground truncate">{m.designation || m.role}{m.department ? ` · ${m.department}` : ""}</div>
                </div>
                {canPromote(m) && (
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-muted-foreground hover:text-primary" disabled={busy}
                          onClick={() => setAdmin(m, true)} aria-label={`Make ${m.name} an admin`} title="Make admin" data-testid="connect-promote-admin-btn">
                    <ShieldPlus className="h-4 w-4" />
                  </Button>
                )}
                {canDemote(m) && (
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-muted-foreground hover:text-amber-600" disabled={busy}
                          onClick={() => setAdmin(m, false)} aria-label={`Remove ${m.name} as admin`} title="Remove as admin" data-testid="connect-demote-admin-btn">
                    <ShieldMinus className="h-4 w-4" />
                  </Button>
                )}
                {canRemove(m) && (
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-muted-foreground hover:text-destructive" disabled={busy}
                          onClick={() => removeMember(m)} aria-label={`Remove ${m.name}`} data-testid="connect-remove-member-btn">
                    <UserMinus className="h-4 w-4" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <DialogFooter className="sm:justify-between gap-2">
            {canLeave ? (
              <Button variant="outline" className="text-destructive" disabled={busy}
                      onClick={() => removeMember({ id: user?.id, name: user?.name })} data-testid="connect-leave-btn">
                <LogOut className="h-4 w-4 mr-1.5" /> Leave
              </Button>
            ) : <span />}
            {targetManage && (
              <Button onClick={() => { setMembersOpen(false); openAdd(target, members.map(m => m.id)); }}>
                <UserPlus className="h-4 w-4 mr-1.5" /> Add members
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manage all channels (Founder / Admin): membership metadata only, no message content */}
      <Dialog open={manageOpen} onOpenChange={setManageOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-display">Manage channels</DialogTitle>
            <DialogDescription>Every channel and group, including ones you're not in. You can manage members and admins; messages stay visible to members only.</DialogDescription>
          </DialogHeader>
          <div className="relative">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search channels…" value={manageQ} onChange={(e) => setManageQ(e.target.value)} className="h-8 pl-8 text-[13px]" />
          </div>
          <ul className="max-h-[400px] overflow-y-auto scrollbar-thin divide-y divide-border rounded-md border border-border" data-testid="connect-manage-list">
            {manageList.length === 0 ? (
              <li className="text-center py-6 text-sm text-muted-foreground">No channels found.</li>
            ) : manageList.map(r => {
              const Icon = KIND_ICON[r.kind] || Hash;
              return (
                <li key={r.id} className="flex items-center gap-3 px-3 py-2">
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium truncate flex items-center gap-1.5">
                      <span className="truncate">{r.name}</span>
                      {r.kind === "announcement" ? (
                        <Badge className="bg-info/10 text-info hover:bg-info/10 text-[9.5px] px-1.5 py-0 h-4 font-normal">Announcement</Badge>
                      ) : r.members_only ? (
                        <Badge variant="secondary" className="text-[9.5px] px-1.5 py-0 h-4 font-normal"><Lock className="h-2.5 w-2.5 mr-1" />{r.department ? "Department" : "Private"}</Badge>
                      ) : (
                        <Badge variant="outline" className="text-[9.5px] px-1.5 py-0 h-4 font-normal">Public</Badge>
                      )}
                    </div>
                    <div className="text-[11px] text-muted-foreground truncate">
                      {r.kind === "announcement" ? "Everyone" : `${r.member_count} member${r.member_count === 1 ? "" : "s"}`}
                      {r.is_member ? " · you're a member" : ""}
                    </div>
                  </div>
                  {r.can_convert && (
                    <Button variant="outline" size="sm" className="h-7 px-2 text-[12px]" disabled={busy}
                            onClick={() => { setConvertDepts([]); setManageOpen(false); setConvertRow(r); }} data-testid="connect-convert-btn">
                      <Lock className="h-3.5 w-3.5 mr-1" /> Make members-only
                    </Button>
                  )}
                  {r.members_only && r.kind !== "announcement" && (
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-[12px]" onClick={() => openMembers(r, true)} data-testid="connect-manage-members-btn">
                      <Users2 className="h-3.5 w-3.5 mr-1" /> Members
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </DialogContent>
      </Dialog>

      {/* Convert a legacy public channel to members-only (Founder / Admin) */}
      <Dialog open={Boolean(convertRow)} onOpenChange={(open) => { if (!open) closeConvert(); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display">Make members-only</DialogTitle>
            <DialogDescription>
              {convertRow ? `${convertRow.name} will stop being visible to everyone. Its ${convertRow.member_count} current member${convertRow.member_count === 1 ? "" : "s"} and its creator keep access; the creator (or you, if it has none) becomes its admin.` : ""}
            </DialogDescription>
          </DialogHeader>
          <DepartmentPicker departments={departments} selected={convertDepts} onChange={setConvertDepts} />
          <p className="text-[11.5px] text-muted-foreground">Optionally add whole departments. People who aren't members lose access to the channel and its history.</p>
          <DialogFooter>
            <Button variant="outline" onClick={closeConvert}>Cancel</Button>
            <Button onClick={convertToMembersOnly} disabled={busy} data-testid="connect-convert-submit"><Lock className="h-4 w-4 mr-1.5" /> Make members-only</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New DM dialog */}
      <Dialog open={dmOpen} onOpenChange={setDmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <MessagesSquare className="h-5 w-5 text-primary" />
              Start a direct message
            </DialogTitle>
            <DialogDescription>
              {user?.department
                ? `Connect with members of ${user.department} or company leadership.`
                : "Connect with colleagues and company leadership."}
            </DialogDescription>
          </DialogHeader>

          <div className="relative mt-1">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by name, role, designation or department…"
              value={dmSearch}
              onChange={(e) => setDmSearch(e.target.value)}
              className="h-9 pl-8 text-[13px]"
            />
          </div>

          <div className="max-h-[380px] overflow-y-auto scrollbar-thin -mx-6 px-6 space-y-4 pt-1">
            {deptMembers.length === 0 && leadershipMembers.length === 0 && otherMembers.length === 0 ? (
              <div className="text-center py-8 text-sm text-muted-foreground">
                No matching members found.
              </div>
            ) : (
              <>
                {deptMembers.length > 0 && (
                  <div>
                    <div className="text-[10.5px] uppercase tracking-[0.14em] font-semibold text-muted-foreground flex items-center gap-1.5 mb-1.5 px-1">
                      <Building2 className="h-3.5 w-3.5 text-primary" />
                      {user?.department ? `${user.department} Department` : "My Department"}
                      <span className="text-[10px] text-muted-foreground font-normal">({deptMembers.length})</span>
                    </div>
                    <ul className="divide-y divide-border">
                      {deptMembers.map(u => renderUserRow(u))}
                    </ul>
                  </div>
                )}

                {leadershipMembers.length > 0 && (
                  <div>
                    <div className="text-[10.5px] uppercase tracking-[0.14em] font-semibold text-muted-foreground flex items-center gap-1.5 mb-1.5 px-1">
                      <ShieldCheck className="h-3.5 w-3.5 text-amber-500" />
                      Company Leadership & High Designation
                      <span className="text-[10px] text-muted-foreground font-normal">({leadershipMembers.length})</span>
                    </div>
                    <ul className="divide-y divide-border">
                      {leadershipMembers.map(u => renderUserRow(u))}
                    </ul>
                  </div>
                )}

                {otherMembers.length > 0 && (
                  <div>
                    <div className="text-[10.5px] uppercase tracking-[0.14em] font-semibold text-muted-foreground flex items-center gap-1.5 mb-1.5 px-1">
                      <Users2 className="h-3.5 w-3.5 text-muted-foreground" />
                      Other Team Members
                      <span className="text-[10px] text-muted-foreground font-normal">({otherMembers.length})</span>
                    </div>
                    <ul className="divide-y divide-border">
                      {otherMembers.map(u => renderUserRow(u))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}