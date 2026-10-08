"""CRM module API (mounted at /api/crm) — customer 360.

Reads the marketplace collections (`customers`, `bookings`, `support_tickets`,
`kyc_requests`, `reviews`, `cities`) without modifying them. CRM-owned state lives in:
  crm_profiles   one doc per customer_id: tags
  crm_notes      notes on a customer (author, pinned)
  crm_followups  follow-up tasks (due date, owner, done)
  crm_segments   saved customer filters

Customer metrics are computed from bookings on every request, so they are always live:
bookings count, lifetime value (revenue statuses only), first/last booking, average
rating given, open support tickets and a lifecycle stage (see LIFECYCLE_* below).
"""
# No `from __future__ import annotations`: FastAPI resolves body models from runtime annotations.
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from db import get_db
from auth_utils import get_current_user
from models import UserPublic
from hub_utils import serialize, utc_iso, log_activity, notify
from permissions import can

router = APIRouter(prefix="/crm", tags=["crm"])

MODULE = "CRM"
COMPANY_TZ = ZoneInfo("Asia/Kolkata")

# Bookings in these statuses count towards lifetime value (same rule as Marketplace revenue).
REVENUE_STATUSES = ("confirmed", "active", "completed")
# Cancelled bookings never happened from the customer's point of view: they don't count as bookings.
EXCLUDED_BOOKING_STATUSES = ("cancelled",)
OPEN_TICKET_STATUSES = ("open", "in_progress")

# Lifecycle thresholds (days since the customer's last booking).
LIFECYCLE_ACTIVE_DAYS = 60     # booked within this many days -> Active (or New with one booking)
LIFECYCLE_CHURN_DAYS = 180     # last booking older than this -> Churned; in between -> At risk
LIFECYCLE_STAGES = ("lead", "new", "active", "at_risk", "churned")
LIFECYCLE_LABELS = {"lead": "Lead", "new": "New", "active": "Active", "at_risk": "At risk", "churned": "Churned"}

KYC_STATUSES = ("pending", "approved", "rejected")
SORT_FIELDS = ("ltv", "last_booking", "bookings", "name", "created_at")
MAX_TAGS = 20
MAX_TAG_LEN = 32
TREND_MONTHS = 12
TOP_CUSTOMERS = 5


# ------------------------- permissions -------------------------

def _require(action: str):
    async def dep(current: UserPublic = Depends(get_current_user)) -> UserPublic:
        if not can(current.role, action):
            raise HTTPException(403, "You don't have permission to do this")
        return current
    return dep


view_user = _require("crm.view")
edit_user = _require("crm.edit")


# ------------------------- helpers -------------------------

