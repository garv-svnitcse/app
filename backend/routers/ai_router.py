from __future__ import annotations
"""WavyGo AI — Claude-powered assistant (mounted at /api/ai).

Conversations live in `ai_conversations` and belong to exactly one user. A message is
answered over Server-Sent Events: the model streams text and may call read-only tools
over company data. Every tool reuses the visibility rules of the module router that owns
the data (tasks, opportunities, calendar, employees, dashboard, notifications), so the
assistant can never read anything the caller could not open in the app.

Environment:
  ANTHROPIC_API_KEY      required; without it the module reports `configured: false`.
  ANTHROPIC_MODEL        optional model override (default claude-opus-5).
  ANTHROPIC_BASE_URL     optional, read by the SDK (used by the local test mock).
  WAVYGO_AI_TEST_TOOLS   "1" exposes POST /api/ai/_test/tools/{name} for scoping tests.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

import anthropic
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth_utils import get_current_user
from db import get_db
from hub_utils import log_activity, role_notification_filter, utc_iso
from models import UserPublic
from permissions import can, can_view_module
from routers.calendar_router import _as_utc, _overlap_filter, _visibility_filter
from routers.dashboard_router import _marketplace_section, _parse_due, _windows
from routers.opportunities_router import _lakhs, _scope_filter as _opp_scope_filter
from routers.tasks_router import _task_filter_for

router = APIRouter(prefix="/ai", tags=["wavygo-ai"])
logger = logging.getLogger("wavygo.ai")

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_MODEL = "claude-opus-5"
# Claude Opus 5 supports server-side refusal fallbacks; other overrides run without them.
FALLBACK_MODELS = {"claude-opus-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORT = "medium"                  # chat + light tool use; high adds latency for little gain here
MAX_OUTPUT_TOKENS = 16000
MAX_TOOL_ROUNDS = 6                # model turns that may call tools before a forced text answer
API_TIMEOUT = anthropic.Timeout(120.0, connect=10.0)
TURN_DEADLINE_SECONDS = 240
MAX_MESSAGE_CHARS = 4000
MAX_TITLE_CHARS = 120
MAX_HISTORY_MESSAGES = 30          # oldest turns are trimmed from what the model sees
MAX_HISTORY_CHARS = 60_000
MAX_STORED_MESSAGES = 400
RATE_LIMIT_PER_HOUR = int(os.environ.get("WAVYGO_AI_RATE_LIMIT", "30"))
MAX_TOOL_RESULT_CHARS = 12_000
DEFAULT_TITLE = "New chat"

COMPANY = "WAVYGO MOBILITY SERVICES PRIVATE LIMITED"

STABLE_SYSTEM = f"""You are WavyGo AI, the internal assistant inside WavyGo OS, the operating system of {COMPANY} (CIN U77100BR2025PTC077095). WavyGo is a travel-tech and mobility company that runs a two-wheeler rental business (scooters, bikes and EVs) headquartered in Bihar, India, working with vehicle vendors across Indian cities. WavyGo OS has modules for the Marketplace (vehicles, vendors, bookings, customers), Task Board, Opportunity Hub, Employees (attendance, leave, performance), WavyGo Connect (chat), Calendar, CRM, Finance, Marketing, Analytics and Notifications.

You help one signed-in team member at a time. Their name, role, department and today's date are given below. Roles are Founder, Admin, Manager, Employee and Intern; each role sees a different slice of company data.

