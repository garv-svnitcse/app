import { useEffect, useMemo, useState } from "react";
import { addDays, addMinutes, format, startOfDay } from "date-fns";
import { AlertTriangle, CheckCircle2, Loader2, Sparkles } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BROWSER_TZ, initials, rangesOverlap, toDateParam } from "./calendarUtils";

// Timeline window and the working hours "Find a time" searches within.
const VIEW_FROM_HOUR = 7;
const VIEW_TO_HOUR = 21;
const WORK_FROM_HOUR = 9;
const WORK_TO_HOUR = 18;
const SEARCH_DAYS = 7;
const STEP_MINUTES = 15;
const DEBOUNCE_MS = 350;

const toBlocks = (busy) => busy.map((b) => ({ ...b, start: new Date(b.start), end: new Date(b.end) }));

/** First slot of `minutes` from `from` onwards, inside working hours, where nobody is busy. */
function findFreeSlot(from, minutes, people) {
  const blocks = people.flatMap((p) => p.blocks);
  const firstDay = startOfDay(from);
  for (let d = 0; d < SEARCH_DAYS; d += 1) {
    const day = addDays(firstDay, d);
    const dayOpen = addMinutes(day, WORK_FROM_HOUR * 60);
    const dayClose = addMinutes(day, WORK_TO_HOUR * 60);
    let t = from > dayOpen ? new Date(Math.ceil(from / (STEP_MINUTES * 60000)) * STEP_MINUTES * 60000) : dayOpen;
    while (addMinutes(t, minutes) <= dayClose) {
      const end = addMinutes(t, minutes);
      const clash = blocks.find((b) => rangesOverlap(t, end, b.start, b.end));
      if (!clash) return { start: t, end };
      // Jump past the clashing block rather than stepping through it.
      t = new Date(Math.max(+addMinutes(t, STEP_MINUTES), Math.ceil(clash.end / (STEP_MINUTES * 60000)) * STEP_MINUTES * 60000));
    }
  }
  return null;
}

/**
 * Free/busy for the organiser and invited people around the chosen time: a timeline for the
 * start day, a list of clashes, and a one-click "next time everyone is free".
 */