def _to_dt(value) -> Optional[datetime]:
    """ISO string or datetime -> aware UTC datetime (None when missing/unparseable)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), COMPANY_TZ)
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_local() -> date:
    return datetime.now(COMPANY_TZ).date()


def _customer_oid(customer_id: str) -> ObjectId:
    if not ObjectId.is_valid(customer_id):
        raise HTTPException(404, "Customer not found")
    return ObjectId(customer_id)


def _doc_oid(value: str, what: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(404, f"{what} not found")
    return ObjectId(value)


def lifecycle_stage(bookings: int, last_booking: Optional[datetime], now: Optional[datetime] = None) -> str:
    """Lead: no bookings. Churned: last booking > LIFECYCLE_CHURN_DAYS ago. At risk: last booking
    LIFECYCLE_ACTIVE_DAYS–LIFECYCLE_CHURN_DAYS ago. Otherwise New (exactly one booking) or Active."""
    if bookings <= 0 or last_booking is None:
        return "lead"
    days = ((now or _now()) - last_booking).total_seconds() / 86400
    if days > LIFECYCLE_CHURN_DAYS:
        return "churned"
    if days > LIFECYCLE_ACTIVE_DAYS:
        return "at_risk"
    return "new" if bookings == 1 else "active"


def _clean_tags(tags: list[str]) -> list[str]:
    out, seen = [], set()
    for t in tags:
        t = re.sub(r"\s+", " ", (t or "").strip())
        if not t:
            continue
        if len(t) > MAX_TAG_LEN:
            raise ValueError(f"Tags must be at most {MAX_TAG_LEN} characters")
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    if len(out) > MAX_TAGS:
        raise ValueError(f"At most {MAX_TAGS} tags per customer")
    return out


# ------------------------- metrics -------------------------

BOOKING_FIELDS = {"customer_id": 1, "amount": 1, "status": 1, "created_at": 1, "start_time": 1}


def _booking_time(b: dict) -> Optional[datetime]:
    return _to_dt(b.get("created_at")) or _to_dt(b.get("start_time"))


async def _compute_rows(db, customer_filter: Optional[dict] = None) -> list[dict]:
    """One row per customer with live metrics. `customer_filter` narrows the customers read."""
    customers = await db.customers.find(customer_filter or {}).to_list(None)
    if not customers:
        return []
    ids = [str(c["_id"]) for c in customers]
    only = {"$in": ids} if customer_filter else {"$exists": True}

    stats: dict[str, dict] = {}
    booking_owner: dict[str, str] = {}
    async for b in db.bookings.find({"customer_id": only}, BOOKING_FIELDS):
        cid = b.get("customer_id")
        booking_owner[str(b["_id"])] = cid
        if b.get("status") in EXCLUDED_BOOKING_STATUSES:
            continue
        s = stats.setdefault(cid, {"bookings": 0, "ltv": 0.0, "first": None, "last": None})
        s["bookings"] += 1
        if b.get("status") in REVENUE_STATUSES:
            s["ltv"] += float(b.get("amount") or 0)
        at = _booking_time(b)
        if at:
            s["first"] = at if s["first"] is None or at < s["first"] else s["first"]
            s["last"] = at if s["last"] is None or at > s["last"] else s["last"]

    # Reviews reference a booking (preferred) or only carry the reviewer's name.
    # Names are matched against every customer so a name shared by two customers stays ambiguous.
    all_customers = customers if not customer_filter else await db.customers.find({}, {"name": 1}).to_list(None)
    by_name = {}
    for c in all_customers:
        by_name.setdefault((c.get("name") or "").strip().lower(), []).append(str(c["_id"]))
    ratings: dict[str, list[float]] = {}
    async for r in db.reviews.find({}, {"booking_id": 1, "customer_name": 1, "rating": 1}):
        if r.get("rating") is None:
            continue
        if r.get("booking_id"):
            cid = booking_owner.get(r["booking_id"])
            targets = [cid] if cid else []
        else:
            targets = by_name.get((r.get("customer_name") or "").strip().lower(), [])
        # An ambiguous name (shared by several customers) is not attributed to anyone.
        if len(targets) == 1:
            ratings.setdefault(targets[0], []).append(float(r["rating"]))

    tickets: dict[str, int] = {}
    async for t in db.support_tickets.aggregate([
        {"$match": {"customer_id": only, "status": {"$in": list(OPEN_TICKET_STATUSES)}}},
        {"$group": {"_id": "$customer_id", "n": {"$sum": 1}}},
    ]):
        tickets[t["_id"]] = t["n"]

    tags = {p["customer_id"]: p.get("tags", []) async for p in db.crm_profiles.find({"customer_id": only})}

    now = _now()
    rows = []
    for c in customers:
        cid = str(c["_id"])
        s = stats.get(cid, {"bookings": 0, "ltv": 0.0, "first": None, "last": None})
        rs = ratings.get(cid, [])
        rows.append({
            "id": cid,
            "name": c.get("name"),
            "email": c.get("email"),
            "phone": c.get("phone"),
            "city": c.get("city"),
            "kyc_status": c.get("kyc_status") or "pending",
            "created_at": _iso(_to_dt(c.get("created_at"))),
            "tags": tags.get(cid, []),
            "bookings": s["bookings"],
            "ltv": round(s["ltv"], 2),
            "first_booking": _iso(s["first"]),
            "last_booking": _iso(s["last"]),
            "days_since_last_booking": int((now - s["last"]).total_seconds() // 86400) if s["last"] else None,
            "avg_rating": round(sum(rs) / len(rs), 2) if rs else None,
            "reviews": len(rs),
            "open_tickets": tickets.get(cid, 0),
            "lifecycle": lifecycle_stage(s["bookings"], s["last"], now),
        })
    return rows


class SegmentFilters(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    q: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    kyc_status: Optional[Literal["pending", "approved", "rejected"]] = None
    lifecycle: Optional[Literal["lead", "new", "active", "at_risk", "churned"]] = None
    tag: Optional[str] = Field(None, max_length=MAX_TAG_LEN)
    min_ltv: Optional[float] = Field(None, ge=0)
    min_bookings: Optional[int] = Field(None, ge=0)

    @field_validator("q", "city", "tag", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    def is_empty(self) -> bool:
        return not any(v is not None for v in self.model_dump().values())


def apply_filters(rows: list[dict], f: SegmentFilters) -> list[dict]:
    rx = re.compile(re.escape(f.q), re.I) if f.q else None
    out = []
    for r in rows:
        if rx and not any(rx.search(r.get(k) or "") for k in ("name", "email", "phone")):
            continue
        if f.city and (r.get("city") or "").lower() != f.city.lower():
            continue
        if f.kyc_status and r["kyc_status"] != f.kyc_status:
            continue
        if f.lifecycle and r["lifecycle"] != f.lifecycle:
            continue
        if f.tag and f.tag.lower() not in {t.lower() for t in r["tags"]}:
            continue
        if f.min_ltv is not None and r["ltv"] < f.min_ltv:
            continue
        if f.min_bookings is not None and r["bookings"] < f.min_bookings:
            continue
        out.append(r)
    return out


def _sort_rows(rows: list[dict], sort: str, order: str) -> list[dict]:
    desc = order == "desc"
    if sort in ("name",):
        key = lambda r: (r.get("name") or "").lower()
        return sorted(rows, key=key, reverse=desc)
    # Missing dates always sort last, whichever direction.
    present = [r for r in rows if r.get(sort) is not None]
    missing = [r for r in rows if r.get(sort) is None]
    present.sort(key=lambda r: (r[sort], (r.get("name") or "").lower()), reverse=desc)
    return present + sorted(missing, key=lambda r: (r.get("name") or "").lower())


async def segment_customer_ids(db, segment_id: str) -> Optional[set[str]]:
    """Customer ids currently matching a saved segment (None when the segment does not exist).
    Used by Marketing to size a campaign audience."""
    if not ObjectId.is_valid(segment_id or ""):
        return None
    seg = await db.crm_segments.find_one({"_id": ObjectId(segment_id)})
    if not seg:
        return None
    rows = apply_filters(await _compute_rows(db), SegmentFilters(**(seg.get("filters") or {})))
    return {r["id"] for r in rows}


# ------------------------- indexes -------------------------

async def ensure_indexes(db) -> None:
    """Indexes for CRM collections plus the marketplace lookups CRM relies on. Idempotent."""
    await db.crm_profiles.create_index("customer_id", unique=True)
    await db.crm_notes.create_index([("customer_id", 1), ("created_at", -1)])
    await db.crm_followups.create_index([("customer_id", 1), ("due_date", 1)])
    await db.crm_followups.create_index([("owner_id", 1), ("done", 1), ("due_date", 1)])
    await db.crm_segments.create_index("name_lower", unique=True)
    await db.bookings.create_index("customer_id")
    await db.support_tickets.create_index("customer_id")
    await db.kyc_requests.create_index([("subject_type", 1), ("subject_id", 1)])


# ------------------------- meta & overview -------------------------

@router.get("/meta")
async def crm_meta(current: UserPublic = Depends(view_user)):
    db = get_db()
    cities = sorted({c.get("name") for c in await db.cities.find({}, {"name": 1}).to_list(None) if c.get("name")}
                    | {c for c in await db.customers.distinct("city") if c})
    tags = sorted({t for p in await db.crm_profiles.find({}, {"tags": 1}).to_list(None) for t in p.get("tags", [])},
                  key=str.lower)
    return {
        "cities": cities,
        "tags": tags,
        "kyc_statuses": list(KYC_STATUSES),
        "lifecycle_stages": [{"key": k, "label": LIFECYCLE_LABELS[k]} for k in LIFECYCLE_STAGES],
        "thresholds": {"active_days": LIFECYCLE_ACTIVE_DAYS, "churn_days": LIFECYCLE_CHURN_DAYS},
        "revenue_statuses": list(REVENUE_STATUSES),
        "can_edit": can(current.role, "crm.edit"),
    }


def _month_keys(today: date, n: int) -> list[str]:
    y, m = today.year, today.month
    keys = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return keys[::-1]


@router.get("/overview")
async def crm_overview(current: UserPublic = Depends(view_user)):
    db = get_db()
    rows = await _compute_rows(db)
    by_stage = {k: 0 for k in LIFECYCLE_STAGES}
    for r in rows:
        by_stage[r["lifecycle"]] += 1

    months = _month_keys(_today_local(), TREND_MONTHS)
    per_month = {k: 0 for k in months}
    for r in rows:
        dt = _to_dt(r["created_at"])
        if dt:
            key = dt.astimezone(COMPANY_TZ).strftime("%Y-%m")
            if key in per_month:
                per_month[key] += 1

    booked = [r for r in rows if r["bookings"] > 0]
    repeat = [r for r in booked if r["bookings"] >= 2]
    total_ltv = sum(r["ltv"] for r in rows)
    top = sorted((r for r in rows if r["ltv"] > 0), key=lambda r: r["ltv"], reverse=True)[:TOP_CUSTOMERS]

    today = _today_local().isoformat()
    open_followups = await db.crm_followups.count_documents({"done": False})
    overdue_followups = await db.crm_followups.count_documents({"done": False, "due_date": {"$lt": today}})

    return {
        "totals": {
            "customers": len(rows),
            "booked_customers": len(booked),
            "repeat_customers": len(repeat),
            "repeat_rate": round(len(repeat) / len(booked) * 100, 1) if booked else None,
            "total_ltv": round(total_ltv, 2),
            "avg_ltv": round(total_ltv / len(booked), 2) if booked else None,
            "open_tickets": sum(r["open_tickets"] for r in rows),
            "open_followups": open_followups,
            "overdue_followups": overdue_followups,
        },
        "by_lifecycle": [{"stage": k, "label": LIFECYCLE_LABELS[k], "count": by_stage[k]} for k in LIFECYCLE_STAGES],
        "new_customers": [{"month": k, "count": per_month[k]} for k in months],
        "top_customers": top,
    }


# ------------------------- customers -------------------------

@router.get("/customers")
async def list_customers(
    q: Optional[str] = Query(None, max_length=100),
    city: Optional[str] = None,
    kyc_status: Optional[Literal["pending", "approved", "rejected"]] = None,
    lifecycle: Optional[Literal["lead", "new", "active", "at_risk", "churned"]] = None,
    tag: Optional[str] = None,
    min_ltv: Optional[float] = Query(None, ge=0),
    min_bookings: Optional[int] = Query(None, ge=0),
    segment_id: Optional[str] = None,
    sort: Literal["ltv", "last_booking", "bookings", "name", "created_at"] = "ltv",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current: UserPublic = Depends(view_user),
):
    db = get_db()
    rows = await _compute_rows(db)
    if segment_id:
        seg = await db.crm_segments.find_one({"_id": _doc_oid(segment_id, "Segment")})
        if not seg:
            raise HTTPException(404, "Segment not found")
        rows = apply_filters(rows, SegmentFilters(**(seg.get("filters") or {})))
    rows = apply_filters(rows, SegmentFilters(q=q, city=city, kyc_status=kyc_status, lifecycle=lifecycle,
                                              tag=tag, min_ltv=min_ltv, min_bookings=min_bookings))
    rows = _sort_rows(rows, sort, order)
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }


def _day_label(value) -> str:
    """YYYY-MM-DD -> "20 Sep 2026" (the value unchanged when it isn't a date)."""
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return f"{d.day} {d.strftime('%b %Y')}"


def _timeline(bookings, tickets, kycs, reviews, notes, followups) -> list[dict]:
    items = []

    def add(kind, ref_id, at, title, **extra):
        dt = _to_dt(at)
        if dt:
            items.append({"type": kind, "ref_id": ref_id, "at": dt.isoformat(), "title": title, **extra})

    for b in bookings:
        add("booking", str(b["_id"]), b.get("created_at") or b.get("start_time"),
            f"Booked {b.get('vehicle_label') or 'a vehicle'}",
            status=b.get("status"), amount=b.get("amount"), city=b.get("city"))
    for t in tickets:
        add("ticket", str(t["_id"]), t.get("created_at"), f"Support ticket: {t.get('subject') or 'Untitled'}",
            status=t.get("status"), priority=t.get("priority"), detail=t.get("description"))
    for k in kycs:
        doc_type = (k.get("doc_type") or "document").upper()
        add("kyc", str(k["_id"]), k.get("created_at"), f"KYC submitted ({doc_type})", status="pending",
            detail=k.get("notes"))
        if k.get("status") in ("approved", "rejected"):
            add("kyc", str(k["_id"]), k.get("updated_at") or k.get("created_at"),
                f"KYC {k['status']} ({doc_type})", status=k["status"])
    for r in reviews:
        add("review", str(r["_id"]), r.get("created_at"), f"Reviewed {r.get('vendor_name') or 'a vendor'}",
            rating=r.get("rating"), detail=r.get("comment"))
    for n in notes:
        add("note", str(n["_id"]), n.get("created_at"), f"Note by {n.get('author_name') or 'someone'}",
            detail=n.get("body"), pinned=n.get("pinned", False))
    for f in followups:
        add("followup", str(f["_id"]), f.get("created_at"), f"Follow-up scheduled: {f.get('title')}",
            detail=f"Due {_day_label(f.get('due_date'))} · {f.get('owner_name') or 'Unassigned'}", status="open")
        if f.get("done") and f.get("done_at"):
            add("followup", str(f["_id"]), f["done_at"], f"Follow-up completed: {f.get('title')}",
                detail=f.get("done_by_name") and f"By {f['done_by_name']}", status="completed")
    items.sort(key=lambda i: i["at"], reverse=True)
    return items


async def _customer_or_404(db, customer_id: str) -> dict:
    c = await db.customers.find_one({"_id": _customer_oid(customer_id)})
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


def _note_out(n: dict) -> dict:
    return serialize(n)


def _followup_out(f: dict, today: Optional[str] = None) -> dict:
    out = serialize(f)
    out["overdue"] = (not f.get("done")) and f.get("due_date", "") < (today or _today_local().isoformat())
    return out


@router.get("/customers/{customer_id}")
async def customer_360(customer_id: str, current: UserPublic = Depends(view_user)):
    db = get_db()
    c = await _customer_or_404(db, customer_id)
    rows = await _compute_rows(db, {"_id": c["_id"]})
    metrics = rows[0]

    bookings = await db.bookings.find({"customer_id": customer_id}).to_list(None)
    booking_ids = [str(b["_id"]) for b in bookings]
    tickets = await db.support_tickets.find({"customer_id": customer_id}).to_list(None)
    kycs = await db.kyc_requests.find({"subject_type": "customer", "subject_id": customer_id}).to_list(None)
    # Same review attribution as the metrics: booking link, else a name that belongs only to this customer.
    name = (c.get("name") or "").strip()
    same_name = await db.customers.count_documents(
        {"name": {"$regex": f"^\\s*{re.escape(name)}\\s*$", "$options": "i"}}) if name else 0
    review_q = [{"booking_id": {"$in": booking_ids}}]
    if name and same_name == 1:
        review_q.append({"booking_id": {"$in": [None, ""]},
                         "customer_name": {"$regex": f"^\\s*{re.escape(name)}\\s*$", "$options": "i"}})
    reviews = await db.reviews.find({"$or": review_q}).to_list(None)
    notes = await db.crm_notes.find({"customer_id": customer_id}).sort([("pinned", -1), ("created_at", -1)]).to_list(None)
    followups = await db.crm_followups.find({"customer_id": customer_id}).sort([("done", 1), ("due_date", 1)]).to_list(None)

    revenue_bookings = [b for b in bookings if b.get("status") in REVENUE_STATUSES]
    today = _today_local().isoformat()
    return {
        "customer": serialize(c),
        "metrics": metrics,
        "kpis": {
            "bookings": metrics["bookings"],
            "ltv": metrics["ltv"],
            "avg_booking_value": round(metrics["ltv"] / len(revenue_bookings), 2) if revenue_bookings else None,
            "cancelled_bookings": sum(1 for b in bookings if b.get("status") in EXCLUDED_BOOKING_STATUSES),
            "avg_rating": metrics["avg_rating"],
            "open_tickets": metrics["open_tickets"],
            "total_tickets": len(tickets),
        },
        "tags": metrics["tags"],
        "notes": [_note_out(n) for n in notes],
        "followups": [_followup_out(f, today) for f in followups],
        "timeline": _timeline(bookings, tickets, kycs, reviews, notes, followups),
    }


# ------------------------- customer records -------------------------
# Marketplace customer CRUD is Founder-only; CRM editors (Founder/Admin/Manager) add and maintain
# customer records here. Same `customers` collection and shape as Marketplace creates.

class CustomerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=40)
    city: str = Field(..., min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("phone", mode="before")
    @classmethod
    def _blank_phone(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class CustomerPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=40)
    city: Optional[str] = Field(None, min_length=1, max_length=100)

    @field_validator("phone", mode="before")
    @classmethod
    def _blank_phone(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


async def _ensure_unique_email(db, email: str, exclude: Optional[ObjectId] = None):
    q: dict = {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
    if exclude is not None:
        q["_id"] = {"$ne": exclude}
    if await db.customers.find_one(q, {"_id": 1}):
        raise HTTPException(409, f"A customer with email {email} already exists")


@router.post("/customers", status_code=201)
async def create_customer(payload: CustomerCreate, current: UserPublic = Depends(edit_user)):
    db = get_db()
    try:
        tags = _clean_tags(payload.tags)
    except ValueError as e:
        raise HTTPException(422, str(e))
    email = str(payload.email).lower()
    await _ensure_unique_email(db, email)
    now = utc_iso()
    doc = {"name": payload.name, "email": email, "phone": payload.phone, "city": payload.city,
           "kyc_status": "pending", "created_at": now, "updated_at": now}
    res = await db.customers.insert_one(doc)
    cid = str(res.inserted_id)
    if tags:
        await db.crm_profiles.update_one(
            {"customer_id": cid},
            {"$set": {"tags": tags, "updated_at": now, "updated_by": current.id},
             "$setOnInsert": {"customer_id": cid, "created_at": now}},
            upsert=True,
        )
    await log_activity(db, current, "Added customer", MODULE, target=payload.name, meta={"customer_id": cid})
    rows = await _compute_rows(db, {"_id": res.inserted_id})
    return rows[0]


@router.patch("/customers/{customer_id}")
async def update_customer(customer_id: str, payload: CustomerPatch, current: UserPublic = Depends(edit_user)):
    db = get_db()
    c = await _customer_or_404(db, customer_id)
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
               if v is not None or k == "phone"}
    if "email" in changes:
        changes["email"] = str(changes["email"]).lower()
        if changes["email"] != (c.get("email") or "").lower():
            await _ensure_unique_email(db, changes["email"], exclude=c["_id"])
    changes = {k: v for k, v in changes.items() if v != c.get(k)}
    if changes:
        changes["updated_at"] = utc_iso()
        await db.customers.update_one({"_id": c["_id"]}, {"$set": changes})
        if "name" in changes:
            # Keep the denormalised name on CRM records in step.
            await db.crm_notes.update_many({"customer_id": customer_id}, {"$set": {"customer_name": changes["name"]}})
            await db.crm_followups.update_many({"customer_id": customer_id}, {"$set": {"customer_name": changes["name"]}})
        await log_activity(db, current, "Updated customer", MODULE, target=changes.get("name", c.get("name")),
                           meta={"customer_id": customer_id, "fields": [k for k in changes if k != "updated_at"]})
    rows = await _compute_rows(db, {"_id": c["_id"]})
    return rows[0]


@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: str, current: UserPublic = Depends(edit_user)):
    db = get_db()
    c = await _customer_or_404(db, customer_id)
    bookings = await db.bookings.count_documents({"customer_id": customer_id})
    if bookings:
        raise HTTPException(409, f"This customer has {bookings} booking(s) and can't be deleted")
    tickets = await db.support_tickets.count_documents({"customer_id": customer_id})
    if tickets:
        raise HTTPException(409, f"This customer has {tickets} support ticket(s) and can't be deleted")
    await db.customers.delete_one({"_id": c["_id"]})
    await db.crm_profiles.delete_many({"customer_id": customer_id})
    await db.crm_notes.delete_many({"customer_id": customer_id})
    await db.crm_followups.delete_many({"customer_id": customer_id})
    await db.kyc_requests.delete_many({"subject_type": "customer", "subject_id": customer_id})
    await log_activity(db, current, "Deleted customer", MODULE, target=c.get("name"), meta={"customer_id": customer_id})
    return {"ok": True}


# ------------------------- tags -------------------------

class TagsIn(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=100)


@router.put("/customers/{customer_id}/tags")
async def set_tags(customer_id: str, payload: TagsIn, current: UserPublic = Depends(edit_user)):
    db = get_db()
    c = await _customer_or_404(db, customer_id)
    tags = _clean_tags(payload.tags)
    before = await db.crm_profiles.find_one({"customer_id": customer_id}) or {}
    await db.crm_profiles.update_one(
        {"customer_id": customer_id},
        {"$set": {"tags": tags, "updated_at": utc_iso(), "updated_by": current.id},
         "$setOnInsert": {"customer_id": customer_id, "created_at": utc_iso()}},
        upsert=True,
    )
    old = before.get("tags", [])
    added = [t for t in tags if t not in old]
    removed = [t for t in old if t not in tags]
    await log_activity(db, current, "Updated customer tags", MODULE, target=c.get("name"),
                       meta={"customer_id": customer_id, "added": added, "removed": removed})
    return {"customer_id": customer_id, "tags": tags}


# ------------------------- notes -------------------------

class NoteIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(..., min_length=1, max_length=5000)
    pinned: bool = False


class NotePatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: Optional[str] = Field(None, min_length=1, max_length=5000)
    pinned: Optional[bool] = None


@router.post("/customers/{customer_id}/notes", status_code=201)
async def add_note(customer_id: str, payload: NoteIn, current: UserPublic = Depends(edit_user)):
    db = get_db()
    c = await _customer_or_404(db, customer_id)
    now = utc_iso()  # one timestamp: the UI shows "edited" whenever updated_at differs from created_at
    doc = {
        "customer_id": customer_id, "customer_name": c.get("name"),
        "body": payload.body, "pinned": payload.pinned,
        "author_id": current.id, "author_name": current.name,
        "created_at": now, "updated_at": now,
    }
    res = await db.crm_notes.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Added customer note", MODULE, target=c.get("name"),
                       meta={"customer_id": customer_id, "note_id": str(res.inserted_id)})
    return _note_out(doc)


