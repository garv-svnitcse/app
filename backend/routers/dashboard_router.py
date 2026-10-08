from __future__ import annotations
"""Founder dashboard aggregates — every number comes from the Marketplace, Tasks,
Opportunities, Employees, Calendar and Notifications collections. An empty
database yields zeros and empty lists, never illustrative figures.

Time windows (today, month-to-date, weekly/monthly series) use the company
timezone, Asia/Kolkata. Revenue counts confirmed, active and completed bookings;
pending and cancelled bookings never count.

RBAC: Founder/Admin/Manager get the team view, but marketplace / revenue
sections are only included for roles that can view the Marketplace module.
Tasks and opportunities use the same visibility as their modules (a Manager
sees their department), so every listed item can be opened.
Employee/Intern get a role-scoped payload with the same top-level shape."""
import os
import time
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user
from models import UserPublic
from hub_utils import role_notification_filter
from permissions import can_view_module
from routers.calendar_router import _visibility_filter, _as_utc
from routers.notifications_router import _serialize as _serialize_notification
from routers.tasks_router import _task_filter_for
from routers.opportunities_router import _scope_filter as _opportunity_scope
from routers.employees_router import _dept_ids

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

IST = ZoneInfo("Asia/Kolkata")
REVENUE_STATUSES = ["confirmed", "active", "completed"]
# Tasks not yet migrated may still hold inline file data; the dashboard never needs it.
TASK_FIELDS = {"attachments": 0, "comments": 0}
# "review" is still open work (matches the Task Board's "mine" count), so it can be overdue too.
OPEN_TASK_STATUSES = ["todo", "in_progress", "review"]
CLOSED_OPPORTUNITY_STATUSES = ["won", "lost", "closed"]
PRIORITY_RANK = {"urgent": 4, "high": 3, "medium": 2, "low": 1}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
LIVE_KPI_TTL_SECONDS = 60
_live_kpi_cache: dict = {"at": 0.0, "data": None}


# ------------------------- time helpers -------------------------

def _windows(now: datetime) -> dict:
    """IST boundaries (as aware datetimes) for the current and comparison periods."""
    local = now.astimezone(IST)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
    # Last month up to the same elapsed point, clamped to the end of last month.
    prev_mtd_end = min(prev_month_start + (local - month_start), month_start)
    return {
        "day_start": day_start,
        "month_start": month_start,
        "mtd": (month_start, now),
        "prev_mtd": (prev_month_start, prev_mtd_end),
        "today": (day_start, now),
        "yday": (day_start - timedelta(days=1), now - timedelta(days=1)),
        "week": (now - timedelta(days=7), now),
        "prev_week": (now - timedelta(days=14), now - timedelta(days=7)),
        # Everything that existed "a month ago" — baseline for cumulative totals.
        "month_ago": (EPOCH, prev_mtd_end),
    }


def _delta(current: float, previous: float):
    """Percent change; None when there is no previous period to compare with."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _as_date_expr(field: str) -> dict:
    """created_at is stored as an ISO string (sometimes a BSON date) — normalise to a date."""
    return {"$convert": {"input": f"${field}", "to": "date", "onError": None, "onNull": None}}


def _in_window(window) -> dict:
    start, end = window
    return {"$and": [{"$gte": ["$_ts", start]}, {"$lt": ["$_ts", end]}]}


def _parse_due(value) -> date | None:
    """Task due_date is either YYYY-MM-DD (company-local) or an ISO datetime."""
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return _as_utc(value).astimezone(IST).date()
        if len(value) == 10:
            return date.fromisoformat(value)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(IST).date()
    except (TypeError, ValueError):
        return None


def _format_when(start: datetime, all_day: bool, today: date) -> str:
    """IST label such as "Today, 4:00 PM", "Tomorrow, 11:00 AM", "Wed, 9:30 AM", "Mon 12 Oct, All day"."""
    local = _as_utc(start).astimezone(IST)
    days = (local.date() - today).days
    if days == 0:
        day = "Today"
    elif days == 1:
        day = "Tomorrow"
    elif days < 7:
        day = local.strftime("%a")
    else:
        day = f"{local:%a} {local.day} {local:%b}"
    clock = "All day" if all_day else f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    return f"{day}, {clock}"


def _fmt_count(n: int) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567."""
    s = str(int(n))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


# ------------------------- shared sections -------------------------

