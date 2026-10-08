import { useEffect, useMemo, useState } from "react";
import { Globe2, Lock, Search, X, Check, Users, Building2, ShieldCheck, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export const VAULT_ROLES = ["Founder", "Admin", "Manager", "Employee", "Intern"];
export const EVERYONE_ACCESS = { mode: "everyone", roles: [], departments: [], user_ids: [] };

/** Normalise whatever the API returned (legacy items have no access) into a full access object. */
export function normalizeAccess(access) {
  if (!access || access.mode !== "restricted") return { ...EVERYONE_ACCESS };
  return {
    mode: "restricted",
    roles: access.roles || [],
    departments: access.departments || [],
    user_ids: access.user_ids || [],
  };
}

// People and departments are shared by every picker on the page; fetch them once per session.
let optionsPromise = null;
function loadOptions() {
  if (!optionsPromise) {
    optionsPromise = Promise.all([
      api.get("/users/directory").then((r) => r.data).catch(() => []),
      api.get("/employees/departments/list").then((r) => r.data).catch(() => []),
    ]).then(([people, depts]) => ({
      people: people || [],
      departments: [...new Set((depts || []).map((d) => (d.name || "").trim()).filter(Boolean))],
    }));
    // Let a failed/empty load be retried next time a picker opens.
    optionsPromise.then((o) => { if (!o.people.length) optionsPromise = null; });
  }
  return optionsPromise;
}

export function useAccessOptions() {
  const [options, setOptions] = useState(null);
  useEffect(() => {
    let alive = true;
    loadOptions().then((o) => alive && setOptions(o));
    return () => { alive = false; };
  }, []);
  return options;
}

/** Short human description of an access setting, e.g. "Managers, Sales +2 people". */
export function accessSummary(access, peopleById = {}) {
  const a = normalizeAccess(access);
  if (a.mode === "everyone") return "Everyone with vault access";
  const parts = [
    ...a.roles.map((r) => `${r}s`),
    ...a.departments.map((d) => `${d} dept.`),
  ];
  const names = a.user_ids.map((id) => peopleById[id]?.name).filter(Boolean);
  if (names.length && names.length <= 2 && parts.length === 0) parts.push(...names);
  else if (a.user_ids.length) parts.push(`${a.user_ids.length} ${a.user_ids.length === 1 ? "person" : "people"}`);
  return parts.length ? parts.join(", ") : "Only the owner (and Founders/Admins)";
}

/** Small lock badge shown on restricted items; renders nothing for "everyone". */
export function AccessBadge({ access, peopleById, className, showLabel = true }) {
  const a = normalizeAccess(access);
  if (a.mode !== "restricted") return null;
  const summary = accessSummary(a, peopleById);
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn("inline-flex items-center gap-1 h-5 px-1.5 rounded text-[10.5px] font-semibold whitespace-nowrap bg-primary/10 text-primary", className)}
            aria-label={`Restricted: ${summary}`}
            data-testid="vault-access-badge"
          >
            <Lock className="h-3 w-3" />
            {showLabel && "Restricted"}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-[260px]">Visible to: {summary}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function Chip({ active, onClick, disabled, children }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1 h-7 px-2.5 rounded-full border text-[12px] transition-colors disabled:opacity-50",
        active ? "border-primary bg-primary/10 text-primary font-medium" : "border-border bg-card hover:bg-muted text-foreground/80",
      )}
    >
      {active && <Check className="h-3 w-3" />}
      {children}
    </button>
  );
}

