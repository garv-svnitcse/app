import { useEffect, useMemo, useState } from "react";
import { addDays, addHours, format } from "date-fns";
import { Check, ChevronsUpDown, Loader2, Search, X } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import AvailabilityPanel from "./AvailabilityPanel";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  CATEGORIES, DEFAULT_REMINDER, DURATION_PRESETS, REMINDERS, STATUSES, VISIBILITY, categoryStyle, combineDateTime,
  durationLabel, eventEnd, eventStart, initials, lastEventDay, safeUrl,
} from "./calendarUtils";

const DATE = "yyyy-MM-dd";
// Which validation message each form field feeds, so editing a field clears its error.
const ERROR_KEYS = {
  title: ["title"], startDate: ["start", "end"], startTime: ["start", "end"], endDate: ["end"], endTime: ["end"],
  allDay: ["start", "end"], meetingLink: ["meetingLink"],
};
const TIME = "HH:mm";

function formFromEvent(ev) {
  const start = eventStart(ev);
  const end = ev.all_day ? lastEventDay(ev) : eventEnd(ev);
  return {
    title: ev.title,
    description: ev.description || "",
    category: ev.category,
    allDay: ev.all_day,
    startDate: format(start, DATE),
    startTime: format(start, TIME),
    endDate: format(end, DATE),
    endTime: format(ev.all_day ? addHours(start, 1) : end, TIME),
    location: ev.location || "",
    meetingLink: ev.meeting_link || "",
    visibility: ev.visibility,
    participantIds: ev.participants?.map((p) => p.id) || ev.participant_ids || [],
    status: ev.status,
    reminder: ev.reminder_minutes === null || ev.reminder_minutes === undefined ? "none" : String(ev.reminder_minutes),
  };
}

function blankForm(start, requestedEnd) {
  const end = requestedEnd && requestedEnd > start ? requestedEnd : addHours(start, 1);
  return {
    title: "",
    description: "",
    category: "Meeting",
    allDay: false,
    startDate: format(start, DATE),
    startTime: format(start, TIME),
    endDate: format(end, DATE),
    endTime: format(end, TIME),
    location: "",
    meetingLink: "",
    visibility: "public",
    participantIds: [],
    status: "confirmed",
    reminder: DEFAULT_REMINDER,
  };
}

function resolveTimes(f) {
  if (f.allDay) {
    const start = combineDateTime(f.startDate, "00:00");
    const lastDay = combineDateTime(f.endDate, "00:00");
    return { start, end: lastDay && addDays(lastDay, 1) };
  }
  return { start: combineDateTime(f.startDate, f.startTime), end: combineDateTime(f.endDate, f.endTime) };
}

function validate(f) {
  const errors = {};
  if (!f.title.trim()) errors.title = "Give the event a title.";
  const { start, end } = resolveTimes(f);
  if (!start) errors.start = "Pick a valid start.";
  if (!end) errors.end = "Pick a valid end.";
  // All-day ends are exclusive (the day after the last day), so they must be strictly later.
  if (start && end && (f.allDay ? end <= start : end < start)) errors.end = "End must be after the start.";
  if (f.meetingLink.trim() && !safeUrl(f.meetingLink.trim())) errors.meetingLink = "Use a full link starting with https://";
  return errors;
}

