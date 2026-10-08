import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Archive, FileStack, HardDrive, CalendarClock, AlertOctagon, Plus, UploadCloud, Search, LayoutGrid, List,
  Folder, FolderOpen, Inbox, MoreHorizontal, Pencil, Trash2, AlertTriangle, RefreshCw, Loader2, ChevronLeft,
  ChevronRight, Lock, X, FolderPlus,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader, StatCard, EmptyState } from "@/components/module/ModulePrimitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import UploadDialog from "@/components/vault/UploadDialog";
import DocumentSheet from "@/components/vault/DocumentSheet";
import FolderDialog from "@/components/vault/FolderDialog";
import { AccessBadge, accessSummary, useAccessOptions } from "@/components/vault/AccessPicker";
import { expiryBadge, formatBytes, formatDate, typeMeta } from "@/components/vault/vaultUtils";
import { useLiveRefresh } from "@/hooks/useLiveRefresh";
import { usePermission } from "@/hooks/usePermission";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 24;
const VIEW_KEY = "wavygo_vault_view";
const ALL = "all";
const UNFILED = "unfiled";
const ANY_TAG = "__any__";
const EXPIRY_OPTIONS = [
  { value: ALL, label: "Any expiry" },
  { value: "expiring", label: "Expiring in 30 days" },
  { value: "expired", label: "Expired" },
  { value: "any", label: "Has an expiry date" },
];
const SORT_OPTIONS = [
  { value: "updated", label: "Recently updated" },
  { value: "title", label: "Title A–Z" },
  { value: "size", label: "Largest first" },
  { value: "expiry", label: "Expiry date" },
];

