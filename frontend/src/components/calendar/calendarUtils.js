import {
  addDays, addMonths, addWeeks, differenceInCalendarDays, endOfWeek, format, isSameDay,
  isSameMonth, isValid, parseISO, startOfDay, startOfWeek,
} from "date-fns";

export const VIEWS = [
  { key: "month", label: "Month" },
  { key: "week", label: "Week" },
  { key: "day", label: "Day" },
  { key: "agenda", label: "Agenda" },
];
export const VIEW_KEYS = VIEWS.map((v) => v.key);

export const CATEGORIES = ["Meeting", "Product Launch", "Team Sync", "Workshop", "Milestone", "Reminder", "Other"];
export const VISIBILITY = [
  { key: "public", label: "Everyone", hint: "Visible to the whole company" },
  { key: "department", label: "My department", hint: "Visible to your department" },
  { key: "private", label: "Private", hint: "Only you and invited participants" },
];
export const REMINDERS = [
  { value: "none", label: "No reminder" },
  { value: "0", label: "At start time" },
  { value: "5", label: "5 minutes before" },
  { value: "10", label: "10 minutes before" },
  { value: "15", label: "15 minutes before" },
  { value: "30", label: "30 minutes before" },
  { value: "60", label: "1 hour before" },
  { value: "1440", label: "1 day before" },
];
export const DEFAULT_REMINDER = "15";

export function reminderLabel(minutes) {
  if (minutes === null || minutes === undefined) return null;
  const known = REMINDERS.find((r) => r.value === String(minutes));
  if (known) return known.label;
  if (minutes % 1440 === 0) return `${minutes / 1440} days before`;
  if (minutes % 60 === 0) return `${minutes / 60} hours before`;
  return `${minutes} minutes before`;
}

export const STATUSES = [
  { key: "confirmed", label: "Confirmed" },
  { key: "tentative", label: "Tentative" },
  { key: "cancelled", label: "Cancelled" },
];

// Monday-first weeks, matching the backend's `week_start=monday`.
export const WEEK_STARTS_ON = 1;
export const AGENDA_DAYS = 30;
export const AGENDA_PAGE_SIZE = 50;

// Day boundaries are computed by the backend in the viewer's zone.
export const BROWSER_TZ = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  } catch {
    return "Asia/Kolkata";
  }
})();

