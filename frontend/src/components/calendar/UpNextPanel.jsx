import { useEffect, useState } from "react";
import { format, isToday, isTomorrow } from "date-fns";
import { CalendarClock, Video } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BROWSER_TZ, categoryStyle, eventStart, formatEventTime, relativeStart, safeUrl } from "./calendarUtils";

const LOOKAHEAD_DAYS = 14;
const LIMIT = 4;

const dayWord = (d) => (isToday(d) ? "Today" : isTomorrow(d) ? "Tomorrow" : format(d, "EEE d MMM"));

/** The signed-in user's next few events, with a live countdown and replies still owed. */
export default function UpNextPanel({ user, refreshKey, onSelectEvent }) {
  const [items, setItems] = useState(null);
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    api.get("/calendar/agenda", {
      params: { start: new Date().toISOString(), days: LOOKAHEAD_DAYS, page_size: LIMIT, participant_id: "me", tz: BROWSER_TZ },
    })
      .then(({ data }) => { if (alive) setItems(data.items); })
      .catch(() => { if (alive) setItems([]); });
    return () => { alive = false; };
  }, [refreshKey]);

  // Countdowns move on their own between data refreshes.
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30000);
    return () => clearInterval(t);
  }, []);

  const now = new Date();
  const upcoming = (items || []).filter((ev) => new Date(ev.end_time) > now);
  const owed = upcoming.filter((ev) => ev.participants?.some((p) => p.id === user?.id && p.response === "pending")).length;

  return (
    <div className="rounded-xl border border-border bg-card p-4" data-testid="calendar-up-next">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground flex items-center gap-1.5">
          <CalendarClock className="h-3.5 w-3.5" /> Up next for you
        </div>
        {owed > 0 && (
          <span className="text-[10.5px] font-semibold rounded-full bg-primary/10 text-primary px-1.5 py-0.5">{owed} to reply</span>
        )}
      </div>
      {items === null && <div className="space-y-2">{[0, 1].map((i) => <Skeleton key={i} className="h-11 w-full" />)}</div>}
      {items !== null && upcoming.length === 0 && (
        <p className="text-[12.5px] text-muted-foreground">Nothing on your calendar for the next two weeks.</p>
      )}
      <ul className="space-y-1">
        {upcoming.map((ev, i) => {
          const style = categoryStyle(ev.category);
          const relative = relativeStart(ev, now);
          const live = relative === "Happening now";
          const link = safeUrl(ev.meeting_link);
          return (
            <li key={ev.id}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSelectEvent(ev)}
                onKeyDown={(e) => { if (e.key === "Enter") onSelectEvent(ev); }}
                className={cn(
                  "group flex gap-2.5 rounded-lg px-2 py-2 cursor-pointer hover:bg-muted/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  i === 0 && "bg-muted/40",
                )}
              >
                <span className={cn("w-1 rounded-full shrink-0", style.dot)} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium truncate">{ev.title}</div>
                  <div className="text-[11.5px] text-muted-foreground truncate">
                    {dayWord(eventStart(ev))} · {formatEventTime(ev)}
                  </div>
                  {i === 0 && relative && (
                    <div className={cn("text-[11px] font-semibold mt-0.5", live ? "text-destructive" : "text-primary")}>{relative}</div>
                  )}
                </div>
                {link && (
                  <a
                    href={link}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    title="Join meeting"
                    aria-label={`Join ${ev.title}`}
                    className={cn(
                      "self-center h-7 w-7 rounded-md flex items-center justify-center shrink-0 transition-colors",
                      live ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-background hover:text-foreground",
                    )}
                  >
                    <Video className="h-3.5 w-3.5" />
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