async def _due_tasks(docs: list[dict], today: date, name_for) -> tuple[list[dict], int]:
    """Open tasks due today or overdue: top 5 by priority, plus how many there are."""
    due = [(t, d) for t in docs if (d := _parse_due(t.get("due_date"))) and d <= today]
    due.sort(key=lambda td: (-PRIORITY_RANK.get(td[0].get("priority"), 0), td[1]))
    items = []
    for t, d in due[:5]:
        items.append({
            "id": str(t["_id"]), "title": t["title"], "priority": t.get("priority", "medium"),
            "status": t["status"], "due": t.get("due_date"), "overdue": d < today,
            "assignee_name": await name_for(t.get("assignee_id")), "module": t.get("module"),
        })
    return items, len(due)


async def _upcoming_events(db, current: UserPublic, now: datetime, today: date) -> list[dict]:
    """Next 5 non-cancelled calendar events the caller is allowed to see, including ones in progress."""
    q = {"$or": [{"end_time": {"$gt": now}}, {"start_time": {"$gte": now}}], "status": {"$ne": "cancelled"}}
    visibility = _visibility_filter(current)
    if visibility:
        q = {"$and": [q, visibility]}
    docs = await db.calendar_events.find(q).sort([("start_time", 1), ("_id", 1)]).to_list(5)

    def when(e: dict) -> str:
        if _as_utc(e["start_time"]) < now:
            # Already started (possibly on an earlier day): label by what is happening now
            if e.get("all_day", False):
                return "Today, All day"
            return f"Now, until {_format_when(e['end_time'], False, today)}"
        return _format_when(e["start_time"], e.get("all_day", False), today)

    return [{
        "id": str(e["_id"]), "title": e["title"],
        "when": when(e),
        "start_time": _as_utc(e["start_time"]).isoformat(),
        "category": e.get("category"), "link": f"/calendar?event={e['_id']}",
    } for e in docs]


async def _recent_notifications(db, current: UserPublic) -> list[dict]:
    notif_q = role_notification_filter(current.role, current.id)
    notif_docs = await db.notifications.find(notif_q).sort("created_at", -1).to_list(5)
    # Same shape and per-user read state as /notifications (broadcasts track readers in read_by).
    return [_serialize_notification(n, current.id) for n in notif_docs]


def _opportunity_card(o: dict) -> dict:
    return {
        "id": str(o["_id"]), "title": o["title"], "stage": o["status"].replace("_", " ").title(),
        "value": o.get("value_lakhs") or 0,
        "probability": {"open": 30, "assigned": 50, "in_progress": 65}.get(o["status"], 40),
    }


async def _personal_stats(db, current: UserPublic):
    """Role-scoped dashboard payload for Employee / Intern. Preserves top-level shape."""
    uid = current.id
    now = datetime.now(timezone.utc)
    today = now.astimezone(IST).date()

    async def tc(q): return await db.tasks.count_documents(q)
    my_todo = await tc({"assignee_id": uid, "status": "todo"})
    my_prog = await tc({"assignee_id": uid, "status": "in_progress"})
    my_review = await tc({"assignee_id": uid, "status": "review"})
    my_done = await tc({"assignee_id": uid, "status": "completed"})
    my_leave = await db.leave_requests.count_documents({"employee_id": uid, "status": "pending"})

    kpis = [
        {"key": "my_todo",        "label": "My To-do",      "value": my_todo,   "delta": 0, "format": "number"},
        {"key": "my_in_progress", "label": "In Progress",   "value": my_prog,   "delta": 0, "format": "number"},
        {"key": "my_review",      "label": "In Review",     "value": my_review, "delta": 0, "format": "number"},
        {"key": "my_completed",   "label": "Completed",     "value": my_done,   "delta": 0, "format": "number"},
        {"key": "my_leave",       "label": "Pending Leave", "value": my_leave,  "delta": 0, "format": "number"},
    ]

    async def my_name(_): return current.name
    my_open = await db.tasks.find({"assignee_id": uid, "status": {"$in": OPEN_TASK_STATUSES}}, TASK_FIELDS).to_list(1000)
    tasks_today, tasks_due_count = await _due_tasks(my_open, today, my_name)

    opportunities = []
    if current.role == "Employee":
        opp_docs = await db.opportunities.find(
            {"assignee_id": uid, "status": {"$nin": CLOSED_OPPORTUNITY_STATUSES}}).sort("deadline", 1).to_list(10)
        opportunities = [_opportunity_card(o) for o in opp_docs[:3]]
    pipeline_count, pipeline_lakhs = await _open_pipeline(db, {"assignee_id": uid}) if current.role == "Employee" else (0, 0)

    return {
        "kpis": kpis,
        "revenue_series": [],
        "bookings_series": [],
        "cities": [],
        "vendor_perf": [],
        "tasks_today": tasks_today,
        "tasks_due_count": tasks_due_count,
        "upcoming_events": await _upcoming_events(db, current, now, today),
        "opportunities": opportunities,
        "pipeline": {"count": pipeline_count, "value_lakhs": round(pipeline_lakhs, 2)},
        "recent_notifications": await _recent_notifications(db, current),
        "company_health": None,
        "system_status": None,
    }