async def _note_for_write(db, note_id: str, current: UserPublic) -> dict:
    note = await db.crm_notes.find_one({"_id": _doc_oid(note_id, "Note")})
    if not note:
        raise HTTPException(404, "Note not found")
    if note.get("author_id") != current.id and current.role not in ("Founder", "Admin"):
        raise HTTPException(403, "Only the author, a Founder or an Admin can change this note")
    return note


@router.patch("/notes/{note_id}")
async def update_note(note_id: str, payload: NotePatch, current: UserPublic = Depends(edit_user)):
    db = get_db()
    note = await _note_for_write(db, note_id, current)
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "Nothing to update")
    # updated_at marks the note as edited in the UI, so only a changed body moves it (pinning doesn't).
    if changes.get("body") is not None and changes["body"] != note.get("body"):
        changes["updated_at"] = utc_iso()
    else:
        changes.pop("body", None)
    if not changes:
        return _note_out(note)
    await db.crm_notes.update_one({"_id": note["_id"]}, {"$set": changes})
    doc = await db.crm_notes.find_one({"_id": note["_id"]})
    action = ("Pinned customer note" if changes.get("pinned") else "Unpinned customer note") \
        if "body" not in changes else "Edited customer note"
    await log_activity(db, current, action, MODULE, target=note.get("customer_name"),
                       meta={"customer_id": note["customer_id"], "note_id": note_id})
    return _note_out(doc)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, current: UserPublic = Depends(edit_user)):
    db = get_db()
    note = await _note_for_write(db, note_id, current)
    await db.crm_notes.delete_one({"_id": note["_id"]})
    await log_activity(db, current, "Deleted customer note", MODULE, target=note.get("customer_name"),
                       meta={"customer_id": note["customer_id"], "note_id": note_id})
    return {"ok": True}


