import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, formatApiError } from "@/lib/api";
import AccessPicker, { normalizeAccess } from "./AccessPicker";

/** Create a folder (folder = null) or rename / change access of an existing one. */
export default function FolderDialog({ open, onOpenChange, folder, onSaved }) {
  const [name, setName] = useState("");
  const [access, setAccess] = useState(normalizeAccess(null));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(folder?.name || "");
      setAccess(normalizeAccess(folder?.access));
    }
  }, [open, folder]);

  const submit = async (e) => {
    e.preventDefault();
    const value = name.trim();
    if (!value) return toast.error("Folder name is required");
    setSaving(true);
    try {
      const { data } = folder
        ? await api.patch(`/vault/folders/${folder.id}`, { name: value, access })
        : await api.post("/vault/folders", { name: value, access });
      toast.success(folder ? "Folder saved" : "Folder created");
      onSaved(data);
    } catch (e2) {
      toast.error(formatApiError(e2));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !saving && onOpenChange(v)}>
      <DialogContent className="max-w-md max-h-[92vh] overflow-y-auto" data-testid="vault-folder-dialog">
        <DialogHeader>
          <DialogTitle className="font-display tracking-tight">{folder ? "Edit folder" : "New folder"}</DialogTitle>
          <DialogDescription>Folders group related documents, e.g. Legal, Insurance or Licences. A restricted folder hides everything inside it from people outside its access list.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label htmlFor="vault-folder-name">Name</Label>
            <Input id="vault-folder-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
                   autoFocus disabled={saving} data-testid="vault-folder-name" />
          </div>
          <AccessPicker value={access} onChange={setAccess} disabled={saving} idPrefix="vault-folder-access" scope="folder" />
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
            <Button type="submit" disabled={saving || !name.trim()} data-testid="vault-folder-save">
              {saving && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
              {folder ? "Save" : "Create folder"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