# ------------------------- marketplace sections (Founder) -------------------------

async def _booking_aggregates(db, w: dict) -> dict:
    """One $facet pass over bookings: window totals, 6-month revenue, 7-day volume, cities."""
    rev_expr = {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, {"$ifNull": ["$amount", 0]}, 0]}
    totals = {"_id": None, "total": {"$sum": 1}}
    for name in ("mtd", "prev_mtd", "today", "yday", "week", "prev_week", "month_ago"):
        totals[f"rev_{name}"] = {"$sum": {"$cond": [_in_window(w[name]), "$_rev", 0]}}
        totals[f"cnt_{name}"] = {"$sum": {"$cond": [_in_window(w[name]), 1, 0]}}

    series_start = w["month_start"]
    for _ in range(5):
        series_start = (series_start - timedelta(days=1)).replace(day=1)
    week_start = w["day_start"] - timedelta(days=6)

    pipeline = [
        {"$project": {"status": 1, "city": 1, "_rev": rev_expr, "_ts": _as_date_expr("created_at")}},
        {"$facet": {
            "totals": [{"$group": totals}],
            "monthly": [
                {"$match": {"_ts": {"$gte": series_start}}},
                {"$group": {"_id": {"$dateToString": {"date": "$_ts", "format": "%Y-%m", "timezone": "Asia/Kolkata"}},
                            "revenue": {"$sum": "$_rev"}}},
            ],
            "daily": [
                {"$match": {"_ts": {"$gte": week_start}}},
                {"$group": {"_id": {"$dateToString": {"date": "$_ts", "format": "%Y-%m-%d", "timezone": "Asia/Kolkata"}},
                            "bookings": {"$sum": 1}}},
            ],
            "cities": [
                {"$match": {"city": {"$nin": [None, ""]}}},
                {"$group": {"_id": "$city", "bookings": {"$sum": 1}, "revenue": {"$sum": "$_rev"},
                            "rev_mtd": {"$sum": {"$cond": [_in_window(w["mtd"]), "$_rev", 0]}},
                            "rev_prev_mtd": {"$sum": {"$cond": [_in_window(w["prev_mtd"]), "$_rev", 0]}}}},
                {"$sort": {"revenue": -1, "bookings": -1, "_id": 1}}, {"$limit": 8},
            ],
        }},
    ]
    r = (await db.bookings.aggregate(pipeline).to_list(1))[0]
    t = r["totals"][0] if r["totals"] else {}

    monthly = {m["_id"]: m["revenue"] for m in r["monthly"]}
    revenue_series, cursor = [], series_start
    for _ in range(6):
        revenue_series.append({"month": cursor.strftime("%b"),
                               "revenue": round(monthly.get(cursor.strftime("%Y-%m"), 0) / 100000, 2)})
        cursor = (cursor + timedelta(days=32)).replace(day=1)

    daily = {d["_id"]: d["bookings"] for d in r["daily"]}
    bookings_series = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        bookings_series.append({"day": day.strftime("%a"), "bookings": daily.get(day.strftime("%Y-%m-%d"), 0)})

    cities = [{"city": c["_id"], "bookings": c["bookings"], "revenue": round(c["revenue"] / 100000, 2),
               "growth": _delta(c["rev_mtd"], c["rev_prev_mtd"])} for c in r["cities"]]

    return {"t": t, "revenue_series": revenue_series, "bookings_series": bookings_series, "cities": cities}