# ------------------------- follow-ups -------------------------

def _parse_due(value: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except (AttributeError, ValueError):
        raise ValueError("due_date must be YYYY-MM-DD")


class FollowupIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(..., min_length=1, max_length=200)
    due_date: str
    owner_id: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("due_date")
    @classmethod
    def _due(cls, v):
        return _parse_due(v)


class FollowupPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    due_date: Optional[str] = None
    owner_id: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=2000)
    done: Optional[bool] = None

    @field_validator("due_date")
    @classmethod
    def _due(cls, v):
        return None if v is None else _parse_due(v)


async def _resolve_owner(db, owner_id: Optional[str], current: UserPublic) -> tuple[str, str]:
    if not owner_id or owner_id == current.id:
        return current.id, current.name
    if not ObjectId.is_valid(owner_id):
        raise ValueError("Unknown owner")
    u = await db.users.find_one({"_id": ObjectId(owner_id)}, {"name": 1, "role": 1, "status": 1, "is_active": 1})
    if not u or u.get("status") == "deactivated" or u.get("is_active") is False:
        raise ValueError("Unknown owner")
    if not can(u.get("role"), "crm.view"):
        raise ValueError("The owner must have access to CRM")
    return str(u["_id"]), u.get("name")


def _customer_link(customer_id: str) -> str:
    return f"/crm?customer={customer_id}"