function ParticipantPicker({ people, value, onChange, loading }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = value.map((id) => people.find((p) => p.id === id)).filter(Boolean);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return people;
    return people.filter((p) => [p.name, p.department, p.designation, p.role].some((v) => v?.toLowerCase().includes(q)));
  }, [people, query]);

  const toggle = (id) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" className="w-full justify-between font-normal" data-testid="calendar-participant-picker">
            <span className="text-muted-foreground">
              {loading ? "Loading people…" : value.length ? `${value.length} invited` : "Invite people"}
            </span>
            <ChevronsUpDown className="h-4 w-4 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name, team or role"
              className="h-10 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <ul className="max-h-64 overflow-y-auto scrollbar-thin p-1" role="listbox" aria-multiselectable="true">
            {!loading && filtered.length === 0 && (
              <li className="px-3 py-6 text-center text-sm text-muted-foreground">
                {query.trim() ? `No one matches “${query.trim()}”` : "No one else to invite yet"}
              </li>
            )}
            {filtered.map((p) => {
              const active = value.includes(p.id);
              return (
                <li key={p.id} role="option" aria-selected={active}>
                  <button
                    type="button"
                    onClick={() => toggle(p.id)}
                    className="w-full flex items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-muted focus:outline-none focus-visible:bg-muted"
                  >
                    <Avatar className="h-7 w-7">
                      <AvatarImage src={p.photo || undefined} alt="" />
                      <AvatarFallback className="text-[10px]">{initials(p.name)}</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium truncate">{p.name}</div>
                      <div className="text-[11.5px] text-muted-foreground truncate">
                        {[p.designation || p.role, p.department].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                    <Check className={cn("h-4 w-4 text-primary", !active && "invisible")} />
                  </button>
                </li>
              );
            })}
          </ul>
        </PopoverContent>
      </Popover>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((p) => (
            <span key={p.id} className="inline-flex items-center gap-1 rounded-full bg-muted pl-2.5 pr-1 py-0.5 text-[12px]">
              {p.name}
              <button type="button" onClick={() => toggle(p.id)} className="rounded-full p-0.5 hover:bg-foreground/10" aria-label={`Remove ${p.name}`}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function FieldError({ children }) {
  return children ? <p className="text-[12px] text-destructive mt-1">{children}</p> : null;
}

/** A duplicate keeps everything but the status, which starts fresh. */
function formFromTemplate(ev) {
  return { ...formFromEvent(ev), status: "confirmed" };
}

export default function EventDialog({ open, onOpenChange, event, template, defaultStart, defaultEnd, onSaved, user }) {
  const editing = !!event;
  const [form, setForm] = useState(() => blankForm(defaultStart || new Date()));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [people, setPeople] = useState([]);
  const [peopleLoading, setPeopleLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (event) setForm(formFromEvent(event));
    else if (template) setForm(formFromTemplate(template));
    else setForm(blankForm(defaultStart || new Date(), defaultEnd));
    setErrors({});
  }, [open, event, template, defaultStart, defaultEnd]);

  useEffect(() => {
    if (!open || people.length) return;
    let alive = true;
    setPeopleLoading(true);
    api.get("/calendar/invitees")
      .then(({ data }) => { if (alive) setPeople(data.filter((p) => p.id !== user?.id)); })
      .catch((e) => toast.error(`Couldn't load people: ${formatApiError(e)}`))
      .finally(() => { if (alive) setPeopleLoading(false); });
    return () => { alive = false; };
  }, [open, people.length, user?.id]);

  const clearErrors = (patch) => {
    const keys = Object.keys(patch).flatMap((k) => ERROR_KEYS[k] || []);
    setErrors((e) => {
      if (!keys.some((k) => e[k])) return e;
      const next = { ...e };
      keys.forEach((k) => delete next[k]);
      return next;
    });
  };

  const set = (patch) => {
    clearErrors(patch);
    setForm((f) => ({ ...f, ...patch }));
  };

  /** Moving the start keeps the event's duration, like most calendar apps. */
  const setStart = (patch) => {
    clearErrors(patch);
    setForm((f) => {
      const next = { ...f, ...patch };
      const before = resolveTimes(f);
      const after = resolveTimes(next);
      if (before.start && before.end && after.start) {
        const moved = new Date(after.start.getTime() + (before.end - before.start));
        const end = f.allDay ? addDays(moved, -1) : moved;
        next.endDate = format(end, DATE);
        if (!f.allDay) next.endTime = format(end, TIME);
      }
      return next;
    });
  };

  /** Quick duration: keep the start, move the end. */
  const setDuration = (minutes) => {
    const { start } = resolveTimes(form);
    if (!start) return;
    const end = new Date(start.getTime() + minutes * 60000);
    set({ endDate: format(end, DATE), endTime: format(end, TIME) });
  };

  const pickSlot = (start, end) => {
    set({ startDate: format(start, DATE), startTime: format(start, TIME), endDate: format(end, DATE), endTime: format(end, TIME) });
    toast.success(`Moved to ${format(start, "EEE d MMM, h:mm a")}`);
  };

  const times = resolveTimes(form);
  const duration = !form.allDay && times.start && times.end ? Math.round((times.end - times.start) / 60000) : null;
  const organizer = editing
    ? { id: event.organizer_id, name: event.organizer_name || "Organiser", you: event.organizer_id === user?.id }
    : user && { id: user.id, name: user.name, photo: user.photo, you: true };
  const availabilityPeople = useMemo(() => {
    const invited = form.participantIds.map((id) => people.find((p) => p.id === id)).filter(Boolean);
    return [organizer, ...invited.filter((p) => p.id !== organizer?.id)].filter((p) => p?.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.participantIds, people, organizer?.id]);

  const submit = async (e) => {
    e.preventDefault();
    if (saving) return;
    const found = validate(form);
    setErrors(found);
    if (Object.keys(found).length) return;

    const { start, end } = resolveTimes(form);
    const payload = {
      title: form.title.trim(),
      description: form.description.trim(),
      category: form.category,
      all_day: form.allDay,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      location: form.location.trim() || null,
      meeting_link: form.meetingLink.trim() || null,
      visibility: form.visibility,
      participant_ids: form.participantIds,
      reminder_minutes: form.reminder === "none" ? null : Number(form.reminder),
      ...(editing ? { status: form.status } : {}),
    };
    setSaving(true);
    try {
      const { data } = editing
        ? await api.patch(`/calendar/events/${event.id}`, payload)
        : await api.post("/calendar/events", payload);
      toast.success(editing ? "Event updated" : `“${data.title}” scheduled`);
      onSaved(data);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  const visibilityOptions = VISIBILITY.filter((v) => v.key !== "department" || user?.department || form.visibility === "department");

  return (
    <Dialog open={open} onOpenChange={(o) => !saving && onOpenChange(o)}>
      <DialogContent className="max-w-xl max-h-[92vh] overflow-y-auto scrollbar-thin" data-testid="calendar-event-form">
        <DialogHeader>
          <DialogTitle className="font-display">{editing ? "Edit event" : template ? "Duplicate event" : "New event"}</DialogTitle>
          <DialogDescription>
            {editing
              ? "Changes are visible to everyone who can see this event. Moving it asks invitees to respond again."
              : "Invited people get a notification and can reply Going, Maybe or Can't go."}
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={submit}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e); }}
          className="space-y-4"
          noValidate
        >
          <div>
            <Label htmlFor="ev-title">Title</Label>
            <Input id="ev-title" className="mt-1" autoFocus maxLength={200} value={form.title}
                   onChange={(e) => set({ title: e.target.value })} placeholder="e.g. Q4 fleet expansion review"
                   aria-invalid={!!errors.title} data-testid="calendar-title-input" />
            <FieldError>{errors.title}</FieldError>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label>Category</Label>
              <Select value={form.category} onValueChange={(v) => set({ category: v })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>
                      <span className="inline-flex items-center gap-2">
                        <span className={cn("h-2 w-2 rounded-full", categoryStyle(c).dot)} />{c}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Visible to</Label>
              <Select value={form.visibility} onValueChange={(v) => set({ visibility: v })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {visibilityOptions.map((v) => (
                    <SelectItem key={v.key} value={v.key}>
                      {v.key === "department" && user?.department ? `${v.label} (${user.department})` : v.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="rounded-lg border border-border p-3 space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor="ev-allday" className="cursor-pointer">All-day event</Label>
              <Switch id="ev-allday" checked={form.allDay} onCheckedChange={(v) => set({ allDay: v })} />
            </div>
            <div className="grid grid-cols-[1fr_auto] sm:grid-cols-[auto_1fr_auto] items-center gap-2">
              <span className="text-[12.5px] text-muted-foreground w-10 col-span-2 sm:col-span-1">Starts</span>
              <Input type="date" value={form.startDate} onChange={(e) => setStart({ startDate: e.target.value })} aria-invalid={!!errors.start} />
              {!form.allDay
                ? <Input type="time" step={300} className="w-32" value={form.startTime} onChange={(e) => setStart({ startTime: e.target.value })} />
                : <span />}
              <span className="text-[12.5px] text-muted-foreground w-10 col-span-2 sm:col-span-1">Ends</span>
              <Input type="date" value={form.endDate} min={form.startDate} onChange={(e) => set({ endDate: e.target.value })} aria-invalid={!!errors.end} />
              {!form.allDay
                ? <Input type="time" step={300} className="w-32" value={form.endTime} onChange={(e) => set({ endTime: e.target.value })} />
                : <span />}
            </div>
            {!form.allDay && (
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11.5px] text-muted-foreground mr-0.5">Duration</span>
                {DURATION_PRESETS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setDuration(m)}
                    className={cn(
                      "h-6 px-2 rounded-full border text-[11.5px] tabular-nums transition-colors",
                      duration === m ? "border-primary bg-primary/10 text-primary font-medium" : "border-border hover:bg-muted",
                    )}
                  >
                    {durationLabel(m)}
                  </button>
                ))}
                {duration !== null && duration > 0 && !DURATION_PRESETS.includes(duration) && (
                  <span className="text-[11.5px] text-muted-foreground tabular-nums">· {durationLabel(duration)}</span>
                )}
              </div>
            )}
            <FieldError>{errors.start || errors.end}</FieldError>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label htmlFor="ev-location">Location</Label>
              <Input id="ev-location" className="mt-1" maxLength={300} value={form.location}
                     onChange={(e) => set({ location: e.target.value })} placeholder="Conference room, office, city" />
            </div>
            <div>
              <Label htmlFor="ev-link">Meeting link</Label>
              <Input id="ev-link" className="mt-1" type="url" maxLength={500} value={form.meetingLink}
                     onChange={(e) => set({ meetingLink: e.target.value })} placeholder="https://meet.google.com/…"
                     aria-invalid={!!errors.meetingLink} />
              <FieldError>{errors.meetingLink}</FieldError>
            </div>
          </div>

          <div className="sm:w-1/2">
            <Label>Reminder</Label>
            <Select value={form.reminder} onValueChange={(v) => set({ reminder: v })}>
              <SelectTrigger className="mt-1" data-testid="calendar-reminder-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {REMINDERS.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="text-[11.5px] text-muted-foreground mt-1">You and everyone invited get a notification.</p>
          </div>

          <div>
            <Label>Participants</Label>
            <div className="mt-1">
              <ParticipantPicker people={people} loading={peopleLoading} value={form.participantIds}
                                 onChange={(ids) => set({ participantIds: ids })} />
            </div>
          </div>

          {!form.allDay && form.participantIds.length > 0 && times.start && times.end && times.end >= times.start && (
            <AvailabilityPanel
              start={times.start}
              end={times.end}
              people={availabilityPeople}
              excludeEventId={event?.id}
              onPickSlot={pickSlot}
            />
          )}

          <div>
            <Label htmlFor="ev-desc">Description</Label>
            <Textarea id="ev-desc" rows={3} className="mt-1" maxLength={5000} value={form.description}
                      onChange={(e) => set({ description: e.target.value })} placeholder="Agenda, goals, preparation notes…" />
          </div>

          {editing && (
            <div className="sm:w-1/2">
              <Label>Status</Label>
              <Select value={form.status} onValueChange={(v) => set({ status: v })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => <SelectItem key={s.key} value={s.key}>{s.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter className="gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
            <Button type="submit" disabled={saving} className="gap-1.5" data-testid="calendar-save-event">
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              {editing ? "Save changes" : "Schedule event"}
              <kbd className="hidden sm:inline ml-1 text-[10px] opacity-60 font-sans">Ctrl ↵</kbd>
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
