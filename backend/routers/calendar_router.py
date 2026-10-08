"""Calendar events: CRUD plus the retrieval views the Calendar module needs —
single event, date range, month, week, day, agenda, participant filtering,
search, RSVP and participant availability (free/busy).

Storage: `calendar_events`, with start_time / end_time stored as BSON datetimes
(UTC) so range queries compare instants, not strings. Every list is sorted by
start_time, then end_time, then _id, which keeps pagination stable.

Range semantics are half-open: an event is inside [start, end) when it starts
before `end` and ends after `start`. Zero-length events (start == end) count
when they start inside the range.
"""
# No `from __future__ import annotations` here: FastAPI resolves the class-based
# dependencies below (EventFilters, Pagination) from runtime annotations.
import asyncio
import calendar as pycal
import logging
import math
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from db import get_db
from auth_utils import get_current_user
from models import UserPublic
from models_part2 import CalendarEventIn, CalendarEventPatch, CalendarRsvpIn, EventCategory
from hub_utils import serialize, utc_iso, log_activity, notify
from email_utils import send_calendar_email
from permissions import can

router = APIRouter(prefix="/calendar", tags=["calendar"])
logger = logging.getLogger("wavygo.calendar")

DEFAULT_TZ = "Asia/Kolkata"
MAX_RANGE_DAYS = 366
MAX_VIEW_EVENTS = 2000
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
SORT = [("start_time", 1), ("end_time", 1), ("_id", 1)]
USER_FIELDS = {"name": 1, "photo": 1, "role": 1}
NON_NULLABLE = ("title", "start_time", "end_time", "all_day", "category", "visibility", "status")
WEEK_START = {"monday": 0, "sunday": 6}
REMINDER_INTERVAL_SECONDS = float(os.environ.get("CALENDAR_REMINDER_INTERVAL_SECONDS", "60"))
# Zero-length events (reminders, deadlines) still get their reminder shortly after start.
REMINDER_GRACE = timedelta(minutes=10)
INTERNAL_FIELDS = ("reminder_at", "reminder_sent", "responses")
MAX_SEARCH_LENGTH = 100
MAX_AVAILABILITY_USERS = 50
MAX_AVAILABILITY_DAYS = 31


# ------------------------- time helpers -------------------------

def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, f"Unknown timezone: {tz}")


def _as_utc(dt: datetime) -> datetime:
    """Mongo returns naive UTC datetimes; make the zone explicit."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _local_midnight(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, zone).astimezone(timezone.utc)


def _parse_instant(value: str, zone: ZoneInfo, field: str) -> datetime:
    """YYYY-MM-DD means local midnight in `zone`; a datetime without offset is local to `zone`."""
    value = value.strip()
    # An unencoded "+05:30" in a query string arrives as " 05:30".
    value = re.sub(r" (\d{2}:?\d{2})$", r"+\1", value)
    try:
        if len(value) == 10:
            return _local_midnight(date.fromisoformat(value), zone)
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{field} must be YYYY-MM-DD or an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(timezone.utc)


def _parse_date(value: Optional[str], zone: ZoneInfo, field: str = "date") -> date:
    if not value:
        return datetime.now(zone).date()
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(422, f"{field} must be YYYY-MM-DD")


# ------------------------- query helpers -------------------------

def _event_oid(event_id: str) -> ObjectId:
    if not ObjectId.is_valid(event_id):
        raise HTTPException(404, "Event not found")
    return ObjectId(event_id)


def _visibility_filter(current: UserPublic) -> Optional[dict]:
    """Founder/Admin see everything. Everyone else sees public events, their
    department's events, and events they organise or are invited to."""
    if can(current.role, "calendar.view_all"):
        return None
    clauses = [
        {"visibility": "public"},
        {"organizer_id": current.id},
        {"participant_ids": current.id},
    ]
    if current.department:
        clauses.append({"visibility": "department", "department": current.department})
    return {"$or": clauses}


def _overlap_filter(start: datetime, end: datetime) -> dict:
    return {
        "start_time": {"$lt": end},
        "$or": [{"end_time": {"$gt": start}}, {"start_time": {"$gte": start}}],
    }


def _resolve_user_id(value: Optional[str], current: UserPublic, field: str) -> Optional[str]:
    if not value:
        return None
    if value == "me":
        return current.id
    if not ObjectId.is_valid(value):
        raise HTTPException(422, f"{field} must be a user id or 'me'")
    return value