function readView() {
  try { return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid"; } catch { return "grid"; }
}

function ExpiryPill({ doc }) {
  const badge = expiryBadge(doc);
  if (!badge || doc.expiry_status === "valid") return null;
  return (
    <span className={cn("inline-flex items-center gap-1 h-5 px-1.5 rounded text-[10.5px] font-semibold whitespace-nowrap", badge.className)}>
      {doc.expiry_status === "expired" ? <AlertOctagon className="h-3 w-3" /> : <CalendarClock className="h-3 w-3" />}
      {badge.label}
    </span>
  );
}

function TypeIcon({ contentType, className }) {
  const meta = typeMeta(contentType);
  const Icon = meta.icon;
  return (
    <div className={cn("rounded-md flex items-center justify-center shrink-0", meta.tone, className)}>
      <Icon className="h-5 w-5" />
    </div>
  );
}

function DocumentCard({ doc, folderName, onOpen, peopleById }) {
  const meta = typeMeta(doc.content_type);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="text-left rounded-xl border border-border bg-card p-4 hover-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring flex flex-col min-w-0"
      data-testid={`vault-doc-${doc.id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <TypeIcon contentType={doc.content_type} className="h-10 w-10" />
        <div className="flex flex-wrap justify-end gap-1">
          <AccessBadge access={doc.access} peopleById={peopleById} />
          <ExpiryPill doc={doc} />
        </div>
      </div>
      <div className="font-display text-[14.5px] font-semibold text-foreground mt-3 line-clamp-2 break-words">{doc.title}</div>
      <div className="text-[12px] text-muted-foreground mt-0.5 truncate">{doc.file_name}</div>
      <div className="mt-auto pt-3 flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <span className="font-semibold text-foreground/70">{meta.label}</span>
        <span>·</span>
        <span>{formatBytes(doc.size)}</span>
        <span>·</span>
        <span>v{doc.version}</span>
        <span className="ml-auto truncate flex items-center gap-1 min-w-0">
          <Folder className="h-3 w-3 shrink-0" /><span className="truncate">{folderName}</span>
        </span>
      </div>
    </button>
  );
}

function DocumentRow({ doc, folderName, onOpen, peopleById }) {
  return (
    <tr className="border-b border-border last:border-0 hover:bg-muted/40 cursor-pointer" onClick={onOpen} data-testid={`vault-row-${doc.id}`}>
      <td className="p-3">
        <div className="flex items-center gap-3 min-w-0">
          <TypeIcon contentType={doc.content_type} className="h-9 w-9" />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 min-w-0">
              <button type="button" className="text-[13.5px] font-medium text-foreground truncate block max-w-full text-left hover:underline"
                      onClick={(e) => { e.stopPropagation(); onOpen(); }}>
                {doc.title}
              </button>
              <AccessBadge access={doc.access} peopleById={peopleById} showLabel={false} className="shrink-0" />
            </div>
            <div className="text-[11.5px] text-muted-foreground truncate">
              {doc.file_name}<span className="md:hidden"> · {formatBytes(doc.size)}</span>
            </div>
            <div className="sm:hidden mt-1"><ExpiryPill doc={doc} /></div>
          </div>
        </div>
      </td>
      <td className="p-3 hidden lg:table-cell text-[12.5px] text-muted-foreground whitespace-nowrap">{folderName}</td>
      <td className="p-3 hidden md:table-cell text-[12.5px] text-muted-foreground whitespace-nowrap">{formatBytes(doc.size)}</td>
      <td className="p-3 hidden md:table-cell text-[12.5px] text-muted-foreground">v{doc.version}</td>
      <td className="p-3 hidden sm:table-cell whitespace-nowrap">
        {doc.expires_on
          ? <div className="flex flex-col items-start gap-1"><span className="text-[12.5px] text-muted-foreground">{formatDate(doc.expires_on)}</span><ExpiryPill doc={doc} /></div>
          : <span className="text-[12.5px] text-muted-foreground">—</span>}
      </td>
      <td className="p-3 hidden xl:table-cell text-[12.5px] text-muted-foreground whitespace-nowrap">{formatDate(doc.updated_at)}</td>
    </tr>
  );
}

function ListSkeleton({ view }) {
  if (view === "list") {
    return (
      <div className="rounded-xl border border-border bg-card p-3 space-y-2">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12 w-full" />)}
      </div>
    );
  }
  return (
    <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-[150px] rounded-xl" />)}
    </div>
  );
}

function FolderButton({ active, icon: Icon, label, count, onClick, menu, testId, restricted }) {
  return (
    <div className={cn("group flex items-center rounded-md shrink-0 lg:shrink transition-colors", active ? "bg-muted" : "hover:bg-muted/60")}>
      <button
        type="button"
        aria-pressed={active}
        onClick={onClick}
        data-testid={testId}
        className={cn("flex-1 min-w-0 flex items-center gap-2.5 px-2.5 py-1.5 text-[13px] text-left whitespace-nowrap", active && "font-medium")}
      >
        <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
        <span className="truncate">{label}</span>
        {restricted && <Lock className="h-3 w-3 shrink-0 text-primary" aria-label={`Restricted: ${restricted}`} />}
        <span className="ml-auto pl-2 text-[11.5px] text-muted-foreground tabular-nums">{count}</span>
      </button>
      {menu}
    </div>
  );
}

export default function CompanyVault() {
  const { can } = usePermission();
  const canView = can("vault.view");
  const canManage = can("vault.manage");
  const [searchParams, setSearchParams] = useSearchParams();

  const [folderData, setFolderData] = useState(null);
  const [stats, setStats] = useState(null);
  const [tags, setTags] = useState([]);
  const [docs, setDocs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [folder, setFolder] = useState(ALL);
  const [tag, setTag] = useState("");
  const [expiry, setExpiry] = useState(ALL);
  const [sort, setSort] = useState("updated");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [view, setView] = useState(readView);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [sheet, setSheet] = useState({ open: false, id: null, initial: null });
  const [folderDialog, setFolderDialog] = useState({ open: false, folder: null });
  const [folderToDelete, setFolderToDelete] = useState(null);
  const [deletingFolder, setDeletingFolder] = useState(false);
  const requestId = useRef(0);
  const accessOptions = useAccessOptions();
  const peopleById = useMemo(
    () => Object.fromEntries((accessOptions?.people || []).map((p) => [p.id, p])),
    [accessOptions],
  );

  const folders = useMemo(() => folderData?.folders || [], [folderData]);
  const folderNames = useMemo(() => Object.fromEntries(folders.map((f) => [f.id, f.name])), [folders]);
  const nameOf = (id) => (id ? folderNames[id] || "Unknown folder" : "Unfiled");

  // Debounce the search box.
  useEffect(() => {
    const t = setTimeout(() => { setQ(search.trim()); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    try { localStorage.setItem(VIEW_KEY, view); } catch { /* storage unavailable */ }
  }, [view]);

  const loadMeta = useCallback(async () => {
    const [f, s, t] = await Promise.all([api.get("/vault/folders"), api.get("/vault/stats"), api.get("/vault/tags")]);
    setFolderData(f.data);
    setStats(s.data);
    setTags(t.data);
  }, []);

  const loadDocs = useCallback(async () => {
    const params = {
      page, page_size: PAGE_SIZE, sort,
      folder_id: folder === ALL ? undefined : folder,
      tag: tag || undefined,
      q: q || undefined,
      expiry: expiry === ALL ? undefined : expiry,
    };
    const { data } = await api.get("/vault/documents", { params });
    return data;
  }, [page, sort, folder, tag, q, expiry]);

  const refresh = useCallback(async ({ background = false } = {}) => {
    if (!canView) return;
    const id = ++requestId.current;
    if (!background) { setLoading(true); setError(null); }
    try {
      const [data] = await Promise.all([loadDocs(), loadMeta()]);
      if (id !== requestId.current) return;
      // A delete can leave us past the last page.
      if (data.items.length === 0 && data.page > 1 && data.total > 0) { setPage(data.pages); return; }
      setDocs(data);
      setError(null);
    } catch (e) {
      if (id !== requestId.current || background) return;
      setError(formatApiError(e));
    } finally {
      if (id === requestId.current && !background) setLoading(false);
    }
  }, [canView, loadDocs, loadMeta]);

  useEffect(() => { refresh(); }, [refresh]);
  useLiveRefresh(refresh, 5 * 60 * 1000);

  // ?doc=<id> (from expiry notifications) opens that document.
  useEffect(() => {
    const docId = searchParams.get("doc");
    if (!docId) return;
    setSheet({ open: true, id: docId, initial: null });
    setSearchParams((p) => { p.delete("doc"); return p; }, { replace: true });
  }, [searchParams, setSearchParams]);

  // ?create=document (Quick Create) opens the upload dialog.
  useEffect(() => {
    if (searchParams.get("create") !== "document") return;
    if (canManage) setUploadOpen(true);
    setSearchParams((p) => { p.delete("create"); return p; }, { replace: true });
  }, [searchParams, setSearchParams, canManage]);

  const openDoc = (doc) => setSheet({ open: true, id: doc.id, initial: doc });
  const chooseFolder = (value) => { setFolder(value); setPage(1); };
  const clearFilters = () => { setTag(""); setExpiry(ALL); setSearch(""); setQ(""); setPage(1); };
  const filtered = !!(tag || q || expiry !== ALL);

  const deleteFolder = async () => {
    setDeletingFolder(true);
    try {
      await api.delete(`/vault/folders/${folderToDelete.id}`);
      toast.success(`Folder “${folderToDelete.name}” deleted`);
      if (folder === folderToDelete.id) chooseFolder(ALL);
      setFolderToDelete(null);
      refresh({ background: true });
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setDeletingFolder(false);
    }
  };

  if (!canView) {
    return (
      <div data-testid="vault-page">
        <PageHeader eyebrow="Module" title="Company Vault" />
        <EmptyState icon={Lock} title="No access" description="Your role doesn't have access to the Company Vault. Ask a Founder or Admin if you need a document from it." />
      </div>
    );
  }

  // ------------------------- render pieces -------------------------

  const statCards = (
    <div className="grid gap-3 grid-cols-2 xl:grid-cols-4 mb-6">
      {stats ? (
        <>
          <StatCard label="Documents" value={stats.count.toLocaleString()} icon={FileStack}
                    sub={`${folders.length} folder${folders.length === 1 ? "" : "s"}`} />
          <StatCard label="Storage used" value={formatBytes(stats.storage_size)} icon={HardDrive} tone="info"
                    sub={stats.stored_files ? `${stats.stored_files} file${stats.stored_files === 1 ? "" : "s"}` : undefined} />
          <button type="button" className="text-left" onClick={() => { setExpiry("expiring"); setPage(1); }} aria-label="Show documents expiring in 30 days">
            <StatCard label="Expiring ≤ 30 days" value={stats.expiring_30d} icon={CalendarClock} tone="warning" />
          </button>
          <button type="button" className="text-left" onClick={() => { setExpiry("expired"); setPage(1); }} aria-label="Show expired documents">
            <StatCard label="Expired" value={stats.expired} icon={AlertOctagon} tone="danger" />
          </button>
        </>
      ) : (
        Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[112px] rounded-xl" />)
      )}
    </div>
  );

  const folderMenu = (f) => canManage && f.can_edit && (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-7 w-7 mr-0.5 shrink-0 lg:opacity-0 lg:group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                aria-label={`Folder actions for ${f.name}`}>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => setFolderDialog({ open: true, folder: f })}><Pencil className="h-4 w-4 mr-2" /> Rename &amp; access</DropdownMenuItem>
        <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setFolderToDelete(f)}>
          <Trash2 className="h-4 w-4 mr-2" /> Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const sidebar = (
    <aside className="min-w-0 lg:self-start rounded-xl border border-border bg-card p-2 lg:p-3">
      <div className="hidden lg:flex items-center justify-between px-1 mb-2">
        <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Folders</div>
        {canManage && (
          <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="New folder"
                  onClick={() => setFolderDialog({ open: true, folder: null })} data-testid="vault-new-folder">
            <FolderPlus className="h-4 w-4" />
          </Button>
        )}
      </div>
      {!folderData ? (
        <div className="flex lg:flex-col gap-1.5">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-8 w-28 lg:w-full" />)}</div>
      ) : (
        <nav className="flex lg:flex-col gap-1 overflow-x-auto lg:overflow-visible -mx-1 px-1 pb-0.5" aria-label="Vault folders">
          <FolderButton active={folder === ALL} icon={Archive} label="All documents" count={folderData.total_count}
                        onClick={() => chooseFolder(ALL)} testId="vault-folder-all" />
          {folders.map((f) => (
            <FolderButton key={f.id} active={folder === f.id} icon={folder === f.id ? FolderOpen : Folder} label={f.name}
                          count={f.count} onClick={() => chooseFolder(f.id)} menu={folderMenu(f)} testId={`vault-folder-${f.id}`}
                          restricted={f.access?.mode === "restricted" ? accessSummary(f.access, peopleById) : null} />
          ))}
          <FolderButton active={folder === UNFILED} icon={Inbox} label="Unfiled" count={folderData.unfiled_count}
                        onClick={() => chooseFolder(UNFILED)} testId="vault-folder-unfiled" />
          {canManage && (
            <Button variant="ghost" size="sm" className="lg:hidden shrink-0 gap-1.5 text-muted-foreground"
                    onClick={() => setFolderDialog({ open: true, folder: null })}>
              <FolderPlus className="h-4 w-4" /> New folder
            </Button>
          )}
        </nav>
      )}
    </aside>
  );

  const toolbar = (
    <div className="flex flex-col md:flex-row gap-2 md:items-center">
      <div className="relative flex-1 min-w-0">
        <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search title, file name, tags…"
               className="pl-9" maxLength={200} data-testid="vault-search" />
      </div>
      <div className="grid grid-cols-2 sm:flex gap-2">
        <Select value={tag || ANY_TAG} onValueChange={(v) => { setTag(v === ANY_TAG ? "" : v); setPage(1); }}>
          <SelectTrigger className="sm:w-[150px]" data-testid="vault-tag-filter"><SelectValue placeholder="All tags" /></SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY_TAG}>All tags</SelectItem>
            {tags.map((t) => <SelectItem key={t.tag} value={t.tag}>#{t.tag} ({t.count})</SelectItem>)}
            {tag && !tags.some((t) => t.tag === tag) && <SelectItem value={tag}>#{tag}</SelectItem>}
          </SelectContent>
        </Select>
        <Select value={expiry} onValueChange={(v) => { setExpiry(v); setPage(1); }}>
          <SelectTrigger className="sm:w-[180px]" data-testid="vault-expiry-filter"><SelectValue /></SelectTrigger>
          <SelectContent>{EXPIRY_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={sort} onValueChange={(v) => { setSort(v); setPage(1); }}>
          <SelectTrigger className="sm:w-[165px]" data-testid="vault-sort"><SelectValue /></SelectTrigger>
          <SelectContent>{SORT_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
        </Select>
        <ToggleGroup type="single" value={view} onValueChange={(v) => v && setView(v)} variant="outline" className="justify-start">
          <ToggleGroupItem value="grid" aria-label="Grid view" className="h-9 w-9 p-0"><LayoutGrid className="h-4 w-4" /></ToggleGroupItem>
          <ToggleGroupItem value="list" aria-label="List view" className="h-9 w-9 p-0"><List className="h-4 w-4" /></ToggleGroupItem>
        </ToggleGroup>
      </div>
    </div>
  );

  const body = () => {
    if (error) {
      return (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-10 text-center" data-testid="vault-error">
          <AlertTriangle className="h-6 w-6 text-destructive mx-auto" />
          <div className="font-display text-[15px] font-semibold mt-3">Couldn't load the vault</div>
          <div className="text-[13px] text-muted-foreground mt-1">{error}</div>
          <Button variant="outline" size="sm" className="mt-4 gap-1.5" onClick={() => refresh()}>
            <RefreshCw className="h-3.5 w-3.5" /> Try again
          </Button>
        </div>
      );
    }
    if (!docs) return <ListSkeleton view={view} />;
    if (docs.items.length === 0) {
      if (filtered) {
        return (
          <EmptyState icon={Search} title="No matching documents" description="Try a different search, tag or expiry filter."
                      action={<Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>} />
        );
      }
      const inFolder = folder !== ALL;
      return (
        <EmptyState
          icon={inFolder ? FolderOpen : Archive}
          title={inFolder ? `Nothing in ${folder === UNFILED ? "Unfiled" : nameOf(folder)} yet` : "The vault is empty"}
          description="Upload incorporation papers, licences, insurance policies, agreements and other company records. Add an expiry date to get reminders before renewals."
          action={canManage && (
            <Button size="sm" className="gap-1.5" onClick={() => setUploadOpen(true)}>
              <UploadCloud className="h-4 w-4" /> Upload document
            </Button>
          )}
        />
      );
    }
    return (
      <div className={cn("transition-opacity", loading && "opacity-60 pointer-events-none")}>
        {view === "grid" ? (
          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" data-testid="vault-grid">
            {docs.items.map((d) => <DocumentCard key={d.id} doc={d} folderName={nameOf(d.folder_id)} onOpen={() => openDoc(d)} peopleById={peopleById} />)}
          </div>
        ) : (
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="vault-list">
            <table className="w-full table-fixed">
              <thead className="bg-muted/40 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="p-3 text-left font-medium">Document</th>
                  <th className="p-3 text-left font-medium hidden lg:table-cell w-[150px]">Folder</th>
                  <th className="p-3 text-left font-medium hidden md:table-cell w-[90px]">Size</th>
                  <th className="p-3 text-left font-medium hidden md:table-cell w-[70px]">Ver.</th>
                  <th className="p-3 text-left font-medium hidden sm:table-cell w-[150px]">Expiry</th>
                  <th className="p-3 text-left font-medium hidden xl:table-cell w-[120px]">Updated</th>
                </tr>
              </thead>
              <tbody>
                {docs.items.map((d) => <DocumentRow key={d.id} doc={d} folderName={nameOf(d.folder_id)} onOpen={() => openDoc(d)} peopleById={peopleById} />)}
              </tbody>
            </table>
          </div>
        )}
        {docs.pages > 1 && (
          <div className="flex items-center justify-between gap-3 mt-4 text-[12.5px] text-muted-foreground">
            <span>Page {docs.page} of {docs.pages}</span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="gap-1" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft className="h-4 w-4" /> Previous
              </Button>
              <Button variant="outline" size="sm" className="gap-1" disabled={page >= docs.pages || loading} onClick={() => setPage((p) => p + 1)}>
                Next <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  };

  const activeFilters = [
    q && { key: "q", label: `“${q}”`, clear: () => { setSearch(""); setQ(""); setPage(1); } },
    tag && { key: "tag", label: `#${tag}`, clear: () => { setTag(""); setPage(1); } },
    expiry !== ALL && { key: "expiry", label: EXPIRY_OPTIONS.find((o) => o.value === expiry)?.label, clear: () => { setExpiry(ALL); setPage(1); } },
  ].filter(Boolean);

  return (
    <div data-testid="vault-page">
      <PageHeader
        eyebrow="Module"
        title="Company Vault"
        description="Confidential company documents with version history and expiry reminders. Each folder and document can be limited to specific roles, departments or people."
        actions={canManage && (
          <Button onClick={() => setUploadOpen(true)} className="gap-1.5 font-medium" data-testid="vault-upload">
            <Plus className="h-4 w-4" /> Upload
          </Button>
        )}
      />

      {statCards}

      <div className="grid gap-4 lg:gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        {sidebar}
        <section className="min-w-0 space-y-4">
          {toolbar}
          <div className="flex flex-wrap items-center gap-2 min-h-5 text-[12px] text-muted-foreground">
            {loading && docs && <Loader2 className="h-3 w-3 animate-spin" />}
            {docs && !error && <span>{docs.total} document{docs.total === 1 ? "" : "s"}</span>}
            {activeFilters.map((f) => (
              <button key={f.key} type="button" onClick={f.clear}
                      className="inline-flex items-center gap-1 h-6 px-2 rounded-full border border-border bg-card hover:bg-muted text-foreground/80">
                {f.label} <X className="h-3 w-3" />
              </button>
            ))}
          </div>
          {body()}
        </section>
      </div>

      {canManage && (
        <UploadDialog
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          folders={folders}
          defaultFolderId={folder !== ALL && folder !== UNFILED ? folder : ""}
          onUploaded={(doc) => { setUploadOpen(false); refresh({ background: true }); openDoc(doc); }}
        />
      )}
      <DocumentSheet
        docId={sheet.id}
        initial={sheet.initial}
        open={sheet.open}
        onOpenChange={(open) => setSheet((s) => ({ ...s, open }))}
        folders={folders}
        canManage={canManage}
        onChanged={() => refresh({ background: true })}
      />
      <FolderDialog
        open={folderDialog.open}
        folder={folderDialog.folder}
        onOpenChange={(open) => setFolderDialog((s) => ({ ...s, open }))}
        onSaved={() => { setFolderDialog({ open: false, folder: null }); refresh({ background: true }); }}
      />
      <AlertDialog open={!!folderToDelete} onOpenChange={(v) => !v && !deletingFolder && setFolderToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete folder “{folderToDelete?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              {folderToDelete?.count
                ? `This folder still holds ${folderToDelete.count} document${folderToDelete.count === 1 ? "" : "s"}. Move or delete them first.`
                : "The folder is empty and will be removed."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deletingFolder}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); deleteFolder(); }}
              disabled={deletingFolder || !!folderToDelete?.count}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deletingFolder && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
              Delete folder
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
