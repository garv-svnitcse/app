import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, BookmarkPlus, ChevronLeft, ChevronRight, Loader2, Plus, Search, Users, X } from "lucide-react";
import { EmptyState, StatusPill } from "@/components/module/ModulePrimitives";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { LIFECYCLE, LIFECYCLE_KEYS, inr, relativeDays, useResource } from "./crmShared";
import { ErrorBlock, LifecyclePill, RowSkeletons } from "./StateBlocks";

const ALL = "all";
const SORTS = [
  { key: "ltv", label: "Lifetime value" },
  { key: "last_booking", label: "Last booking" },
  { key: "bookings", label: "Bookings" },
  { key: "name", label: "Name" },
  { key: "created_at", label: "Customer since" },
];
const PAGE_SIZE = 25;
export const EMPTY_FILTERS = { q: "", city: "", kyc_status: "", lifecycle: "", tag: "", min_ltv: "", min_bookings: "", segment_id: "" };

/** A non-negative number typed into a filter box, as a query value ("" when blank or invalid). */
function cleanMin(value, integer) {
  const v = String(value ?? "").trim();
  if (!v) return "";
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0 || (integer && !Number.isInteger(n))) return "";
  return String(n);
}

function FilterSelect({ value, onChange, placeholder, options, testid, className }) {
  return (
    <Select value={value || ALL} onValueChange={(v) => onChange(v === ALL ? "" : v)}>
      <SelectTrigger className={cn("h-9 w-full sm:w-[150px] text-[13px]", className)} data-testid={testid}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{placeholder}</SelectItem>
        {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

export default function CustomerList({ meta, segments, filters, setFilters, onOpenCustomer, onSaveSegment, onAddCustomer, canEdit, paused, refreshKey }) {
  const [search, setSearch] = useState(filters.q);
  const [minLtv, setMinLtv] = useState(filters.min_ltv);
  const [minBookings, setMinBookings] = useState(filters.min_bookings);
  const [sort, setSort] = useState({ key: "ltv", order: "desc" });
  const [page, setPage] = useState(1);

  // Debounce typing into the search filter.
  useEffect(() => {
    const id = setTimeout(() => setFilters((f) => (f.q === search.trim() ? f : { ...f, q: search.trim() })), 300);
    return () => clearTimeout(id);
  }, [search, setFilters]);
  useEffect(() => { setSearch(filters.q); }, [filters.q]);
  // Same for the minimum LTV / bookings boxes; invalid input (negative, fractional bookings) is ignored.
  useEffect(() => {
    const id = setTimeout(() => setFilters((f) => {
      const next = { min_ltv: cleanMin(minLtv, false), min_bookings: cleanMin(minBookings, true) };
      return f.min_ltv === next.min_ltv && f.min_bookings === next.min_bookings ? f : { ...f, ...next };
    }), 400);
    return () => clearTimeout(id);
  }, [minLtv, minBookings, setFilters]);
  useEffect(() => { setMinLtv(filters.min_ltv); }, [filters.min_ltv]);
  useEffect(() => { setMinBookings(filters.min_bookings); }, [filters.min_bookings]);
  useEffect(() => { setPage(1); }, [filters, sort]);

  const params = { ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), sort: sort.key, order: sort.order, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useResource("/crm/customers", params, { paused });
  // A customer added / edited / deleted elsewhere on the page refreshes the list in place.
  useEffect(() => { if (refreshKey) reload({ background: true }); }, [refreshKey, reload]);
  // A delete (or live refresh) can shrink the list below the current page: fall back to the last page.
  useEffect(() => { if (data && page > data.pages) setPage(data.pages); }, [data, page]);

  const set = (key) => (value) => setFilters((f) => ({ ...f, [key]: value }));
  const active = Object.entries(filters).some(([, v]) => v);
  const segment = segments?.find((s) => s.id === filters.segment_id);
  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, order: s.order === "desc" ? "asc" : "desc" } : { key, order: key === "name" ? "asc" : "desc" }));

  const SortHead = ({ k, children, className }) => (
    <TableHead className={cn("text-[11px] uppercase tracking-[0.1em]", className)}>
      <button type="button" onClick={() => toggleSort(k)} className="inline-flex items-center gap-1 hover:text-foreground">
        {children}
        {sort.key === k && (sort.order === "desc" ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
      </button>
    </TableHead>
  );

  return (
    <div className="space-y-4" data-testid="crm-customers">
      <div className="flex flex-col gap-2">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1 min-w-0 sm:max-w-sm">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, email or phone…"
                   className="pl-9 h-9" data-testid="crm-search" />
          </div>
          <div className="flex gap-2 sm:ml-auto">
            <Select value={sort.key} onValueChange={(v) => setSort({ key: v, order: v === "name" ? "asc" : "desc" })}>
              <SelectTrigger className="h-9 flex-1 sm:w-[170px] text-[13px]" data-testid="crm-sort"><SelectValue /></SelectTrigger>
              <SelectContent>{SORTS.map((s) => <SelectItem key={s.key} value={s.key}>Sort: {s.label}</SelectItem>)}</SelectContent>
            </Select>
            <Button variant="outline" size="icon" className="h-9 w-9 shrink-0" aria-label="Toggle sort direction"
                    onClick={() => setSort((s) => ({ ...s, order: s.order === "desc" ? "asc" : "desc" }))}>
              {sort.order === "desc" ? <ArrowDown className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:flex sm:flex-wrap gap-2">
          <FilterSelect value={filters.city} onChange={set("city")} placeholder="All cities" testid="crm-filter-city"
                        options={(meta?.cities || []).map((c) => ({ value: c, label: c }))} />
          <FilterSelect value={filters.lifecycle} onChange={set("lifecycle")} placeholder="All stages" testid="crm-filter-lifecycle"
                        options={LIFECYCLE_KEYS.map((k) => ({ value: k, label: LIFECYCLE[k].label }))} />
          <FilterSelect value={filters.kyc_status} onChange={set("kyc_status")} placeholder="Any KYC" testid="crm-filter-kyc"
                        options={["pending", "approved", "rejected"].map((k) => ({ value: k, label: `KYC ${k}` }))} />
          <FilterSelect value={filters.tag} onChange={set("tag")} placeholder="Any tag" testid="crm-filter-tag"
                        options={(meta?.tags || []).map((t) => ({ value: t, label: t }))} />
          <Input type="number" min="0" step="any" inputMode="decimal" value={minLtv} onChange={(e) => setMinLtv(e.target.value)}
                 placeholder="Min LTV (₹)" aria-label="Minimum lifetime value in rupees"
                 aria-invalid={Boolean(minLtv) && !cleanMin(minLtv, false)}
                 className="h-9 w-full sm:w-[130px] text-[13px]" data-testid="crm-filter-min-ltv" />
          <Input type="number" min="0" step="1" inputMode="numeric" value={minBookings} onChange={(e) => setMinBookings(e.target.value)}
                 placeholder="Min bookings" aria-label="Minimum number of bookings"
                 aria-invalid={Boolean(minBookings) && !cleanMin(minBookings, true)}
                 className="h-9 w-full sm:w-[130px] text-[13px]" data-testid="crm-filter-min-bookings" />
          <FilterSelect value={filters.segment_id} onChange={set("segment_id")} placeholder="No segment" testid="crm-filter-segment"
                        className="col-span-2 sm:w-[180px]"
                        options={(segments || []).map((s) => ({ value: s.id, label: s.name }))} />
          {active && (
            <div className="col-span-2 flex gap-2 sm:col-auto">
              <Button variant="ghost" size="sm" className="h-9 gap-1" onClick={() => setFilters(EMPTY_FILTERS)} data-testid="crm-clear-filters">
                <X className="h-3.5 w-3.5" /> Clear
              </Button>
              {canEdit && !filters.segment_id && (
                <Button variant="outline" size="sm" className="h-9 gap-1.5" onClick={() => onSaveSegment(filters)} data-testid="crm-save-segment">
                  <BookmarkPlus className="h-3.5 w-3.5" /> Save as segment
                </Button>
              )}
            </div>
          )}
        </div>
      </div>

      {segment && (
        <div className="text-[12.5px] text-muted-foreground">
          Showing segment <span className="font-medium text-foreground">{segment.name}</span>, narrowed by any filters above.
        </div>
      )}

      {error ? (
        <ErrorBlock title="Couldn't load customers" error={error} onRetry={reload} />
      ) : !data ? (
        <RowSkeletons rows={8} />
      ) : data.total === 0 ? (
        <EmptyState icon={Users} title={active ? "No customers match these filters" : "No customers yet"}
                    description={active ? "Try widening the filters." : "Add your first customer, or they appear here when created in Marketplace."}
                    action={!active && canEdit && onAddCustomer && (
                      <Button size="sm" className="gap-1.5" onClick={onAddCustomer} data-testid="crm-add-customer-empty">
                        <Plus className="h-4 w-4" /> Add customer
                      </Button>
                    )} />
      ) : (
        <>
          <Card className={cn("border-border overflow-hidden transition-opacity", loading && "opacity-60")}>
            {/* Phone: stacked cards */}
            <ul className="md:hidden divide-y divide-border">
              {data.items.map((c) => (
                <li key={c.id}>
                  <button type="button" className="w-full text-left p-3.5 hover:bg-muted/40" onClick={() => onOpenCustomer(c.id)}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-medium text-[14px] truncate">{c.name}</div>
                        <div className="text-[12px] text-muted-foreground truncate">{c.city || "—"} · {c.email}</div>
                      </div>
                      <span className="font-display font-semibold tabular-nums">{inr(c.ltv)}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 mt-2 text-[11.5px] text-muted-foreground">
                      <LifecyclePill stage={c.lifecycle} />
                      <StatusPill status={`kyc ${c.kyc_status}`} className={c.kyc_status === "approved" ? "bg-success/10 text-success" : c.kyc_status === "rejected" ? "bg-destructive/10 text-destructive" : "bg-warning/10 text-warning"} />
                      <span>{c.bookings} bookings · last {relativeDays(c.days_since_last_booking).toLowerCase()}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            {/* Tablet and up: table */}
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <SortHead k="name">Customer</SortHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em]">Stage</TableHead>
                    <SortHead k="bookings" className="text-right">Bookings</SortHead>
                    <SortHead k="ltv" className="text-right">LTV</SortHead>
                    <SortHead k="last_booking">Last booking</SortHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] hidden lg:table-cell">KYC</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] hidden xl:table-cell text-right">Rating</TableHead>
                    <TableHead className="text-[11px] uppercase tracking-[0.1em] hidden xl:table-cell text-right">Tickets</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((c) => (
                    <TableRow key={c.id} className="hover:bg-muted/40 cursor-pointer" onClick={() => onOpenCustomer(c.id)} data-testid="crm-customer-row">
                      <TableCell className="max-w-[260px]">
                        <div className="font-medium truncate">{c.name}</div>
                        <div className="text-[11.5px] text-muted-foreground truncate">
                          {c.city || "—"}{c.tags.length ? ` · ${c.tags.slice(0, 2).join(", ")}${c.tags.length > 2 ? "…" : ""}` : ""}
                        </div>
                      </TableCell>
                      <TableCell><LifecyclePill stage={c.lifecycle} /></TableCell>
                      <TableCell className="text-right tabular-nums">{c.bookings}</TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{inr(c.ltv)}</TableCell>
                      <TableCell className="text-[12.5px] text-muted-foreground whitespace-nowrap">{relativeDays(c.days_since_last_booking)}</TableCell>
                      <TableCell className="hidden lg:table-cell"><StatusPill status={c.kyc_status} /></TableCell>
                      <TableCell className="hidden xl:table-cell text-right tabular-nums">{c.avg_rating ?? "—"}</TableCell>
                      <TableCell className="hidden xl:table-cell text-right tabular-nums">{c.open_tickets || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>

          <div className="flex items-center justify-between text-[12.5px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              {loading && <Loader2 className="h-3 w-3 animate-spin" />}
              {data.total.toLocaleString("en-IN")} customer{data.total === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="tabular-nums">Page {data.page} of {data.pages}</span>
              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Next page" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