def _build_query(current: UserPublic, start: datetime, end: datetime, filters: "EventFilters") -> dict:
    clauses = [_overlap_filter(start, end)]
    visibility = _visibility_filter(current)
    if visibility:
        clauses.append(visibility)
    if filters.category:
        clauses.append({"category": filters.category})
    participant_id = _resolve_user_id(filters.participant_id, current, "participant_id")
    if participant_id:
        clauses.append({"$or": [{"participant_ids": participant_id}, {"organizer_id": participant_id}]})
    organizer_id = _resolve_user_id(filters.organizer_id, current, "organizer_id")
    if organizer_id:
        clauses.append({"organizer_id": organizer_id})
    if filters.q:
        pattern = {"$regex": re.escape(filters.q), "$options": "i"}
        clauses.append({"$or": [{"title": pattern}, {"location": pattern}, {"description": pattern}]})
    if not filters.include_cancelled:
        clauses.append({"status": {"$ne": "cancelled"}})
    return {"$and": clauses}


class EventFilters:
    """Filters shared by every list endpoint."""

    def __init__(
        self,
        category: Optional[EventCategory] = None,
        participant_id: Optional[str] = Query(None, description="User id or 'me'. Matches organiser or participant."),
        organizer_id: Optional[str] = Query(None, description="User id or 'me'."),
        include_cancelled: bool = False,
        q: Optional[str] = Query(None, max_length=MAX_SEARCH_LENGTH,
                                 description="Case-insensitive search in title, location and description."),
        tz: str = Query(DEFAULT_TZ, description="IANA timezone used to interpret dates and day boundaries."),
    ):
        self.category = category
        self.participant_id = participant_id
        self.organizer_id = organizer_id
        self.include_cancelled = include_cancelled
        self.q = (q or "").strip() or None
        self.zone = _zone(tz)


class Pagination:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    ):
        self.page = page
        self.page_size = page_size


# ------------------------- serialisation -------------------------

async def _serialize_events(db, docs: list[dict]) -> list[dict]:
    """Serialise events with organiser/participant names, resolving all users in one query."""
    user_ids = {
        uid
        for d in docs
        for uid in (d.get("organizer_id"), *d.get("participant_ids", []))
        if uid and ObjectId.is_valid(uid)
    }
    users = {}
    if user_ids:
        async for u in db.users.find({"_id": {"$in": [ObjectId(u) for u in user_ids]}}, USER_FIELDS):
            users[str(u["_id"])] = u

    out = []
    for d in docs:
        event = serialize(d, drop=("password_hash", *INTERNAL_FIELDS))
        event["start_time"] = _as_utc(d["start_time"]).isoformat()
        event["end_time"] = _as_utc(d["end_time"]).isoformat()
        organizer = users.get(d.get("organizer_id"))
        event["organizer_name"] = organizer["name"] if organizer else None
        responses = d.get("responses") or {}
        event["participants"] = [
            {
                "id": pid, "name": users[pid]["name"], "photo": users[pid].get("photo"), "role": users[pid].get("role"),
                "response": responses.get(pid, "pending"),
            }
            for pid in d.get("participant_ids", [])
            if pid in users
        ]
        out.append(event)
    return out


async def _paginate(db, query: dict, pagination: Pagination) -> dict:
    total = await db.calendar_events.count_documents(query)
    skip = (pagination.page - 1) * pagination.page_size
    docs = await (
        db.calendar_events.find(query).sort(SORT).skip(skip).limit(pagination.page_size).to_list(pagination.page_size)
    )
    return {
        "items": await _serialize_events(db, docs),
        "page": pagination.page,
        "page_size": pagination.page_size,
        "total": total,
        "total_pages": math.ceil(total / pagination.page_size),
        "has_more": skip + len(docs) < total,
    }


def _bucket_by_day(docs: list[dict], first_day: date, last_day: date, zone: ZoneInfo) -> list[dict]:
    """Map each local day in the view to the ids of events touching it (multi-day events repeat)."""
    buckets = {first_day + timedelta(days=i): [] for i in range((last_day - first_day).days + 1)}
    for d in docs:
        start, end = _as_utc(d["start_time"]), _as_utc(d["end_time"])
        start_day = start.astimezone(zone).date()
        # End is exclusive: an event ending at midnight does not spill into the next day.
        end_day = (end - timedelta(microseconds=1)).astimezone(zone).date() if end > start else start_day
        day = max(start_day, first_day)
        while day <= min(end_day, last_day):
            buckets[day].append(str(d["_id"]))
            day += timedelta(days=1)
    return [{"date": day.isoformat(), "event_ids": ids} for day, ids in buckets.items()]