function toggle(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/**
 * Access picker for vault documents and folders.
 * value: { mode: "everyone" | "restricted", roles, departments, user_ids }
 */
export default function AccessPicker({ value, onChange, disabled, idPrefix = "vault-access", scope = "document" }) {
  const access = normalizeAccess(value);
  const options = useAccessOptions();
  const [query, setQuery] = useState("");

  const peopleById = useMemo(
    () => Object.fromEntries((options?.people || []).map((p) => [p.id, p])),
    [options],
  );
  const departments = useMemo(() => {
    const all = [...(options?.departments || [])];
    // Keep departments already on the item even if they no longer exist in the directory.
    access.departments.forEach((d) => { if (!all.some((x) => x.toLowerCase() === d.toLowerCase())) all.push(d); });
    return all;
  }, [options, access.departments]);
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const people = options?.people || [];
    const list = q
      ? people.filter((p) => [p.name, p.department, p.designation, p.role].some((f) => (f || "").toLowerCase().includes(q)))
      : people;
    return list.slice(0, 50);
  }, [options, query]);

  const set = (patch) => onChange({ ...access, ...patch });
  const restricted = access.mode === "restricted";
  const hasDept = (d) => access.departments.some((x) => x.toLowerCase() === d.toLowerCase());
  const toggleDept = (d) => set({
    departments: hasDept(d) ? access.departments.filter((x) => x.toLowerCase() !== d.toLowerCase()) : [...access.departments, d],
  });

  return (
    <div className="space-y-3" data-testid={`${idPrefix}-picker`}>
      <div>
        <Label>Who can see this {scope}?</Label>
        <div className="grid grid-cols-2 gap-2 mt-1.5" role="radiogroup" aria-label="Visibility">
          {[
            { mode: "everyone", icon: Globe2, title: "Everyone", sub: "All vault users" },
            { mode: "restricted", icon: Lock, title: "Restricted", sub: "Roles, departments, people" },
          ].map((o) => {
            const active = access.mode === o.mode;
            const Icon = o.icon;
            return (
              <button
                key={o.mode}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={disabled}
                onClick={() => set({ mode: o.mode })}
                data-testid={`${idPrefix}-${o.mode}`}
                className={cn(
                  "flex items-start gap-2.5 rounded-lg border p-2.5 text-left transition-colors disabled:opacity-50",
                  active ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50",
                )}
              >
                <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium">{o.title}</span>
                  <span className="block text-[11.5px] text-muted-foreground">{o.sub}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {restricted && (
        <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-3">
          <div>
            <div className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground mb-1.5">
              <ShieldCheck className="h-3.5 w-3.5" /> Roles
            </div>
            <div className="flex flex-wrap gap-1.5">
              {VAULT_ROLES.map((r) => (
                <Chip key={r} active={access.roles.includes(r)} disabled={disabled} onClick={() => set({ roles: toggle(access.roles, r) })}>
                  {r}
                </Chip>
              ))}
            </div>
          </div>

          <div>
            <div className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground mb-1.5">
              <Building2 className="h-3.5 w-3.5" /> Departments
            </div>
            {!options ? (
              <div className="text-[12px] text-muted-foreground flex items-center gap-1.5"><Loader2 className="h-3 w-3 animate-spin" /> Loading…</div>
            ) : departments.length === 0 ? (
              <div className="text-[12px] text-muted-foreground">No departments set up yet.</div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {departments.map((d) => (
                  <Chip key={d} active={hasDept(d)} disabled={disabled} onClick={() => toggleDept(d)}>{d}</Chip>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground mb-1.5">
              <Users className="h-3.5 w-3.5" /> Specific people
            </div>
            {access.user_ids.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {access.user_ids.map((id) => (
                  <span key={id} className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-full bg-primary/10 text-primary text-[12px]">
                    {peopleById[id]?.name || "Unknown user"}
                    <button type="button" className="rounded-full p-0.5 hover:bg-primary/20" disabled={disabled}
                            aria-label={`Remove ${peopleById[id]?.name || "user"}`}
                            onClick={() => set({ user_ids: access.user_ids.filter((x) => x !== id) })}>
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="relative">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              <Input id={`${idPrefix}-people-search`} value={query} onChange={(e) => setQuery(e.target.value)}
                     placeholder="Search employees by name, department…" className="pl-8 h-8 text-[12.5px]" disabled={disabled}
                     aria-label="Search employees" />
            </div>
            <div className="mt-1.5 max-h-40 overflow-y-auto rounded-md border border-border bg-card divide-y divide-border" role="listbox"
                 aria-multiselectable="true" aria-label="Employees">
              {!options ? (
                <div className="p-2.5 text-[12px] text-muted-foreground flex items-center gap-1.5"><Loader2 className="h-3 w-3 animate-spin" /> Loading…</div>
              ) : matches.length === 0 ? (
                <div className="p-2.5 text-[12px] text-muted-foreground">No matching employees.</div>
              ) : matches.map((p) => {
                const selected = access.user_ids.includes(p.id);
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    disabled={disabled}
                    onClick={() => set({ user_ids: toggle(access.user_ids, p.id) })}
                    className={cn("w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-muted/60", selected && "bg-primary/5")}
                  >
                    <span className={cn("h-4 w-4 shrink-0 rounded border flex items-center justify-center",
                      selected ? "bg-primary border-primary text-primary-foreground" : "border-border")}>
                      {selected && <Check className="h-3 w-3" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] truncate">{p.name}</span>
                      <span className="block text-[11px] text-muted-foreground truncate">
                        {[p.role, p.department, p.designation].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <p className="text-[11.5px] text-muted-foreground leading-relaxed">
            Anyone matching a selected role, department <em>or</em> person can see it. Founders, Admins and the owner always keep access
            {scope === "folder" ? "; documents inside this folder are hidden from everyone else." : "."}
            {access.roles.length + access.departments.length + access.user_ids.length === 0 && " Nothing selected: only the owner, Founders and Admins."}
          </p>
        </div>
      )}
    </div>
  );
}
