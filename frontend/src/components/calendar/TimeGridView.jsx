import { useEffect, useMemo, useRef, useState } from "react";
import { addDays, addMinutes, format, isSameDay, startOfDay } from "date-fns";
import { cn } from "@/lib/utils";
import {
  categoryStyle, durationLabel, eventEnd, eventStart, formatEventTime, lastEventDay, minutesIntoDay,
} from "./calendarUtils";

const HOUR_HEIGHT = 48;
const MIN_EVENT_HEIGHT = 22;
const HOURS = Array.from({ length: 24 }, (_, h) => h);
const SCROLL_TO_HOUR = 8;
// Overlapping events cascade: each is offset by its column but drawn wider than a strict
// 1/n slice, so titles stay readable in a narrow week column.
const CASCADE_WIDTH = 1.7;
// Dragging snaps to quarter hours; a pointer has to travel this far before a press becomes a drag.
const SNAP_MINUTES = 15;
const DRAG_THRESHOLD_PX = 4;
const DAY_MINUTES = 24 * 60;

const DAY_MS = 24 * 3600 * 1000;

/** All-day events and anything lasting a full day or more go in the top row; the rest in the grid. */
const inAllDayRow = (ev) => ev.all_day || eventEnd(ev) - eventStart(ev) >= DAY_MS;

const snap = (minutes) => Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Clip timed events to one day and lay out overlapping ones side by side. */
function layoutDay(day, events) {
  const dayStart = startOfDay(day);
  const dayEnd = addDays(dayStart, 1);
  const segments = [];
  for (const ev of events) {
    if (inAllDayRow(ev)) continue;
    const s = eventStart(ev);
    const e = eventEnd(ev);
    const touches = +s === +e ? s >= dayStart && s < dayEnd : s < dayEnd && e > dayStart;
    if (!touches) continue;
    const clipped = s < dayStart || e > dayEnd;
    segments.push({ ev, start: s < dayStart ? dayStart : s, end: e > dayEnd ? dayEnd : e, clipped });
  }
  segments.sort((a, b) => a.start - b.start || b.end - a.end);

  // Greedy columns within each cluster of visually overlapping segments.
  const minMs = (MIN_EVENT_HEIGHT / HOUR_HEIGHT) * 3600 * 1000;
  const placed = [];
  let cluster = [];
  let clusterEnd = 0;
  const flush = () => {
    const cols = Math.max(...cluster.map((c) => c.col)) + 1;
    cluster.forEach((c) => placed.push({ ...c, cols }));
    cluster = [];
  };
  for (const seg of segments) {
    if (cluster.length && +seg.start >= clusterEnd) flush();
    const visualEnd = Math.max(+seg.end, +seg.start + minMs);
    const taken = new Set(cluster.filter((c) => c.visualEnd > +seg.start).map((c) => c.col));
    let col = 0;
    while (taken.has(col)) col += 1;
    cluster.push({ ...seg, col, visualEnd });
    clusterEnd = cluster.length === 1 ? visualEnd : Math.max(clusterEnd, visualEnd);
  }
  if (cluster.length) flush();
  return placed;
}

function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60 * 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

const blockPosition = (start, end) => {
  const top = (minutesIntoDay(start) / 60) * HOUR_HEIGHT;
  const minutes = (end - start) / 60000;
  return { top, height: Math.max((minutes / 60) * HOUR_HEIGHT, MIN_EVENT_HEIGHT) };
};

