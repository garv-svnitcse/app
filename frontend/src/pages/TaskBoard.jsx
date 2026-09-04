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
import { Plus, ClipboardList, CheckCircle2, Clock, Sparkles, Calendar as CalIcon, MessageSquare, Trash2, FileText, Paperclip, Download, X, ExternalLink, Github, Linkedin, Link as LinkIcon, Loader2 } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { usePermission } from "@/hooks/usePermission";
import { toast } from "sonner";

const STATUS_ORDER = ["todo", "in_progress", "review", "completed", "cancelled"];
const STATUS_LABEL = { todo: "To do", in_progress: "In progress", review: "Review", completed: "Completed", cancelled: "Cancelled" };

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

function PdfChip({ url, name }) {
  if (!url) return null;
  return (
    <a
      href={url}
      download={name || "Document.pdf"}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-red-500/10 hover:bg-red-500/20 text-red-600 border border-red-200 dark:border-red-900/40 text-[11px] font-medium transition-colors"
      title="Click to view/download PDF"
    >
      <FileText className="h-3.5 w-3.5 text-red-500" />
      <span className="truncate max-w-[180px]">{name || "Document.pdf"}</span>
      <Download className="h-3 w-3 ml-0.5 opacity-70" />
    </a>
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
              <span>{new Date(task.due_date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
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
        if (id) onStatusChange(id, status);
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
  const [form, setForm] = useState({ title: "", description: "", status: "todo", priority: "medium", module: "General", attachments: [], link: "" });
  const [submitting, setSubmitting] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState(null);

  const [comment, setComment] = useState("");
  const [commentPdf, setCommentPdf] = useState(null); // { url, name }
  const [editingLink, setEditingLink] = useState(false);
  const [linkInput, setLinkInput] = useState("");

  const commentFileInputRef = useRef(null);
  const taskFileInputRef = useRef(null);
  const detailFileInputRef = useRef(null);

  async function load() {
    try {
      const [{ data: t }, { data: u }, { data: s }] = await Promise.all([
        api.get("/tasks?limit=300"),
        api.get("/users").catch(() => ({ data: [] })),
        api.get("/tasks/stats/overview").catch(() => ({ data: null })),
      ]);
      setTasks(t || []); setUsers(u || []); setStats(s || null);
    } catch (e) {
      toast.error(formatApiError(e));
    }
  }

  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (searchParams.get("create") === "task" || searchParams.get("action") === "create-task") {
      setForm({ title: "", description: "", status: "todo", priority: "medium", module: "General", attachments: [], link: "" });
      setOpen(true);
      setSearchParams(params => {
        params.delete("create");
        params.delete("action");
        return params;
      }, { replace: true });
    }
  }, [searchParams]);

  const filtered = useMemo(() => {
    if (!q) return tasks;
    const t = q.toLowerCase();
    return tasks.filter(x => JSON.stringify(x).toLowerCase().includes(t));
  }, [tasks, q]);

  const byStatus = useMemo(() => {
    const m = Object.fromEntries(STATUS_ORDER.map(s => [s, []]));
    for (const t of filtered) (m[t.status] || (m[t.status] = [])).push(t);
    return m;
  }, [filtered]);

  function handleFileSelect(e, callback) {
    const file = e.target.files?.[0];
    if (!file) return;
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
      e.target.value = "";
    };
    reader.readAsDataURL(file);
  }

  async function createTask() {
    setSubmitting(true);
    try {
      await api.post("/tasks", form);
      toast.success("Task created");
      setOpen(false);
      setForm({ title: "", description: "", status: "todo", priority: "medium", module: "General", attachments: [], link: "" });
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
    setLinkInput(t.link || "");
    setDetailOpen(true);
    try {
      const { data } = await api.get(`/tasks/${t.id}`);
      setActiveTask(data);
      setLinkInput(data.link || "");
    } catch { /* noop */ }
  }

  async function saveTaskLink() {
    if (!activeTask) return;
    setActionLoadingId(`link-${activeTask.id}`);
    try {
      await api.patch(`/tasks/${activeTask.id}`, { link: linkInput.trim() });
      const { data } = await api.get(`/tasks/${activeTask.id}`);
      setActiveTask(data);
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
        attachments: commentPdf ? [commentPdf.url] : [],
        attachment_name: commentPdf ? commentPdf.name : null,
      };
      await api.post(`/tasks/${activeTask.id}/comments`, payload);
      setComment("");
      setCommentPdf(null);
      const { data } = await api.get(`/tasks/${activeTask.id}`);
      setActiveTask(data);
      load();
      toast.success("Comment added");
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
      const currentAttachments = activeTask.attachments || [];
      const updatedAttachments = [...currentAttachments, pdfObj.url];
      await api.patch(`/tasks/${activeTask.id}`, { attachments: updatedAttachments });
      const { data } = await api.get(`/tasks/${activeTask.id}`);
      setActiveTask(data);
      load();
      toast.success("PDF document attached to task");
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

  const userOpts = users.map(u => ({ value: u.id, label: u.name }));

  return (
    <div data-testid="taskboard-page" className="space-y-6">
      <PageHeader
        eyebrow="Module"
        title={taskTitle}
        description={taskDesc}
        actions={canCreate && (
          <Button onClick={() => { setForm({ title: "", description: "", status: "todo", priority: "medium", module: "General", attachments: [], link: "" }); setOpen(true); }} data-testid="task-create-btn">
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

      <Input placeholder="Filter tasks by title, assignee, module…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-md" data-testid="task-search" />

      <Tabs defaultValue="kanban">
        <TabsList>
          <TabsTrigger value="kanban" data-testid="task-tab-kanban">Kanban</TabsTrigger>
          <TabsTrigger value="list" data-testid="task-tab-list">List</TabsTrigger>
          <TabsTrigger value="calendar" data-testid="task-tab-calendar">Calendar</TabsTrigger>
        </TabsList>

        <TabsContent value="kanban" className="mt-4">
          <div className="flex gap-3 overflow-x-auto scrollbar-thin pb-4">
            {STATUS_ORDER.map(s => (
              <Column
                key={s}
                status={s}
                tasks={byStatus[s] || []}
                onOpen={openDetail}
                onStatusChange={setStatus}
                onNew={(status) => { setForm(f => ({ ...f, status })); setOpen(true); }}
                canCreate={canCreate}
              />
            ))}
          </div>
        </TabsContent>

        <TabsContent value="list" className="mt-4">
          <Card className="border-border">
            {filtered.length === 0 ? (
              <EmptyState icon={ClipboardList} title="No tasks match your filter" />
            ) : (
              <div className="divide-y divide-border">
                {filtered.map(t => (
                  <div key={t.id} onClick={() => openDetail(t)} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/40 cursor-pointer">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium truncate flex items-center gap-2">
                        <span>{t.title}</span>
                        {t.attachments?.length > 0 && (
                          <Badge variant="outline" className="text-[10px] gap-1 bg-red-500/10 text-red-600 border-red-200 font-normal">
                            <FileText className="h-3 w-3" /> PDF
                          </Badge>
                        )}
                      </div>
                      <div className="text-[11.5px] text-muted-foreground">{t.module} · {t.assignee_name || "Unassigned"}</div>
                    </div>
                    <div className="w-[110px] flex justify-end shrink-0">
                      <StatusPill status={t.status} />
                    </div>
                    <div className="w-[85px] flex justify-end shrink-0">
                      <StatusPill status={t.priority} />
                    </div>
                    <div className="text-[12px] text-muted-foreground hidden sm:block w-[60px] text-right shrink-0">
                      {t.due_date 
                        ? new Date(t.due_date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })
                        : "---"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
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
                        <div>{new Date(t.due_date).toLocaleDateString("en-IN", { month: "short" })}</div>
                        <div className="text-[14px] font-bold leading-none">{new Date(t.due_date).getDate()}</div>
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
        <DialogContent className="max-w-xl">
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
                  <SelectContent>{["low","medium","high","urgent"].map(p => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Module</Label><Input className="mt-1" value={form.module} onChange={(e) => setForm(s => ({ ...s, module: e.target.value }))} />
              </div>
              {canAssign && (
                <div>
                  <Label>Assignee</Label>
                  <Select value={form.assignee_id || ""} onValueChange={(v) => setForm(s => ({ ...s, assignee_id: v }))}>
                    <SelectTrigger className="mt-1"><SelectValue placeholder="Select teammate" /></SelectTrigger>
                    <SelectContent>{userOpts.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              )}
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
                  setForm(s => ({ ...s, attachments: [...(s.attachments || []), pdfObj.url] }));
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
        <DialogContent className="max-w-2xl">
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
                    <Select value={activeTask.status} onValueChange={(v) => setStatus(activeTask.id, v).then(() => openDetail({ ...activeTask, status: v }))} disabled={actionLoadingId === `status-${activeTask.id}`}>
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

                {activeTask.description && (
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Description</div>
                    <p className="text-[13.5px] text-foreground mt-1.5 leading-relaxed">{activeTask.description}</p>
                  </div>
                )}

                {/* Reference Link Section (View & Edit) */}
                <div className="border-t border-border pt-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-1.5">
                      <LinkIcon className="h-3.5 w-3.5 text-primary" /> Reference Link (GitHub / LinkedIn)
                    </div>
                    {!editingLink && (
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
                  </div>

                  <div className="mt-2.5 flex flex-wrap gap-2">
                    {(activeTask.attachments || []).length === 0 ? (
                      <span className="text-xs text-muted-foreground italic">No PDF documents attached yet.</span>
                    ) : (
                      activeTask.attachments.map((pdfUrl, idx) => (
                        <PdfChip key={idx} url={pdfUrl} name={`Task_Document_${idx + 1}.pdf`} />
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
                        <div className="flex items-center justify-between">
                          <div className="text-[12px] font-semibold text-foreground">{c.author_name}</div>
                          {c.created_at && (
                            <span className="text-[10px] text-muted-foreground">
                              {new Date(c.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                            </span>
                          )}
                        </div>
                        <div className="text-[13px] text-foreground">{c.body}</div>

                        {/* Comment Attachments */}
                        {(c.attachments?.length > 0 || c.attachment_name) && (
                          <div className="pt-1 flex flex-wrap gap-1.5">
                            {c.attachments?.map((attUrl, i) => (
                              <PdfChip key={i} url={attUrl} name={c.attachment_name || `Comment_Attachment_${i+1}.pdf`} />
                            )) || (
                              c.attachment_name && <Badge variant="outline" className="text-[10px] gap-1"><FileText className="h-3 w-3 text-red-500" /> {c.attachment_name}</Badge>
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
                <Button onClick={() => setDetailOpen(false)}>Close</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