How to answer:
- For any fact about the company, its people, tasks, events, opportunities, attendance, leave, notifications or marketplace numbers, call the tools and answer only from what they return. Never invent names, numbers, dates or statuses.
- The tools already apply the user's permissions. If a tool returns an error or no data, say plainly that the information is not available to them or does not exist; do not guess and do not suggest ways around permissions.
- Never reveal or speculate about another person's private details (contact details, attendance, leave, performance, salary) unless a tool returned them for this user.
- If a question needs a tool you do not have, say that this data is not available in WavyGo AI for their role.
- General questions (writing help, explanations, planning, drafting messages) can be answered from your own knowledge; make clear when something is general advice rather than company data.
- You can only read data. You cannot create, edit, assign or delete anything; tell the user which WavyGo OS module to use instead.
- Money is in Indian rupees (₹). Opportunity values are in lakhs. Dates and times are in India Standard Time (Asia/Kolkata) unless stated otherwise.
- Be concise and practical. Use short paragraphs, bullet lists and **bold** for key figures. Use a small table only when comparing several items.
- Do not include internal or system XML tags in your response."""

_client: anthropic.AsyncAnthropic | None = None
_client_key: str | None = None
_indexes_ready = False
# conversation id -> monotonic start of the reply being generated. An entry older than the turn deadline is
# stale (e.g. the client hung up before the stream generator ever ran, so its cleanup never happened).
_active_conversations: dict[str, float] = {}
_background: set[asyncio.Task] = set()


# ============================================================
# CONFIG / CLIENT
# ============================================================

def _api_key() -> str:
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _model() -> str:
    return (os.environ.get("ANTHROPIC_MODEL") or "").strip() or DEFAULT_MODEL


def _get_client() -> anthropic.AsyncAnthropic:
    global _client, _client_key
    key = _api_key()
    if _client is None or _client_key != key:
        _client = anthropic.AsyncAnthropic(api_key=key, timeout=API_TIMEOUT, max_retries=2)
        _client_key = key
    return _client


async def _ensure_indexes(db) -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db.ai_conversations.create_index([("user_id", 1), ("updated_at", -1)])
        await db.ai_usage.create_index([("user_id", 1), ("created_at", -1)])
        await db.ai_usage.create_index("created_at", expireAfterSeconds=2 * 3600)
        _indexes_ready = True
    except Exception as e:  # indexes are an optimisation; never block the request
        logger.warning("AI index creation failed: %s", e)


def _require_ai(current: UserPublic) -> None:
    if not can_view_module(current.role, "wavygo-ai") or not can(current.role, "ai.use"):
        raise HTTPException(403, "Your role cannot use WavyGo AI")


async def _ai_user(current: UserPublic = Depends(get_current_user)) -> UserPublic:
    _require_ai(current)
    return current


# ============================================================
# TOOL HELPERS
# ============================================================

class ToolError(Exception):
    """A tool refused (permission) or got bad input; the message is shown to the model."""

    def __init__(self, message: str, forbidden: bool = False):
        super().__init__(message)
        self.forbidden = forbidden


def _int_arg(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = args.get(key, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ToolError(f"'{key}' must be a number")
    try:
        n = int(float(v))
    except ValueError:
        raise ToolError(f"'{key}' must be a number")
    return max(lo, min(hi, n))


def _str_arg(args: dict, key: str, max_len: int = 100) -> Optional[str]:
    v = args.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ToolError(f"'{key}' must be a string")
    return v.strip()[:max_len] or None


def _bool_arg(args: dict, key: str, default: bool = False) -> bool:
    v = args.get(key, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ToolError(f"'{key}' must be true or false")
    return v


def _enum_arg(args: dict, key: str, allowed: tuple[str, ...], default: Optional[str]) -> Optional[str]:
    v = args.get(key)
    if v is None or v == "":
        return default
    if v not in allowed:
        raise ToolError(f"'{key}' must be one of {', '.join(allowed)}")
    return v


def _short(text: Any, n: int = 200) -> Optional[str]:
    if not text:
        return None
    s = str(text).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _ist(dt: datetime, all_day: bool = False) -> str:
    local = _as_utc(dt).astimezone(IST)
    return local.strftime("%a %d %b %Y") if all_day else local.strftime("%a %d %b %Y, %I:%M %p IST")


def _today_ist():
    return datetime.now(IST).date()


def _contains(text: str) -> dict:
    return {"$regex": re.escape(text), "$options": "i"}


async def _names(db, ids) -> dict:
    oids = list({ObjectId(i) for i in ids if isinstance(i, str) and ObjectId.is_valid(i)})
    if not oids:
        return {}
    return {str(u["_id"]): u.get("name") async for u in db.users.find({"_id": {"$in": oids}}, {"name": 1})}


def _and(*parts: Optional[dict]) -> dict:
    parts = [p for p in parts if p]
    if not parts:
        return {}
    return parts[0] if len(parts) == 1 else {"$and": parts}


def _cap_result(result: Any) -> str:
    """JSON-encode a tool result, trimming the longest list until it fits the size cap."""
    text = json.dumps(result, default=str, ensure_ascii=False, separators=(",", ":"))
    while len(text) > MAX_TOOL_RESULT_CHARS and isinstance(result, dict):
        lists = [(k, v) for k, v in result.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            return text[:MAX_TOOL_RESULT_CHARS]
        key, longest = max(lists, key=lambda kv: len(kv[1]))
        result = {**result, key: longest[: len(longest) // 2], "truncated": True}
        text = json.dumps(result, default=str, ensure_ascii=False, separators=(",", ":"))
    return text


# ============================================================
# TOOLS (read-only, role-scoped)
# ============================================================

TASK_STATUSES = ("todo", "in_progress", "review", "completed", "cancelled")
OPEN_TASK = ["todo", "in_progress", "review"]
TASK_PROJECTION = {"title": 1, "status": 1, "priority": 1, "due_date": 1, "assignee_id": 1,
                   "reporter_id": 1, "module": 1, "created_at": 1, "description": 1}


async def _tasks_query(db, user: UserPublic, args: dict, mine: bool) -> dict:
    limit = _int_arg(args, "limit", 15, 1, 25)
    status = _enum_arg(args, "status", ("open", "all", *TASK_STATUSES), "open")
    text = _str_arg(args, "query")
    overdue_only = _bool_arg(args, "overdue_only")
    assignee_name = None if mine else _str_arg(args, "assignee_name")

    role_filter = await _task_filter_for(db, user)
    q: dict = {}
    if status == "open":
        q["status"] = {"$in": OPEN_TASK}
    elif status != "all":
        q["status"] = status
    if text:
        q["title"] = _contains(text)
    if mine:
        q["assignee_id"] = user.id
    elif assignee_name:
        ids = [str(u["_id"]) async for u in db.users.find({"name": _contains(assignee_name)}, {"_id": 1}).limit(50)]
        q["assignee_id"] = {"$in": ids}
    query = _and(q, role_filter)

    docs = await db.tasks.find(query, TASK_PROJECTION).sort("created_at", -1).to_list(500)
    today = _today_ist()
    if overdue_only:
        docs = [d for d in docs if d.get("status") in OPEN_TASK and (due := _parse_due(d.get("due_date"))) and due < today]
    # Soonest due first, undated last.
    docs.sort(key=lambda d: (_parse_due(d.get("due_date")) or datetime.max.date()))
    total = len(docs)
    docs = docs[:limit]
    names = await _names(db, [d.get(k) for d in docs for k in ("assignee_id", "reporter_id")])

    counts: dict = {}
    async for row in db.tasks.aggregate([{"$match": role_filter or {}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[str(row["_id"])] = row["n"]

    items = []
    for d in docs:
        due = _parse_due(d.get("due_date"))
        items.append({
            "id": str(d["_id"]),
            "title": _short(d.get("title"), 150),
            "status": d.get("status"),
            "priority": d.get("priority"),
            "due_date": due.isoformat() if due else None,
            "overdue": bool(due and due < today and d.get("status") in OPEN_TASK),
            "assignee": names.get(d.get("assignee_id")),
            "reporter": names.get(d.get("reporter_id")),
            "module": d.get("module"),
            "description": _short(d.get("description"), 160),
        })
    return {"total_matching": total, "returned": len(items), "tasks": items,
            "status_counts_visible_to_user": counts}


async def tool_my_tasks(db, user: UserPublic, args: dict) -> dict:
    return await _tasks_query(db, user, args, mine=True)


async def tool_search_tasks(db, user: UserPublic, args: dict) -> dict:
    return await _tasks_query(db, user, args, mine=False)


async def tool_upcoming_events(db, user: UserPublic, args: dict) -> dict:
    days = _int_arg(args, "days", 7, 1, 60)
    limit = _int_arg(args, "limit", 15, 1, 25)
    include_cancelled = _bool_arg(args, "include_cancelled")
    now = datetime.now(timezone.utc)
    q = _and(_overlap_filter(now, now + timedelta(days=days)), _visibility_filter(user),
             None if include_cancelled else {"status": {"$ne": "cancelled"}})
    docs = await db.calendar_events.find(q, {"reminder_at": 0, "reminder_sent": 0}) \
        .sort([("start_time", 1), ("_id", 1)]).to_list(limit)
    names = await _names(db, [x for d in docs for x in (d.get("organizer_id"), *(d.get("participant_ids") or [])[:8])])
    events = []
    for d in docs:
        all_day = bool(d.get("all_day"))
        events.append({
            "title": _short(d.get("title"), 150),
            "start": _ist(d["start_time"], all_day),
            "end": _ist(d["end_time"], all_day),
            "all_day": all_day,
            "category": d.get("category"),
            "status": d.get("status"),
            "location": _short(d.get("location"), 100),
            "has_meeting_link": bool(d.get("meeting_link")),
            "organizer": names.get(d.get("organizer_id")),
            "participants": [names[p] for p in (d.get("participant_ids") or [])[:8] if p in names],
            "description": _short(d.get("description"), 160),
        })
    return {"window_days": days, "returned": len(events), "events": events}


async def tool_opportunities_summary(db, user: UserPublic, args: dict) -> dict:
    if not can_view_module(user.role, "opportunity-hub"):
        raise ToolError("Your role does not have access to the Opportunity Hub.", forbidden=True)
    limit = _int_arg(args, "limit", 10, 1, 20)
    status = _enum_arg(args, "status", ("active", "all", "open", "assigned", "in_progress", "won", "lost", "closed"), "active")
    scope = await _opp_scope_filter(db, user)

    counts: dict = {}
    pipeline_lakhs = won_lakhs = 0.0
    async for d in db.opportunities.find(scope or {}, {"status": 1, "value_lakhs": 1}):
        s = d.get("status") or "open"
        counts[s] = counts.get(s, 0) + 1
        if s in ("open", "assigned", "in_progress"):
            pipeline_lakhs += _lakhs(d.get("value_lakhs"))
        elif s == "won":
            won_lakhs += _lakhs(d.get("value_lakhs"))

    sq = {"status": {"$in": ["open", "assigned", "in_progress"]}} if status == "active" else (
        None if status == "all" else {"status": status})
    docs = await db.opportunities.find(_and(sq, scope)).sort("deadline", 1).to_list(limit)
    names = await _names(db, [d.get("assignee_id") for d in docs])
    items = [{
        "title": _short(d.get("title"), 150),
        "type": d.get("type"),
        "status": d.get("status"),
        "organisation": _short(d.get("organisation"), 100),
        "deadline": d.get("deadline"),
        "value_lakhs": _lakhs(d.get("value_lakhs")),
        "assignee": names.get(d.get("assignee_id")),
    } for d in docs]
    return {"status_counts": counts, "pipeline_value_lakhs": round(pipeline_lakhs, 2),
            "won_value_lakhs": round(won_lakhs, 2), "returned": len(items), "opportunities": items}


async def tool_team_directory(db, user: UserPublic, args: dict) -> dict:
    limit = _int_arg(args, "limit", 25, 1, 40)
    text = _str_arg(args, "query")
    department = _str_arg(args, "department")
    role = _enum_arg(args, "role", ("Founder", "Admin", "Manager", "Employee", "Intern"), None)
    # Same audience and fields as GET /api/users/directory: active users, no contact details.
    q: dict = {"status": {"$ne": "deactivated"}, "is_active": {"$ne": False}, "active": {"$ne": False}}
    if text:
        q["$or"] = [{"name": _contains(text)}, {"designation": _contains(text)}, {"department": _contains(text)}]
    if department:
        q["department"] = {"$regex": f"^{re.escape(department)}$", "$options": "i"}
    if role:
        q["role"] = role
    proj = {"name": 1, "role": 1, "department": 1, "designation": 1}
    total = await db.users.count_documents(q)
    docs = await db.users.find(q, proj).sort("name", 1).to_list(limit)
    people = [{"name": d.get("name"), "role": d.get("role"), "department": d.get("department"),
               "designation": d.get("designation")} for d in docs]
    return {"total_matching": total, "returned": len(people), "people": people}


async def tool_attendance_and_leave(db, user: UserPublic, args: dict) -> dict:
    scope = _enum_arg(args, "scope", ("me", "team"), "me")
    days = _int_arg(args, "days", 14, 1, 60)
    since = (_today_ist() - timedelta(days=days - 1)).isoformat()

    if scope == "me":
        att = await db.attendance.find({"employee_id": user.id, "date": {"$gte": since}}).sort("date", -1).to_list(60)
        leaves = await db.leave_requests.find({"employee_id": user.id}).sort("created_at", -1).to_list(10)
        summary: dict = {}
        for a in att:
            summary[a.get("status", "present")] = summary.get(a.get("status", "present"), 0) + 1
        return {
            "scope": "me", "since": since, "attendance_summary": summary,
            "attendance": [{"date": a.get("date"), "status": a.get("status"),
                            "check_in": a.get("check_in"), "check_out": a.get("check_out")} for a in att[:31]],
            "leave_requests": [{"from": lv.get("from_date"), "to": lv.get("to_date"), "kind": lv.get("kind"),
                                "status": lv.get("status"), "reason": _short(lv.get("reason"), 120)} for lv in leaves],
        }

    # Team view: same rules as /employees/attendance/records and /employees/leave/requests.
    if user.role in ("Employee", "Intern"):
        raise ToolError("Your role can only see your own attendance and leave.", forbidden=True)
    member_filter: dict = {}
    if user.role == "Manager":
        dept = [str(u["_id"]) async for u in db.users.find({"department": user.department}, {"_id": 1})] \
            if user.department else []
        member_filter = {"employee_id": {"$in": dept}}
    per_emp: dict = {}
    async for a in db.attendance.find(_and(member_filter, {"date": {"$gte": since}}), {"employee_id": 1, "status": 1}):
        e = per_emp.setdefault(a.get("employee_id"), {})
        e[a.get("status", "present")] = e.get(a.get("status", "present"), 0) + 1
    today = _today_ist().isoformat()
    today_counts: dict = {}
    async for a in db.attendance.find(_and(member_filter, {"date": today}), {"status": 1}):
        today_counts[a.get("status", "present")] = today_counts.get(a.get("status", "present"), 0) + 1
    pending = await db.leave_requests.find(_and(member_filter, {"status": "pending"})).sort("created_at", -1).to_list(20)
    upcoming = await db.leave_requests.find(_and(member_filter, {"status": "approved", "to_date": {"$gte": today}})) \
        .sort("from_date", 1).to_list(20)
    names = await _names(db, list(per_emp.keys()) + [lv.get("employee_id") for lv in pending + upcoming])

    def leave_row(lv):
        return {"employee": names.get(lv.get("employee_id")), "from": lv.get("from_date"), "to": lv.get("to_date"),
                "kind": lv.get("kind"), "status": lv.get("status"), "reason": _short(lv.get("reason"), 100)}

    return {
        "scope": "team" if user.role == "Manager" else "company",
        "department": user.department if user.role == "Manager" else None,
        "since": since,
        "today": {"date": today, "counts": today_counts},
        "attendance_by_employee": [{"employee": names.get(k) or "Unknown", "counts": v}
                                   for k, v in sorted(per_emp.items(), key=lambda kv: names.get(kv[0]) or "")][:40],
        "pending_leave_requests": [leave_row(lv) for lv in pending],
        "approved_upcoming_leave": [leave_row(lv) for lv in upcoming],
    }


async def tool_marketplace_kpis(db, user: UserPublic, args: dict) -> dict:
    if not can(user.role, "marketplace.any"):
        raise ToolError("Marketplace figures are only available to the Founder.", forbidden=True)
    section = await _marketplace_section(db, _windows(datetime.now(timezone.utc)))
    return {
        "kpis": [{"label": k["label"], "value": k["value"], "change_pct": k.get("delta"), "compared_to": k.get("compare"),
                  "format": k.get("format")} for k in section["kpis"]],
        "revenue_last_6_months_lakhs": section["revenue_series"],
        "bookings_last_7_days": section["bookings_series"],
        "top_cities": section["cities"],
        "top_vendors_by_vehicles": section["vendor_perf"],
        "notes": "Revenue counts confirmed, active and completed bookings. inr values are rupees; series revenue is in lakhs.",
    }


async def tool_notifications_recent(db, user: UserPublic, args: dict) -> dict:
    limit = _int_arg(args, "limit", 10, 1, 20)
    unread_only = _bool_arg(args, "unread_only")
    q = role_notification_filter(user.role, user.id)
    if unread_only:
        q = _and(q, {"$or": [{"user_id": user.id, "read": {"$ne": True}},
                             {"user_id": None, "read_by": {"$ne": user.id}}]})
    docs = await db.notifications.find(q).sort("created_at", -1).to_list(limit)
    items = []
    for d in docs:
        read = user.id in (d.get("read_by") or []) if d.get("user_id") is None else bool(d.get("read"))
        items.append({"title": _short(d.get("title"), 120), "body": _short(d.get("body"), 200),
                      "kind": d.get("kind"), "read": read, "created_at": d.get("created_at")})
    return {"returned": len(items), "notifications": items}


ToolFn = Callable[[Any, UserPublic, dict], Awaitable[dict]]

# name -> (fn, available(role), description, input properties). Order is fixed so the
# tool list (the start of the cached prompt prefix) is byte-stable per role.
TOOLS: dict[str, tuple[ToolFn, Callable[[str], bool], str, dict]] = {
    "my_tasks": (
        tool_my_tasks, lambda r: can_view_module(r, "task-board"),
        "Tasks assigned to the current user, soonest due date first, with overdue flags and "
        "the status counts of every task the user can see.",
        {
            "status": {"type": "string", "enum": ["open", "all", *TASK_STATUSES],
                       "description": "open = todo/in_progress/review (default)."},
            "query": {"type": "string", "description": "Text to match in the task title."},
            "overdue_only": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
    ),
    "search_tasks": (
        tool_search_tasks, lambda r: can_view_module(r, "task-board"),
        "Search all tasks visible to the user on the Task Board (Founder/Admin: all; Manager: department; "
        "Employee: assigned or reported; Intern: assigned). Filter by status, title text, assignee name or overdue.",
        {
            "status": {"type": "string", "enum": ["open", "all", *TASK_STATUSES]},
            "query": {"type": "string", "description": "Text to match in the task title."},
            "assignee_name": {"type": "string", "description": "Part of the assignee's name."},
            "overdue_only": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
    ),
    "upcoming_events": (
        tool_upcoming_events, lambda r: can_view_module(r, "calendar"),
        "Calendar events visible to the user (public, their department's, or ones they organise or attend) "
        "from now until N days ahead, in IST.",
        {
            "days": {"type": "integer", "minimum": 1, "maximum": 60, "description": "Default 7."},
            "include_cancelled": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
    ),
    "opportunities_summary": (
        tool_opportunities_summary, lambda r: can_view_module(r, "opportunity-hub"),
        "Opportunity Hub pipeline visible to the user: counts by status, pipeline and won value (lakhs), "
        "and opportunities sorted by nearest deadline.",
        {
            "status": {"type": "string", "enum": ["active", "all", "open", "assigned", "in_progress", "won", "lost", "closed"],
                       "description": "active = open/assigned/in_progress (default)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
    ),
    "team_directory": (
        tool_team_directory, lambda r: True,
        "Company directory of active team members: name, role, department and designation only "
        "(no contact details).",
        {
            "query": {"type": "string", "description": "Text to match in name, designation or department."},
            "department": {"type": "string"},
            "role": {"type": "string", "enum": ["Founder", "Admin", "Manager", "Employee", "Intern"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 40},
        },
    ),
    "attendance_and_leave": (
        tool_attendance_and_leave, lambda r: can_view_module(r, "employees"),
        "Attendance and leave. scope=me: the user's own records. scope=team: department (Manager) or "
        "company-wide (Founder/Admin) attendance counts and pending/upcoming leave; not available to Employees or Interns.",
        {
            "scope": {"type": "string", "enum": ["me", "team"], "description": "Default me."},
            "days": {"type": "integer", "minimum": 1, "maximum": 60, "description": "Look-back window, default 14."},
        },
    ),
    "marketplace_kpis": (
        tool_marketplace_kpis, lambda r: can(r, "marketplace.any"),
        "Founder-only Marketplace KPIs: revenue (MTD, today, 7 days), bookings, active customers, vehicles "
        "and vendors, 6-month revenue trend, 7-day bookings, top cities and vendors.",
        {},
    ),
    "notifications_recent": (
        tool_notifications_recent, lambda r: can_view_module(r, "notifications"),
        "The user's most recent notifications (newest first).",
        {
            "unread_only": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
    ),
}


def _tool_defs(role: str) -> list[dict]:
    return [
        {
            "name": name,
            "description": desc,
            "input_schema": {"type": "object", "properties": props, "additionalProperties": False},
            # Streamed request with client tools: inputs stream as generated; we validate every input.
            "eager_input_streaming": True,
        }
        for name, (_fn, available, desc, props) in TOOLS.items()
        if available(role)
    ]


async def run_tool(db, user: UserPublic, name: str, args: Any) -> tuple[bool, str, str]:
    """Run one tool for `user`. Returns (ok, json_or_error_text, short summary for the UI)."""
    spec = TOOLS.get(name)
    if not spec:
        return False, f"Unknown tool: {name}", "unknown tool"
    fn, available, _desc, props = spec
    if not available(user.role):
        return False, "This data is not available for your role.", "not permitted"
    if not isinstance(args, dict) or any(k not in props for k in args):
        return False, json.dumps({"INVALID_INPUT": args}, default=str)[:500], "invalid input"
    try:
        result = await fn(db, user, args)
    except ToolError as e:
        return False, str(e), "not permitted" if e.forbidden else "invalid input"
    except Exception:
        logger.exception("AI tool %s failed", name)
        return False, "The tool failed while reading data. Try again later.", "failed"
    summary = f"{result['returned']} result{'s' if result['returned'] != 1 else ''}" if "returned" in result else "ok"
    return True, _cap_result(result), summary


# ============================================================
# PROMPT / HISTORY
# ============================================================

def _user_context(user: UserPublic) -> str:
    today = datetime.now(IST)
    return (
        "Signed-in user:\n"
        f"- Name: {user.name}\n"
        f"- Role: {user.role}\n"
        f"- Department: {user.department or 'none'}\n"
        f"- Designation: {user.designation or 'not set'}\n"
        f"Today's date: {today.strftime('%A, %d %B %Y')} (Asia/Kolkata)."
    )


def _system_blocks(user: UserPublic) -> list[dict]:
    # Stable instructions first with a cache breakpoint (tools + this block are cached per role);
    # the per-user, per-day context comes after it so it never invalidates that prefix.
    return [
        {"type": "text", "text": STABLE_SYSTEM, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": _user_context(user)},
    ]


def _history(messages: list[dict]) -> list[dict]:
    """Stored text turns -> API messages, newest kept, trimmed by count and size, user-first."""
    turns = [{"role": m["role"], "content": m["content"]} for m in messages
             if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()]
    turns = turns[-MAX_HISTORY_MESSAGES:]
    total = 0
    kept: list[dict] = []
    for t in reversed(turns):
        total += len(t["content"])
        if kept and total > MAX_HISTORY_CHARS:
            break
        kept.append(t)
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept


def _block_dicts(content) -> list[dict]:
    out = []
    for b in content:
        d = b.to_dict() if hasattr(b, "to_dict") else dict(b)
        d.pop("parsed_output", None)
        out.append(d)
    return out


# ============================================================
# ERRORS
# ============================================================

def _friendly_error(e: Exception) -> tuple[str, str]:
    if isinstance(e, anthropic.APITimeoutError):
        return "timeout", "The AI service took too long to respond. Please try again."
    if isinstance(e, anthropic.APIConnectionError):
        return "connection", "Could not reach the AI service. Check the server's internet connection and try again."
    if isinstance(e, anthropic.AuthenticationError):
        return "auth", "The AI service rejected the configured API key. Ask an administrator to check ANTHROPIC_API_KEY."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "auth", "The configured API key is not allowed to use this model. Ask an administrator to check it."
    if isinstance(e, anthropic.NotFoundError):
        return "model", f"The configured model ({_model()}) is not available. Ask an administrator to check ANTHROPIC_MODEL."
    if isinstance(e, anthropic.RateLimitError):
        return "busy", "The AI service is busy right now. Please wait a minute and try again."
    if isinstance(e, anthropic.BadRequestError):
        return "bad_request", "The AI service could not process this conversation. Try a new chat or a shorter message."
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code >= 500:
            return "unavailable", "The AI service is temporarily unavailable. Please try again shortly."
        return "api", "The AI service returned an error. Please try again."
    return "internal", "Something went wrong while generating the answer. Please try again."


# ============================================================
# SCHEMAS
# ============================================================

class ConversationIn(BaseModel):
    title: Optional[str] = Field(None, max_length=MAX_TITLE_CHARS)


class ConversationPatch(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_CHARS)


class MessageIn(BaseModel):
    content: str = Field("", max_length=MAX_MESSAGE_CHARS)
    regenerate: bool = False


# ============================================================
# HELPERS
# ============================================================

def _conv_oid(conv_id: str) -> ObjectId:
    if not ObjectId.is_valid(conv_id):
        raise HTTPException(404, "Conversation not found")
    return ObjectId(conv_id)


async def _load_conv(db, conv_id: str, user: UserPublic) -> dict:
    doc = await db.ai_conversations.find_one({"_id": _conv_oid(conv_id), "user_id": user.id})
    if not doc:
        raise HTTPException(404, "Conversation not found")
    return doc


def _conv_summary(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "title": d.get("title") or DEFAULT_TITLE,
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
        "message_count": len(d.get("messages") or []) if "messages" in d else d.get("message_count", 0),
    }


def _conv_full(d: dict) -> dict:
    return {**_conv_summary(d), "messages": d.get("messages") or []}


def _auto_title(text: str) -> str:
    t = " ".join(text.split())
    return (t[:57] + "…") if len(t) > 58 else (t or DEFAULT_TITLE)


async def _check_rate(db, user: UserPublic) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    used = await db.ai_usage.count_documents({"user_id": user.id, "created_at": {"$gte": since}})
    if used >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(429, f"You have reached the limit of {RATE_LIMIT_PER_HOUR} AI messages per hour. Please try again later.")
    return RATE_LIMIT_PER_HOUR - used


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


def _spawn(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/status")
async def ai_status(current: UserPublic = Depends(_ai_user)):
    db = get_db()
    await _ensure_indexes(db)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    used = await db.ai_usage.count_documents({"user_id": current.id, "created_at": {"$gte": since}})
    return {
        "configured": bool(_api_key()),
        "model": _model(),
        "limits": {
            "messages_per_hour": RATE_LIMIT_PER_HOUR,
            "remaining_this_hour": max(0, RATE_LIMIT_PER_HOUR - used),
            "max_message_chars": MAX_MESSAGE_CHARS,
        },
        "tools": [t["name"] for t in _tool_defs(current.role)],
    }


@router.get("/conversations")
async def list_conversations(current: UserPublic = Depends(_ai_user)):
    db = get_db()
    await _ensure_indexes(db)
    pipeline = [
        {"$match": {"user_id": current.id}},
        {"$sort": {"updated_at": -1}},
        {"$limit": 200},
        {"$project": {"title": 1, "created_at": 1, "updated_at": 1,
                      "message_count": {"$size": {"$ifNull": ["$messages", []]}}}},
    ]
    return [_conv_summary(d) async for d in db.ai_conversations.aggregate(pipeline)]


@router.post("/conversations", status_code=201)
async def create_conversation(payload: ConversationIn | None = None, current: UserPublic = Depends(_ai_user)):
    db = get_db()
    await _ensure_indexes(db)
    now = utc_iso()
    title = ((payload.title if payload else None) or "").strip() or DEFAULT_TITLE
    doc = {"user_id": current.id, "title": title, "messages": [], "created_at": now, "updated_at": now}
    res = await db.ai_conversations.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Started AI conversation", "WavyGo AI", target=title)
    return _conv_full(doc)


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, current: UserPublic = Depends(_ai_user)):
    return _conv_full(await _load_conv(get_db(), conv_id, current))


@router.patch("/conversations/{conv_id}")
async def rename_conversation(conv_id: str, payload: ConversationPatch, current: UserPublic = Depends(_ai_user)):
    db = get_db()
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, "Title is required")
    res = await db.ai_conversations.update_one(
        {"_id": _conv_oid(conv_id), "user_id": current.id},
        {"$set": {"title": title, "title_locked": True}})
    if not res.matched_count:
        raise HTTPException(404, "Conversation not found")
    return _conv_summary(await _load_conv(db, conv_id, current))


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, current: UserPublic = Depends(_ai_user)):
    db = get_db()
    res = await db.ai_conversations.delete_one({"_id": _conv_oid(conv_id), "user_id": current.id})
    if not res.deleted_count:
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@router.post("/conversations/{conv_id}/messages")
async def send_message(conv_id: str, payload: MessageIn, current: UserPublic = Depends(_ai_user)):
    db = get_db()
    await _ensure_indexes(db)
    conv = await _load_conv(db, conv_id, current)
    if not _api_key():
        raise HTTPException(503, "WavyGo AI is not configured. An administrator must set ANTHROPIC_API_KEY on the server.")

    stored = list(conv.get("messages") or [])
    if payload.regenerate:
        while stored and stored[-1].get("role") == "assistant":
            stored.pop()
        if not stored or stored[-1].get("role") != "user":
            raise HTTPException(400, "There is no message to retry")
        user_text = stored[-1]["content"]
    else:
        user_text = payload.content.strip()
        if not user_text:
            raise HTTPException(422, "Message cannot be empty")

    key = str(conv["_id"])
    started = _active_conversations.get(key)
    if started is not None and time.monotonic() - started < TURN_DEADLINE_SECONDS + 60:
        raise HTTPException(409, "A reply is already being generated in this conversation")
    await _check_rate(db, current)
    await db.ai_usage.insert_one({"user_id": current.id, "conversation_id": key,
                                  "created_at": datetime.now(timezone.utc)})

    now = utc_iso()
    user_msg = {"role": "user", "content": user_text, "created_at": now}
    if payload.regenerate:
        # Drop the replies being replaced; the user message stays as is.
        await db.ai_conversations.update_one({"_id": conv["_id"]}, {"$set": {"messages": stored, "updated_at": now}})
    else:
        stored.append(user_msg)
        update: dict = {"$push": {"messages": {"$each": [user_msg], "$slice": -MAX_STORED_MESSAGES}},
                        "$set": {"updated_at": now}}
        if (conv.get("title") in (None, "", DEFAULT_TITLE)) and not conv.get("title_locked"):
            update["$set"]["title"] = _auto_title(user_text)
        await db.ai_conversations.update_one({"_id": conv["_id"]}, update)

    _active_conversations[key] = time.monotonic()
    return StreamingResponse(
        _stream_reply(db, current, conv["_id"], _history(stored)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def _persist_reply(db, conv_oid: ObjectId, msg: dict) -> None:
    try:
        await db.ai_conversations.update_one(
            {"_id": conv_oid},
            {"$push": {"messages": {"$each": [msg], "$slice": -MAX_STORED_MESSAGES}},
             "$set": {"updated_at": utc_iso()}})
    except Exception:
        logger.exception("Could not save AI reply")


async def _stream_reply(db, user: UserPublic, conv_oid: ObjectId, history: list[dict]):
    client = _get_client()
    model = _model()
    tools = _tool_defs(user.role)
    messages: list[dict] = list(history)
    text = ""
    tool_calls: list[dict] = []
    stopped = True        # flips to False once the turn completes (normally or with an error)
    error: Optional[dict] = None
    deadline = time.monotonic() + TURN_DEADLINE_SECONDS

    params: dict = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": _system_blocks(user),
        "tools": tools,
        "cache_control": {"type": "ephemeral"},   # auto-breakpoint on the newest turn
    }
    if not model.startswith("claude-haiku"):
        params["output_config"] = {"effort": EFFORT}
    if model in FALLBACK_MODELS:
        params["betas"] = [FALLBACK_BETA]
        params["fallbacks"] = "default"

    try:
        yield _sse("start", {"model": model})
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            if time.monotonic() > deadline:
                error = {"code": "timeout", "detail": "The answer took too long and was stopped. Please try a narrower question."}
                break
            # After the tool budget is spent, keep the tool list (cache) but forbid further calls.
            extra = {"tool_choice": {"type": "none"}} if round_no == MAX_TOOL_ROUNDS and tools else {}
            round_start = text
            separated = False
            final = None
            for attempt in range(3):
                try:
                    async with client.beta.messages.stream(messages=messages, **params, **extra) as stream:
                        async for event in stream:
                            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                                chunk = event.delta.text
                                if not separated and text and not text.endswith("\n"):
                                    chunk = "\n\n" + chunk
                                separated = True
                                text += chunk
                                yield _sse("delta", {"text": chunk})
                        final = await stream.get_final_message()
                    break
                except ValueError:
                    # Eager tool-input streaming produced JSON the SDK could not parse at all:
                    # discard this round's text and re-issue it (bounded).
                    logger.warning("AI tool input was not valid JSON (attempt %s)", attempt + 1)
                    text, separated = round_start, False
                    yield _sse("reset", {"text": text})
            if final is None:
                error = {"code": "invalid_tool_call", "detail": "The assistant produced an invalid tool call. Please retry."}
                break

            if final.stop_reason == "refusal":
                if not text.strip():
                    text = "I can't help with that request."
                    yield _sse("delta", {"text": text})
                break
            tool_uses = [b for b in final.content if b.type == "tool_use"]
            if not tool_uses or final.stop_reason != "tool_use":
                if final.stop_reason == "max_tokens":
                    note = "\n\n_(Answer truncated — ask me to continue.)_"
                    text += note
                    yield _sse("delta", {"text": note})
                break

            for b in tool_uses:
                yield _sse("tool", {"id": b.id, "name": b.name, "status": "running"})
            results = await asyncio.gather(*(run_tool(db, user, b.name, b.input) for b in tool_uses))
            tool_results = []
            for b, (ok, content, summary) in zip(tool_uses, results):
                tool_calls.append({"name": b.name, "input": b.input if isinstance(b.input, dict) else {},
                                   "ok": ok, "summary": summary})
                yield _sse("tool", {"id": b.id, "name": b.name, "status": "done" if ok else "error", "summary": summary})
                block = {"type": "tool_result", "tool_use_id": b.id, "content": content}
                if not ok:
                    block["is_error"] = True
                tool_results.append(block)
            messages.append({"role": "assistant", "content": _block_dicts(final.content)})
            messages.append({"role": "user", "content": tool_results})
        stopped = False
    except Exception as e:  # noqa: BLE001 — every failure becomes a friendly SSE error
        stopped = False
        code, detail = _friendly_error(e)
        if code in ("internal", "bad_request", "api"):
            logger.exception("AI reply failed")
        else:
            logger.warning("AI reply failed: %s: %s", type(e).__name__, e)
        error = {"code": code, "detail": detail}
    finally:
        _active_conversations.pop(str(conv_oid), None)
        if text.strip() or tool_calls:
            msg = {"role": "assistant", "content": text, "created_at": utc_iso(), "model": model,
                   "tool_calls": tool_calls}
            if stopped:
                msg["stopped"] = True
            if error:
                msg["error"] = error["detail"]
            # A background task: when the browser aborts, this generator is being cancelled.
            _spawn(_persist_reply(db, conv_oid, msg))
        else:
            msg = None
    if error:
        yield _sse("error", error)
    yield _sse("done", {"message": msg})


# ============================================================
# TEST-ONLY TOOL RUNNER
# ============================================================

@router.post("/_test/tools/{name}", include_in_schema=False)
async def test_run_tool(name: str, args: dict | None = None, current: UserPublic = Depends(_ai_user)):
    """Runs one tool for the caller without the LLM. Exists only when WAVYGO_AI_TEST_TOOLS=1."""
    if os.environ.get("WAVYGO_AI_TEST_TOOLS") != "1":
        raise HTTPException(404, "Not Found")
    ok, content, summary = await run_tool(get_db(), current, name, args or {})
    if not ok:
        raise HTTPException(403 if summary == "not permitted" else 400, content)
    return json.loads(content)