function AllDayRow({ days, events, onSelectEvent }) {
  const long = events.filter(inAllDayRow);
  if (!long.length) return null;
  return (
    <div className="flex border-b border-border">
      <div className="w-14 shrink-0 px-2 py-1.5 text-[10px] uppercase tracking-wide text-muted-foreground text-right">All day</div>
      <div className="flex-1 grid" style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}>
        {days.map((day) => {
          const todays = long.filter((ev) => startOfDay(eventStart(ev)) <= day && day <= lastEventDay(ev));
          return (
            <div key={day.toISOString()} className="border-l border-border p-1 space-y-0.5 min-w-0">
              {todays.map((ev) => (
                <button
                  key={ev.id}
                  type="button"
                  onClick={() => onSelectEvent(ev)}
                  title={ev.title}
                  className={cn(
                    "w-full truncate rounded px-1.5 h-[22px] text-left text-[11.5px] font-medium",
                    categoryStyle(ev.category).solid,
                    ev.status === "cancelled" && "opacity-60 line-through",
                  )}
                >
                  {ev.title}
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Week / day grid.
 *  - Press and drag on empty space to select a time range for a new event (a plain click books an hour).
 *  - Drag an editable event to move it (across days in week view), or its bottom edge to change the end.
 */
export default function TimeGridView({
  days, events, onSelectEvent, onCreateAt, onCreateRange, onSelectDay, onReschedule, canEdit,
}) {
  const scrollRef = useRef(null);
  const gridRef = useRef(null);
  const suppressClick = useRef(false);
  const [drag, setDragState] = useState(null);
  // Pointer handlers read the latest drag from a ref; state only drives rendering.
  const dragRef = useRef(null);
  const setDrag = (next) => { dragRef.current = next; setDragState(next); };
  const now = useNow();
  const layouts = useMemo(() => days.map((d) => layoutDay(d, events)), [days, events]);
  const cols = { gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` };

  useEffect(() => {
    if (!scrollRef.current) return;
    const today = days.some((d) => isSameDay(d, new Date()));
    const hour = today ? Math.max(0, new Date().getHours() - 2) : SCROLL_TO_HOUR;
    scrollRef.current.scrollTop = Math.min(hour, SCROLL_TO_HOUR) * HOUR_HEIGHT;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Day column and minutes-into-day under the pointer. */
  const pointAt = (clientX, clientY) => {
    const rect = gridRef.current.getBoundingClientRect();
    const dayIndex = clamp(Math.floor(((clientX - rect.left) / rect.width) * days.length), 0, days.length - 1);
    const minutes = clamp(((clientY - rect.top) / HOUR_HEIGHT) * 60, 0, DAY_MINUTES);
    return { dayIndex, minutes };
  };

  // Window-level listeners while a press is active, so the drag survives leaving the grid.
  useEffect(() => {
    if (!drag) return undefined;
    const onMove = (e) => {
      const d = dragRef.current;
      if (!d) return;
      const travelled = Math.abs(e.clientX - d.originX) + Math.abs(e.clientY - d.originY);
      if (!d.active && travelled < DRAG_THRESHOLD_PX) return;
      const { dayIndex, minutes } = pointAt(e.clientX, e.clientY);
      if (d.mode === "create") {
        const at = snap(minutes);
        const [a, b] = at >= d.anchor ? [d.anchor, Math.max(at, d.anchor + SNAP_MINUTES)] : [at, d.anchor];
        setDrag({ ...d, active: true, startMin: a, endMin: b });
      } else if (d.mode === "resize") {
        setDrag({ ...d, active: true, endMin: clamp(snap(minutes), d.startMin + SNAP_MINUTES, DAY_MINUTES) });
      } else {
        const duration = d.endMin0 - d.startMin0;
        const startMin = clamp(snap(minutes - d.grabOffset), 0, DAY_MINUTES - Math.max(duration, SNAP_MINUTES));
        setDrag({ ...d, active: true, dayIndex: days.length > 1 ? dayIndex : d.dayIndex, startMin, endMin: startMin + duration });
      }
    };
    const onUp = () => {
      const d = dragRef.current;
      setDrag(null);
      if (!d) return;
      const day = startOfDay(days[d.dayIndex]);
      if (d.mode === "create") {
        if (d.active) onCreateRange(addMinutes(day, d.startMin), addMinutes(day, d.endMin));
        else onCreateAt(addMinutes(day, Math.floor(d.anchor / 30) * 30));
      } else if (d.active) {
        suppressClick.current = true;
        const start = addMinutes(day, d.startMin);
        const end = addMinutes(day, d.endMin);
        if (+start !== +eventStart(d.ev) || +end !== +eventEnd(d.ev)) onReschedule(d.ev, start, end);
      }
    };
    const onCancel = () => setDrag(null);
    const onKey = (e) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey);
    };
    // Re-subscribe only when a press starts or ends; handlers read the latest drag from dragRef.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!drag, days]);

  const startCreate = (dayIndex, e) => {
    if (e.button !== 0 || !onCreateAt) return;
    const { minutes } = pointAt(e.clientX, e.clientY);
    const anchor = Math.floor(minutes / SNAP_MINUTES) * SNAP_MINUTES;
    setDrag({ mode: "create", dayIndex, anchor, startMin: anchor, endMin: anchor + 60, originX: e.clientX, originY: e.clientY, active: false });
  };

  const startEventDrag = (seg, dayIndex, mode, e) => {
    // Never let a press on an event fall through to the column (which would start a new event).
    e.stopPropagation();
    if (e.button !== 0 || seg.clipped || !canEdit?.(seg.ev) || !onReschedule) return;
    const { minutes } = pointAt(e.clientX, e.clientY);
    const startMin0 = minutesIntoDay(seg.start);
    const endMin0 = startMin0 + (seg.end - seg.start) / 60000;
    setDrag({
      mode, ev: seg.ev, dayIndex, startMin: startMin0, endMin: endMin0, startMin0, endMin0,
      grabOffset: minutes - startMin0, originX: e.clientX, originY: e.clientY, active: false,
    });
  };

  const draggingId = drag?.active && drag.mode !== "create" ? drag.ev.id : null;

  return (
    <div
      className={cn("rounded-xl border border-border bg-card overflow-hidden", drag?.active && "select-none")}
      data-testid={`calendar-${days.length === 1 ? "day" : "week"}-view`}
    >
      <div className="flex border-b border-border bg-muted/40">
        <div className="w-14 shrink-0 flex items-end justify-end pr-2 pb-1.5 text-[9.5px] text-muted-foreground/80 tabular-nums">
          {format(now, "O")}
        </div>
        <div className="flex-1 grid" style={cols}>
          {days.map((day, i) => {
            const isToday = isSameDay(day, now);
            const count = layouts[i].length;
            return (
              <button
                key={day.toISOString()}
                type="button"
                onClick={() => onSelectDay(day)}
                disabled={days.length === 1}
                className="border-l border-border py-2 flex flex-col items-center gap-0.5 disabled:cursor-default enabled:hover:bg-muted/60"
              >
                <span className={cn("text-[11px] uppercase tracking-[0.12em]", isToday ? "text-primary font-semibold" : "text-muted-foreground")}>
                  {format(day, "EEE")}
                </span>
                <span className={cn(
                  "h-7 min-w-7 px-1.5 rounded-full flex items-center justify-center font-display text-[15px] font-semibold tabular-nums",
                  isToday && "bg-primary text-primary-foreground",
                )}>
                  {format(day, "d")}
                </span>
                <span className="h-1 flex gap-0.5" aria-hidden>
                  {Array.from({ length: Math.min(count, 4) }, (_, k) => <span key={k} className="h-1 w-1 rounded-full bg-primary/50" />)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <AllDayRow days={days} events={events} onSelectEvent={onSelectEvent} />

      <div ref={scrollRef} className="relative overflow-y-auto scrollbar-thin" style={{ maxHeight: "min(68vh, 720px)" }}>
        <div className="flex" style={{ height: 24 * HOUR_HEIGHT }}>
          <div className="w-14 shrink-0 relative">
            {HOURS.slice(1).map((h) => (
              <div key={h} className="absolute right-2 -translate-y-1/2 text-[10.5px] text-muted-foreground tabular-nums" style={{ top: h * HOUR_HEIGHT }}>
                {format(new Date(2000, 0, 1, h), "h a")}
              </div>
            ))}
          </div>
          <div ref={gridRef} className="flex-1 grid relative" style={cols}>
            {days.map((day, i) => {
              const isToday = isSameDay(day, now);
              return (
                <div
                  key={day.toISOString()}
                  className={cn("relative border-l border-border", onCreateAt ? "cursor-cell" : "cursor-default", isToday && "bg-primary/[0.02]")}
                  onPointerDown={(e) => startCreate(i, e)}
                >
                  {HOURS.map((h) => (
                    <div
                      key={h}
                      className={cn("absolute inset-x-0 border-t border-border/70", (h < 8 || h >= 19) && "bg-muted/25")}
                      style={{ top: h * HOUR_HEIGHT, height: HOUR_HEIGHT }}
                    >
                      <div className="border-t border-dashed border-border/40" style={{ marginTop: HOUR_HEIGHT / 2 - 1 }} />
                    </div>
                  ))}

                  {layouts[i].map((seg) => {
                    const { ev, start, end, col, cols: n, clipped } = seg;
                    const style = categoryStyle(ev.category);
                    const { top, height } = blockPosition(start, end);
                    const compact = height < 44;
                    const editable = !clipped && !!onReschedule && canEdit?.(ev);
                    return (
                      <button
                        key={ev.id}
                        type="button"
                        onPointerDown={(e) => startEventDrag(seg, i, "move", e)}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (suppressClick.current) { suppressClick.current = false; return; }
                          onSelectEvent(ev);
                        }}
                        title={`${ev.title} · ${formatEventTime(ev)}${editable ? " — drag to move" : ""}`}
                        data-testid="calendar-event-block"
                        className={cn(
                          "group/block absolute rounded-md border-l-[3px] px-1.5 py-1 text-left overflow-hidden shadow-sm touch-none",
                          "bg-card ring-1 ring-card hover:ring-primary/40 hover:z-20 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          editable && "cursor-grab active:cursor-grabbing",
                          style.bar,
                          ev.status === "cancelled" && "opacity-60",
                          ev.status === "tentative" && "border-dashed",
                          draggingId === ev.id && "opacity-30",
                        )}
                        style={{
                          top: top + 1,
                          height: height - 2,
                          left: `calc(${(col / n) * 100}% + 2px)`,
                          width: `calc(${Math.min(CASCADE_WIDTH / n, (n - col) / n) * 100}% - 4px)`,
                          zIndex: 10 + col,
                        }}
                      >
                        <div className={cn("absolute inset-0 -z-10", style.chip)} />
                        <div className={cn("text-[11.5px] font-medium leading-tight truncate", ev.status === "cancelled" && "line-through")}>
                          {ev.title}
                        </div>
                        {!compact && (
                          <div className="text-[10.5px] text-muted-foreground mt-0.5 truncate">
                            {formatEventTime(ev)}{ev.location ? ` · ${ev.location}` : ""}
                          </div>
                        )}
                        {editable && (
                          <span
                            aria-hidden
                            onPointerDown={(e) => startEventDrag(seg, i, "resize", e)}
                            className="absolute inset-x-0 bottom-0 h-2 cursor-ns-resize opacity-0 group-hover/block:opacity-100 flex justify-center items-end pb-0.5"
                          >
                            <span className="h-0.5 w-6 rounded-full bg-foreground/30" />
                          </span>
                        )}
                      </button>
                    );
                  })}

                  {drag?.active && drag.dayIndex === i && (
                    <DragPreview drag={drag} day={day} />
                  )}

                  {isToday && (
                    <div className="absolute inset-x-0 z-30 pointer-events-none" style={{ top: (minutesIntoDay(now) / 60) * HOUR_HEIGHT }}>
                      <div className="relative border-t-2 border-destructive">
                        <span className="absolute -left-1 -top-[5px] h-2 w-2 rounded-full bg-destructive" />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function DragPreview({ drag, day }) {
  const start = addMinutes(startOfDay(day), drag.startMin);
  const end = addMinutes(startOfDay(day), drag.endMin);
  const { top, height } = blockPosition(start, end);
  const creating = drag.mode === "create";
  const style = creating ? null : categoryStyle(drag.ev.category);
  const label = `${format(start, "h:mm a")} – ${format(end, "h:mm a")}`;
  return (
    <div
      className={cn(
        "absolute inset-x-1 z-40 rounded-md px-1.5 py-1 pointer-events-none shadow-lg ring-2",
        creating ? "bg-primary/15 ring-primary/60 border border-dashed border-primary" : cn("bg-card ring-primary/50 border-l-[3px]", style.bar),
      )}
      style={{ top: top + 1, height: height - 2 }}
    >
      {!creating && <div className={cn("absolute inset-0 -z-10 rounded-md", style.chip)} />}
      <div className="text-[11.5px] font-semibold leading-tight truncate">{creating ? "New event" : drag.ev.title}</div>
      <div className="text-[10.5px] text-foreground/70 tabular-nums truncate">
        {label} · {durationLabel(drag.endMin - drag.startMin)}
      </div>
    </div>
  );
}
