import { useMemo, useState } from "react";
import { addDays, differenceInCalendarDays, format, getISOWeek, isSameDay, isSameMonth, isWeekend, parseISO, startOfDay } from "date-fns";
import { cn } from "@/lib/utils";
import { categoryStyle, chipTime, eventEnd, eventStart, isMultiDay, weekDays } from "./calendarUtils";

const MAX_VISIBLE = 3;
const DRAG_TYPE = "application/x-wavygo-event";

function EventChip({ ev, onSelect, draggable }) {
  const style = categoryStyle(ev.category);
  const cancelled = ev.status === "cancelled";
  const multi = isMultiDay(ev);
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onSelect(ev); }}
      draggable={draggable}
      onDragStart={(e) => {
        e.stopPropagation();
        e.dataTransfer.setData(DRAG_TYPE, ev.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      title={draggable ? `${ev.title} — drag to another day to move` : ev.title}
      data-testid="calendar-event-chip"
      className={cn(
        "w-full flex items-center gap-1.5 rounded px-1.5 h-[22px] text-left text-[11.5px] leading-none transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        multi ? style.solid : cn(style.chip, "hover:brightness-95 dark:hover:brightness-125"),
        draggable && "cursor-grab active:cursor-grabbing",
        ev.status === "tentative" && "border border-dashed border-foreground/25",
        cancelled && "opacity-60 line-through",
      )}
    >
      {!multi && <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", style.dot)} />}
      {!multi && <span className="shrink-0 tabular-nums opacity-75">{chipTime(eventStart(ev))}</span>}
      <span className="truncate font-medium">{ev.title}</span>
    </button>
  );
}

/**
 * Month grid. Click a day to add an event, its number to open the day, and drag an
 * editable event onto another day to move it (time of day and duration are kept).
 */
export default function MonthView({ data, anchorDate, onSelectEvent, onSelectDay, onCreateAt, onReschedule, canEdit }) {
  const byId = useMemo(() => new Map(data.events.map((e) => [e.id, e])), [data.events]);
  const [dropDay, setDropDay] = useState(null);
  const today = new Date();
  const headers = weekDays(anchorDate);

  const onDrop = (day, e) => {
    const ev = byId.get(e.dataTransfer.getData(DRAG_TYPE));
    setDropDay(null);
    if (!ev || !onReschedule) return;
    e.preventDefault();
    const shift = differenceInCalendarDays(day, startOfDay(eventStart(ev)));
    if (!shift) return;
    // Shift in calendar days (not raw ms) so a DST change keeps the wall-clock time.
    onReschedule(ev, addDays(eventStart(ev), shift), addDays(eventEnd(ev), shift));
  };

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="calendar-month-view">
      <div className="grid grid-cols-[28px_repeat(7,minmax(0,1fr))] border-b border-border bg-muted/40">
        <div />
        {headers.map((d) => (
          <div key={d.toISOString()} className="px-2 py-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            <span className="hidden sm:inline">{format(d, "EEE")}</span>
            <span className="sm:hidden">{format(d, "EEEEE")}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-[28px_repeat(7,minmax(0,1fr))] auto-rows-fr">
        {data.days.map(({ date, event_ids }, i) => {
          const day = parseISO(date);
          const events = event_ids.map((id) => byId.get(id)).filter(Boolean)
            .sort((a, b) => Number(isMultiDay(b)) - Number(isMultiDay(a)));
          const outside = !isSameMonth(day, anchorDate);
          const isToday = isSameDay(day, today);
          const isPast = day < startOfDay(today);
          const hidden = events.length - MAX_VISIBLE;
          const dropping = dropDay === date;
          return [
            i % 7 === 0 && (
              <button
                key={`w-${date}`}
                type="button"
                onClick={() => onSelectDay(day, "week")}
                title={`Open week ${getISOWeek(day)}`}
                className={cn(
                  "text-[10px] text-muted-foreground/70 tabular-nums pt-2.5 hover:text-primary hover:bg-muted/50 border-r border-border",
                  i < data.days.length - 7 && "border-b",
                )}
              >
                {getISOWeek(day)}
              </button>
            ),
            <div
              key={date}
              role="button"
              tabIndex={0}
              aria-label={`${format(day, "d MMMM yyyy")}, ${events.length} events`}
              onClick={() => onCreateAt(day)}
              onKeyDown={(e) => { if (e.key === "Enter") onSelectDay(day); }}
              onDragOver={(e) => {
                if (!onReschedule || !e.dataTransfer.types.includes(DRAG_TYPE)) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                if (dropDay !== date) setDropDay(date);
              }}
              onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDropDay((d) => (d === date ? null : d)); }}
              onDrop={(e) => onDrop(day, e)}
              className={cn(
                "group min-h-[116px] p-1.5 flex flex-col gap-1 cursor-pointer transition-colors",
                "hover:bg-primary/[0.03] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                i % 7 !== 6 && "border-r border-border",
                i < data.days.length - 7 && "border-b border-border",
                isWeekend(day) && !outside && "bg-muted/15",
                outside && "bg-muted/30",
                isToday && "bg-primary/[0.04]",
                dropping && "bg-primary/10 ring-2 ring-inset ring-primary/50",
              )}
            >
              <div className="flex items-center justify-between px-0.5">
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onSelectDay(day); }}
                  className={cn(
                    "h-6 min-w-6 px-1.5 rounded-full text-[12px] font-medium tabular-nums transition-colors",
                    isToday ? "bg-primary text-primary-foreground" : "hover:bg-muted",
                    outside && !isToday && "text-muted-foreground/60",
                    isPast && !outside && !isToday && "text-muted-foreground",
                  )}
                >
                  {day.getDate() === 1 ? format(day, "d MMM") : format(day, "d")}
                </button>
                {events.length > 0 && (
                  <span className="text-[10px] text-muted-foreground/70 tabular-nums opacity-0 group-hover:opacity-100 transition-opacity">
                    {events.length}
                  </span>
                )}
              </div>
              <div className="flex flex-col gap-0.5 min-w-0">
                {events.slice(0, MAX_VISIBLE).map((ev) => (
                  <EventChip key={ev.id} ev={ev} onSelect={onSelectEvent} draggable={!!onReschedule && !!canEdit?.(ev)} />
                ))}
                {hidden > 0 && (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onSelectDay(day); }}
                    className="text-left px-1.5 text-[11px] font-medium text-muted-foreground hover:text-foreground"
                  >
                    +{hidden} more
                  </button>
                )}
              </div>
            </div>,
          ];
        })}
      </div>
    </div>
  );
}