async def _view(db, current: UserPublic, view: str, first_day: date, last_day: date, filters: EventFilters) -> dict:
    zone = filters.zone
    start = _local_midnight(first_day, zone)
    end = _local_midnight(last_day + timedelta(days=1), zone)
    query = _build_query(current, start, end, filters)
    docs = await db.calendar_events.find(query).sort(SORT).limit(MAX_VIEW_EVENTS + 1).to_list(MAX_VIEW_EVENTS + 1)
    truncated = len(docs) > MAX_VIEW_EVENTS
    docs = docs[:MAX_VIEW_EVENTS]
    return {
        "view": view,
        "timezone": zone.key,
        "range": {
            "first_day": first_day.isoformat(),
            "last_day": last_day.isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "total": len(docs),
        "truncated": truncated,
        "events": await _serialize_events(db, docs),
        "days": _bucket_by_day(docs, first_day, last_day, zone),
    }


def _week_bounds(day: date, week_start: str) -> tuple[date, date]:
    first = day - timedelta(days=(day.weekday() - WEEK_START[week_start]) % 7)
    return first, first + timedelta(days=6)


async def ensure_indexes(db) -> None:
    """Indexes backing the range, participant and organiser queries. Idempotent."""
    await db.calendar_events.create_index([("start_time", 1), ("end_time", 1), ("_id", 1)])
    await db.calendar_events.create_index("participant_ids")
    await db.calendar_events.create_index("organizer_id")
    await db.calendar_events.create_index([("reminder_sent", 1), ("reminder_at", 1)])


# ------------------------- write helpers -------------------------

async def _validate_participants(db, ids: list[str]) -> None:
    invalid = [i for i in ids if not ObjectId.is_valid(i)]
    if invalid:
        raise HTTPException(422, f"Invalid participant ids: {', '.join(invalid)}")
    if not ids:
        return
    found = {str(u["_id"]) async for u in db.users.find({"_id": {"$in": [ObjectId(i) for i in ids]}}, {"_id": 1})}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(422, f"Unknown participant ids: {', '.join(missing)}")


def _can_modify(current: UserPublic, event: dict, action: str) -> bool:
    return event.get("organizer_id") == current.id or can(current.role, action)


def _when(dt: datetime) -> str:
    return _as_utc(dt).astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d %b %Y, %I:%M %p")


def _event_link(event: dict) -> str:
    return f"/calendar?event={event['_id']}"


# Emails go out on worker threads (the Brevo client is blocking); keep references until they finish.
_email_tasks: set = set()


def _email_when(doc: dict) -> str:
    zone = ZoneInfo(DEFAULT_TZ)
    start = _as_utc(doc["start_time"]).astimezone(zone)
    if doc.get("all_day"):
        last = (_as_utc(doc["end_time"]) - timedelta(microseconds=1)).astimezone(zone)
        if last.date() <= start.date():
            return start.strftime("%a %d %b %Y · All day")
        return f"{start.strftime('%a %d %b')} – {last.strftime('%a %d %b %Y')} · All day"
    end = _as_utc(doc["end_time"]).astimezone(zone)
    tail = end.strftime("%I:%M %p") if end.date() == start.date() else end.strftime("%d %b, %I:%M %p")
    return f"{start.strftime('%a %d %b %Y, %I:%M %p')} – {tail} IST"


async def _email_many(db, user_ids, kind: str, doc: dict, actor: str = "", when_phrase: str = "starts soon") -> None:
    """Email active users about an event without holding up the request."""
    ids = [ObjectId(u) for u in dict.fromkeys(user_ids) if u and ObjectId.is_valid(u)]
    if not ids:
        return
    query = {"_id": {"$in": ids}, "status": {"$ne": "deactivated"}, "is_active": {"$ne": False}}
    async for u in db.users.find(query, {"email": 1, "name": 1}):
        email = (u.get("email") or "").strip()
        if not email:
            continue
        task = asyncio.create_task(asyncio.to_thread(
            send_calendar_email,
            recipient_email=email,
            recipient_name=u.get("name") or "",
            kind=kind,
            title=doc["title"],
            when=_email_when(doc),
            actor=actor,
            location=doc.get("location"),
            meeting_link=doc.get("meeting_link"),
            event_id=str(doc["_id"]),
            when_phrase=when_phrase,
        ))
        _email_tasks.add(task)
        task.add_done_callback(_email_tasks.discard)


async def _notify_many(db, user_ids, title: str, body: str, link: str = "/calendar") -> None:
    for uid in user_ids:
        await notify(db, uid, title, body, kind="info", link=link)


def _reminder_fields(start: datetime, minutes: Optional[int]) -> dict:
    """Schedule (or clear) the reminder; the reminder loop sends it once reminder_at passes."""
    if minutes is None:
        return {"reminder_at": None, "reminder_sent": False}
    return {"reminder_at": start - timedelta(minutes=minutes), "reminder_sent": False}


def _humanize_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        hours = round(minutes / 60)
        return f"{hours} hour{'s' if hours != 1 else ''}"
    days = round(minutes / (24 * 60))
    return f"{days} day{'s' if days != 1 else ''}"


async def send_due_reminders(db, now: Optional[datetime] = None) -> int:
    """Notify organiser + participants of every event whose reminder time has passed.
    Each event is claimed with an atomic update, so several workers never send twice."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    while True:
        doc = await db.calendar_events.find_one_and_update(
            {
                "reminder_sent": False,
                "reminder_at": {"$lte": now},
                "status": {"$ne": "cancelled"},
                "$or": [{"end_time": {"$gt": now}}, {"start_time": {"$gt": now - REMINDER_GRACE}}],
            },
            {"$set": {"reminder_sent": True}},
        )
        if not doc:
            return sent
        minutes = math.ceil((_as_utc(doc["start_time"]) - now).total_seconds() / 60)
        when = f"starts in {_humanize_minutes(minutes)}" if minutes >= 1 else "is starting now"
        recipients = [uid for uid in dict.fromkeys([doc.get("organizer_id"), *doc.get("participant_ids", [])]) if uid]
        await _notify_many(db, recipients, "Event reminder", f"{doc['title']} {when} · {_when(doc['start_time'])}",
                           link=_event_link(doc))
        await _email_many(db, recipients, "reminder", doc, when_phrase=when)
        sent += 1


async def reminder_loop() -> None:
    """Background task started with the app; checks for due reminders every interval."""
    while True:
        try:
            await send_due_reminders(get_db())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Calendar reminder pass failed")
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)


# ------------------------- write endpoints -------------------------

@router.post("/events", status_code=201)
async def create_event(payload: CalendarEventIn, current: UserPublic = Depends(get_current_user)):
    if not can(current.role, "calendar.create"):
        raise HTTPException(403, "You cannot create calendar events")
    db = get_db()
    doc = payload.model_dump()
    if doc["visibility"] == "department":
        doc["department"] = doc.get("department") or current.department
        if not doc["department"]:
            raise HTTPException(422, "department is required for department-visible events")
    await _validate_participants(db, doc["participant_ids"])

    doc["start_time"] = _as_utc(doc["start_time"])
    doc["end_time"] = _as_utc(doc["end_time"])
    doc["organizer_id"] = current.id
    doc.update(_reminder_fields(doc["start_time"], doc["reminder_minutes"]))
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    res = await db.calendar_events.insert_one(doc)
    doc["_id"] = res.inserted_id

    await log_activity(db, current, "Scheduled event", "Calendar", target=doc["title"])
    invitees = [p for p in doc["participant_ids"] if p != current.id]
    await _notify_many(
        db, invitees, "Event invitation",
        f"{current.name} invited you to {doc['title']} on {_when(doc['start_time'])}",
        link=_event_link(doc),
    )
    if doc["status"] != "cancelled":
        await _email_many(db, invitees, "invite", doc, actor=current.name)
    return (await _serialize_events(db, [doc]))[0]


@router.patch("/events/{event_id}")
async def update_event(event_id: str, payload: CalendarEventPatch, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    _id = _event_oid(event_id)
    existing = await db.calendar_events.find_one({"_id": _id})
    if not existing:
        raise HTTPException(404, "Event not found")
    if not _can_modify(current, existing, "calendar.edit_any"):
        raise HTTPException(403, "Only the organiser can edit this event")

    updates = payload.model_dump(exclude_unset=True)
    nulled = [k for k in NON_NULLABLE if k in updates and updates[k] is None]
    if nulled:
        raise HTTPException(422, f"Fields cannot be null: {', '.join(nulled)}")
    for field in ("start_time", "end_time"):
        if field in updates:
            updates[field] = _as_utc(updates[field])

    start = updates.get("start_time", _as_utc(existing["start_time"]))
    end = updates.get("end_time", _as_utc(existing["end_time"]))
    if end < start:
        raise HTTPException(422, "end_time must not be before start_time")
    if updates.get("visibility", existing.get("visibility")) == "department":
        updates["department"] = updates.get("department") or existing.get("department") or current.department
        if not updates["department"]:
            raise HTTPException(422, "department is required for department-visible events")
    if "participant_ids" in updates:
        await _validate_participants(db, updates["participant_ids"])
    rescheduled = start != _as_utc(existing["start_time"]) or end != _as_utc(existing["end_time"])
    responses = existing.get("responses") or {}
    if rescheduled and responses:
        # A new time needs fresh answers: people who accepted the old slot may not be free.
        updates["responses"] = {}
    elif "participant_ids" in updates and responses:
        kept = {uid: r for uid, r in responses.items() if uid in updates["participant_ids"]}
        if kept != responses:
            updates["responses"] = kept
    if "start_time" in updates or "reminder_minutes" in updates:
        minutes = updates["reminder_minutes"] if "reminder_minutes" in updates else existing.get("reminder_minutes")
        # The edit form always resends start_time and reminder_minutes; only re-arm the reminder when
        # one of them actually changed, or every edit (even a title fix) would send the reminder again.
        if start != _as_utc(existing["start_time"]) or minutes != existing.get("reminder_minutes"):
            updates.update(_reminder_fields(start, minutes))
    if not updates:
        return (await _serialize_events(db, [existing]))[0]

    updates["updated_at"] = utc_iso()
    await db.calendar_events.update_one({"_id": _id}, {"$set": updates})
    doc = await db.calendar_events.find_one({"_id": _id})

    await log_activity(db, current, "Updated event", "Calendar", target=doc["title"])
    previous = set(existing.get("participant_ids", []))
    added = [p for p in doc.get("participant_ids", []) if p not in previous and p != current.id]
    await _notify_many(db, added, "Event invitation",
                       f"{current.name} invited you to {doc['title']} on {_when(doc['start_time'])}",
                       link=_event_link(doc))
    if doc.get("status") != "cancelled":
        await _email_many(db, added, "invite", doc, actor=current.name)
    others = [p for p in doc.get("participant_ids", []) if p != current.id and p not in added]
    if updates.get("status") == "cancelled" and existing.get("status") != "cancelled":
        await _notify_many(db, others, "Event cancelled", f"{current.name} cancelled {doc['title']}",
                           link=_event_link(doc))
        await _email_many(db, others, "cancelled", doc, actor=current.name)
    elif rescheduled and doc.get("status") != "cancelled":
        await _notify_many(db, others, "Event rescheduled",
                           f"{current.name} moved {doc['title']} to {_when(doc['start_time'])}",
                           link=_event_link(doc))
        await _email_many(db, others, "rescheduled", doc, actor=current.name)
    return (await _serialize_events(db, [doc]))[0]


@router.post("/events/{event_id}/rsvp")
async def rsvp_event(event_id: str, payload: CalendarRsvpIn, current: UserPublic = Depends(get_current_user)):
    """An invited participant accepts, declines or tentatively accepts; the organiser is told."""
    db = get_db()
    _id = _event_oid(event_id)
    existing = await db.calendar_events.find_one({"_id": _id})
    if not existing or current.id not in existing.get("participant_ids", []):
        # Same response as an unknown id, so invitations cannot be probed.
        raise HTTPException(404, "Event not found")
    if existing.get("status") == "cancelled":
        raise HTTPException(409, "This event was cancelled")
    previous = (existing.get("responses") or {}).get(current.id)
    await db.calendar_events.update_one({"_id": _id}, {"$set": {f"responses.{current.id}": payload.response}})
    doc = await db.calendar_events.find_one({"_id": _id})
    organizer = existing.get("organizer_id")
    if previous != payload.response and organizer and organizer != current.id:
        verb = {"accepted": "accepted", "declined": "declined", "tentative": "might attend"}[payload.response]
        await notify(db, organizer, "Event response", f"{current.name} {verb} {doc['title']}",
                     kind="info", link=_event_link(doc))
    return (await _serialize_events(db, [doc]))[0]


@router.delete("/events/{event_id}")
async def delete_event(event_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    _id = _event_oid(event_id)
    existing = await db.calendar_events.find_one({"_id": _id})
    if not existing:
        raise HTTPException(404, "Event not found")
    if not _can_modify(current, existing, "calendar.delete_any"):
        raise HTTPException(403, "Only the organiser can delete this event")
    await db.calendar_events.delete_one({"_id": _id})
    await log_activity(db, current, "Deleted event", "Calendar", target=existing["title"])
    return {"ok": True}


# ------------------------- read endpoints -------------------------

@router.get("/invitees")
async def list_invitees(current: UserPublic = Depends(get_current_user)):
    """Active users that can be invited to an event — the participant picker's source.
    Returns only what the picker shows, so it is safe for every role."""
    db = get_db()
    query = {"status": {"$ne": "deactivated"}, "is_active": {"$ne": False}}
    fields = {"name": 1, "photo": 1, "role": 1, "department": 1, "designation": 1}
    docs = await db.users.find(query, fields).sort("name", 1).to_list(1000)
    return [
        {
            "id": str(d["_id"]),
            "name": d.get("name"),
            "photo": d.get("photo"),
            "role": d.get("role"),
            "department": d.get("department"),
            "designation": d.get("designation"),
        }
        for d in docs
    ]


@router.get("/availability")
async def availability(
    user_ids: str = Query(..., description="Comma-separated user ids ('me' allowed)."),
    start: str = Query(..., description="Range start: YYYY-MM-DD or ISO 8601 datetime."),
    end: str = Query(..., description="Range end: YYYY-MM-DD or ISO 8601 datetime (exclusive)."),
    exclude_event_id: Optional[str] = Query(None, description="Ignore this event, e.g. the one being edited."),
    tz: str = Query(DEFAULT_TZ),
    current: UserPublic = Depends(get_current_user),
):
    """Free/busy for the given people: timed events they organise or were invited to
    (and did not decline). Titles are shown only for events the caller can see;
    anything else is reported as a plain "Busy" block."""
    zone = _zone(tz)
    range_start = _parse_instant(start, zone, "start")
    range_end = _parse_instant(end, zone, "end")
    if range_end <= range_start:
        raise HTTPException(422, "end must be after start")
    if range_end - range_start > timedelta(days=MAX_AVAILABILITY_DAYS):
        raise HTTPException(422, f"Range cannot exceed {MAX_AVAILABILITY_DAYS} days")
    ids = list(dict.fromkeys(
        _resolve_user_id(v.strip(), current, "user_ids") for v in user_ids.split(",") if v.strip()
    ))
    if not ids:
        raise HTTPException(422, "user_ids is required")
    if len(ids) > MAX_AVAILABILITY_USERS:
        raise HTTPException(422, f"At most {MAX_AVAILABILITY_USERS} people at a time")

    clauses = [
        _overlap_filter(range_start, range_end),
        {"status": {"$ne": "cancelled"}},
        {"all_day": {"$ne": True}},
        {"$or": [{"organizer_id": {"$in": ids}}, {"participant_ids": {"$in": ids}}]},
    ]
    if exclude_event_id and ObjectId.is_valid(exclude_event_id):
        clauses.append({"_id": {"$ne": ObjectId(exclude_event_id)}})
    db = get_db()
    docs = await db.calendar_events.find({"$and": clauses}).sort(SORT).limit(MAX_VIEW_EVENTS).to_list(MAX_VIEW_EVENTS)

    visible = {d["_id"] for d in docs}
    visibility = _visibility_filter(current)
    if visibility and docs:
        query = {"$and": [{"_id": {"$in": list(visible)}}, visibility]}
        visible = {d["_id"] async for d in db.calendar_events.find(query, {"_id": 1})}

    busy = {uid: [] for uid in ids}
    for d in docs:
        responses = d.get("responses") or {}
        people = {d.get("organizer_id"), *d.get("participant_ids", [])}
        shown = d["_id"] in visible
        for uid in ids:
            if uid not in people or responses.get(uid) == "declined":
                continue
            busy[uid].append({
                "start": _as_utc(d["start_time"]).isoformat(),
                "end": _as_utc(d["end_time"]).isoformat(),
                "title": d["title"] if shown else "Busy",
                "event_id": str(d["_id"]) if shown else None,
                "tentative": d.get("status") == "tentative" or responses.get(uid) == "tentative",
            })
    return {
        "range": {"start": range_start.isoformat(), "end": range_end.isoformat()},
        "users": [{"user_id": uid, "busy": busy[uid]} for uid in ids],
    }


@router.get("/events")
async def list_events(
    start: str = Query(..., description="Range start: YYYY-MM-DD or ISO 8601 datetime (inclusive)."),
    end: str = Query(..., description="Range end: YYYY-MM-DD or ISO 8601 datetime (exclusive)."),
    filters: EventFilters = Depends(),
    pagination: Pagination = Depends(),
    current: UserPublic = Depends(get_current_user),
):
    """Events overlapping [start, end), sorted by start_time, paginated."""
    range_start = _parse_instant(start, filters.zone, "start")
    range_end = _parse_instant(end, filters.zone, "end")
    if range_end <= range_start:
        raise HTTPException(422, "end must be after start")
    if range_end - range_start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(422, f"Range cannot exceed {MAX_RANGE_DAYS} days")
    db = get_db()
    return await _paginate(db, _build_query(current, range_start, range_end, filters), pagination)


@router.get("/events/{event_id}")
async def get_event(event_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    query = {"_id": _event_oid(event_id)}
    visibility = _visibility_filter(current)
    if visibility:
        query = {"$and": [query, visibility]}
    doc = await db.calendar_events.find_one(query)
    if not doc:
        # Same response for missing and not-visible, so ids cannot be probed.
        raise HTTPException(404, "Event not found")
    return (await _serialize_events(db, [doc]))[0]


@router.get("/month")
async def month_view(
    year: Optional[int] = Query(None, ge=1970, le=9999),
    month: Optional[int] = Query(None, ge=1, le=12),
    full_weeks: bool = Query(False, description="Pad to whole weeks, as a month grid shows."),
    week_start: Literal["monday", "sunday"] = "monday",
    filters: EventFilters = Depends(),
    current: UserPublic = Depends(get_current_user),
):
    today = datetime.now(filters.zone).date()
    year, month = year or today.year, month or today.month
    first_day = date(year, month, 1)
    last_day = date(year, month, pycal.monthrange(year, month)[1])
    if full_weeks:
        first_day = _week_bounds(first_day, week_start)[0]
        last_day = _week_bounds(last_day, week_start)[1]
    return await _view(get_db(), current, "month", first_day, last_day, filters)


@router.get("/week")
async def week_view(
    date_: Optional[str] = Query(None, alias="date", description="Any day in the week, YYYY-MM-DD. Defaults to today."),
    week_start: Literal["monday", "sunday"] = "monday",
    filters: EventFilters = Depends(),
    current: UserPublic = Depends(get_current_user),
):
    first_day, last_day = _week_bounds(_parse_date(date_, filters.zone), week_start)
    return await _view(get_db(), current, "week", first_day, last_day, filters)


@router.get("/day")
async def day_view(
    date_: Optional[str] = Query(None, alias="date", description="YYYY-MM-DD. Defaults to today."),
    filters: EventFilters = Depends(),
    current: UserPublic = Depends(get_current_user),
):
    day = _parse_date(date_, filters.zone)
    return await _view(get_db(), current, "day", day, day, filters)


@router.get("/agenda")
async def agenda(
    start: Optional[str] = Query(None, description="Agenda start, YYYY-MM-DD or ISO 8601 datetime. Defaults to the start of today in `tz`."),
    days: int = Query(30, ge=1, le=MAX_RANGE_DAYS),
    filters: EventFilters = Depends(),
    pagination: Pagination = Depends(),
    current: UserPublic = Depends(get_current_user),
):
    """Events for the next `days` days, paginated. The default start is local midnight today
    (not "now"), so meetings earlier today are still listed under today."""
    if start:
        range_start = _parse_instant(start, filters.zone, "start")
    else:
        range_start = _local_midnight(datetime.now(filters.zone).date(), filters.zone)
    range_end = range_start + timedelta(days=days)
    db = get_db()
    result = await _paginate(db, _build_query(current, range_start, range_end, filters), pagination)
    result["range"] = {"start": range_start.isoformat(), "end": range_end.isoformat()}
    result["timezone"] = filters.zone.key
    return result