@router.get("/followups")
async def list_followups(
    status: Literal["open", "done", "all"] = "open",
    mine: bool = False,
    customer_id: Optional[str] = None,
    current: UserPublic = Depends(view_user),
):
    db = get_db()
    q: dict = {}
    if status != "all":
        q["done"] = status == "done"
    if mine:
        q["owner_id"] = current.id
    if customer_id:
        q["customer_id"] = customer_id
    sort = [("done", 1), ("due_date", 1), ("_id", 1)] if status != "done" else [("done_at", -1)]
    docs = await db.crm_followups.find(q).sort(sort).to_list(1000)
    today = _today_local().isoformat()
    return [_followup_out(d, today) for d in docs]


@router.post("/customers/{customer_id}/followups", status_code=201)
async def add_followup(customer_id: str, payload: FollowupIn, current: UserPublic = Depends(edit_user)):
    db = get_db()
    c = await _customer_or_404(db, customer_id)
    owner_id, owner_name = await _resolve_owner(db, payload.owner_id, current)
    doc = {
        "customer_id": customer_id, "customer_name": c.get("name"),
        "title": payload.title, "notes": payload.notes, "due_date": payload.due_date,
        "owner_id": owner_id, "owner_name": owner_name,
        "created_by": current.id, "created_by_name": current.name,
        "done": False, "done_at": None, "done_by_name": None,
        "created_at": utc_iso(), "updated_at": utc_iso(),
    }
    res = await db.crm_followups.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Scheduled customer follow-up", MODULE, target=c.get("name"),
                       meta={"customer_id": customer_id, "followup_id": str(res.inserted_id), "due_date": payload.due_date})
    if owner_id != current.id:
        await notify(db, owner_id, "CRM follow-up assigned",
                     f"{current.name} assigned you a follow-up with {c.get('name')}: {payload.title} (due {payload.due_date}).",
                     kind="info", link=_customer_link(customer_id))
    return _followup_out(doc)


