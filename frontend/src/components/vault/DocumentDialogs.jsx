import { useEffect, useState } from "react";
import { Loader2, Save, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { api, formatApiError } from "@/lib/api";
import FolderSelect from "./FolderSelect";
import AccessPicker, { normalizeAccess } from "./AccessPicker";
import { DropZone } from "./UploadDialog";
import { parseTags, validateFile } from "./vaultUtils";

export function EditDocumentDialog({ doc, open, onOpenChange, folders, onSaved }) {
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && doc) {
      setForm({
        title: doc.title || "", folderId: doc.folder_id || "", tags: (doc.tags || []).join(", "),
        expiresOn: doc.expires_on || "", description: doc.description || "", access: normalizeAccess(doc.access),
      });
    }
  }, [open, doc]);

  if (!form) return null;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.title.trim()) return toast.error("Title is required");
    setSaving(true);
    try {
      const { data } = await api.patch(`/vault/documents/${doc.id}`, {
        title: form.title.trim(),
        folder_id: form.folderId || null,
        tags: parseTags(form.tags),
        expires_on: form.expiresOn || null,
        description: form.description.trim() || null,
        access: form.access,
      });
      toast.success("Details saved");
      onSaved(data);
    } catch (e2) {
      toast.error(formatApiError(e2));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !saving && onOpenChange(v)}>
      <DialogContent className="max-w-lg max-h-[92vh] overflow-y-auto" data-testid="vault-edit-dialog">
        <DialogHeader>
          <DialogTitle className="font-display tracking-tight">Edit details</DialogTitle>
          <DialogDescription>Changing the expiry date re-arms the expiry reminders. Access applies on top of the folder's access.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label htmlFor="vault-edit-title">Title</Label>
            <Input id="vault-edit-title" value={form.title} onChange={set("title")} maxLength={200} disabled={saving} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label>Folder</Label>
              <FolderSelect value={form.folderId} onChange={(v) => setForm((f) => ({ ...f, folderId: v }))} folders={folders} disabled={saving} />
            </div>
            <div>
              <Label htmlFor="vault-edit-expiry">Expires on</Label>
              <Input id="vault-edit-expiry" type="date" value={form.expiresOn} onChange={set("expiresOn")} disabled={saving} />
            </div>
          </div>
          <div>
            <Label htmlFor="vault-edit-tags">Tags</Label>
            <Input id="vault-edit-tags" value={form.tags} onChange={set("tags")} disabled={saving} placeholder="Comma separated" />
          </div>
          <div>
            <Label htmlFor="vault-edit-desc">Description</Label>
            <Textarea id="vault-edit-desc" rows={3} value={form.description} onChange={set("description")} maxLength={2000} disabled={saving} />
          </div>
          <AccessPicker value={form.access} onChange={(access) => setForm((f) => ({ ...f, access }))} disabled={saving}
                        idPrefix="vault-edit-access" />
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
            <Button type="submit" disabled={saving} className="gap-1.5" data-testid="vault-edit-save">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function NewVersionDialog({ doc, open, onOpenChange, onUploaded }) {
  const [file, setFile] = useState(null);
  const [note, setNote] = useState("");
  const [progress, setProgress] = useState(null);
  const busy = progress !== null;

  useEffect(() => {
    if (open) { setFile(null); setNote(""); setProgress(null); }
  }, [open]);

  if (!doc) return null;

  const submit = async (e) => {
    e.preventDefault();
    const err = validateFile(file);
    if (err) return toast.error(err);
    const body = new FormData();
    body.append("file", file);
    if (note.trim()) body.append("note", note.trim());
    setProgress(0);
    try {
      const { data } = await api.post(`/vault/documents/${doc.id}/versions`, body, {
        onUploadProgress: (p) => p.total && setProgress(Math.round((p.loaded / p.total) * 100)),
      });
      toast.success(`Version ${data.version} uploaded`);
      onUploaded(data);
    } catch (e2) {
      toast.error(formatApiError(e2));
      setProgress(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="max-w-lg" data-testid="vault-version-dialog">
        <DialogHeader>
          <DialogTitle className="font-display tracking-tight">Upload new version</DialogTitle>
          <DialogDescription className="truncate">
            “{doc.title}” is at version {doc.version}. Earlier versions stay available in the history.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <DropZone file={file} onFile={setFile} disabled={busy} testId="vault-version-dropzone" />
          <div>
            <Label htmlFor="vault-version-note">What changed? <span className="text-muted-foreground font-normal">(optional)</span></Label>
            <Input id="vault-version-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} disabled={busy}
                   placeholder="e.g. Signed copy, renewed for 2027" />
          </div>
          {busy && <Progress value={progress} className="h-1.5" />}
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
            <Button type="submit" disabled={!file || busy} className="gap-1.5" data-testid="vault-version-submit">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
              Upload version
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
