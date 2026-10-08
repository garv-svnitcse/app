import { useEffect, useState } from "react";
import {
  Download, Pencil, Trash2, UploadCloud, Loader2, RotateCcw, History, Folder, HardDrive, User,
  CalendarClock, CalendarPlus, Fingerprint, AlertTriangle, RefreshCw, Copy, Check, Lock, Globe2,
} from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EditDocumentDialog, NewVersionDialog } from "./DocumentDialogs";
import { accessSummary, normalizeAccess, useAccessOptions } from "./AccessPicker";
import {
  PREVIEWABLE, blobErrorMessage, downloadFile, expiryBadge, fetchBlob, formatBytes, formatDate, formatDateTime, typeMeta,
} from "./vaultUtils";

function Row({ icon: Icon, label, children }) {
  return (
    <div className="flex items-start gap-3 text-[13px]">
      <Icon className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
      <div className="w-24 shrink-0 text-muted-foreground">{label}</div>
      <div className="min-w-0 flex-1 text-foreground break-words">{children}</div>
    </div>
  );
}

/** Inline preview for PDFs and images, fetched through the authenticated client as a blob URL. */
function Preview({ doc }) {
  const [state, setState] = useState({ url: null, error: null, loading: true });
  const [retry, setRetry] = useState(0);
  const previewable = PREVIEWABLE.has(doc.content_type);

  useEffect(() => {
    if (!previewable) return undefined;
    const controller = new AbortController();
    let url = null;
    setState({ url: null, error: null, loading: true });
    fetchBlob(doc.id, { inline: true, signal: controller.signal })
      .then((blob) => {
        url = URL.createObjectURL(new Blob([blob], { type: doc.content_type }));
        setState({ url, error: null, loading: false });
      })
      .catch(async (e) => {
        if (controller.signal.aborted) return;
        setState({ url: null, error: await blobErrorMessage(e, "Couldn't load the preview"), loading: false });
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [doc.id, doc.version, doc.content_type, previewable, retry]);

  const meta = typeMeta(doc.content_type);
  if (!previewable) {
    const Icon = meta.icon;
    return (
      <div className="rounded-lg border border-border bg-muted/30 p-8 text-center">
        <div className={cn("h-12 w-12 rounded-md flex items-center justify-center mx-auto", meta.tone)}>
          <Icon className="h-6 w-6" />
        </div>
        <div className="text-[13px] text-muted-foreground mt-3">Preview isn't available for {meta.label} files. Download to open it.</div>
      </div>
    );
  }
  if (state.loading) return <Skeleton className="h-[320px] w-full rounded-lg" />;
  if (state.error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
        <AlertTriangle className="h-5 w-5 text-destructive mx-auto" />
        <div className="text-[13px] text-muted-foreground mt-2">{state.error}</div>
        <Button variant="outline" size="sm" className="mt-3 gap-1.5" onClick={() => setRetry((r) => r + 1)}>
          <RefreshCw className="h-3.5 w-3.5" /> Try again
        </Button>
      </div>
    );
  }
  if (doc.content_type === "application/pdf") {
    return (
      <iframe
        title={`Preview of ${doc.title}`}
        src={state.url}
        className="w-full h-[420px] sm:h-[520px] rounded-lg border border-border bg-muted/30"
        data-testid="vault-preview-pdf"
      />
    );
  }
  return (
    <div className="rounded-lg border border-border bg-muted/30 flex items-center justify-center p-2">
      <img src={state.url} alt={doc.title} className="max-h-[420px] w-auto max-w-full object-contain rounded" data-testid="vault-preview-image" />
    </div>
  );
}

function ChecksumRow({ checksum }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(checksum);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy to clipboard");
    }
  };
  return (
    <Row icon={Fingerprint} label="SHA-256">
      <button type="button" onClick={copy} title="Copy checksum"
              className="inline-flex items-center gap-1.5 font-mono text-[11.5px] text-muted-foreground hover:text-foreground">
        {checksum.slice(0, 16)}…
        {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
      </button>
    </Row>
  );
}

export default function DocumentSheet({ docId, initial, open, onOpenChange, folders, canManage, onChanged }) {
  const [doc, setDoc] = useState(initial || null);
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const options = useAccessOptions();
  const peopleById = Object.fromEntries((options?.people || []).map((p) => [p.id, p]));

  // Always load the fresh record (the list row may be stale, or we came from a notification link).
  useEffect(() => {
    if (!open || !docId) return undefined;
    const controller = new AbortController();
    setLoadError(null);
    if (initial?.id === docId) setDoc(initial);
    else setDoc(null);
    api.get(`/vault/documents/${docId}`, { signal: controller.signal })
      .then(({ data }) => setDoc(data))
      .catch((e) => { if (!controller.signal.aborted) setLoadError(formatApiError(e)); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, docId, reloadKey]);

  const updated = (data) => {
    setDoc(data);
    onChanged(data);
  };

  const download = async (version) => {
    setBusy(`dl-${version || "current"}`);
    try {
      const v = version ? doc.versions.find((x) => x.version === version) : null;
      await downloadFile(doc.id, v ? v.file_name : doc.file_name, version);
    } catch (e) {
      toast.error(await blobErrorMessage(e, "Download failed"));
    } finally {
      setBusy(null);
    }
  };

  const restore = async (version) => {
    setBusy(`restore-${version}`);
    try {
      const { data } = await api.post(`/vault/documents/${doc.id}/versions/${version}/restore`);
      toast.success(`Version ${version} restored as version ${data.version}`);
      updated(data);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy("delete");
    try {
      await api.delete(`/vault/documents/${doc.id}`);
      toast.success("Document deleted");
      setConfirmDelete(false);
      onOpenChange(false);
      onChanged(null);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const folderName = doc?.folder_id ? folders.find((f) => f.id === doc.folder_id)?.name || "Unknown folder" : "Unfiled";
  const badge = doc ? expiryBadge(doc) : null;
  const meta = doc ? typeMeta(doc.content_type) : null;
  // vault.manage lets a role upload; changing an existing document is limited to its owner, Founders and Admins.
  const canEdit = canManage && !!doc?.can_edit;
  const access = normalizeAccess(doc?.access);
  const folderAccess = doc?.folder_id ? normalizeAccess(folders.find((f) => f.id === doc.folder_id)?.access) : null;

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full sm:max-w-xl p-0 flex flex-col gap-0" data-testid="vault-document-sheet">
          {!doc ? (
            <div className="p-6 space-y-4">
              <SheetHeader><SheetTitle className="sr-only">Document</SheetTitle><SheetDescription className="sr-only">Loading document</SheetDescription></SheetHeader>
              {loadError ? (
                <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-8 text-center mt-6">
                  <AlertTriangle className="h-6 w-6 text-destructive mx-auto" />
                  <div className="font-display text-[15px] font-semibold mt-3">Couldn't open this document</div>
                  <div className="text-[13px] text-muted-foreground mt-1">{loadError}</div>
                  <Button variant="outline" size="sm" className="mt-4 gap-1.5" onClick={() => setReloadKey((k) => k + 1)}>
                    <RefreshCw className="h-3.5 w-3.5" /> Try again
                  </Button>
                </div>
              ) : (
                <>
                  <Skeleton className="h-7 w-2/3" />
                  <Skeleton className="h-[320px] w-full" />
                  <Skeleton className="h-24 w-full" />
                </>
              )}
            </div>
          ) : (
            <>
              <SheetHeader className="p-5 pr-12 border-b border-border text-left space-y-2">
                <div className="flex items-center gap-2 flex-wrap text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                  <span className={cn("inline-flex items-center h-5 px-1.5 rounded font-semibold", meta.tone)}>{meta.label}</span>
                  <span>v{doc.version}</span>
                  {badge && (
                    <span className={cn("inline-flex items-center h-5 px-1.5 rounded text-[10.5px] font-semibold normal-case tracking-normal", badge.className)}>
                      {badge.label}
                    </span>
                  )}
                </div>
                <SheetTitle className="font-display text-xl tracking-tight break-words">{doc.title}</SheetTitle>
                <SheetDescription className="text-[12.5px] truncate">{doc.file_name} · {formatBytes(doc.size)}</SheetDescription>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button size="sm" className="gap-1.5" onClick={() => download()} disabled={!!busy} data-testid="vault-download">
                    {busy === "dl-current" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Download
                  </Button>
                  {canEdit && (
                    <>
                      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setVersionOpen(true)} disabled={!!busy} data-testid="vault-new-version">
                        <UploadCloud className="h-4 w-4" /> New version
                      </Button>
                      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setEditOpen(true)} disabled={!!busy} data-testid="vault-edit">
                        <Pencil className="h-4 w-4" /> Edit
                      </Button>
                      <Button size="sm" variant="ghost" className="gap-1.5 text-destructive hover:text-destructive hover:bg-destructive/10"
                              onClick={() => setConfirmDelete(true)} disabled={!!busy} data-testid="vault-delete">
                        <Trash2 className="h-4 w-4" /> Delete
                      </Button>
                    </>
                  )}
                </div>
              </SheetHeader>

              <div className="flex-1 overflow-y-auto p-5 space-y-6">
                <Preview doc={doc} />

                <section className="space-y-3">
                  <Row icon={Folder} label="Folder">{folderName}</Row>
                  <Row icon={access.mode === "restricted" ? Lock : Globe2} label="Access">
                    <span data-testid="vault-access-summary">{accessSummary(access, peopleById)}</span>
                    {folderAccess?.mode === "restricted" && (
                      <span className="block text-[11.5px] text-muted-foreground mt-0.5">
                        Also limited by the folder: {accessSummary(folderAccess, peopleById)}
                      </span>
                    )}
                    {doc.access_legacy && (
                      <span className="block text-[11.5px] text-muted-foreground mt-0.5">Added before access control; visible to everyone.</span>
                    )}
                  </Row>
                  <Row icon={HardDrive} label="Size">{formatBytes(doc.size)}</Row>
                  <Row icon={User} label="Uploaded by">{doc.uploaded_by_name || "Unknown"}</Row>
                  <Row icon={CalendarPlus} label="Added">{formatDateTime(doc.created_at)}</Row>
                  <Row icon={History} label="Updated">{formatDateTime(doc.updated_at)}</Row>
                  <Row icon={CalendarClock} label="Expires">{doc.expires_on ? formatDate(doc.expires_on) : "No expiry"}</Row>
                  {doc.checksum && <ChecksumRow checksum={doc.checksum} />}
                  {doc.tags?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {doc.tags.map((t) => <Badge key={t} variant="secondary" className="font-normal">#{t}</Badge>)}
                    </div>
                  )}
                  {doc.description && (
                    <p className="text-[13px] leading-relaxed text-foreground/90 whitespace-pre-wrap border-t border-border pt-3">{doc.description}</p>
                  )}
                </section>

                <section>
                  <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-2">
                    Version history · {doc.versions.length}
                  </div>
                  <ol className="rounded-lg border border-border divide-y divide-border" data-testid="vault-versions">
                    {doc.versions.map((v) => {
                      const current = v.version === doc.version;
                      return (
                        <li key={v.version} className="p-3 flex items-start gap-3">
                          <div className={cn(
                            "h-8 w-8 shrink-0 rounded-md flex items-center justify-center text-[12px] font-semibold",
                            current ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                          )}>
                            v{v.version}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="text-[13px] font-medium truncate">{v.file_name}</span>
                              {current && <span className="shrink-0 inline-flex items-center h-5 px-1.5 rounded text-[10.5px] font-semibold uppercase tracking-wide bg-success/10 text-success">Current</span>}
                            </div>
                            <div className="text-[11.5px] text-muted-foreground mt-0.5">
                              {formatBytes(v.size)} · {v.uploaded_by_name || "Unknown"} · {formatDateTime(v.uploaded_at)}
                            </div>
                            {v.note && <div className="text-[12px] text-foreground/80 mt-1">{v.note}</div>}
                          </div>
                          <div className="flex shrink-0">
                            <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Download version ${v.version}`}
                                    title="Download" onClick={() => download(v.version)} disabled={!!busy}>
                              {busy === `dl-${v.version}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                            </Button>
                            {canEdit && !current && (
                              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Restore version ${v.version}`}
                                      title="Restore as current" onClick={() => restore(v.version)} disabled={!!busy}>
                                {busy === `restore-${v.version}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                              </Button>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                </section>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {doc && canEdit && (
        <>
          <EditDocumentDialog doc={doc} open={editOpen} onOpenChange={setEditOpen} folders={folders}
                              onSaved={(d) => { setEditOpen(false); updated(d); }} />
          <NewVersionDialog doc={doc} open={versionOpen} onOpenChange={setVersionOpen}
                            onUploaded={(d) => { setVersionOpen(false); updated(d); }} />
          <AlertDialog open={confirmDelete} onOpenChange={(v) => busy !== "delete" && setConfirmDelete(v)}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete “{doc.title}”?</AlertDialogTitle>
                <AlertDialogDescription>
                  This permanently removes the document and all {doc.versions.length} version{doc.versions.length === 1 ? "" : "s"}. It can't be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={busy === "delete"}>Keep document</AlertDialogCancel>
                <AlertDialogAction
                  onClick={(e) => { e.preventDefault(); remove(); }}
                  disabled={busy === "delete"}
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  data-testid="vault-delete-confirm"
                >
                  {busy === "delete" && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
                  Delete document
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </>
      )}
    </>
  );
}