export default function AvailabilityPanel({ start, end, people, excludeEventId, onPickSlot }) {
  const [state, setState] = useState({ loading: false, data: null, error: false });
  const ids = people.map((p) => p.id);
  const idsKey = ids.join(",");
  const dayKey = start ? toDateParam(start) : "";

  useEffect(() => {
    if (!start || !ids.length) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setState((s) => ({ ...s, loading: true, error: false }));
      api.get("/calendar/availability", {
        params: {
          user_ids: idsKey,
          start: dayKey,
          end: toDateParam(addDays(startOfDay(start), SEARCH_DAYS)),
          exclude_event_id: excludeEventId || undefined,
          tz: BROWSER_TZ,
        },
        signal: controller.signal,
      })
        .then(({ data }) => setState({ loading: false, data, error: false }))
        .catch(() => { if (!controller.signal.aborted) setState({ loading: false, data: null, error: true }); });
    }, DEBOUNCE_MS);
    return () => { clearTimeout(timer); controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, dayKey, excludeEventId]);

  const rows = useMemo(() => {
    const byId = new Map((state.data?.users || []).map((u) => [u.user_id, toBlocks(u.busy)]));
    return people.map((p) => ({ ...p, blocks: byId.get(p.id) || [] }));
  }, [people, state.data]);

  if (!start || !end || !people.length) return null;

  const conflicts = rows.flatMap((p) =>
    p.blocks.filter((b) => rangesOverlap(start, end, b.start, b.end)).map((b) => ({ person: p, block: b })));
  const minutes = Math.max(STEP_MINUTES, Math.round((end - start) / 60000));
  const suggestion = conflicts.length && state.data ? findFreeSlot(start, minutes, rows) : null;

  const dayStart = addMinutes(startOfDay(start), VIEW_FROM_HOUR * 60);
  const span = (VIEW_TO_HOUR - VIEW_FROM_HOUR) * 60;
  const pct = (d) => Math.max(0, Math.min(100, ((d - dayStart) / 60000 / span) * 100));
  const bar = (s, e) => ({ left: `${pct(s)}%`, width: `${Math.max(pct(e) - pct(s), 0.8)}%` });
  const hours = Array.from({ length: VIEW_TO_HOUR - VIEW_FROM_HOUR + 1 }, (_, i) => VIEW_FROM_HOUR + i);

  return (
    <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-3" data-testid="calendar-availability">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[12px] font-medium flex items-center gap-1.5">
          Availability · {format(start, "EEE d MMM")}
          {state.loading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
        </div>
        {state.data && !state.loading && (
          conflicts.length
            ? <span className="text-[11.5px] text-amber-700 dark:text-amber-300 inline-flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" />{conflicts.length} clash{conflicts.length === 1 ? "" : "es"}</span>
            : <span className="text-[11.5px] text-emerald-700 dark:text-emerald-300 inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" />Everyone is free</span>
        )}
      </div>

      {state.error && <p className="text-[12px] text-muted-foreground">Couldn't check availability right now.</p>}

      {state.data && (
        <div className="space-y-1.5">
          <div className="relative h-3 ml-[92px] text-[9.5px] text-muted-foreground tabular-nums">
            {hours.filter((h) => h % 2 === 1).map((h) => (
              <span key={h} className="absolute -translate-x-1/2" style={{ left: `${((h - VIEW_FROM_HOUR) / (VIEW_TO_HOUR - VIEW_FROM_HOUR)) * 100}%` }}>
                {format(new Date(2000, 0, 1, h), "ha").toLowerCase()}
              </span>
            ))}
          </div>
          {rows.map((p) => (
            <div key={p.id} className="flex items-center gap-2">
              <div className="w-[84px] shrink-0 flex items-center gap-1.5 min-w-0">
                <Avatar className="h-5 w-5">
                  <AvatarImage src={p.photo || undefined} alt="" />
                  <AvatarFallback className="text-[8.5px]">{initials(p.name)}</AvatarFallback>
                </Avatar>
                <span className="text-[11.5px] truncate">{p.you ? "You" : p.name.split(" ")[0]}</span>
              </div>
              <div className="relative flex-1 h-5 rounded bg-background border border-border overflow-hidden">
                {hours.slice(1, -1).map((h) => (
                  <span key={h} className="absolute inset-y-0 w-px bg-border/60" style={{ left: `${((h - VIEW_FROM_HOUR) / (VIEW_TO_HOUR - VIEW_FROM_HOUR)) * 100}%` }} />
                ))}
                {p.blocks.filter((b) => b.end > dayStart && b.start < addMinutes(dayStart, span)).map((b, k) => (
                  <span
                    key={k}
                    title={`${b.title} · ${format(b.start, "h:mm a")} – ${format(b.end, "h:mm a")}`}
                    className={cn("absolute inset-y-0.5 rounded-sm", b.tentative ? "bg-amber-400/50" : "bg-slate-500/45 dark:bg-slate-400/40")}
                    style={bar(b.start, b.end)}
                  />
                ))}
                <span
                  className={cn("absolute inset-y-0 rounded-sm ring-2", conflicts.some((c) => c.person.id === p.id) ? "ring-rose-500 bg-rose-500/15" : "ring-primary bg-primary/15")}
                  style={bar(start, end)}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {conflicts.length > 0 && (
        <ul className="space-y-1 text-[12px]">
          {conflicts.slice(0, 4).map(({ person, block }, k) => (
            <li key={k} className="flex gap-1.5 text-foreground/85">
              <span className="font-medium">{person.you ? "You" : person.name}</span>
              <span className="text-muted-foreground truncate">
                {block.tentative ? "maybe busy" : "busy"} {format(block.start, "h:mm")}–{format(block.end, "h:mm a")} · {block.title}
              </span>
            </li>
          ))}
          {conflicts.length > 4 && <li className="text-muted-foreground">and {conflicts.length - 4} more…</li>}
        </ul>
      )}

      {suggestion && (
        <Button type="button" size="sm" variant="secondary" className="gap-1.5 h-8" onClick={() => onPickSlot(suggestion.start, suggestion.end)}
                data-testid="calendar-suggest-slot">
          <Sparkles className="h-3.5 w-3.5" />
          Everyone's free {format(suggestion.start, "EEE d MMM, h:mm a")} — use it
        </Button>
      )}
      {conflicts.length > 0 && state.data && !suggestion && (
        <p className="text-[11.5px] text-muted-foreground">No shared free {minutes}-minute slot in working hours this week.</p>
      )}
    </div>
  );
}
