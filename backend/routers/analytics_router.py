from __future__ import annotations
"""Analytics module API (mounted at /api/analytics).

Every figure is aggregated from the live collections (bookings, vehicles, vendors,
customers, tasks, opportunities, attendance, leave_requests, calendar_events, users).
Empty data yields zeros / empty lists, never illustrative values.

Conventions
- Ranges are company-local (Asia/Kolkata) calendar days: `from` and `to` are
  inclusive YYYY-MM-DD dates (default: the last 30 days). Alternatively `days`
  (1, 3, 7, 30 or 90) selects a rolling window ending today and overrides from/to.
  The comparison period is the equally long window immediately before `from`.
- Time series are hourly for a 1-day range, daily up to ~3 months, then weekly/monthly.
- Revenue counts confirmed, active and completed bookings; a booking belongs to the
  period its `created_at` falls in. Timestamps may be ISO strings or BSON dates.
- Utilisation = booked vehicle-days / available vehicle-days in the range. A vehicle is
  available from max(range start, its created_at); retired vehicles are excluded.
  Booked days are the overlap of confirmed/active/completed bookings with the range.
- Cohorts group customers by the IST month of their first paid booking; retention at
  month +k is the share of the cohort with a paid booking in that month.

RBAC
- Module "analytics" (analytics.view): Founder, Admin, Manager. Exports: analytics.export.
- Marketplace analytics (bookings, revenue, customers, cities, fleet) additionally
  require the Marketplace module — Founder only.
- Operations analytics: Founder/Admin company-wide (optional department filter);
  Managers are locked to their own department.
"""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from auth_utils import get_current_user
from db import get_db
from hub_utils import log_activity
from models import UserPublic
from permissions import can, can_view_module

router = APIRouter(prefix="/analytics", tags=["analytics"])

IST = ZoneInfo("Asia/Kolkata")
TZ = "Asia/Kolkata"
REVENUE_STATUSES = ["confirmed", "active", "completed"]
BOOKING_STATUSES = ["pending", "confirmed", "active", "completed", "cancelled"]
OPEN_TASK_STATUSES = ["todo", "in_progress", "review"]
OPEN_OPP_STATUSES = ["open", "assigned", "in_progress"]
OPP_STAGES = ["open", "assigned", "in_progress", "won", "lost", "closed"]
ATTENDED = {"present": 1.0, "wfh": 1.0, "half_day": 0.5}
MAX_RANGE_DAYS = 3 * 366
ALLOWED_DAYS = (1, 3, 7, 30, 90)
DEFAULT_DAYS = 30
COHORT_OFFSETS = 11
MAX_COHORTS = 12
DAY_MS = 86_400_000
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
AMOUNT = {"$convert": {"input": "$amount", "to": "double", "onError": 0, "onNull": 0}}


# ------------------------- ranges & helpers -------------------------

@dataclass
class Range:
    d_from: date
    d_to: date  # inclusive

    @property
    def start(self) -> datetime:
        return datetime.combine(self.d_from, time.min, IST)

    @property
    def end(self) -> datetime:  # exclusive
        return datetime.combine(self.d_to + timedelta(days=1), time.min, IST)

    @property
    def days(self) -> int:
        return (self.d_to - self.d_from).days + 1

    @property
    def prev(self) -> "Range":
        return Range(self.d_from - timedelta(days=self.days), self.d_from - timedelta(days=1))

    def as_dict(self) -> dict:
        return {"from": self.d_from.isoformat(), "to": self.d_to.isoformat(), "days": self.days,
                "previous": {"from": self.prev.d_from.isoformat(), "to": self.prev.d_to.isoformat()}}


def _today() -> date:
    return datetime.now(IST).date()


def days_range(days: int) -> Range:
    """Rolling window of `days` IST calendar days ending today (inclusive)."""
    if days not in ALLOWED_DAYS:
        raise ValueError(f"days must be one of {', '.join(map(str, ALLOWED_DAYS))}")
    d_to = _today()
    return Range(d_to - timedelta(days=days - 1), d_to)


def parse_range(from_: str | None, to: str | None) -> Range:
    try:
        d_to = date.fromisoformat(to) if to else _today()
        d_from = date.fromisoformat(from_) if from_ else d_to - timedelta(days=29)
    except ValueError:
        raise ValueError("Dates must be YYYY-MM-DD")
    if d_from > d_to:
        raise ValueError("'from' must not be after 'to'")
    if (d_to - d_from).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"Range is limited to {MAX_RANGE_DAYS} days")
    return Range(d_from, d_to)


def _ts(field: str) -> dict:
    """ISO string or BSON date → date (null when unparseable)."""
    return {"$convert": {"input": f"${field}", "to": "date", "onError": None, "onNull": None}}


def _pad(d: date, days: int) -> str:
    return (d + timedelta(days=days)).isoformat()


def _created_prefilter(field: str, r_start: date, r_end_incl: date) -> dict:
    """Index-friendly coarse filter (strings padded a day each side for offsets, or dates);
    the exact IST window is applied after conversion."""
    s = datetime.combine(r_start, time.min, IST)
    e = datetime.combine(r_end_incl + timedelta(days=1), time.min, IST)
    return {"$or": [{field: {"$gte": _pad(r_start, -1), "$lt": _pad(r_end_incl, 2)}},
                    {field: {"$gte": s, "$lt": e}}]}


def _created_in(field: str, d_from: date, d_to: date, extra: dict | None = None) -> list:
    s = datetime.combine(d_from, time.min, IST)
    e = datetime.combine(d_to + timedelta(days=1), time.min, IST)
    return [
        {"$match": {**(extra or {}), **_created_prefilter(field, d_from, d_to)}},
        {"$addFields": {"_ts": _ts(field)}},
        {"$match": {"_ts": {"$gte": s, "$lt": e}}},
    ]


def _in(start: datetime, end: datetime, field: str = "$_ts") -> dict:
    return {"$and": [{"$gte": [field, start]}, {"$lt": [field, end]}]}


def _day_key(field: str = "$_ts") -> dict:
    return {"$dateToString": {"date": field, "format": "%Y-%m-%d", "timezone": TZ}}


def _bucket_key(g: str, field: str = "$_ts") -> dict:
    """Group key for a series: IST hour (YYYY-MM-DDTHH) for hourly buckets, else IST day."""
    if g == "hour":
        return {"$dateToString": {"date": field, "format": "%Y-%m-%dT%H", "timezone": TZ}}
    return _day_key(field)


