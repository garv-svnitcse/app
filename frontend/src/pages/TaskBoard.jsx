import { useEffect, useMemo, useState, useRef } from "react";
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
import { Plus, ClipboardList, CheckCircle2, Clock, Sparkles, Calendar as CalIcon, MessageSquare, Trash2, FileText, Paperclip, Download, X, ExternalLink, Github, Linkedin, Link as LinkIcon, Loader2, List, LayoutGrid, ArrowUpDown, Calendar } from "lucide-react";
import { useLiveRefresh } from "@/hooks/useLiveRefresh";
import { api, formatApiError } from "@/lib/api";
import { usePermission } from "@/hooks/usePermission";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

const STATUS_ORDER = ["todo", "in_progress", "review", "completed", "cancelled"];
const STATUS_LABEL = { todo: "To do", in_progress: "In progress", review: "Review", completed: "Completed", cancelled: "Cancelled" };
const PRIORITIES = ["low", "medium", "high", "urgent"];
const EMPTY_FORM = { title: "", description: "", status: "todo", priority: "medium", module: "General", attachments: [], link: "" };

// "YYYY-MM-DD" due dates are calendar days: parse them as local dates, not UTC midnight.
function parseDate(s) {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function formatDateBadge(t) {
  const d = parseDate(t.due_date || t.created_at);
  if (!d) {
    return <span className="text-[12px] text-muted-foreground">---</span>;
  }

  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();

  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const isTomorrow = d.toDateString() === tomorrow.toDateString();

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();

  const isOverdue = t.due_date && d < new Date(now.getFullYear(), now.getMonth(), now.getDate()) && t.status !== "completed" && t.status !== "cancelled";

  if (isToday) {
    return (
      <Badge className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-300 dark:border-emerald-800 text-[11px] font-medium gap-1 shrink-0">
        <Clock className="h-3 w-3" /> Today
      </Badge>
    );
  }
  if (isTomorrow) {
    return (
      <Badge variant="outline" className="bg-blue-500/10 text-blue-600 border-blue-200 dark:border-blue-800 text-[11px] font-medium shrink-0">
        Tomorrow
      </Badge>
    );
  }
  // An open task due yesterday is overdue (red); "Yesterday" is only for done/undated items.
  if (isOverdue) {
    return (
      <Badge variant="destructive" className="text-[11px] font-medium shrink-0">
        Overdue · {d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
      </Badge>
    );
  }
  if (isYesterday) {
    return (
      <Badge variant="outline" className="bg-amber-500/10 text-amber-600 border-amber-200 dark:border-amber-800 text-[11px] font-medium shrink-0">
        Yesterday
      </Badge>
    );
  }

  return (
    <span className="text-[12px] text-foreground/85 font-medium shrink-0" title={d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}>
      {t.due_date ? `Due ${d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
    </span>
  );
}

function initials(name) {
  return (name || "?").split(" ").map(s => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

function getLinkIcon(url) {
  if (!url) return <ExternalLink className="h-3 w-3" />;
  const l = url.toLowerCase();
  if (l.includes("github.com")) return <Github className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />;
  if (l.includes("linkedin.com")) return <Linkedin className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" />;
  return <LinkIcon className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />;
}

function getLinkLabel(url) {
  if (!url) return "Link";
  const l = url.toLowerCase();
  if (l.includes("github.com")) return "GitHub";
  if (l.includes("linkedin.com")) return "LinkedIn";
  return "Reference";
}

// Attachments are metadata ({id, name, ...}); content is fetched with auth from /tasks/:id/files/:fileId.
// Legacy external links carry a `url` instead and open directly.
function PdfChip({ taskId, att, onRemove }) {
  if (!att) return null;
  const meta = typeof att === "string" ? { url: att } : att;
  const name = meta.name || "Document.pdf";

  async function openFile(e) {
    e.stopPropagation();
    if (meta.url) {
      window.open(meta.url.startsWith("http") ? meta.url : `https://${meta.url}`, "_blank", "noopener,noreferrer");
      return;
    }
    try {
      const { data } = await api.get(`/tasks/${taskId}/files/${meta.id}`, { responseType: "blob" });
      const href = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = href;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(href), 10000);
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-red-500/10 hover:bg-red-500/20 text-red-600 border border-red-200 dark:border-red-900/40 text-[11px] font-medium transition-colors">
      <button type="button" onClick={openFile} className="inline-flex items-center gap-1.5" title="Click to view/download PDF">
        <FileText className="h-3.5 w-3.5 text-red-500" />
        <span className="truncate max-w-[180px]">{name}</span>
        <Download className="h-3 w-3 ml-0.5 opacity-70" />
      </button>
      {onRemove && (
        <button type="button" onClick={(e) => { e.stopPropagation(); onRemove(meta); }} className="opacity-60 hover:opacity-100" title="Remove attachment" data-testid={`task-attachment-remove-${meta.id}`}>
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}

function TaskCard({ task, onOpen }) {
  return (
    <div
      onClick={() => onOpen(task)}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/task-id", task.id)}
      className="rounded-lg bg-card border border-border p-3.5 shadow-sm hover:border-primary/40 cursor-pointer space-y-2 group transition-all"
      data-testid={`task-card-${task.id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[13.5px] font-medium text-foreground line-clamp-2 leading-snug group-hover:text-primary transition-colors">
          {task.title}
        </span>
        <StatusPill status={task.priority} />
      </div>

      {task.description && (
        <p className="text-[12px] text-muted-foreground line-clamp-2">{task.description}</p>
      )}

      {/* Badges container */}
      <div className="flex flex-wrap gap-1.5 items-center pt-0.5">
        {task.attachments?.length > 0 && (
          <Badge variant="outline" className="text-[10px] gap-1 bg-red-500/10 text-red-600 border-red-200 font-normal">
            <FileText className="h-3 w-3" /> PDF ({task.attachments.length})
          </Badge>
        )}
        {task.comments?.length > 0 && (
          <Badge variant="outline" className="text-[10px] gap-1 font-normal">
            <MessageSquare className="h-3 w-3" /> {task.comments.length}
          </Badge>
        )}
        {task.link && (
          <a
            href={task.link.startsWith("http") ? task.link : `https://${task.link}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            title={task.link}
            className="inline-flex items-center"
          >
            <Badge variant="outline" className="text-[10px] gap-1 bg-muted/50 hover:bg-muted text-foreground cursor-pointer transition-colors">
              {getLinkIcon(task.link)} {getLinkLabel(task.link)}
            </Badge>
          </a>
        )}
      </div>

      <div className="pt-1 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          {task.due_date && (
            <>
              <Clock className="h-3 w-3" />
              <span>{parseDate(task.due_date)?.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
            </>
          )}
        </div>
        {task.assignee_name && (
          <Avatar className="h-6 w-6 ring-1 ring-border">
            <AvatarImage src={task.assignee_photo || undefined} />
            <AvatarFallback className="bg-wavygo-100 text-wavygo-800 text-[9px] font-semibold">{initials(task.assignee_name)}</AvatarFallback>
          </Avatar>
        )}
      </div>
    </div>
  );
}

function Column({ status, tasks, onOpen, onStatusChange, onNew, canCreate }) {
  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        const id = e.dataTransfer.getData("text/task-id");
        // Dropping a card back into its own column is not a status change.
        if (id && !tasks.some(t => t.id === id)) onStatusChange(id, status);
      }}
      className="min-w-[260px] w-[280px] shrink-0 rounded-xl bg-muted/40 border border-border p-3 flex flex-col"
      data-testid={`kanban-column-${status}`}
    >
      <div className="flex items-center justify-between mb-3 px-1">
        <div className="flex items-center gap-2">
          <StatusPill status={status} />
          <span className="text-[12px] text-muted-foreground">{tasks.length}</span>
        </div>
        {canCreate && (
          <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => onNew(status)}>
            <Plus className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      <div className="space-y-2 flex-1">
        {tasks.map(t => <TaskCard key={t.id} task={t} onOpen={onOpen} />)}
      </div>
    </div>
  );
}

export default function TaskBoard() {
  const { can, role } = usePermission();
  const canCreate = can("task.create");
  const canDelete = can("task.delete");
  const canAssign = can("task.assign");
  const canEditAny = can("task.edit_any");
  // Interns may only move their tasks between statuses; everyone else edits the tasks they can see.
  const canEditFields = can("task.edit_own") && role !== "Intern";
  const { user: me } = useAuth();
  const canRemoveFile = (att) => canEditAny || (!!me && att?.uploaded_by === me.id);
  const taskTitle = role === "Employee" ? "My Tasks" : role === "Intern" ? "Assigned Tasks" : "Task Board";
  const taskDesc = role === "Employee" || role === "Intern"
    ? "Your tasks — track progress, add PDF attachments & comments, and move across statuses."
    : "Every task across WavyGo — assign, attach PDFs, comment, drag between statuses, and never lose track.";

  const [tasks, setTasks] = useState([]);
  const [users, setUsers] = useState([]);
  const [stats, setStats] = useState(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [activeTask, setActiveTask] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState(null);
  const [actionLoadingId, setActionLoadingId] = useState(null);

  const [comment, setComment] = useState("");
  const [commentPdf, setCommentPdf] = useState(null); // { url, name }
  const [editingLink, setEditingLink] = useState(false);
  const [linkInput, setLinkInput] = useState("");

  const commentFileInputRef = useRef(null);
  const taskFileInputRef = useRef(null);
  const detailFileInputRef = useRef(null);

  async function load({ background = false } = {}) {
    try {
      const [{ data: t }, { data: u }, { data: s }] = await Promise.all([
        api.get("/tasks?limit=300"),
        api.get("/users/directory").catch(() => ({ data: [] })),
        api.get("/tasks/stats/overview").catch(() => ({ data: null })),
      ]);
      setTasks(t || []); setUsers(u || []); setStats(s || null);
    } catch (e) {
      if (!background) toast.error(formatApiError(e));
    }
  }
  const [searchParams, setSearchParams] = useSearchParams();
  useLiveRefresh(load, 60000);

useEffect(() => {
  load();
}, []);

useEffect(() => {
  if (
    searchParams.get("create") === "task" ||
    searchParams.get("action") === "create-task"
  ) {
    // Only roles that may create tasks get the dialog; the deep link is dropped otherwise.
    if (canCreate) {
      setForm(EMPTY_FORM);
      setOpen(true);
    }

    setSearchParams(
      (params) => {
        params.delete("create");
        params.delete("action");
        return params;
      },
      { replace: true }
    );
  }
}, [searchParams, setSearchParams, canCreate]);

/*
 * Open a task directly when coming from a notification.
 *
 * Example notification link:
 * /task-board?task_id=68c123abc...
 *
 * This uses the SAME Task Details dialog that is already
 * used when clicking a task card.
 */
useEffect(() => {
  
  const taskId = searchParams.get("task_id");

  if (!taskId) return;

  async function openNotificationTask() {
    try {
      // Fetch the exact task from the backend
      const { data } = await api.get(`/tasks/${taskId}`);

      // Open the existing Task Details dialog
      setActiveTask(data);
      setCommentPdf(null);
      setEditingLink(false);
      setEditMode(false);
      setLinkInput(data.link || "");
      setDetailOpen(true);
    } catch (error) {
      console.error("Failed to open notification task:", error);
      toast.error(formatApiError(error) || "Could not open this task.");
    } finally {
      // Remove task_id from the URL (also on failure) so it is not retried on every URL change.
      setSearchParams(
        (params) => {
          params.delete("task_id");
          return params;
        },
        { replace: true }
      );
    }
  }

  openNotificationTask();
}, [searchParams, setSearchParams]);

  const [sortBy, setSortBy] = useState("current-first");
  const [statusFilter, setStatusFilter] = useState("all");
  const [moduleFilter, setModuleFilter] = useState("all");

  const modules = useMemo(() => {
    const set = new Set(["General"]);
    tasks.forEach(t => { if (t.module) set.add(t.module); });
    return Array.from(set);
  }, [tasks]);

  const filtered = useMemo(() => {
    let list = tasks;
    if (q) {
      const t = q.toLowerCase();
      list = list.filter(x => [x.title, x.description, x.assignee_name, x.module]
        .some(v => (v || "").toLowerCase().includes(t)));
    }
    if (statusFilter !== "all") {
      list = list.filter(x => x.status === statusFilter);
    }
    if (moduleFilter !== "all") {
      list = list.filter(x => x.module === moduleFilter);
    }

    const now = new Date();
    const isDateToday = (dStr) => {
      const d = parseDate(dStr);
      return !!d && d.toDateString() === now.toDateString();
    };

    const getTaskTime = (t) => parseDate(t.due_date || t.created_at)?.getTime() || 0;

    return [...list].sort((a, b) => {
      if (sortBy === "current-first") {
        // Today / current tasks on top
        const aToday = isDateToday(a.due_date) || isDateToday(a.created_at);
        const bToday = isDateToday(b.due_date) || isDateToday(b.created_at);
        if (aToday && !bToday) return -1;
        if (!aToday && bToday) return 1;
        // Then newest / latest dates first
        return getTaskTime(b) - getTaskTime(a);
      }
      if (sortBy === "date-asc") {
        return getTaskTime(a) - getTaskTime(b);
      }
      if (sortBy === "due-urgent") {
        const dueA = parseDate(a.due_date)?.getTime() ?? Infinity;
        const dueB = parseDate(b.due_date)?.getTime() ?? Infinity;
        return dueA - dueB;
      }
      if (sortBy === "priority-desc") {
        const pMap = { urgent: 4, high: 3, medium: 2, low: 1 };
        return (pMap[b.priority] || 0) - (pMap[a.priority] || 0);
      }
      if (sortBy === "title-asc") {
        return (a.title || "").localeCompare(b.title || "");
      }
      return getTaskTime(b) - getTaskTime(a);
    });
  }, [tasks, q, statusFilter, moduleFilter, sortBy]);

  const byStatus = useMemo(() => {
    const m = Object.fromEntries(STATUS_ORDER.map(s => [s, []]));
    for (const t of filtered) (m[t.status] || (m[t.status] = [])).push(t);
    return m;
  }, [filtered]);

  function handleFileSelect(e, callback) {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset right away so picking the same file again (e.g. after a rejection) still fires onChange.
    e.target.value = "";
    if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
      toast.error("Please select a valid PDF file (.pdf)");
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      toast.error("PDF size should be under 15MB");
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      callback({
        url: event.target.result,
        name: file.name,
      });
    };
    reader.readAsDataURL(file);
  }

  // Upload one picked PDF ({url: dataUrl, name}) to the task, or to a comment of it.
  function uploadFile(taskId, pdfObj, commentId = null) {
    return api.post(`/tasks/${taskId}/files`, {
      name: pdfObj.name,
      content_type: "application/pdf",
      data: pdfObj.url,
      comment_id: commentId,
    });
  }

  async function refreshActive(id) {
    const { data } = await api.get(`/tasks/${id}`);
    setActiveTask(data);
    return data;
  }

  async function createTask() {
    if (!form.title?.trim()) {
      toast.error("Please enter a task title");
      return;
    }
    setSubmitting(true);
    try {
      const { attachments, ...rest } = form;
      const { data: created } = await api.post("/tasks", { ...rest, title: rest.title.trim(), assignee_id: rest.assignee_id || null });
      let failed = 0;
      for (const pdf of attachments || []) {
        try { await uploadFile(created.id, pdf); } catch { failed += 1; }
      }
      if (failed) toast.error(`Task created, but ${failed} PDF(s) could not be uploaded`);
      else toast.success("Task created");
      setOpen(false);
      setForm(EMPTY_FORM);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function setStatus(id, status) {
    setActionLoadingId(`status-${id}`);
    try {
      await api.patch(`/tasks/${id}/status`, { status });
      toast.success(`Task status updated to ${STATUS_LABEL[status] || status}`);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingId(null);
    }
  }

  async function openDetail(t) {
    setActiveTask(t);
    setCommentPdf(null);
    setEditingLink(false);
    setEditMode(false);
    setLinkInput(t.link || "");
    setDetailOpen(true);
    try {
      const { data } = await api.get(`/tasks/${t.id}`);
      setActiveTask(data);
      setLinkInput(data.link || "");
    } catch { /* noop */ }
  }

  function startEdit() {
    setEditForm({
      title: activeTask.title || "",
      description: activeTask.description || "",
      priority: activeTask.priority || "medium",
      module: activeTask.module || "General",
      due_date: activeTask.due_date || "",
      assignee_id: activeTask.assignee_id || "",
    });
    setEditMode(true);
  }

  async function saveEdit() {
    if (!activeTask || !editForm) return;
    if (!editForm.title.trim()) {
      toast.error("Please enter a task title");
      return;
    }
    // Send only what changed; the assignee only when the caller may reassign.
    const next = { ...editForm, title: editForm.title.trim(), due_date: editForm.due_date || null, assignee_id: editForm.assignee_id || null };
    if (!canAssign) delete next.assignee_id;
    const payload = Object.fromEntries(Object.entries(next).filter(([k, v]) => (activeTask[k] ?? null) !== v && !(k === "description" && !activeTask[k] && !v)));
    if (Object.keys(payload).length === 0) {
      setEditMode(false);
      return;
    }
    setActionLoadingId(`edit-${activeTask.id}`);
    try {
      await api.patch(`/tasks/${activeTask.id}`, payload);
      await refreshActive(activeTask.id);
      setEditMode(false);
      load();
      toast.success("Task updated");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingId(null);
    }
  }

  async function saveTaskLink() {
    if (!activeTask) return;
    setActionLoadingId(`link-${activeTask.id}`);
    try {
      await api.patch(`/tasks/${activeTask.id}`, { link: linkInput.trim() });
      await refreshActive(activeTask.id);
      setEditingLink(false);
      load();
      toast.success("Reference link saved");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingId(null);
    }
  }

  async function addComment() {
    if ((!comment.trim() && !commentPdf) || !activeTask) return;
    setActionLoadingId(`comment-${activeTask.id}`);
    try {
      const payload = {
        body: comment.trim() || (commentPdf ? `Attached document: ${commentPdf.name}` : ""),
        attachment_name: commentPdf ? commentPdf.name : null,
      };
      const { data: created } = await api.post(`/tasks/${activeTask.id}/comments`, payload);
      let uploadError = null;
      if (commentPdf) {
        try { await uploadFile(activeTask.id, commentPdf, created.id); } catch (err) { uploadError = err; }
      }
      setComment("");
      setCommentPdf(null);
      await refreshActive(activeTask.id);
      load();
      if (uploadError) toast.error(`Comment added, but the PDF failed: ${formatApiError(uploadError)}`);
      else toast.success("Comment added");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingId(null);
    }
  }

  async function addPdfToActiveTask(pdfObj) {
    if (!activeTask) return;
    setActionLoadingId(`pdf-${activeTask.id}`);
    try {
      await uploadFile(activeTask.id, pdfObj);
      await refreshActive(activeTask.id);
      load();
      toast.success("PDF document attached to task");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingId(null);
    }
  }

  async function removeAttachment(att) {
    if (!activeTask || !confirm(`Remove ${att.name || "this attachment"}?`)) return;
    setActionLoadingId(`pdf-${activeTask.id}`);
    try {
      await api.delete(`/tasks/${activeTask.id}/files/${att.id}`);
      await refreshActive(activeTask.id);
      load();
      toast.success("Attachment removed");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingId(null);
    }
  }

  async function deleteTask(id) {
    if (!confirm("Delete this task?")) return;
    setActionLoadingId(`del-${id}`);
    try {
      await api.delete(`/tasks/${id}`);
      toast.success("Task deleted");
      setDetailOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setActionLoadingId(null);
    }
  }

  // Assignee choices mirror the server rules: Founder/Admin pick anyone, Managers stay in their
  // department, everyone else may only take a task themselves.
  const userOpts = (canAssign
    ? users.filter(u => role !== "Manager" || u.id === me?.id || (me?.department && u.department === me.department))
    : users.filter(u => u.id === me?.id)
  ).map(u => ({ value: u.id, label: u.id === me?.id ? `${u.name} (me)` : u.name }));

  return (
    <div data-testid="taskboard-page" className="space-y-6">
      <PageHeader
        eyebrow="Module"
        title={taskTitle}
        description={taskDesc}
        actions={canCreate && (
          <Button onClick={() => { setForm(EMPTY_FORM); setOpen(true); }} data-testid="task-create-btn">
            <Plus className="h-4 w-4 mr-1.5" /> New task
          </Button>
        )}
      />

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <StatCard label="Total" value={Object.values(stats).reduce((a, b) => a + b, 0) - (stats.mine || 0)} icon={ClipboardList} />
          <StatCard label="To do" value={stats.todo} icon={ClipboardList} tone="info" />
          <StatCard label="In progress" value={stats.in_progress} icon={Sparkles} tone="info" />
          <StatCard label="Review" value={stats.review} icon={Sparkles} tone="warning" />
          <StatCard label="Completed" value={stats.completed} icon={CheckCircle2} tone="success" />
          <StatCard label="Assigned to me" value={stats.mine} icon={ClipboardList} tone="default" />
        </div>
      )}

      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <div className="flex-1 flex flex-wrap items-center gap-2.5">
          <Input
            placeholder="Filter tasks by title, assignee, module…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="w-full sm:max-w-xs h-9 text-[13px]"
            data-testid="task-search"
          />

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[130px] h-9 text-[12.5px]">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              {STATUS_ORDER.map(s => (
                <SelectItem key={s} value={s}>{STATUS_LABEL[s] || s}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={moduleFilter} onValueChange={setModuleFilter}>
            <SelectTrigger className="w-[130px] h-9 text-[12.5px]">
              <SelectValue placeholder="Module" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Modules</SelectItem>
              {modules.map(m => (
                <SelectItem key={m} value={m}>{m}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[12px] text-muted-foreground flex items-center gap-1">
            <ArrowUpDown className="h-3.5 w-3.5" /> Sort:
          </span>
          <Select value={sortBy} onValueChange={setSortBy}>
            <SelectTrigger className="w-[185px] h-9 text-[12.5px]">
              <SelectValue placeholder="Sort order" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="current-first">Current / Newest first</SelectItem>
              <SelectItem value="date-asc">Oldest first</SelectItem>
              <SelectItem value="due-urgent">Due Date (Urgent)</SelectItem>
              <SelectItem value="priority-desc">Priority (High to Low)</SelectItem>
              <SelectItem value="title-asc">Title (A to Z)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Tabs defaultValue="list">
        <TabsList className="bg-muted/60 p-1">
          <TabsTrigger value="list" data-testid="task-tab-list" className="gap-1.5">
            <List className="h-4 w-4" /> List
          </TabsTrigger>
          <TabsTrigger value="kanban" data-testid="task-tab-kanban" className="gap-1.5">
            <LayoutGrid className="h-4 w-4" /> Kanban
          </TabsTrigger>
          <TabsTrigger value="calendar" data-testid="task-tab-calendar" className="gap-1.5">
            <CalIcon className="h-4 w-4" /> Calendar
          </TabsTrigger>
        </TabsList>

        <TabsContent value="list" className="mt-4">
          <Card className="border-border">
            {filtered.length === 0 ? (
              <EmptyState icon={ClipboardList} title="No tasks match your filter" />
            ) : (
              <div>
                <div className="hidden sm:grid sm:grid-cols-12 gap-4 px-5 py-3 bg-muted/40 text-[11.5px] font-semibold text-muted-foreground uppercase tracking-wider border-b border-border">
                  <div className="col-span-6">Task Title & Details</div>
                  <div className="col-span-2">Date / Due</div>
                  <div className="col-span-2">Priority</div>
                  <div className="col-span-2 text-right">Status</div>
                </div>
                <div className="divide-y divide-border">
                  {filtered.map(t => (
                    <div
                      key={t.id}
                      onClick={() => openDetail(t)}
                      className="flex flex-col sm:grid sm:grid-cols-12 gap-3 sm:gap-4 px-5 py-3.5 hover:bg-muted/40 transition-colors cursor-pointer items-start sm:items-center"
                    >
                      <div className="col-span-6 min-w-0">
                        <div className="text-[13.5px] font-medium truncate flex items-center gap-2">
                          <span className="truncate">{t.title}</span>
                          {t.attachments?.length > 0 && (
                            <Badge variant="outline" className="text-[10px] gap-1 bg-red-500/10 text-red-600 border-red-200 font-normal shrink-0">
                              <FileText className="h-3 w-3" /> PDF
                            </Badge>
                          )}
                          {t.link && (
                            <Badge variant="outline" className="text-[10px] gap-1 bg-primary/10 text-primary border-primary/20 font-normal shrink-0">
                              {getLinkIcon(t.link)} {getLinkLabel(t.link)}
                            </Badge>
                          )}
                        </div>
                        <div className="text-[11.5px] text-muted-foreground flex items-center gap-2 mt-0.5">
                          <span className="font-medium text-foreground/75">{t.module}</span>
                          <span>·</span>
                          <span className="flex items-center gap-1.5">
                            <Avatar className="h-4 w-4 text-[9px]">
                              {t.assignee_photo ? <AvatarImage src={t.assignee_photo} /> : null}
                              <AvatarFallback className="text-[9px]">{initials(t.assignee_name)}</AvatarFallback>
                            </Avatar>
                            {t.assignee_name || "Unassigned"}
                          </span>
                        </div>
                      </div>

                      <div className="col-span-2 flex items-center">
                        {formatDateBadge(t)}
                      </div>

                      <div className="col-span-2 flex items-center">
                        <StatusPill status={t.priority} />
                      </div>

                      <div className="col-span-2 flex justify-end items-center">
                        <StatusPill status={t.status} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="kanban" className="mt-4">
          <div className="flex gap-3 overflow-x-auto scrollbar-thin pb-4">
            {STATUS_ORDER.map(s => (
              <Column
                key={s}
                status={s}
                tasks={byStatus[s] || []}
                onOpen={openDetail}
                onStatusChange={setStatus}
                onNew={(status) => { setForm({ ...EMPTY_FORM, status }); setOpen(true); }}
                canCreate={canCreate}
              />
            ))}
          </div>
        </TabsContent>

        <TabsContent value="calendar" className="mt-4">
          <Card className="border-border">
            <CardHeader className="pb-2"><CardTitle className="font-display text-[16px]">Upcoming by due date</CardTitle></CardHeader>
            <CardContent>
              {filtered.filter(t => t.due_date).length === 0 ? (
                <EmptyState icon={CalIcon} title="No tasks with due dates" />
              ) : (
                <ul className="space-y-3">
                  {filtered.filter(t => t.due_date).sort((a, b) => (a.due_date || "").localeCompare(b.due_date || "")).map(t => (
                    <li key={t.id} onClick={() => openDetail(t)} className="flex items-center gap-3 p-3 rounded-md border border-border hover:border-primary/40 cursor-pointer">
                      <div className="h-10 w-10 rounded-md bg-primary/10 text-primary flex flex-col items-center justify-center text-[10px] uppercase font-semibold">
                        <div>{parseDate(t.due_date)?.toLocaleDateString("en-IN", { month: "short" })}</div>
                        <div className="text-[14px] font-bold leading-none">{parseDate(t.due_date)?.getDate()}</div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13.5px] font-medium flex items-center gap-2">
                          <span>{t.title}</span>
                          {t.attachments?.length > 0 && (
                            <Badge variant="outline" className="text-[10px] gap-1 bg-red-500/10 text-red-600 border-red-200">
                              <FileText className="h-3 w-3" /> PDF
                            </Badge>
                          )}
                        </div>
                        <div className="text-[11.5px] text-muted-foreground">{t.assignee_name || "Unassigned"} · {t.module}</div>
                      </div>
                      <StatusPill status={t.status} />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Create Task Dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">New task</DialogTitle>
            <DialogDescription>Add a task, attach PDF documents, and assign to a team member.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label>Title</Label><Input className="mt-1" value={form.title} onChange={(e) => setForm(s => ({ ...s, title: e.target.value }))} data-testid="task-title-input" placeholder="e.g. Prepare Patna EV fleet proposal" /></div>
            <div><Label>Description</Label><Textarea rows={3} className="mt-1" value={form.description} onChange={(e) => setForm(s => ({ ...s, description: e.target.value }))} placeholder="Key deliverables, scope, or notes…" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Status</Label>
                <Select value={form.status} onValueChange={(v) => setForm(s => ({ ...s, status: v }))}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>{STATUS_ORDER.map(s => <SelectItem key={s} value={s}>{STATUS_LABEL[s]}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Priority</Label>
                <Select value={form.priority} onValueChange={(v) => setForm(s => ({ ...s, priority: v }))}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>{PRIORITIES.map(p => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Module</Label><Input className="mt-1" value={form.module} onChange={(e) => setForm(s => ({ ...s, module: e.target.value }))} />
              </div>
              <div>
                <Label>Assignee</Label>
                <Select value={form.assignee_id || "__none"} onValueChange={(v) => setForm(s => ({ ...s, assignee_id: v === "__none" ? "" : v }))}>
                  <SelectTrigger className="mt-1" data-testid="task-assignee-select"><SelectValue placeholder="Select teammate" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none">Unassigned</SelectItem>
                    {userOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div><Label>Due date</Label><Input type="date" className="mt-1" value={form.due_date || ""} onChange={(e) => setForm(s => ({ ...s, due_date: e.target.value }))} /></div>

            <div>
              <Label className="flex items-center gap-1.5 text-xs font-semibold">
                <LinkIcon className="h-3.5 w-3.5 text-primary" /> Reference Link (GitHub / LinkedIn / External URL)
              </Label>
              <Input
                className="mt-1"
                value={form.link || ""}
                onChange={(e) => setForm(s => ({ ...s, link: e.target.value }))}
                placeholder="https://github.com/org/repo/issues/1 or https://linkedin.com/in/..."
              />
            </div>

            {/* PDF Attachment Input on Task Creation */}
            <div className="border-t border-border pt-3">
              <Label className="flex items-center gap-1.5 text-xs font-semibold">
                <Paperclip className="h-3.5 w-3.5 text-red-500" /> Attach PDF Document
              </Label>
              <input
                type="file"
                ref={taskFileInputRef}
                accept=".pdf,application/pdf"
                className="hidden"
                onChange={(e) => handleFileSelect(e, (pdfObj) => {
                  // Kept locally and uploaded once the task exists.
                  setForm(s => ({ ...s, attachments: [...(s.attachments || []), pdfObj] }));
                  toast.success(`Attached PDF: ${pdfObj.name}`);
                })}
              />
              <div className="mt-2 flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs gap-1.5"
                  onClick={() => taskFileInputRef.current?.click()}
                >
                  <Paperclip className="h-3.5 w-3.5" /> Upload PDF
                </Button>
                {form.attachments?.length > 0 && (
                  <span className="text-xs text-muted-foreground font-medium">{form.attachments.length} PDF(s) attached</span>
                )}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={createTask} disabled={submitting} data-testid="task-submit-btn">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {submitting ? "Creating task..." : "Create task"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Task Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          {activeTask && (
            <>
              <DialogHeader>
                <div className="flex items-start gap-2">
                  <StatusPill status={activeTask.priority} />
                  <DialogTitle className="font-display flex-1">{activeTask.title}</DialogTitle>
                </div>
                <DialogDescription>{activeTask.module} · Reported by {activeTask.reporter_name || "system"}</DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Status</div>
                    <Select value={activeTask.status} onValueChange={(v) => setStatus(activeTask.id, v).then(() => refreshActive(activeTask.id)).catch(() => {})} disabled={actionLoadingId === `status-${activeTask.id}`}>
                      <SelectTrigger className="mt-1.5"><SelectValue /></SelectTrigger>
                      <SelectContent>{STATUS_ORDER.map(s => <SelectItem key={s} value={s}>{STATUS_LABEL[s]}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Assignee</div>
                    <div className="mt-1.5 flex items-center gap-2">
                      {activeTask.assignee_name ? (
                        <>
                          <Avatar className="h-7 w-7"><AvatarFallback className="bg-wavygo-100 text-wavygo-800 text-[10px]">{initials(activeTask.assignee_name)}</AvatarFallback></Avatar>
                          <div className="text-[13px] font-medium">{activeTask.assignee_name}</div>
                        </>
                      ) : <div className="text-[13px] text-muted-foreground">Unassigned</div>}
                    </div>
                  </div>
                </div>

                {editMode && editForm ? (
                  <div className="space-y-3 border-t border-border pt-3" data-testid="task-edit-form">
                    <div><Label>Title</Label><Input className="mt-1" value={editForm.title} onChange={(e) => setEditForm(s => ({ ...s, title: e.target.value }))} data-testid="task-edit-title-input" /></div>
                    <div><Label>Description</Label><Textarea rows={3} className="mt-1" value={editForm.description} onChange={(e) => setEditForm(s => ({ ...s, description: e.target.value }))} /></div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <Label>Priority</Label>
                        <Select value={editForm.priority} onValueChange={(v) => setEditForm(s => ({ ...s, priority: v }))}>
                          <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                          <SelectContent>{PRIORITIES.map(p => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}</SelectContent>
                        </Select>
                      </div>
                      <div><Label>Module</Label><Input className="mt-1" value={editForm.module} onChange={(e) => setEditForm(s => ({ ...s, module: e.target.value }))} /></div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div><Label>Due date</Label><Input type="date" className="mt-1" value={editForm.due_date || ""} onChange={(e) => setEditForm(s => ({ ...s, due_date: e.target.value }))} /></div>
                      {canAssign && (
                        <div>
                          <Label>Assignee</Label>
                          <Select value={editForm.assignee_id || "__none"} onValueChange={(v) => setEditForm(s => ({ ...s, assignee_id: v === "__none" ? "" : v }))}>
                            <SelectTrigger className="mt-1"><SelectValue placeholder="Select teammate" /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__none">Unassigned</SelectItem>
                              {userOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </div>
                      )}
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => setEditMode(false)} disabled={actionLoadingId === `edit-${activeTask.id}`}>Cancel</Button>
                      <Button size="sm" onClick={saveEdit} disabled={actionLoadingId === `edit-${activeTask.id}`} data-testid="task-edit-save-btn">
                        {actionLoadingId === `edit-${activeTask.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : null}
                        Save changes
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    {activeTask.description && (
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Description</div>
                        <p className="text-[13.5px] text-foreground mt-1.5 leading-relaxed">{activeTask.description}</p>
                      </div>
                    )}
                    {activeTask.due_date && (
                      <div className="text-[12px] text-muted-foreground flex items-center gap-1.5">
                        <Clock className="h-3.5 w-3.5" /> Due {parseDate(activeTask.due_date)?.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                      </div>
                    )}
                  </>
                )}

                {(activeTask.subtasks?.length > 0 || activeTask.tags?.length > 0) && (
                  <div className="space-y-2">
                    {activeTask.tags?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {activeTask.tags.map(tag => <Badge key={tag} variant="outline" className="text-[10px] font-normal">{tag}</Badge>)}
                      </div>
                    )}
                    {activeTask.subtasks?.length > 0 && (
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Subtasks · {activeTask.subtasks.filter(s => s.done).length}/{activeTask.subtasks.length}</div>
                        <ul className="mt-1.5 space-y-1">
                          {activeTask.subtasks.map((s, i) => (
                            <li key={i} className={`text-[12.5px] flex items-center gap-1.5 ${s.done ? "line-through text-muted-foreground" : "text-foreground"}`}>
                              <CheckCircle2 className={`h-3.5 w-3.5 ${s.done ? "text-success" : "text-muted-foreground/40"}`} /> {s.title}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}

                {/* Reference Link Section (View & Edit) */}
                <div className="border-t border-border pt-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-1.5">
                      <LinkIcon className="h-3.5 w-3.5 text-primary" /> Reference Link (GitHub / LinkedIn)
                    </div>
                    {!editingLink && canEditFields && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-xs text-primary"
                        onClick={() => { setLinkInput(activeTask.link || ""); setEditingLink(true); }}
                      >
                        {activeTask.link ? "Edit link" : "+ Add link"}
                      </Button>
                    )}
                  </div>

                  {editingLink ? (
                    <div className="flex items-center gap-2 mt-1">
                      <Input
                        className="h-8 text-xs font-mono"
                        placeholder="https://github.com/... or https://linkedin.com/in/..."
                        value={linkInput}
                        onChange={(e) => setLinkInput(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && saveTaskLink()}
                        disabled={actionLoadingId === `link-${activeTask.id}`}
                      />
                      <Button size="sm" className="h-8 px-3 text-xs" onClick={saveTaskLink} disabled={actionLoadingId === `link-${activeTask.id}`}>
                        {actionLoadingId === `link-${activeTask.id}` ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                        Save
                      </Button>
                      <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => setEditingLink(false)} disabled={actionLoadingId === `link-${activeTask.id}`}>Cancel</Button>
                    </div>
                  ) : activeTask.link ? (
                    <div className="flex items-center gap-2">
                      <a
                        href={activeTask.link.startsWith("http") ? activeTask.link : `https://${activeTask.link}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md bg-muted/60 hover:bg-muted border border-border text-xs font-medium text-foreground transition-colors group"
                      >
                        {getLinkIcon(activeTask.link)}
                        <span className="font-semibold text-muted-foreground">{getLinkLabel(activeTask.link)}:</span>
                        <span className="text-primary hover:underline truncate max-w-[340px]">{activeTask.link}</span>
                        <ExternalLink className="h-3.5 w-3.5 opacity-60 group-hover:opacity-100 ml-1 text-muted-foreground" />
                      </a>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground italic">No GitHub or LinkedIn link added yet.</span>
                  )}
                </div>

                {/* PDF Attachments Section under Task Details */}
                <div className="border-t border-border pt-3">
                  <div className="flex items-center justify-between">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-1.5">
                      <FileText className="h-3.5 w-3.5 text-red-500" /> Attached PDF Documents · {(activeTask.attachments || []).length}
                    </div>
                    {canEditFields && (
                      <>
                        <input
                          type="file"
                          ref={detailFileInputRef}
                          accept=".pdf,application/pdf"
                          className="hidden"
                          onChange={(e) => handleFileSelect(e, (pdfObj) => addPdfToActiveTask(pdfObj))}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs gap-1 text-primary"
                          onClick={() => detailFileInputRef.current?.click()}
                          disabled={actionLoadingId === `pdf-${activeTask.id}`}
                        >
                          {actionLoadingId === `pdf-${activeTask.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <Plus className="h-3.5 w-3.5" />}
                          Attach PDF
                        </Button>
                      </>
                    )}
                  </div>

                  <div className="mt-2.5 flex flex-wrap gap-2">
                    {(activeTask.attachments || []).length === 0 ? (
                      <span className="text-xs text-muted-foreground italic">No PDF documents attached yet.</span>
                    ) : (
                      activeTask.attachments.map((att, idx) => (
                        <PdfChip key={att.id || idx} taskId={activeTask.id} att={att} onRemove={canRemoveFile(att) ? removeAttachment : null} />
                      ))
                    )}
                  </div>
                </div>

                {/* Comments Section */}
                <div className="border-t border-border pt-3">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-1.5">
                    <MessageSquare className="h-3.5 w-3.5" /> Comments · {activeTask.comments?.length || 0}
                  </div>
                  <div className="mt-2 space-y-2 max-h-[220px] overflow-y-auto scrollbar-thin">
                    {(activeTask.comments || []).map(c => (
                      <div key={c.id} className="p-3 rounded-md bg-muted/40 border border-border space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[12px] font-semibold text-foreground">{c.author_name}</div>
                          {c.created_at && (
                            <span className="text-[10px] text-muted-foreground">
                              {new Date(c.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                            </span>
                          )}
                        </div>
                        <div className="text-[13px] text-foreground break-words whitespace-pre-wrap">{c.body}</div>

                        {/* Comment Attachments */}
                        {(c.attachments?.length > 0 || c.attachment_name) && (
                          <div className="pt-1 flex flex-wrap gap-1.5">
                            {c.attachments?.length > 0 ? c.attachments.map((att, i) => (
                              <PdfChip key={att.id || i} taskId={activeTask.id} att={att} onRemove={canRemoveFile(att) ? removeAttachment : null} />
                            )) : (
                              <Badge variant="outline" className="text-[10px] gap-1"><FileText className="h-3 w-3 text-red-500" /> {c.attachment_name}</Badge>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Add Comment Input with PDF Attachment Picker */}
                  <div className="mt-3 space-y-2">
                    {commentPdf && (
                      <div className="flex items-center gap-2 p-1.5 rounded bg-muted/60 text-xs border border-border">
                        <FileText className="h-4 w-4 text-red-500" />
                        <span className="font-medium truncate flex-1">{commentPdf.name}</span>
                        <Button variant="ghost" size="icon" className="h-5 w-5" onClick={() => setCommentPdf(null)}>
                          <X className="h-3 w-3" />
                        </Button>
                      </div>
                    )}

                    <div className="flex items-center gap-2">
                      <Input
                        placeholder="Write a comment with PDF attachment…"
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && addComment()}
                        disabled={actionLoadingId === `comment-${activeTask.id}`}
                      />

                      <input
                        type="file"
                        ref={commentFileInputRef}
                        accept=".pdf,application/pdf"
                        className="hidden"
                        onChange={(e) => handleFileSelect(e, (pdfObj) => setCommentPdf(pdfObj))}
                      />

                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className={`h-9 w-9 shrink-0 ${commentPdf ? "border-red-500 bg-red-50 text-red-600 dark:bg-red-950" : ""}`}
                        title="Attach PDF Document"
                        onClick={() => commentFileInputRef.current?.click()}
                        disabled={actionLoadingId === `comment-${activeTask.id}`}
                      >
                        <Paperclip className="h-4 w-4" />
                      </Button>

                      <Button size="sm" onClick={addComment} disabled={actionLoadingId === `comment-${activeTask.id}`} className="h-9 px-4">
                        {actionLoadingId === `comment-${activeTask.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : null}
                        Post
                      </Button>
                    </div>
                  </div>
                </div>
              </div>

              <DialogFooter>
                {canDelete && (
                  <Button variant="ghost" onClick={() => deleteTask(activeTask.id)} disabled={actionLoadingId === `del-${activeTask.id}`} className="text-destructive">
                    {actionLoadingId === `del-${activeTask.id}` ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <Trash2 className="h-4 w-4 mr-1.5" />}
                    Delete
                  </Button>
                )}
                {canEditFields && !editMode && (
                  <Button variant="outline" onClick={startEdit} data-testid="task-edit-btn">Edit</Button>
                )}
                <Button onClick={() => setDetailOpen(false)}>Close</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