@router.patch("/followups/{followup_id}")
async def update_followup(followup_id: str, payload: FollowupPatch, current: UserPublic = Depends(edit_user)):
    db = get_db()
    f = await db.crm_followups.find_one({"_id": _doc_oid(followup_id, "Follow-up")})
    if not f:
        raise HTTPException(404, "Follow-up not found")
    data = payload.model_dump(exclude_unset=True)
    changes = {k: v for k, v in data.items() if k in ("title", "due_date", "notes") and (v is not None or k == "notes")}
    if "owner_id" in data and data["owner_id"] and data["owner_id"] != f.get("owner_id"):
        changes["owner_id"], changes["owner_name"] = await _resolve_owner(db, data["owner_id"], current)
    if data.get("done") is not None and data["done"] != f.get("done"):
        changes["done"] = data["done"]
        changes["done_at"] = utc_iso() if data["done"] else None
        changes["done_by_name"] = current.name if data["done"] else None
    if not changes:
        return _followup_out(f)
    changes["updated_at"] = utc_iso()
    await db.crm_followups.update_one({"_id": f["_id"]}, {"$set": changes})
    doc = await db.crm_followups.find_one({"_id": f["_id"]})

    if changes.get("done") is True:
        action = "Completed customer follow-up"
    elif changes.get("done") is False:
        action = "Reopened customer follow-up"
    else:
        action = "Updated customer follow-up"
    await log_activity(db, current, action, MODULE, target=f.get("customer_name"),
                       meta={"customer_id": f["customer_id"], "followup_id": followup_id})
    link = _customer_link(f["customer_id"])
    if "owner_id" in changes and changes["owner_id"] != current.id:
        await notify(db, changes["owner_id"], "CRM follow-up assigned",
                     f"{current.name} assigned you a follow-up with {f.get('customer_name')}: {doc['title']} (due {doc['due_date']}).",
                     kind="info", link=link)
    elif "due_date" in changes and changes["due_date"] != f.get("due_date") and doc["owner_id"] != current.id:
        await notify(db, doc["owner_id"], "CRM follow-up rescheduled",
                     f"{doc['title']} with {f.get('customer_name')} is now due {doc['due_date']}.", kind="info", link=link)
    if changes.get("done") is True and f.get("created_by") and f["created_by"] != current.id:
        await notify(db, f["created_by"], "CRM follow-up completed",
                     f"{current.name} completed \"{doc['title']}\" with {f.get('customer_name')}.", kind="success", link=link)
    return _followup_out(doc)


