import { useCallback, useEffect, useState } from "react";
import { Briefcase, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, formatApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";

const EMPTY_ASSIGNEE = "__unassigned__";
const STATUSES = [
  { value: "available", label: "Available" },
  { value: "in_use", label: "In use" },
  { value: "maintenance", label: "Maintenance" },
  { value: "retired", label: "Retired" },
];

const EMPTY_FORM = {
  name: "",
  category: "Other",
  description: "",
  status: "available",
  assigned_to: "",
};

export default function ResourcesSection() {
  const [resources, setResources] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [resourceResponse, employeeResponse] = await Promise.all([
        api.get("/resources"),
        api.get("/employees"),
      ]);
      setResources(resourceResponse.data);
      setEmployees(employeeResponse.data);
    } catch (error) {
      toast.error(formatApiError(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setOpen(true);
  }

  function openEdit(resource) {
    setEditing(resource);
    setForm({
      name: resource.name || "",
      category: resource.category || "Other",
      description: resource.description || "",
      status: resource.status || "available",
      assigned_to: resource.assigned_to || "",
    });
    setOpen(true);
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form, assigned_to: form.assigned_to || null };
      if (editing) {
        await api.patch(`/resources/${editing.id}`, payload);
        toast.success("Resource updated");
      } else {
        await api.post("/resources", payload);
        toast.success("Resource added");
      }
      setOpen(false);
      await load();
    } catch (error) {
      toast.error(formatApiError(error));
    } finally {
      setSaving(false);
    }
  }

  async function remove(resource) {
    if (!window.confirm(`Remove ${resource.name} from company resources?`)) return;
    try {
      await api.delete(`/resources/${resource.id}`);
      toast.success("Resource removed");
      await load();
    } catch (error) {
      toast.error(formatApiError(error));
    }
  }

  return (
    <Card className="border-border" data-testid="dashboard-resources">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="font-display text-[17px] flex items-center gap-2">
              <Briefcase className="h-4 w-4 text-primary" /> Resources
            </CardTitle>
            <CardDescription>Company resources and their current assignments</CardDescription>
          </div>
          <Button size="sm" onClick={openCreate} data-testid="resource-create">
            <Plus className="mr-1.5 h-4 w-4" /> Add resource
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading resources
          </div>
        ) : resources.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">No company resources yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Resource</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Assigned to</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {resources.map((resource) => (
                  <TableRow key={resource.id}>
                    <TableCell>
                      <div className="font-medium">{resource.name}</div>
                      {resource.description && <div className="text-xs text-muted-foreground line-clamp-1">{resource.description}</div>}
                    </TableCell>
                    <TableCell>{resource.category}</TableCell>
                    <TableCell className="text-muted-foreground">{resource.assigned_to_name || "Unassigned"}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{STATUSES.find((status) => status.value === resource.status)?.label || resource.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => openEdit(resource)} aria-label={`Edit ${resource.name}`}>
                          <Pencil className="mr-1 h-3.5 w-3.5" /> Edit
                        </Button>
                        <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive" onClick={() => remove(resource)} aria-label={`Remove ${resource.name}`}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={save} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{editing ? "Edit resource" : "Add company resource"}</DialogTitle>
              <DialogDescription>Keep its details and assignment up to date.</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label htmlFor="resource-name">Name</Label>
                <Input id="resource-name" value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} maxLength={160} required />
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <Label htmlFor="resource-category">Category</Label>
                  <Input id="resource-category" value={form.category} onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))} maxLength={80} required />
                </div>
                <div>
                  <Label>Status</Label>
                  <Select value={form.status} onValueChange={(status) => setForm((current) => ({ ...current, status }))}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{STATUSES.map((status) => <SelectItem key={status.value} value={status.value}>{status.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              <div>
                <Label>Assigned employee</Label>
                <Select value={form.assigned_to || EMPTY_ASSIGNEE} onValueChange={(assigned_to) => setForm((current) => ({ ...current, assigned_to: assigned_to === EMPTY_ASSIGNEE ? "" : assigned_to }))}>
                  <SelectTrigger><SelectValue placeholder="Unassigned" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={EMPTY_ASSIGNEE}>Unassigned</SelectItem>
                    {employees.filter((employee) => employee.status !== "deactivated" && employee.is_active !== false).map((employee) => (
                      <SelectItem key={employee.id} value={employee.id}>{employee.name} · {employee.role}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="resource-description">Details</Label>
                <Textarea id="resource-description" rows={3} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} maxLength={2000} />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={saving}>Cancel</Button>
              <Button type="submit" disabled={saving || !form.name.trim() || !form.category.trim()}>
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {saving ? "Saving..." : editing ? "Save changes" : "Add resource"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
