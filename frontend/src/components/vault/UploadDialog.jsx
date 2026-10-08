import { useEffect, useRef, useState } from "react";
import { UploadCloud, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import FolderSelect from "./FolderSelect";
import AccessPicker, { EVERYONE_ACCESS } from "./AccessPicker";
import { ACCEPT, extOf, formatBytes, parseTags, typeMeta, validateFile } from "./vaultUtils";

const EXT_TYPES = {
  pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  csv: "text/csv", txt: "text/plain",
};

const EMPTY = { title: "", folderId: "", tags: "", expiresOn: "", description: "", access: EVERYONE_ACCESS };

/** Drag-and-drop / file-picker zone shared by the upload and new-version dialogs. */
export function DropZone({ file, onFile, disabled, testId }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  const pick = (f) => {
    if (!f) return;
    const err = validateFile(f);
    if (err) toast.error(err);
    else onFile(f);
  };

  if (file) {
    const meta = typeMeta(EXT_TYPES[extOf(file.name)]);
    const Icon = meta.icon;
    return (
      <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 p-3">
        <div className={cn("h-10 w-10 rounded-md flex items-center justify-center shrink-0", meta.tone)}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium truncate">{file.name}</div>
          <div className="text-[12px] text-muted-foreground">{meta.label} · {formatBytes(file.size)}</div>
        </div>
        <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label="Remove file"
                onClick={() => onFile(null)} disabled={disabled}>
          <X className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid={testId}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !disabled) { e.preventDefault(); inputRef.current?.click(); } }}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (!disabled) pick(e.dataTransfer.files?.[0]); }}
      className={cn(
        "rounded-lg border-2 border-dashed border-border p-6 text-center cursor-pointer transition-colors outline-none",
        "hover:border-primary/50 hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring",
        dragging && "border-primary bg-primary/5",
      )}
    >
      <div className="h-10 w-10 rounded-md bg-primary/10 text-primary flex items-center justify-center mx-auto">
        <UploadCloud className="h-5 w-5" />
      </div>
      <div className="text-[13.5px] font-medium mt-2.5">Drop a file here or <span className="text-primary">browse</span></div>
      <div className="text-[12px] text-muted-foreground mt-1">PDF, images, Office files, CSV or TXT · up to 25 MB</div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }}
      />
    </div>
  );
}

export default function UploadDialog({ open, onOpenChange, folders, defaultFolderId, onUploaded }) {
  const [file, setFile] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [progress, setProgress] = useState(null);
  const busy = progress !== null;

  useEffect(() => {
    if (open) {
      setFile(null);
      setForm({ ...EMPTY, folderId: defaultFolderId || "" });
      setProgress(null);
    }
  }, [open, defaultFolderId]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const chooseFile = (f) => {
    setFile(f);
    // Suggest a title from the file name unless the user already typed one.
    if (f) setForm((s) => (s.title ? s : { ...s, title: f.name.replace(/\.[^.]+$/, "") }));
  };

  const submit = async (e) => {
    e.preventDefault();
    const err = validateFile(file);
    if (err) return toast.error(err);
    const body = new FormData();
    body.append("file", file);
    if (form.title.trim()) body.append("title", form.title.trim());
    if (form.folderId) body.append("folder_id", form.folderId);
    const tags = parseTags(form.tags);
    if (tags.length) body.append("tags", tags.join(","));
    if (form.expiresOn) body.append("expires_on", form.expiresOn);
    if (form.description.trim()) body.append("description", form.description.trim());
    body.append("access", JSON.stringify(form.access));
    setProgress(0);
    try {
      const { data } = await api.post("/vault/documents", body, {
        onUploadProgress: (p) => p.total && setProgress(Math.round((p.loaded / p.total) * 100)),
      });
      toast.success(`“${data.title}” uploaded`);
      onUploaded(data);
    } catch (e2) {
      toast.error(formatApiError(e2));
      setProgress(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="max-w-lg max-h-[92vh] overflow-y-auto" data-testid="vault-upload-dialog">
        <DialogHeader>
          <DialogTitle className="font-display tracking-tight">Upload document</DialogTitle>
          <DialogDescription>Stored privately in the Company Vault. Choose who can see it below; Founders and Admins always can.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <DropZone file={file} onFile={chooseFile} disabled={busy} testId="vault-dropzone" />
          <div>
            <Label htmlFor="vault-title">Title</Label>
            <Input id="vault-title" value={form.title} onChange={set("title")} maxLength={200} disabled={busy}
                   placeholder="e.g. Certificate of Incorporation" data-testid="vault-upload-title" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label>Folder</Label>
              <FolderSelect value={form.folderId} onChange={(v) => setForm((f) => ({ ...f, folderId: v }))}
                            folders={folders} disabled={busy} />
            </div>
            <div>
              <Label htmlFor="vault-expiry">Expires on <span className="text-muted-foreground font-normal">(optional)</span></Label>
              <Input id="vault-expiry" type="date" value={form.expiresOn} onChange={set("expiresOn")} disabled={busy} />
            </div>
          </div>
          <div>
            <Label htmlFor="vault-tags">Tags</Label>
            <Input id="vault-tags" value={form.tags} onChange={set("tags")} disabled={busy} placeholder="Comma separated, e.g. legal, rta" />
          </div>
          <div>
            <Label htmlFor="vault-desc">Description</Label>
            <Textarea id="vault-desc" rows={2} value={form.description} onChange={set("description")} maxLength={2000} disabled={busy} />
          </div>
          <AccessPicker value={form.access} onChange={(access) => setForm((f) => ({ ...f, access }))} disabled={busy}
                        idPrefix="vault-upload-access" />
          {busy && (
            <div className="space-y-1.5">
              <Progress value={progress} className="h-1.5" />
              <div className="text-[11.5px] text-muted-foreground">{progress < 100 ? `Uploading… ${progress}%` : "Processing…"}</div>
            </div>
          )}
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
            <Button type="submit" disabled={!file || busy} className="gap-1.5" data-testid="vault-upload-submit">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
              Upload
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