@router.delete("/followups/{followup_id}")
async def delete_followup(followup_id: str, current: UserPublic = Depends(edit_user)):
    db = get_db()
    f = await db.crm_followups.find_one({"_id": _doc_oid(followup_id, "Follow-up")})
    if not f:
        raise HTTPException(404, "Follow-up not found")
    await db.crm_followups.delete_one({"_id": f["_id"]})
    await log_activity(db, current, "Deleted customer follow-up", MODULE, target=f.get("customer_name"),
                       meta={"customer_id": f["customer_id"], "followup_id": followup_id})
    return {"ok": True}


# ------------------------- segments -------------------------

class SegmentIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    filters: SegmentFilters


class SegmentPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    filters: Optional[SegmentFilters] = None


def _segment_out(seg: dict, rows: list[dict]) -> dict:
    out = serialize(seg)
    out.pop("name_lower", None)
    matched = apply_filters(rows, SegmentFilters(**(seg.get("filters") or {})))
    out["count"] = len(matched)
    out["ltv"] = round(sum(r["ltv"] for r in matched), 2)
    return out


async def _unique_name(db, name: str, exclude: Optional[ObjectId] = None):
    q = {"name_lower": name.lower()}
    if exclude:
        q["_id"] = {"$ne": exclude}
    if await db.crm_segments.find_one(q):
        raise HTTPException(409, "A segment with this name already exists")


