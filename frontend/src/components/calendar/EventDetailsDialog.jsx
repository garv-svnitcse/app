import { useState } from "react";
import {
  Clock, MapPin, Video, Users, Eye, Pencil, Trash2, Ban, RotateCcw, Loader2, ExternalLink, User, Bell,
  Copy, Download, Link2, MoreHorizontal, Check, HelpCircle, X,
} from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/module/ModulePrimitives";
import { api, formatApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  RESPONSE_STYLES, RSVP_OPTIONS, VISIBILITY, canModifyEvent, categoryStyle, downloadIcs, eventEnd, eventStart,
  formatEventDate, formatEventTime, initials, reminderLabel, relativeStart, responseCounts, safeUrl,
} from "./calendarUtils";

const RSVP_ICONS = { accepted: Check, tentative: HelpCircle, declined: X };
// The join button lights up this long before the start.
const JOIN_WINDOW_MINUTES = 10;

function Row({ icon: Icon, children }) {
  return (
    <div className="flex items-start gap-3 text-[13.5px]">
      <Icon className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function ResponseSummary({ event }) {
  const counts = responseCounts(event);
  const total = event.participants.length;
  return (
    <div className="space-y-1.5 mb-2.5">
      <div className="flex h-1.5 rounded-full overflow-hidden bg-muted">
        {["accepted", "tentative", "declined"].map((k) => counts[k] > 0 && (
          <span key={k} className={RESPONSE_STYLES[k].dot} style={{ width: `${(counts[k] / total) * 100}%` }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px] text-muted-foreground">
        {["accepted", "tentative", "declined", "pending"].map((k) => counts[k] > 0 && (
          <span key={k} className="inline-flex items-center gap-1">
            <span className={cn("h-1.5 w-1.5 rounded-full", RESPONSE_STYLES[k].dot)} />
            {counts[k]} {RESPONSE_STYLES[k].label.toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function EventDetailsDialog({ event, open, onOpenChange, onEdit, onDuplicate, onChanged, user, can }) {
  const [busy, setBusy] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (!event) return null;
  const style = categoryStyle(event.category);
  const canEdit = canModifyEvent(event, user, can, "calendar.edit_any");
  const canDelete = canModifyEvent(event, user, can, "calendar.delete_any");
  const canCreate = can("calendar.create");
  const link = safeUrl(event.meeting_link);
  const visibility = VISIBILITY.find((v) => v.key === event.visibility);
  const cancelled = event.status === "cancelled";
  const me = event.participants?.find((p) => p.id === user?.id);
  const now = new Date();
  const relative = cancelled ? null : relativeStart(event, now);
  const joinable = link && !cancelled && eventEnd(event) > now
    && eventStart(event) - now <= JOIN_WINDOW_MINUTES * 60000;

  const setStatus = async (status) => {
    setBusy(status);
    try {
      const { data } = await api.patch(`/calendar/events/${event.id}`, { status });
      toast.success(status === "cancelled" ? "Event cancelled. Participants were notified." : "Event restored");
      onChanged(data);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const respond = async (response) => {
    setBusy(`rsvp-${response}`);
    try {
      const { data } = await api.post(`/calendar/events/${event.id}/rsvp`, { response });
      toast.success(response === "declined" ? "Declined — the organiser was told" : `Replied: ${RESPONSE_STYLES[response].label}`);
      onChanged(data);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy("delete");
    try {
      await api.delete(`/calendar/events/${event.id}`);
      toast.success("Event deleted");
      setConfirmDelete(false);
      onChanged(null);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const copyLink = async () => {
    const url = `${window.location.origin}/calendar?event=${event.id}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link copied");
    } catch {
      toast.error("Couldn't copy the link");
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg max-h-[92vh] overflow-y-auto scrollbar-thin p-0 gap-0" data-testid="calendar-event-details">
          <div className={cn("h-1.5 w-full rounded-t-lg", style.dot)} />
          <div className="p-6 pb-4 space-y-4">
            <DialogHeader className="space-y-1.5">
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground pr-6">
                <span className={cn("h-2 w-2 rounded-full", style.dot)} />
                {event.category}
                {event.status !== "confirmed" && <StatusPill status={event.status} />}
                {relative && (
                  <span className={cn(
                    "ml-auto normal-case tracking-normal text-[11.5px] font-medium rounded-full px-2 py-0.5",
                    relative === "Happening now" ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary",
                  )}>
                    {relative}
                  </span>
                )}
              </div>
              <DialogTitle className={cn("font-display text-xl tracking-tight text-left", cancelled && "line-through text-muted-foreground")}>
                {event.title}
              </DialogTitle>
              <DialogDescription className="sr-only">Event details</DialogDescription>
            </DialogHeader>

            {joinable && (
              <Button asChild className="w-full gap-2" data-testid="calendar-join-meeting">
                <a href={link} target="_blank" rel="noopener noreferrer"><Video className="h-4 w-4" /> Join meeting now</a>
              </Button>
            )}

            {me && !cancelled && (
              <div className="rounded-lg border border-border p-3" data-testid="calendar-rsvp">
                <div className="text-[12px] text-muted-foreground mb-2">
                  {me.response === "pending" ? "You're invited — are you going?" : "Your reply"}
                </div>
                <div className="grid grid-cols-3 gap-1.5">
                  {RSVP_OPTIONS.map((o) => {
                    const Icon = RSVP_ICONS[o.key];
                    const active = me.response === o.key;
                    return (
                      <Button
                        key={o.key}
                        type="button"
                        size="sm"
                        variant={active ? "default" : "outline"}
                        disabled={!!busy}
                        onClick={() => !active && respond(o.key)}
                        aria-pressed={active}
                        className="gap-1.5"
                        data-testid={`calendar-rsvp-${o.key}`}
                      >
                        {busy === `rsvp-${o.key}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
                        {o.label}
                      </Button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="space-y-3.5">
              <Row icon={Clock}>
                <div className="text-foreground">{formatEventDate(event)}</div>
                <div className="text-muted-foreground text-[12.5px]">{formatEventTime(event)}</div>
              </Row>
              {event.location && <Row icon={MapPin}>{event.location}</Row>}
              {event.meeting_link && !joinable && (
                <Row icon={Video}>
                  {link ? (
                    <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline break-all">
                      {new URL(link).hostname.replace(/^www\./, "")} <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    <span className="break-all">{event.meeting_link}</span>
                  )}
                </Row>
              )}
              <Row icon={User}>
                Organised by <span className="font-medium">{event.organizer_id === user?.id ? "you" : event.organizer_name || "Unknown"}</span>
              </Row>
              {event.participants?.length > 0 && (
                <Row icon={Users}>
                  <div className="text-muted-foreground text-[12.5px] mb-1.5">
                    {event.participants.length} participant{event.participants.length === 1 ? "" : "s"}
                  </div>
                  <ResponseSummary event={event} />
                  <div className="flex flex-wrap gap-1.5">
                    {event.participants.map((p) => {
                      const rs = RESPONSE_STYLES[p.response || "pending"];
                      return (
                        <span key={p.id} title={rs.label}
                              className="inline-flex items-center gap-1.5 rounded-full border border-border pl-0.5 pr-2.5 py-0.5 text-[12px]">
                          <span className="relative">
                            <Avatar className="h-5 w-5">
                              <AvatarImage src={p.photo || undefined} alt="" />
                              <AvatarFallback className="text-[9px]">{initials(p.name)}</AvatarFallback>
                            </Avatar>
                            <span className={cn("absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full ring-2 ring-background", rs.dot)} />
                          </span>
                          {p.id === user?.id ? "You" : p.name}
                          {p.response === "declined" && <span className="sr-only">(declined)</span>}
                        </span>
                      );
                    })}
                  </div>
                </Row>
              )}
              {reminderLabel(event.reminder_minutes) && (
                <Row icon={Bell}>Reminder {reminderLabel(event.reminder_minutes).toLowerCase()}</Row>
              )}
              {visibility && (
                <Row icon={Eye}>
                  {visibility.label}
                  {event.visibility === "department" && event.department ? ` · ${event.department}` : ""}
                </Row>
              )}
              {event.description && (
                <p className="text-[13.5px] leading-relaxed text-foreground/90 whitespace-pre-wrap border-t border-border pt-3.5">
                  {event.description}
                </p>
              )}
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-2 sm:justify-between border-t border-border px-6 py-3 bg-muted/30">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-1.5" disabled={!!busy} data-testid="calendar-event-more">
                  <MoreHorizontal className="h-4 w-4" /> More
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-52">
                <DropdownMenuItem onSelect={copyLink}><Link2 className="h-4 w-4 mr-2" /> Copy link</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => downloadIcs(event)}><Download className="h-4 w-4 mr-2" /> Add to my calendar (.ics)</DropdownMenuItem>
                {canCreate && (
                  <DropdownMenuItem onSelect={() => onDuplicate(event)}><Copy className="h-4 w-4 mr-2" /> Duplicate</DropdownMenuItem>
                )}
                {canDelete && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onSelect={() => setConfirmDelete(true)} className="text-destructive focus:text-destructive">
                      <Trash2 className="h-4 w-4 mr-2" /> Delete
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            {canEdit && (
              <div className="flex gap-2">
                <Button variant="outline" size="sm" className="gap-1.5" disabled={!!busy}
                        onClick={() => setStatus(cancelled ? "confirmed" : "cancelled")}>
                  {busy === "cancelled" || busy === "confirmed"
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : cancelled ? <RotateCcw className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
                  {cancelled ? "Restore" : "Cancel event"}
                </Button>
                <Button size="sm" className="gap-1.5" onClick={() => onEdit(event)} disabled={!!busy} data-testid="calendar-edit-event">
                  <Pencil className="h-4 w-4" /> Edit
                </Button>
              </div>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{event.title}”?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the event for everyone. To keep a record, cancel it instead.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy === "delete"}>Keep event</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); remove(); }}
              disabled={busy === "delete"}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {busy === "delete" && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
              Delete event
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