async def _created_growth(db, collection: str, cutoff: datetime) -> tuple[int, int]:
    """(total now, total that existed at `cutoff`) for a collection with created_at."""
    pipeline = [
        {"$project": {"_ts": _as_date_expr("created_at")}},
        {"$group": {"_id": None, "total": {"$sum": 1},
                    "before": {"$sum": {"$cond": [_in_window((EPOCH, cutoff)), 1, 0]}}}},
    ]
    r = await db[collection].aggregate(pipeline).to_list(1)
    return (r[0]["total"], r[0]["before"]) if r else (0, 0)


async def _marketplace_section(db, w: dict) -> dict:
    agg = await _booking_aggregates(db, w)
    t = agg["t"]
    g = lambda k: t.get(k, 0)  # noqa: E731
    total_bookings = g("total")
    active_bookings = await db.bookings.count_documents({"status": {"$in": ["confirmed", "active"]}})
    active_vendors = await db.vendors.count_documents({"active": True})
    active_vehicles = await db.vehicles.count_documents({"status": "available"})
    customers, customers_before = await _created_growth(db, "customers", w["month_ago"][1])

    # `compare` names the comparison period; None means the KPI has no honest baseline.
    kpis = [
        {"key": "revenue",         "label": "Revenue (MTD)",    "value": g("rev_mtd"),   "delta": _delta(g("rev_mtd"), g("rev_prev_mtd")),     "compare": "vs last month, same days", "format": "inr"},
        {"key": "revenue_today",   "label": "Revenue Today",    "value": g("rev_today"), "delta": _delta(g("rev_today"), g("rev_yday")),       "compare": "vs yesterday, same time",  "format": "inr"},
        {"key": "revenue_week",    "label": "Revenue (7d)",     "value": g("rev_week"),  "delta": _delta(g("rev_week"), g("rev_prev_week")),   "compare": "vs previous 7 days",       "format": "inr"},
        {"key": "bookings",        "label": "Bookings (Total)", "value": total_bookings, "delta": _delta(total_bookings, g("cnt_month_ago")),  "compare": "vs a month ago",           "format": "number"},
        {"key": "bookings_today",  "label": "Bookings Today",   "value": g("cnt_today"), "delta": _delta(g("cnt_today"), g("cnt_yday")),       "compare": "vs yesterday, same time",  "format": "number"},
        {"key": "active_bookings", "label": "Active Bookings",  "value": active_bookings, "delta": None, "compare": None, "format": "number"},
        {"key": "customers",       "label": "Active Customers", "value": customers,       "delta": _delta(customers, customers_before), "compare": "vs a month ago", "format": "number"},
        {"key": "vehicles",        "label": "Active Vehicles",  "value": active_vehicles, "delta": None, "compare": None, "format": "number"},
        {"key": "vendors",         "label": "Active Vendors",   "value": active_vendors,  "delta": None, "compare": None, "format": "number"},
    ]

    # Vendor performance — vehicles owned + rating
    vendor_pipe = [
        {"$group": {"_id": "$vendor_id", "vehicles": {"$sum": 1}}},
        {"$sort": {"vehicles": -1}}, {"$limit": 6},
    ]
    vendor_perf = []
    for entry in await db.vehicles.aggregate(vendor_pipe).to_list(6):
        if not entry["_id"] or not ObjectId.is_valid(entry["_id"]):
            continue
        v = await db.vendors.find_one({"_id": ObjectId(entry["_id"])})
        if v:
            vendor_perf.append({"vendor": v["name"], "city": v.get("city"),
                                "rating": v.get("rating"), "vehicles": entry["vehicles"]})

    return {
        "kpis": kpis,
        "revenue_series": agg["revenue_series"],
        "bookings_series": agg["bookings_series"],
        "cities": agg["cities"],
        "vendor_perf": vendor_perf,
    }


def _scoped(query: dict, scope: dict | None) -> dict:
    return {"$and": [query, scope]} if scope else query


async def _open_pipeline(db, opp_scope: dict | None = None) -> tuple[int, float]:
    """(count, total value in lakhs) of every open opportunity in the caller's scope."""
    open_opps = _scoped({"status": {"$nin": CLOSED_OPPORTUNITY_STATUSES}}, opp_scope)
    pipe = [{"$match": open_opps}, {"$group": {"_id": None, "n": {"$sum": 1}, "value": {"$sum": {"$ifNull": ["$value_lakhs", 0]}}}}]
    r = await db.opportunities.aggregate(pipe).to_list(1)
    return (r[0]["n"], r[0]["value"]) if r else (0, 0)