def _delta(cur: float, prev: float):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _pct(num: float, den: float):
    return round(num / den * 100, 1) if den else None


def _city_filter(city: str | None) -> dict:
    return {"city": city} if city else {}


async def _agg(db, coll: str, pipeline: list, n: int | None = None) -> list:
    return await db[coll].aggregate(pipeline, allowDiskUse=True).to_list(n)


# ------------------------- bucketing -------------------------

def granularity_for(r: Range, requested: str | None = None, minimum: str = "hour") -> str:
    """Hourly for a single day, daily up to ~3 months, then weekly / monthly."""
    order = ["hour", "day", "week", "month"]
    if requested in order:
        g = requested
    else:
        g = "hour" if r.days == 1 else "day" if r.days <= 92 else "week" if r.days <= 190 else "month"
    if g == "hour" and r.days > 3:
        g = "day"  # keep hourly series bounded (≤ 72 points)
    return order[max(order.index(g), order.index(minimum))]


def _bucket_start(d: date, g: str) -> date:
    if g == "week":
        return d - timedelta(days=d.weekday())
    if g == "month":
        return d.replace(day=1)
    return d


def _next_bucket(d: date, g: str) -> date:
    if g == "day":
        return d + timedelta(days=1)
    if g == "week":
        return d + timedelta(days=7)
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _label(d: date, g: str) -> str:
    if g == "month":
        return d.strftime("%b %y")
    return f"{d.day} {d.strftime('%b')}"


def buckets(r: Range, g: str) -> list[dict]:
    if g == "hour":
        out = []
        for i in range(r.days):
            d = r.d_from + timedelta(days=i)
            for h in range(24):
                key = f"{d.isoformat()}T{h:02d}"
                label = f"{h:02d}:00" if r.days == 1 else f"{d.day} {d.strftime('%b')} {h:02d}:00"
                out.append({"key": key, "label": label, "start": f"{key}:00"})
        return out
    out, cur = [], _bucket_start(r.d_from, g)
    while cur <= r.d_to:
        out.append({"key": cur.isoformat(), "label": _label(cur, g), "start": max(cur, r.d_from).isoformat()})
        cur = _next_bucket(cur, g)
    return out


def fold_days(r: Range, g: str, daily: dict[str, dict], fields: list[str]) -> list[dict]:
    """Fold {YYYY-MM-DD: {field: n}} (or {YYYY-MM-DDTHH: ...} when hourly) into zero-filled buckets."""
    series = buckets(r, g)
    index = {b["key"]: b for b in series}
    for b in series:
        for f in fields:
            b[f] = 0
    for day, vals in daily.items():
        try:
            key = day if g == "hour" else _bucket_start(date.fromisoformat(day), g).isoformat()
        except (TypeError, ValueError):
            continue
        b = index.get(key)
        if b is None:
            continue
        for f in fields:
            b[f] += vals.get(f) or 0
    return series


# ------------------------- access -------------------------

async def analytics_user(current: UserPublic = Depends(get_current_user)) -> UserPublic:
    if not can(current.role, "analytics.view"):
        raise HTTPException(403, "You do not have access to Analytics")
    return current


def _require_marketplace(current: UserPublic):
    if not can_view_module(current.role, "marketplace"):
        raise HTTPException(403, "Marketplace analytics are restricted to the Founder")


@dataclass
class OpsScope:
    department: str | None
    user_ids: list[str] | None  # None = company-wide
    locked: bool


async def ops_scope(db, current: UserPublic, department: str | None) -> OpsScope:
    department = (department or "").strip() or None
    if current.role == "Manager":
        own = current.department
        if department and department != own:
            raise HTTPException(403, "Managers can only view their own department")
        ids = [str(u["_id"]) async for u in db.users.find({"department": own}, {"_id": 1})] if own else []
        if current.id not in ids:
            ids.append(current.id)
        return OpsScope(own, ids, True)
    if department:
        ids = [str(u["_id"]) async for u in db.users.find({"department": department}, {"_id": 1})]
        return OpsScope(department, ids, False)
    return OpsScope(None, None, False)