const CATEGORY_STYLES = {
  "Meeting":        { dot: "bg-sky-500",     chip: "bg-sky-500/10 text-sky-800 dark:text-sky-200",             bar: "border-l-sky-500",     solid: "bg-sky-500/90 text-white" },
  "Product Launch": { dot: "bg-emerald-500", chip: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200", bar: "border-l-emerald-500", solid: "bg-emerald-600/90 text-white" },
  "Team Sync":      { dot: "bg-violet-500",  chip: "bg-violet-500/10 text-violet-800 dark:text-violet-200",    bar: "border-l-violet-500",  solid: "bg-violet-500/90 text-white" },
  "Workshop":       { dot: "bg-amber-500",   chip: "bg-amber-500/10 text-amber-800 dark:text-amber-200",       bar: "border-l-amber-500",   solid: "bg-amber-500/90 text-white" },
  "Milestone":      { dot: "bg-rose-500",    chip: "bg-rose-500/10 text-rose-800 dark:text-rose-200",          bar: "border-l-rose-500",    solid: "bg-rose-500/90 text-white" },
  "Reminder":       { dot: "bg-teal-500",    chip: "bg-teal-500/10 text-teal-800 dark:text-teal-200",          bar: "border-l-teal-500",    solid: "bg-teal-600/90 text-white" },
  "Other":          { dot: "bg-slate-400",   chip: "bg-slate-500/10 text-slate-700 dark:text-slate-200",       bar: "border-l-slate-400",   solid: "bg-slate-500/90 text-white" },
};

export function categoryStyle(category) {
  return CATEGORY_STYLES[category] || CATEGORY_STYLES.Other;
}

// ------------------------- dates -------------------------

export const toDateParam = (d) => format(d, "yyyy-MM-dd");

export function parseDateParam(value) {
  const d = value ? parseISO(value) : null;
  return d && isValid(d) ? startOfDay(d) : startOfDay(new Date());
}

export const eventStart = (ev) => new Date(ev.start_time);
export const eventEnd = (ev) => new Date(ev.end_time);

export function shiftDate(date, view, direction) {
  if (view === "month") return addMonths(date, direction);
  if (view === "week") return addWeeks(date, direction);
  if (view === "agenda") return addDays(date, direction * AGENDA_DAYS);
  return addDays(date, direction);
}

export function weekDays(date) {
  const first = startOfWeek(date, { weekStartsOn: WEEK_STARTS_ON });
  return Array.from({ length: 7 }, (_, i) => addDays(first, i));
}

export function rangeTitle(date, view) {
  if (view === "month") return format(date, "MMMM yyyy");
  if (view === "day") return format(date, "EEEE, d MMMM yyyy");
  if (view === "agenda") return `${format(date, "d MMM")} – ${format(addDays(date, AGENDA_DAYS - 1), "d MMM yyyy")}`;
  const first = startOfWeek(date, { weekStartsOn: WEEK_STARTS_ON });
  const last = endOfWeek(date, { weekStartsOn: WEEK_STARTS_ON });
  if (isSameMonth(first, last)) return `${format(first, "d")} – ${format(last, "d MMM yyyy")}`;
  if (first.getFullYear() === last.getFullYear()) return `${format(first, "d MMM")} – ${format(last, "d MMM yyyy")}`;
  return `${format(first, "d MMM yyyy")} – ${format(last, "d MMM yyyy")}`;
}

export function dayLabel(day) {
  const today = startOfDay(new Date());
  const diff = differenceInCalendarDays(day, today);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  return format(day, "EEEE");
}

const timeFmt = (d) => format(d, d.getMinutes() ? "h:mm a" : "h a");

/** Last day an event touches; an end at exactly midnight belongs to the previous day. */
export function lastEventDay(ev) {
  const start = eventStart(ev);
  const end = eventEnd(ev);
  if (end <= start) return startOfDay(start);
  return startOfDay(new Date(end.getTime() - 1));
}

export function isMultiDay(ev) {
  return ev.all_day || !isSameDay(eventStart(ev), lastEventDay(ev));
}

export function formatEventTime(ev) {
  const start = eventStart(ev);
  const end = eventEnd(ev);
  const last = lastEventDay(ev);
  if (ev.all_day) {
    return isSameDay(start, last) ? "All day" : `${format(start, "d MMM")} – ${format(last, "d MMM")} · All day`;
  }
  if (+start === +end) return timeFmt(start);
  if (isSameDay(start, last)) return `${timeFmt(start)} – ${timeFmt(end)}`;
  return `${format(start, "d MMM")}, ${timeFmt(start)} – ${format(end, "d MMM")}, ${timeFmt(end)}`;
}

export function formatEventDate(ev) {
  const start = eventStart(ev);
  const last = lastEventDay(ev);
  if (isSameDay(start, last)) return format(start, "EEEE, d MMMM yyyy");
  return `${format(start, "EEE, d MMM yyyy")} – ${format(last, "EEE, d MMM yyyy")}`;
}

export const minutesIntoDay = (d) => d.getHours() * 60 + d.getMinutes();

/** Combine form date (yyyy-MM-dd) and time (HH:mm) into a local Date. */
export function combineDateTime(dateStr, timeStr) {
  const d = new Date(`${dateStr}T${timeStr || "00:00"}`);
  return isValid(d) ? d : null;
}

export function isInProgress(ev, now = new Date()) {
  return eventStart(ev) <= now && now < eventEnd(ev);
}

export function initials(name = "") {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "?";
}

export function safeUrl(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

export function canModifyEvent(ev, user, can, action) {
  return !!user && (ev.organizer_id === user.id || can(action));
}

/** Compact time for month chips: "7:45a", "10p". */
export function chipTime(d) {
  const h = d.getHours();
  const m = d.getMinutes();
  const suffix = h < 12 ? "a" : "p";
  const h12 = h % 12 || 12;
  return m ? `${h12}:${String(m).padStart(2, "0")}${suffix}` : `${h12}${suffix}`;
}

export function canEditEvent(ev, user, can) {
  return canModifyEvent(ev, user, can, "calendar.edit_any");
}

// ------------------------- RSVP -------------------------

export const RSVP_OPTIONS = [
  { key: "accepted", label: "Going" },
  { key: "tentative", label: "Maybe" },
  { key: "declined", label: "Can't go" },
];

export const RESPONSE_STYLES = {
  accepted:  { label: "Going",    dot: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-300" },
  tentative: { label: "Maybe",    dot: "bg-amber-500",   text: "text-amber-700 dark:text-amber-300" },
  declined:  { label: "Can't go", dot: "bg-rose-500",    text: "text-rose-700 dark:text-rose-300" },
  pending:   { label: "Awaiting", dot: "bg-slate-300 dark:bg-slate-600", text: "text-muted-foreground" },
};

export function responseCounts(ev) {
  const counts = { accepted: 0, tentative: 0, declined: 0, pending: 0 };
  for (const p of ev.participants || []) counts[p.response || "pending"] += 1;
  return counts;
}

// ------------------------- scheduling helpers -------------------------

export const DURATION_PRESETS = [15, 30, 45, 60, 90, 120];

export function durationLabel(minutes) {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** "in 25 min", "in 3 h", "now", or null once it's over / far away. */
export function relativeStart(ev, now = new Date()) {
  const start = eventStart(ev);
  const end = eventEnd(ev);
  if (start <= now && now < end) return "Happening now";
  const minutes = Math.round((start - now) / 60000);
  if (minutes < 0) return null;
  if (minutes < 1) return "Starting now";
  if (minutes < 60) return `In ${minutes} min`;
  if (minutes < 24 * 60) return `In ${Math.round(minutes / 60)} h`;
  const days = Math.round(minutes / (24 * 60));
  return `In ${days} day${days === 1 ? "" : "s"}`;
}

/** Overlap of [aStart, aEnd) and [bStart, bEnd); zero-length ranges count when inside. */
export function rangesOverlap(aStart, aEnd, bStart, bEnd) {
  if (+aStart === +aEnd) return aStart >= bStart && aStart < bEnd;
  if (+bStart === +bEnd) return bStart >= aStart && bStart < aEnd;
  return aStart < bEnd && bStart < aEnd;
}

// ------------------------- export -------------------------

const icsDate = (d) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
const icsDay = (d) => format(d, "yyyyMMdd");
const icsText = (v = "") => String(v).replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/[,;]/g, (c) => `\\${c}`);

/** A minimal RFC 5545 file for one event, so it can be added to Google / Outlook / Apple calendars. */
export function buildIcs(ev) {
  const start = eventStart(ev);
  const end = eventEnd(ev);
  const lines = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//WavyGo OS//Calendar//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
    `UID:${ev.id}@wavygo`,
    `DTSTAMP:${icsDate(new Date())}`,
    ...(ev.all_day
      ? [`DTSTART;VALUE=DATE:${icsDay(start)}`, `DTEND;VALUE=DATE:${icsDay(end)}`]
      : [`DTSTART:${icsDate(start)}`, `DTEND:${icsDate(end)}`]),
    `SUMMARY:${icsText(ev.title)}`,
    ev.location && `LOCATION:${icsText(ev.location)}`,
    (ev.description || ev.meeting_link) && `DESCRIPTION:${icsText([ev.description, ev.meeting_link].filter(Boolean).join("\n\n"))}`,
    safeUrl(ev.meeting_link) && `URL:${safeUrl(ev.meeting_link)}`,
    `STATUS:${ev.status === "cancelled" ? "CANCELLED" : ev.status === "tentative" ? "TENTATIVE" : "CONFIRMED"}`,
    "END:VEVENT", "END:VCALENDAR",
  ].filter(Boolean);
  return lines.join("\r\n");
}

export function downloadIcs(ev) {
  const blob = new Blob([buildIcs(ev)], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(ev.title || "event").replace(/[^\w\- ]+/g, "").trim() || "event"}.ics`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