async def _team_kpis(db, open_tasks: int, overdue: int, opp_scope: dict | None = None,
                     leave_q: dict | None = None) -> list[dict]:
    """KPIs for roles without Marketplace access — work, pipeline and people."""
    opp_count, pipeline_lakhs = await _open_pipeline(db, opp_scope)
    pending_leave = await db.leave_requests.count_documents(leave_q or {"status": "pending"})
    return [
        {"key": "open_tasks",         "label": "Open Tasks",         "value": open_tasks,             "delta": None, "compare": None, "format": "number"},
        {"key": "overdue_tasks",      "label": "Overdue Tasks",      "value": overdue,                "delta": None, "compare": None, "format": "number"},
        {"key": "open_opportunities", "label": "Open Opportunities", "value": opp_count,              "delta": None, "compare": None, "format": "number"},
        {"key": "pipeline_value",     "label": "Pipeline Value",     "value": pipeline_lakhs * 100000, "delta": None, "compare": None, "format": "inr"},
        {"key": "pending_leave",      "label": "Pending Leave",      "value": pending_leave,          "delta": None, "compare": None, "format": "number"},
    ]


# ------------------------- health + system status -------------------------

def _signal(label: str, good: int, total: int) -> dict | None:
    if not total:
        return None
    value = round(good / total * 100)
    status = "healthy" if value >= 80 else "watch" if value >= 60 else "at_risk"
    return {"label": label, "value": value, "status": status}


async def _company_health(db, open_tasks: int, overdue: int, marketplace: bool, leave_q: dict | None = None) -> dict:
    # Each signal is a percentage of real records in a good state; a signal with no
    # records is omitted, and the score is the mean of the signals present:
    #   Operations = open tasks not overdue / open tasks
    #   Fleet      = vehicles not in maintenance / non-retired vehicles        (marketplace)
    #   Compliance = customers + vendors KYC-approved / customers + vendors     (marketplace)
    #   Support    = tickets resolved or closed / all tickets                    (marketplace)
    signals = [_signal("Operations", open_tasks - overdue, open_tasks)]
    pending_leave = await db.leave_requests.count_documents(leave_q or {"status": "pending"})
    flags = {"kyc_pending": None, "open_tickets": None, "pending_leave": pending_leave}
    if marketplace:
        fleet = await db.vehicles.count_documents({"status": {"$ne": "retired"}})
        in_maintenance = await db.vehicles.count_documents({"status": "maintenance"})
        kyc_total = await db.customers.count_documents({}) + await db.vendors.count_documents({})
        kyc_ok = (await db.customers.count_documents({"kyc_status": "approved"})
                  + await db.vendors.count_documents({"kyc_status": "approved"}))
        tickets = await db.support_tickets.count_documents({})
        open_tickets = await db.support_tickets.count_documents({"status": {"$in": ["open", "in_progress"]}})
        signals += [
            _signal("Fleet", fleet - in_maintenance, fleet),
            _signal("Compliance", kyc_ok, kyc_total),
            _signal("Support", tickets - open_tickets, tickets),
        ]
        flags["kyc_pending"] = await db.kyc_requests.count_documents({"status": "pending"})
        flags["open_tickets"] = open_tickets
    signals = [s for s in signals if s]
    score = round(sum(s["value"] for s in signals) / len(signals)) if signals else None
    return {"score": score, "signals": signals, "flags": flags}


async def _system_status(db, started: float) -> dict:
    t0 = time.perf_counter()
    try:
        await db.command("ping")
        database = {"name": "Database", "status": "operational", "detail": f"Ping {(time.perf_counter() - t0) * 1000:.1f} ms"}
    except Exception:
        database = {"name": "Database", "status": "down", "detail": "Ping failed"}

    email_ok = bool(os.environ.get("BREVO_API_KEY"))
    email = {"name": "Email notifications", "status": "operational" if email_ok else "not_configured",
             "detail": "Brevo configured" if email_ok else "BREVO_API_KEY not set"}

    last = None
    if database["status"] == "operational":
        doc = await db.activity_logs.find_one({}, {"created_at": 1}, sort=[("created_at", -1)])
        last = doc.get("created_at") if doc else None
    if isinstance(last, datetime):
        last = _as_utc(last).isoformat()
    activity = {"name": "Activity log", "status": "operational" if last else "idle",
                "detail": None if last else "No activity yet", "at": last}

    api = {"name": "API", "status": "operational",
           "detail": f"Responded in {(time.perf_counter() - started) * 1000:.0f} ms"}
    services = [api, database, email, activity]
    statuses = {s["status"] for s in services}
    overall = "down" if "down" in statuses else "degraded" if statuses & {"degraded", "not_configured"} else "operational"
    return {"overall": overall, "services": services, "last_activity_at": last,
            "checked_at": datetime.now(timezone.utc).isoformat()}