async def _users_map(db, ids) -> dict:
    oids = [ObjectId(i) for i in {i for i in ids if i} if ObjectId.is_valid(i)]
    if not oids:
        return {}
    return {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": oids}}, {"name": 1, "department": 1, "role": 1})}


# ============================ MARKETPLACE ============================

async def _booking_windows(db, r: Range, city: str | None) -> dict:
    """Counts / revenue for the current and previous windows in one pass."""
    p = r.prev
    paid = {"$in": ["$status", REVENUE_STATUSES]}
    grp: dict = {"_id": None}
    for tag, w in (("cur", r), ("prev", p)):
        win = _in(w.start, w.end)
        grp[f"bookings_{tag}"] = {"$sum": {"$cond": [win, 1, 0]}}
        grp[f"paid_{tag}"] = {"$sum": {"$cond": [{"$and": [win, paid]}, 1, 0]}}
        grp[f"revenue_{tag}"] = {"$sum": {"$cond": [{"$and": [win, paid]}, AMOUNT, 0]}}
        grp[f"cancelled_{tag}"] = {"$sum": {"$cond": [{"$and": [win, {"$eq": ["$status", "cancelled"]}]}, 1, 0]}}
    rows = await _agg(db, "bookings", _created_in("created_at", p.d_from, r.d_to, _city_filter(city)) + [{"$group": grp}], 1)
    return rows[0] if rows else {}


async def _customer_windows(db, r: Range, city: str | None) -> dict:
    """Unique paying customers, new (first-ever paid booking in window) and repeat (2+) customers."""
    p = r.prev
    end = r.end
    pipe = [
        {"$match": {"status": {"$in": REVENUE_STATUSES}, "customer_id": {"$nin": [None, ""]}, **_city_filter(city),
                    "$or": [{"created_at": {"$lt": _pad(r.d_to, 2)}}, {"created_at": {"$lt": end}}]}},
        {"$addFields": {"_ts": _ts("created_at")}},
        {"$match": {"_ts": {"$ne": None, "$lt": end}}},
        {"$group": {"_id": "$customer_id", "first": {"$min": "$_ts"},
                    "n_cur": {"$sum": {"$cond": [_in(r.start, r.end), 1, 0]}},
                    "n_prev": {"$sum": {"$cond": [_in(p.start, p.end), 1, 0]}}}},
        {"$group": {"_id": None,
                    "customers_cur": {"$sum": {"$cond": [{"$gt": ["$n_cur", 0]}, 1, 0]}},
                    "customers_prev": {"$sum": {"$cond": [{"$gt": ["$n_prev", 0]}, 1, 0]}},
                    "repeat_cur": {"$sum": {"$cond": [{"$gte": ["$n_cur", 2]}, 1, 0]}},
                    "repeat_prev": {"$sum": {"$cond": [{"$gte": ["$n_prev", 2]}, 1, 0]}},
                    "new_cur": {"$sum": {"$cond": [_in(r.start, r.end, "$first"), 1, 0]}},
                    "new_prev": {"$sum": {"$cond": [_in(p.start, p.end, "$first"), 1, 0]}}}},
    ]
    rows = await _agg(db, "bookings", pipe, 1)
    return rows[0] if rows else {}


async def vehicle_rows(db, r: Range, city: str | None = None) -> list[dict]:
    """Per-vehicle availability, booked time (overlap with range) and sales created in range."""
    vq = {"status": {"$ne": "retired"}, **_city_filter(city)}
    vehicles = await _agg(db, "vehicles", [
        {"$match": vq},
        {"$project": {"model": 1, "plate": 1, "kind": 1, "city": 1, "vendor_id": 1,
                      "avail_ms": {"$max": [0, {"$subtract": [r.end, {"$max": [r.start, {"$ifNull": [_ts("created_at"), r.start]}]}]}]}}},
    ])
    overlap = await _agg(db, "bookings", [
        {"$match": {"status": {"$in": REVENUE_STATUSES}, "vehicle_id": {"$nin": [None, ""]}, **_city_filter(city),
                    "$or": [{"start_time": {"$lt": _pad(r.d_to, 2)}, "end_time": {"$gt": _pad(r.d_from, -1)}},
                            {"start_time": {"$lt": r.end}, "end_time": {"$gt": r.start}}]}},
        {"$project": {"vehicle_id": 1, "s": _ts("start_time"), "e": _ts("end_time")}},
        {"$match": {"s": {"$ne": None}, "e": {"$ne": None}}},
        {"$project": {"vehicle_id": 1, "ov": {"$subtract": [{"$min": ["$e", r.end]}, {"$max": ["$s", r.start]}]}}},
        {"$match": {"ov": {"$gt": 0}}},
        {"$group": {"_id": "$vehicle_id", "booked_ms": {"$sum": "$ov"}}},
    ])
    sales = await _agg(db, "bookings", _created_in("created_at", r.d_from, r.d_to, {"vehicle_id": {"$nin": [None, ""]}, **_city_filter(city)}) + [
        {"$group": {"_id": "$vehicle_id", "bookings": {"$sum": 1},
                    "revenue": {"$sum": {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, AMOUNT, 0]}},
                    "cancelled": {"$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}}}},
    ])
    booked = {o["_id"]: o["booked_ms"] for o in overlap}
    sold = {s["_id"]: s for s in sales}
    out = []
    for v in vehicles:
        vid = str(v["_id"])
        avail = v.get("avail_ms") or 0
        b = min(booked.get(vid, 0), avail)
        s = sold.get(vid, {})
        out.append({
            "id": vid, "model": v.get("model"), "plate": v.get("plate"), "kind": v.get("kind") or "other",
            "city": v.get("city"), "vendor_id": v.get("vendor_id"),
            "available_ms": avail, "booked_ms": b,
            "available_days": round(avail / DAY_MS, 2), "booked_days": round(b / DAY_MS, 2),
            "utilisation": _pct(b, avail),
            "bookings": s.get("bookings", 0), "revenue": round(s.get("revenue", 0), 2), "cancelled": s.get("cancelled", 0),
        })
    return out


def _utilisation(rows: list[dict]) -> dict:
    avail = sum(r["available_ms"] for r in rows)
    booked = sum(r["booked_ms"] for r in rows)
    return {"available_days": round(avail / DAY_MS, 2), "booked_days": round(booked / DAY_MS, 2),
            "utilisation": _pct(booked, avail), "vehicles": len(rows)}


async def market_summary(db, r: Range, city: str | None) -> dict:
    b = await _booking_windows(db, r, city)
    c = await _customer_windows(db, r, city)
    u_cur = _utilisation(await vehicle_rows(db, r, city))
    u_prev = _utilisation(await vehicle_rows(db, r.prev, city))
    g = lambda k: b.get(k, 0) or 0  # noqa: E731
    h = lambda k: c.get(k, 0) or 0  # noqa: E731

    def avg(tag):
        return round(g(f"revenue_{tag}") / g(f"paid_{tag}"), 2) if g(f"paid_{tag}") else 0

    def kpi(key, label, cur, prev, fmt, rate=False, inverse=False):
        if rate:
            delta = round(cur - prev, 1) if cur is not None and prev is not None else None
        else:
            delta = _delta(cur, prev)
        return {"key": key, "label": label, "value": cur, "previous": prev, "delta": delta,
                "delta_unit": "pp" if rate else "%", "format": fmt, "inverse": inverse}

    kpis = [
        kpi("revenue", "Revenue", round(g("revenue_cur"), 2), round(g("revenue_prev"), 2), "inr"),
        kpi("bookings", "Bookings", g("bookings_cur"), g("bookings_prev"), "number"),
        kpi("avg_booking_value", "Avg booking value", avg("cur"), avg("prev"), "inr"),
        kpi("customers", "Paying customers", h("customers_cur"), h("customers_prev"), "number"),
        kpi("new_customers", "New customers", h("new_cur"), h("new_prev"), "number"),
        kpi("repeat_rate", "Repeat rate", _pct(h("repeat_cur"), h("customers_cur")), _pct(h("repeat_prev"), h("customers_prev")), "pct", rate=True),
        kpi("cancellation_rate", "Cancellation rate", _pct(g("cancelled_cur"), g("bookings_cur")), _pct(g("cancelled_prev"), g("bookings_prev")), "pct", rate=True, inverse=True),
        kpi("utilisation", "Fleet utilisation", u_cur["utilisation"], u_prev["utilisation"], "pct", rate=True),
    ]
    return {"range": r.as_dict(), "city": city, "kpis": kpis, "utilisation": u_cur}


async def market_trend(db, r: Range, city: str | None, granularity: str | None = None) -> dict:
    g = granularity_for(r, granularity)
    rows = await _agg(db, "bookings", _created_in("created_at", r.d_from, r.d_to, _city_filter(city)) + [
        {"$group": {"_id": _bucket_key(g), "bookings": {"$sum": 1},
                    "paid": {"$sum": {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, 1, 0]}},
                    "revenue": {"$sum": {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, AMOUNT, 0]}},
                    "cancelled": {"$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}}}},
    ])
    series = fold_days(r, g, {x["_id"]: x for x in rows}, ["bookings", "paid", "revenue", "cancelled"])
    for s in series:
        s["revenue"] = round(s["revenue"], 2)
        s["avg_value"] = round(s["revenue"] / s["paid"], 2) if s["paid"] else 0
    return {"range": r.as_dict(), "city": city, "granularity": g, "series": series}


def _month_add(ym: tuple[int, int], k: int) -> tuple[int, int]:
    y, m = ym
    n = y * 12 + (m - 1) + k
    return n // 12, n % 12 + 1


def _ym(d: date) -> tuple[int, int]:
    return d.year, d.month


def _ym_str(ym) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


async def market_cohorts(db, r: Range, city: str | None) -> dict:
    """Customers grouped by first paid-booking month (months overlapping the range, last 12);
    retention[k-1] = % of the cohort with a paid booking in month +k. Cells after `to` are null."""
    first_m, last_m = _ym(r.d_from), _ym(r.d_to)
    months = []
    cur = first_m
    while cur <= last_m:
        months.append(cur)
        cur = _month_add(cur, 1)
    months = months[-MAX_COHORTS:]
    cohort_keys = [_ym_str(m) for m in months]
    horizon_end = datetime.combine(r.d_to + timedelta(days=1), time.min, IST)
    pipe = [
        {"$match": {"status": {"$in": REVENUE_STATUSES}, "customer_id": {"$nin": [None, ""]}, **_city_filter(city),
                    "$or": [{"created_at": {"$lt": _pad(r.d_to, 2)}}, {"created_at": {"$lt": horizon_end}}]}},
        {"$addFields": {"_ts": _ts("created_at")}},
        {"$match": {"_ts": {"$ne": None, "$lt": horizon_end}}},
        {"$group": {"_id": "$customer_id", "first": {"$min": "$_ts"},
                    "months": {"$addToSet": {"$dateToString": {"date": "$_ts", "format": "%Y-%m", "timezone": TZ}}}}},
        {"$addFields": {"cohort": {"$dateToString": {"date": "$first", "format": "%Y-%m", "timezone": TZ}}}},
        {"$match": {"cohort": {"$in": cohort_keys}}},
        {"$unwind": "$months"},
        {"$group": {"_id": {"cohort": "$cohort", "month": "$months"}, "customers": {"$sum": 1}}},
    ]
    counts: dict[str, dict[str, int]] = {}
    for x in await _agg(db, "bookings", pipe):
        counts.setdefault(x["_id"]["cohort"], {})[x["_id"]["month"]] = x["customers"]

    cohorts = []
    sums = [[0, 0] for _ in range(COHORT_OFFSETS)]  # [retained, eligible size]
    for m in months:
        key = _ym_str(m)
        cc = counts.get(key, {})
        size = cc.get(key, 0)
        retained, pct = [], []
        for k in range(1, COHORT_OFFSETS + 1):
            target = _month_add(m, k)
            if target > last_m:
                retained.append(None)
                pct.append(None)
                continue
            n = cc.get(_ym_str(target), 0)
            retained.append(n)
            pct.append(_pct(n, size) if size else None)
            if size:
                sums[k - 1][0] += n
                sums[k - 1][1] += size
        cohorts.append({"cohort": key, "label": date(m[0], m[1], 1).strftime("%b %Y"), "size": size,
                        "retained": retained, "retention": pct})
    average = [_pct(a, b) if b else None for a, b in sums]
    total = sum(c["size"] for c in cohorts)
    return {"range": r.as_dict(), "city": city, "offsets": COHORT_OFFSETS, "cohorts": cohorts,
            "average": average, "customers": total}


async def market_cities(db, r: Range) -> dict:
    rows = await _agg(db, "bookings", _created_in("created_at", r.d_from, r.d_to, {"city": {"$nin": [None, ""]}}) + [
        {"$group": {"_id": "$city", "bookings": {"$sum": 1},
                    "paid": {"$sum": {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, 1, 0]}},
                    "revenue": {"$sum": {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, AMOUNT, 0]}},
                    "cancelled": {"$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}},
                    "customers": {"$addToSet": "$customer_id"}}},
    ])
    fleet: dict[str, list] = {}
    for v in await vehicle_rows(db, r):
        if v["city"]:
            fleet.setdefault(v["city"], []).append(v)
    out = {}
    for x in rows:
        out[x["_id"]] = {"city": x["_id"], "bookings": x["bookings"], "paid_bookings": x["paid"],
                         "revenue": round(x["revenue"], 2), "cancelled": x["cancelled"],
                         "customers": len([c for c in x["customers"] if c])}
    for city in fleet:
        out.setdefault(city, {"city": city, "bookings": 0, "paid_bookings": 0, "revenue": 0, "cancelled": 0, "customers": 0})
    for city, row in out.items():
        u = _utilisation(fleet.get(city, []))
        row.update({"vehicles": u["vehicles"], "utilisation": u["utilisation"],
                    "booked_days": u["booked_days"], "available_days": u["available_days"],
                    "cancellation_rate": _pct(row["cancelled"], row["bookings"]),
                    "avg_value": round(row["revenue"] / row["paid_bookings"], 2) if row["paid_bookings"] else 0})
    cities = sorted(out.values(), key=lambda c: (-c["revenue"], -c["bookings"], c["city"]))
    return {"range": r.as_dict(), "cities": cities}


async def market_city_detail(db, r: Range, city: str, granularity: str | None = None) -> dict:
    exists = (await db.cities.find_one({"name": city}, {"_id": 1})
              or await db.bookings.find_one({"city": city}, {"_id": 1})
              or await db.vehicles.find_one({"city": city}, {"_id": 1}))
    if not exists:
        raise HTTPException(404, "City not found")
    vrows = await vehicle_rows(db, r, city)
    b = await _booking_windows(db, r, city)
    trend = await market_trend(db, r, city, granularity)
    u = _utilisation(vrows)
    bookings, paid, revenue, cancelled = (b.get(k, 0) or 0 for k in ("bookings_cur", "paid_cur", "revenue_cur", "cancelled_cur"))

    vendor_sales = await _agg(db, "bookings", _created_in("created_at", r.d_from, r.d_to, {"city": city}) + [
        {"$group": {"_id": "$vendor_id", "bookings": {"$sum": 1},
                    "revenue": {"$sum": {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, AMOUNT, 0]}},
                    "cancelled": {"$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}}}},
    ])
    vendors: dict[str, dict] = {}
    for v in vrows:
        vendors.setdefault(v["vendor_id"] or "", {"rows": []})["rows"].append(v)
    for s in vendor_sales:
        vendors.setdefault(s["_id"] or "", {"rows": []})["sales"] = s
    vids = [ObjectId(k) for k in vendors if k and ObjectId.is_valid(k)]
    vdocs = {str(d["_id"]): d async for d in db.vendors.find({"_id": {"$in": vids}}, {"name": 1, "rating": 1})} if vids else {}
    vendor_list = []
    for vid, data in vendors.items():
        uu = _utilisation(data["rows"])
        s = data.get("sales", {})
        doc = vdocs.get(vid, {})
        vendor_list.append({"vendor_id": vid or None, "vendor": doc.get("name") or ("Unassigned" if not vid else "Unknown vendor"),
                            "rating": doc.get("rating"), "vehicles": uu["vehicles"], "utilisation": uu["utilisation"],
                            "bookings": s.get("bookings", 0), "revenue": round(s.get("revenue", 0), 2),
                            "cancellation_rate": _pct(s.get("cancelled", 0), s.get("bookings", 0))})
    vendor_list.sort(key=lambda v: (-v["revenue"], -v["bookings"], v["vendor"]))
    top = sorted(vrows, key=lambda v: (-v["revenue"], -v["bookings"], -(v["utilisation"] or 0)))[:10]
    top_vehicles = [{k: v[k] for k in ("id", "model", "plate", "kind", "bookings", "revenue", "booked_days", "available_days", "utilisation")} for v in top]
    return {
        "range": r.as_dict(), "city": city,
        "summary": {"bookings": bookings, "revenue": round(revenue, 2), "paid_bookings": paid,
                    "avg_value": round(revenue / paid, 2) if paid else 0,
                    "cancelled": cancelled, "cancellation_rate": _pct(cancelled, bookings), **u},
        "trend": trend,
        "top_vehicles": top_vehicles,
        "vendors": vendor_list,
    }


async def market_fleet(db, r: Range, city: str | None) -> dict:
    kinds: dict[str, list] = {}
    for v in await vehicle_rows(db, r, city):
        kinds.setdefault(v["kind"], []).append(v)
    out = []
    for kind, rows in kinds.items():
        u = _utilisation(rows)
        out.append({"kind": kind, **u, "bookings": sum(x["bookings"] for x in rows),
                    "revenue": round(sum(x["revenue"] for x in rows), 2)})
    out.sort(key=lambda k: (-(k["utilisation"] or 0), k["kind"]))
    return {"range": r.as_dict(), "city": city, "kinds": out, "total": _utilisation([v for rows in kinds.values() for v in rows])}


async def market_funnel(db, r: Range, city: str | None) -> dict:
    rows = await _agg(db, "bookings", _created_in("created_at", r.d_from, r.d_to, _city_filter(city)) + [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ])
    by = {x["_id"]: x["count"] for x in rows}
    total = sum(by.values())
    statuses = [{"status": s, "count": by.get(s, 0), "share": _pct(by.get(s, 0), total)} for s in BOOKING_STATUSES]
    statuses += [{"status": s, "count": n, "share": _pct(n, total)} for s, n in by.items() if s not in BOOKING_STATUSES and n]
    confirmed = sum(by.get(s, 0) for s in REVENUE_STATUSES)
    started = by.get("active", 0) + by.get("completed", 0)
    steps = [
        {"step": "Created", "count": total},
        {"step": "Confirmed", "count": confirmed},
        {"step": "Started", "count": started},
        {"step": "Completed", "count": by.get("completed", 0)},
    ]
    for s in steps:
        s["share"] = _pct(s["count"], total)
    return {"range": r.as_dict(), "city": city, "total": total, "statuses": statuses, "steps": steps,
            "cancelled": by.get("cancelled", 0)}


async def market_heatmap(db, r: Range, city: str | None) -> dict:
    rows = await _agg(db, "bookings", _created_in("start_time", r.d_from, r.d_to, {"status": {"$ne": "cancelled"}, **_city_filter(city)}) + [
        {"$group": {"_id": {"d": {"$isoDayOfWeek": {"date": "$_ts", "timezone": TZ}},
                            "h": {"$hour": {"date": "$_ts", "timezone": TZ}}}, "count": {"$sum": 1}}},
    ])
    matrix = [[0] * 24 for _ in range(7)]
    for x in rows:
        matrix[x["_id"]["d"] - 1][x["_id"]["h"]] = x["count"]
    flat = [n for row in matrix for n in row]
    return {"range": r.as_dict(), "city": city, "days": WEEKDAYS, "matrix": matrix,
            "max": max(flat) if flat else 0, "total": sum(flat)}


# ============================ OPERATIONS ============================

def _scope_match(scope: OpsScope, field: str = "assignee_id") -> dict:
    return {field: {"$in": scope.user_ids}} if scope.user_ids is not None else {}


async def ops_tasks(db, r: Range, scope: OpsScope) -> dict:
    g = granularity_for(r)
    created = await _agg(db, "tasks", _created_in("created_at", r.d_from, r.d_to, _scope_match(scope)) + [
        {"$group": {"_id": _bucket_key(g), "created": {"$sum": 1}}},
    ])
    done_pipe = [
        {"$match": {"status": "completed", **_scope_match(scope)}},
        {"$addFields": {"_ts": {"$ifNull": [_ts("completed_at"), _ts("updated_at")]}, "_c": _ts("created_at")}},
        {"$match": {"_ts": {"$gte": r.start, "$lt": r.end}}},
        {"$facet": {
            "daily": [{"$group": {"_id": _bucket_key(g), "completed": {"$sum": 1}}}],
            "cycle": [{"$match": {"_c": {"$ne": None}}},
                      {"$project": {"ms": {"$max": [0, {"$subtract": ["$_ts", "$_c"]}]}}},
                      {"$group": {"_id": None, "avg": {"$avg": "$ms"}, "n": {"$sum": 1}}}],
        }},
    ]
    done = (await _agg(db, "tasks", done_pipe, 1))[0]
    daily: dict[str, dict] = {}
    for x in created:
        daily.setdefault(x["_id"], {})["created"] = x["created"]
    for x in done["daily"]:
        daily.setdefault(x["_id"], {})["completed"] = x["completed"]
    series = fold_days(r, g, daily, ["created", "completed"])
    cyc = done["cycle"][0] if done["cycle"] else None

    today = _today().isoformat()
    overdue_rows = await _agg(db, "tasks", [
        {"$match": {"status": {"$in": OPEN_TASK_STATUSES}, "due_date": {"$type": "string", "$nin": [""]}, **_scope_match(scope)}},
        {"$match": {"$expr": {"$lt": [{"$substrCP": ["$due_date", 0, 10]}, today]}}},
        {"$group": {"_id": "$assignee_id", "overdue": {"$sum": 1}}},
    ])
    people = await _users_map(db, [x["_id"] for x in overdue_rows])
    by_assignee, by_dept = [], {}
    for x in overdue_rows:
        u = people.get(x["_id"] or "")
        name = u["name"] if u else ("Unassigned" if not x["_id"] else "Former member")
        dept = (u or {}).get("department") or ("Unassigned" if not x["_id"] else "No department")
        by_assignee.append({"assignee_id": x["_id"], "assignee": name, "department": dept, "overdue": x["overdue"]})
        by_dept[dept] = by_dept.get(dept, 0) + x["overdue"]
    by_assignee.sort(key=lambda a: (-a["overdue"], a["assignee"]))
    return {
        "granularity": g, "series": series,
        "created": sum(s["created"] for s in series), "completed": sum(s["completed"] for s in series),
        "avg_cycle_days": round(cyc["avg"] / DAY_MS, 1) if cyc and cyc["avg"] is not None else None,
        "overdue_total": sum(a["overdue"] for a in by_assignee),
        "overdue_by_assignee": by_assignee,
        "overdue_by_department": sorted([{"department": d, "overdue": n} for d, n in by_dept.items()], key=lambda d: (-d["overdue"], d["department"])),
        "as_of": today,
    }


async def ops_opportunities(db, r: Range, scope: OpsScope) -> dict:
    value = {"$convert": {"input": "$value_lakhs", "to": "double", "onError": 0, "onNull": 0}}
    stages = await _agg(db, "opportunities", [
        {"$match": _scope_match(scope)},
        {"$group": {"_id": "$status", "count": {"$sum": 1}, "value": {"$sum": value}}},
    ])
    by = {x["_id"]: x for x in stages}
    pipeline = [{"stage": s, "count": by.get(s, {}).get("count", 0), "value_lakhs": round(by.get(s, {}).get("value", 0), 2)} for s in OPP_STAGES]
    decided = await _agg(db, "opportunities", [
        {"$match": {"status": {"$in": ["won", "lost"]}, **_scope_match(scope)}},
        {"$addFields": {"_ts": _ts("updated_at")}},
        {"$match": {"_ts": {"$gte": r.start, "$lt": r.end}}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}, "value": {"$sum": value}}},
    ])
    d = {x["_id"]: x for x in decided}
    won, lost = d.get("won", {}).get("count", 0), d.get("lost", {}).get("count", 0)
    open_rows = [p for p in pipeline if p["stage"] in OPEN_OPP_STATUSES]
    return {
        "pipeline": pipeline,
        "open_count": sum(p["count"] for p in open_rows),
        "open_value_lakhs": round(sum(p["value_lakhs"] for p in open_rows), 2),
        "won": won, "lost": lost, "win_rate": _pct(won, won + lost),
        "won_value_lakhs": round(d.get("won", {}).get("value", 0), 2),
    }


async def ops_attendance(db, r: Range, scope: OpsScope) -> dict:
    rows = await _agg(db, "attendance", [
        {"$match": {"date": {"$gte": r.d_from.isoformat(), "$lte": r.d_to.isoformat()}, **_scope_match(scope, "employee_id")}},
        {"$group": {"_id": {"e": "$employee_id", "s": "$status"}, "n": {"$sum": 1}}},
    ])
    people = await _users_map(db, [x["_id"]["e"] for x in rows])
    depts: dict[str, dict] = {}
    for x in rows:
        u = people.get(x["_id"]["e"] or "")
        dept = (u or {}).get("department") or "No department"
        dd = depts.setdefault(dept, {"department": dept, "present": 0, "wfh": 0, "half_day": 0, "absent": 0, "leave": 0, "_emp": set()})
        s = x["_id"]["s"]
        if s in dd:
            dd[s] += x["n"]
        dd["_emp"].add(x["_id"]["e"])
    out = []
    tot_att = tot_den = 0.0
    for dd in depts.values():
        attended = sum(dd[k] * w for k, w in ATTENDED.items())
        den = dd["present"] + dd["wfh"] + dd["half_day"] + dd["absent"]
        tot_att += attended
        tot_den += den
        dd["employees"] = len(dd.pop("_emp"))
        dd["records"] = den + dd["leave"]
        dd["rate"] = _pct(attended, den)
        out.append(dd)
    out.sort(key=lambda d: d["department"])
    return {"departments": out, "rate": _pct(tot_att, tot_den)}


async def ops_leave(db, r: Range, scope: OpsScope) -> dict:
    docs = await db.leave_requests.find(
        {"status": "approved", "from_date": {"$lte": r.d_to.isoformat()}, "to_date": {"$gte": r.d_from.isoformat()},
         **_scope_match(scope, "employee_id")},
        {"employee_id": 1, "from_date": 1, "to_date": 1, "kind": 1},
    ).to_list(None)
    people = await _users_map(db, [d.get("employee_id") for d in docs])
    by_kind: dict[str, float] = {}
    by_dept: dict[str, float] = {}
    total = 0
    for d in docs:
        try:
            a = max(date.fromisoformat(str(d["from_date"])[:10]), r.d_from)
            b = min(date.fromisoformat(str(d["to_date"])[:10]), r.d_to)
        except (KeyError, ValueError):
            continue
        days = (b - a).days + 1
        if days <= 0:
            continue
        total += days
        kind = d.get("kind") or "other"
        dept = (people.get(d.get("employee_id") or "") or {}).get("department") or "No department"
        by_kind[kind] = by_kind.get(kind, 0) + days
        by_dept[dept] = by_dept.get(dept, 0) + days
    return {"days": total, "requests": len(docs),
            "by_kind": sorted([{"kind": k, "days": v} for k, v in by_kind.items()], key=lambda x: -x["days"]),
            "by_department": sorted([{"department": k, "days": v} for k, v in by_dept.items()], key=lambda x: (-x["days"], x["department"]))}


async def ops_calendar(db, r: Range, scope: OpsScope) -> dict:
    g = granularity_for(r)
    match: dict = {"status": {"$ne": "cancelled"}}
    if scope.user_ids is not None:
        ors = [{"organizer_id": {"$in": scope.user_ids}}, {"participant_ids": {"$in": scope.user_ids}}]
        if scope.department:
            ors.append({"visibility": "department", "department": scope.department})
        match["$or"] = ors
    rows = await _agg(db, "calendar_events", [
        {"$match": match},
        {"$addFields": {"_ts": _ts("start_time")}},
        {"$match": {"_ts": {"$gte": r.start, "$lt": r.end}}},
        {"$facet": {
            "daily": [{"$group": {"_id": _bucket_key(g), "events": {"$sum": 1}}}],
            "category": [{"$group": {"_id": "$category", "events": {"$sum": 1}}}, {"$sort": {"events": -1}}],
        }},
    ], 1)
    f = rows[0]
    series = fold_days(r, g, {x["_id"]: x for x in f["daily"]}, ["events"])
    return {"granularity": g, "series": series, "total": sum(s["events"] for s in series),
            "by_category": [{"category": x["_id"] or "Other", "events": x["events"]} for x in f["category"]]}


async def operations(db, r: Range, scope: OpsScope) -> dict:
    return {
        "range": r.as_dict(),
        "scope": {"department": scope.department, "locked": scope.locked},
        "tasks": await ops_tasks(db, r, scope),
        "opportunities": await ops_opportunities(db, r, scope),
        "attendance": await ops_attendance(db, r, scope),
        "leave": await ops_leave(db, r, scope),
        "calendar": await ops_calendar(db, r, scope),
    }


# ------------------------- index support -------------------------

async def ensure_indexes(db):
    """Indexes the analytics pipelines rely on (idempotent)."""
    await db.bookings.create_index("created_at")
    await db.bookings.create_index([("city", 1), ("created_at", 1)])
    await db.bookings.create_index([("customer_id", 1), ("created_at", 1)])
    await db.bookings.create_index([("vehicle_id", 1), ("start_time", 1)])
    await db.tasks.create_index([("assignee_id", 1), ("status", 1)])
    await db.attendance.create_index([("date", 1), ("employee_id", 1)])
    await db.leave_requests.create_index([("status", 1), ("from_date", 1)])


# ============================ ENDPOINTS ============================

def _rng(from_: str | None, to: str | None, days: int | None = None) -> Range:
    """`days` (1/3/7/30/90, rolling window ending today) wins over explicit from/to.
    With neither, the default is the last DEFAULT_DAYS days."""
    if days is not None:
        if days not in ALLOWED_DAYS:
            raise HTTPException(422, f"days must be one of {', '.join(map(str, ALLOWED_DAYS))}")
        return days_range(days)
    if not from_ and not to:
        return days_range(DEFAULT_DAYS)
    return parse_range(from_, to)


FromQ = Query(None, alias="from", description="Inclusive start date, YYYY-MM-DD (IST)")
ToQ = Query(None, description="Inclusive end date, YYYY-MM-DD (IST)")
DaysQ = Query(None, description="Rolling window ending today (IST): one of 1, 3, 7, 30, 90. Overrides from/to.")


@router.get("/meta")
async def meta(current: UserPublic = Depends(analytics_user)):
    db = get_db()
    market = can_view_module(current.role, "marketplace")
    cities: list[str] = []
    if market:
        names = set(await db.cities.distinct("name")) | set(await db.bookings.distinct("city")) | set(await db.vehicles.distinct("city"))
        cities = sorted(c for c in names if isinstance(c, str) and c.strip())
    if current.role == "Manager":
        departments = [current.department] if current.department else []
    else:
        names = set(await db.departments.distinct("name")) | set(await db.users.distinct("department"))
        departments = sorted(d for d in names if isinstance(d, str) and d.strip())
    return {
        "role": current.role,
        "marketplace": market,
        "can_export": can(current.role, "analytics.export"),
        "cities": cities,
        "departments": departments,
        "department_locked": current.department if current.role == "Manager" else None,
        "today": _today().isoformat(),
        "timezone": TZ,
    }


@router.get("/marketplace/summary")
async def marketplace_summary(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ, city: str | None = None,
                              current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_summary(get_db(), _rng(from_, to, days), city or None)


@router.get("/marketplace/trend")
async def marketplace_trend(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ, city: str | None = None,
                            granularity: str | None = Query(None, pattern="^(auto|hour|day|week|month)$"),
                            current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_trend(get_db(), _rng(from_, to, days), city or None, granularity)


@router.get("/marketplace/cohorts")
async def marketplace_cohorts(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ, city: str | None = None,
                              current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_cohorts(get_db(), _rng(from_, to, days), city or None)


@router.get("/marketplace/cities")
async def marketplace_cities(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ,
                             current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_cities(get_db(), _rng(from_, to, days))


@router.get("/marketplace/cities/{city}")
async def marketplace_city(city: str, from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ,
                           granularity: str | None = Query(None, pattern="^(auto|hour|day|week|month)$"),
                           current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_city_detail(get_db(), _rng(from_, to, days), city, granularity)


@router.get("/marketplace/fleet")
async def marketplace_fleet(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ, city: str | None = None,
                            current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_fleet(get_db(), _rng(from_, to, days), city or None)


@router.get("/marketplace/funnel")
async def marketplace_funnel(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ, city: str | None = None,
                             current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_funnel(get_db(), _rng(from_, to, days), city or None)


@router.get("/marketplace/heatmap")
async def marketplace_heatmap(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ, city: str | None = None,
                              current: UserPublic = Depends(analytics_user)):
    _require_marketplace(current)
    return await market_heatmap(get_db(), _rng(from_, to, days), city or None)


@router.get("/operations")
async def operations_overview(from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ, department: str | None = None,
                              current: UserPublic = Depends(analytics_user)):
    db = get_db()
    return await operations(db, _rng(from_, to, days), await ops_scope(db, current, department))


# ------------------------- CSV export -------------------------

def _csv_cell(v):
    if v is None:
        return ""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v  # neutralise spreadsheet formulas
    return v


async def _export_rows(db, dataset: str, r: Range, city: str | None, scope_fn) -> tuple[list[str], list[list]]:
    if dataset == "summary":
        d = await market_summary(db, r, city)
        return ["metric", "value", "previous", "change", "change_unit"], \
            [[k["label"], k["value"], k["previous"], k["delta"], k["delta_unit"]] for k in d["kpis"]]
    if dataset == "trend":
        d = await market_trend(db, r, city)
        return ["period_start", "bookings", "paid_bookings", "revenue", "avg_value", "cancelled"], \
            [[s["start"], s["bookings"], s["paid"], s["revenue"], s["avg_value"], s["cancelled"]] for s in d["series"]]
    if dataset == "cohorts":
        d = await market_cohorts(db, r, city)
        cols = ["cohort", "customers"] + [f"m{k}_pct" for k in range(1, COHORT_OFFSETS + 1)]
        return cols, [[c["cohort"], c["size"], *c["retention"]] for c in d["cohorts"]]
    if dataset == "cities":
        d = await market_cities(db, r)
        cols = ["city", "bookings", "paid_bookings", "revenue", "avg_value", "customers", "cancelled",
                "cancellation_rate", "vehicles", "booked_days", "available_days", "utilisation"]
        return cols, [[c[k] for k in cols] for c in d["cities"]]
    if dataset in ("city_vehicles", "city_vendors"):
        if not city:
            raise ValueError("city is required for this dataset")
        d = await market_city_detail(db, r, city)
        if dataset == "city_vehicles":
            cols = ["model", "plate", "kind", "bookings", "revenue", "booked_days", "available_days", "utilisation"]
            return cols, [[v[k] for k in cols] for v in d["top_vehicles"]]
        cols = ["vendor", "rating", "vehicles", "bookings", "revenue", "cancellation_rate", "utilisation"]
        return cols, [[v[k] for k in cols] for v in d["vendors"]]
    if dataset == "fleet":
        d = await market_fleet(db, r, city)
        cols = ["kind", "vehicles", "bookings", "revenue", "booked_days", "available_days", "utilisation"]
        return cols, [[k[c] for c in cols] for k in d["kinds"]]
    if dataset == "funnel":
        d = await market_funnel(db, r, city)
        return ["status", "count", "share_pct"], [[s["status"], s["count"], s["share"]] for s in d["statuses"]]
    if dataset == "heatmap":
        d = await market_heatmap(db, r, city)
        return ["day"] + [f"{h:02d}:00" for h in range(24)], [[WEEKDAYS[i], *row] for i, row in enumerate(d["matrix"])]

    scope = await scope_fn()
    if dataset == "tasks":
        d = await ops_tasks(db, r, scope)
        return ["period_start", "created", "completed"], [[s["start"], s["created"], s["completed"]] for s in d["series"]]
    if dataset == "overdue":
        d = await ops_tasks(db, r, scope)
        return ["assignee", "department", "overdue"], [[a["assignee"], a["department"], a["overdue"]] for a in d["overdue_by_assignee"]]
    if dataset == "pipeline":
        d = await ops_opportunities(db, r, scope)
        return ["stage", "count", "value_lakhs"], [[p["stage"], p["count"], p["value_lakhs"]] for p in d["pipeline"]]
    if dataset == "attendance":
        d = await ops_attendance(db, r, scope)
        cols = ["department", "employees", "present", "wfh", "half_day", "absent", "leave", "rate"]
        return cols, [[x[c] for c in cols] for x in d["departments"]]
    if dataset == "leave":
        d = await ops_leave(db, r, scope)
        return ["group", "name", "days"], [["kind", k["kind"], k["days"]] for k in d["by_kind"]] + \
            [["department", k["department"], k["days"]] for k in d["by_department"]]
    if dataset == "calendar":
        d = await ops_calendar(db, r, scope)
        return ["period_start", "events"], [[s["start"], s["events"]] for s in d["series"]]
    raise HTTPException(404, "Unknown dataset")


MARKETPLACE_DATASETS = {"summary", "trend", "cohorts", "cities", "city_vehicles", "city_vendors", "fleet", "funnel", "heatmap"}
OPERATIONS_DATASETS = {"tasks", "overdue", "pipeline", "attendance", "leave", "calendar"}


@router.get("/export/{dataset}")
async def export_csv(dataset: str, from_: str | None = FromQ, to: str | None = ToQ, days: int | None = DaysQ,
                     city: str | None = None, department: str | None = None,
                     current: UserPublic = Depends(analytics_user)):
    if not can(current.role, "analytics.export"):
        raise HTTPException(403, "You cannot export analytics")
    if dataset not in MARKETPLACE_DATASETS | OPERATIONS_DATASETS:
        raise HTTPException(404, "Unknown dataset")
    if dataset in MARKETPLACE_DATASETS:
        _require_marketplace(current)
    db = get_db()
    r = _rng(from_, to, days)
    cols, rows = await _export_rows(db, dataset, r, city or None, lambda: ops_scope(db, current, department))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for row in rows:
        w.writerow([_csv_cell(v) for v in row])
    parts = ["wavygo", dataset]
    if city and dataset in MARKETPLACE_DATASETS:
        parts.append("".join(ch if ch.isalnum() else "-" for ch in city).lower())
    parts += [r.d_from.isoformat(), r.d_to.isoformat()]
    filename = "_".join(parts) + ".csv"
    await log_activity(db, current, "Exported analytics", "Analytics", target=filename)
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})