@router.get("/segments")
async def list_segments(current: UserPublic = Depends(view_user)):
    db = get_db()
    segs = await db.crm_segments.find().sort("name_lower", 1).to_list(500)
    rows = await _compute_rows(db) if segs else []
    return [_segment_out(s, rows) for s in segs]


@router.post("/segments", status_code=201)
async def create_segment(payload: SegmentIn, current: UserPublic = Depends(edit_user)):
    db = get_db()
    if payload.filters.is_empty():
        raise HTTPException(400, "Pick at least one filter for the segment")
    await _unique_name(db, payload.name)
    doc = {
        "name": payload.name, "name_lower": payload.name.lower(), "description": payload.description,
        "filters": payload.filters.model_dump(exclude_none=True),
        "created_by": current.id, "created_by_name": current.name,
        "created_at": utc_iso(), "updated_at": utc_iso(),
    }
    res = await db.crm_segments.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Created customer segment", MODULE, target=payload.name,
                       meta={"segment_id": str(res.inserted_id)})
    return _segment_out(doc, await _compute_rows(db))


@router.patch("/segments/{segment_id}")
async def update_segment(segment_id: str, payload: SegmentPatch, current: UserPublic = Depends(edit_user)):
    db = get_db()
    seg = await db.crm_segments.find_one({"_id": _doc_oid(segment_id, "Segment")})
    if not seg:
        raise HTTPException(404, "Segment not found")
    changes = {}
    if payload.name is not None:
        await _unique_name(db, payload.name, seg["_id"])
        changes.update(name=payload.name, name_lower=payload.name.lower())
    if "description" in payload.model_fields_set:
        changes["description"] = payload.description
    if payload.filters is not None:
        if payload.filters.is_empty():
            raise HTTPException(400, "Pick at least one filter for the segment")
        changes["filters"] = payload.filters.model_dump(exclude_none=True)
    if changes:
        changes["updated_at"] = utc_iso()
        await db.crm_segments.update_one({"_id": seg["_id"]}, {"$set": changes})
        await log_activity(db, current, "Updated customer segment", MODULE, target=changes.get("name", seg["name"]),
                           meta={"segment_id": segment_id})
    doc = await db.crm_segments.find_one({"_id": seg["_id"]})
    return _segment_out(doc, await _compute_rows(db))


@router.delete("/segments/{segment_id}")
async def delete_segment(segment_id: str, current: UserPublic = Depends(edit_user)):
    db = get_db()
    seg = await db.crm_segments.find_one({"_id": _doc_oid(segment_id, "Segment")})
    if not seg:
        raise HTTPException(404, "Segment not found")
    in_use = await db.campaigns.count_documents({"audience_segment_id": segment_id})
    if in_use:
        raise HTTPException(409, f"This segment is the audience of {in_use} campaign(s); change them first")
    await db.crm_segments.delete_one({"_id": seg["_id"]})
    await log_activity(db, current, "Deleted customer segment", MODULE, target=seg.get("name"),
                       meta={"segment_id": segment_id})
    return {"ok": True}