# ------------------------- endpoints -------------------------

@router.get("/stats")
async def stats(current: UserPublic = Depends(get_current_user)):
    started = time.perf_counter()
    db = get_db()
    if current.role in ("Employee", "Intern"):
        return await _personal_stats(db, current)
    now = datetime.now(timezone.utc)
    w = _windows(now)
    today = w["day_start"].date()
    marketplace = can_view_module(current.role, "marketplace")

    names: dict = {}

    async def name_for(uid):
        if not uid or not ObjectId.is_valid(uid):
            return None
        if uid not in names:
            u = await db.users.find_one({"_id": ObjectId(uid)}, {"name": 1})
            names[uid] = u["name"] if u else None
        return names[uid]

    # Tasks and opportunities follow the same visibility as their modules (a Manager sees their
    # department), so every item listed here can be opened.
    task_scope = await _task_filter_for(db, current)
    opp_scope = await _opportunity_scope(db, current)
    open_task_docs = await db.tasks.find(_scoped({"status": {"$in": OPEN_TASK_STATUSES}}, task_scope), TASK_FIELDS).to_list(5000)
    open_tasks = len(open_task_docs)
    tasks_today, tasks_due_count = await _due_tasks(open_task_docs, today, name_for)
    overdue = sum(1 for t in open_task_docs if (d := _parse_due(t.get("due_date"))) and d < today)

    opp_docs = await db.opportunities.find(_scoped({"status": {"$nin": CLOSED_OPPORTUNITY_STATUSES}}, opp_scope)).sort("deadline", 1).to_list(3)
    # Pending leave follows the Employees module: a Manager counts their department only.
    leave_q = {"status": "pending"}
    if current.role == "Manager":
        leave_q["employee_id"] = {"$in": await _dept_ids(db, current.department)}

    out = {
        "tasks_today": tasks_today,
        "tasks_due_count": tasks_due_count,
        "upcoming_events": await _upcoming_events(db, current, now, today),
        "opportunities": [_opportunity_card(o) for o in opp_docs],
        "pipeline": dict(zip(("count", "value_lakhs"), await _open_pipeline(db, opp_scope))),
        "recent_notifications": await _recent_notifications(db, current),
        "company_health": await _company_health(db, open_tasks, overdue, marketplace, leave_q),
    }
    if marketplace:
        out = {**await _marketplace_section(db, w), **out}
    else:
        out = {"kpis": await _team_kpis(db, open_tasks, overdue, opp_scope, leave_q), **out}
    out["system_status"] = await _system_status(db, started)
    return out


@router.get("/live-kpis")
async def live_kpis():
    """Public live KPI cards for the login hero — no auth required. Operational counts
    only (no revenue), cached in-process for LIVE_KPI_TTL_SECONDS."""
    if _live_kpi_cache["data"] is not None and time.monotonic() - _live_kpi_cache["at"] < LIVE_KPI_TTL_SECONDS:
        return _live_kpi_cache["data"]
    db = get_db()
    today = _windows(datetime.now(timezone.utc))["today"]
    pipe = [{"$project": {"_ts": _as_date_expr("created_at")}},
            {"$match": {"_ts": {"$gte": today[0], "$lt": today[1]}}}, {"$count": "n"}]
    r = await db.bookings.aggregate(pipe).to_list(1)
    data = {
        "kpis": [
            {"label": "Today's Bookings", "value": _fmt_count(r[0]["n"] if r else 0)},
            {"label": "Active Vendors",   "value": _fmt_count(await db.vendors.count_documents({"active": True}))},
            {"label": "Vehicles Online",  "value": _fmt_count(await db.vehicles.count_documents({"status": "available"}))},
            {"label": "Cities Served",    "value": _fmt_count(await db.cities.count_documents({"status": "active"}))},
        ]
    }
    _live_kpi_cache.update(at=time.monotonic(), data=data)
    return data
