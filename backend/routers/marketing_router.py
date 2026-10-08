"""Marketing module API (mounted at /api/marketing) — campaigns.

Campaigns live in `campaigns`. A campaign's stored `mode` is one of draft / live / paused /
completed; the status shown to users is derived:
  draft, paused, completed (ended early)  -> as stored
  live -> scheduled before start_date, completed after end_date, active in between
Dates are calendar days in the company timezone (Asia/Kolkata), end date inclusive.

Attribution uses only what marketplace data records. A booking is attributed to a campaign
when it carries one of the campaign's linked coupon codes (booking field `coupon_code` or
`coupon`) and was created inside the campaign window. Until some booking has redeemed a coupon,
attribution reports `supported: false`; coupon `used_count`
is lifetime-only and cannot be split by date, so it is shown as context, never attributed.
"""
# No `from __future__ import annotations`: FastAPI resolves body models from runtime annotations.
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from db import get_db
from auth_utils import get_current_user
from models import UserPublic
from hub_utils import serialize, utc_iso, log_activity, notify
from permissions import can
from routers.crm_router import segment_customer_ids

router = APIRouter(prefix="/marketing", tags=["marketing"])

MODULE = "Marketing"
COMPANY_TZ = ZoneInfo("Asia/Kolkata")
REVENUE_STATUSES = ("confirmed", "active", "completed")
# Booking fields that may carry the coupon code a customer redeemed.
BOOKING_COUPON_FIELDS = ("coupon_code", "coupon")
ATTRIBUTION_UNSUPPORTED_REASON = (
    "No marketplace booking has redeemed a coupon yet, so bookings and revenue can't be "
    "attributed to campaigns yet. Coupon redemption counts are lifetime totals and can't be split by campaign dates."
)

CHANNELS = ("social", "search", "email", "sms", "whatsapp", "push", "referral", "influencer", "partnership", "offline")
OBJECTIVES = ("awareness", "acquisition", "activation", "retention", "reactivation", "referral")
MODES = ("draft", "live", "paused", "completed")
STATUSES = ("draft", "scheduled", "active", "paused", "completed")
TOP_CAMPAIGNS = 5


# ------------------------- permissions -------------------------

def _require(action: str):
    async def dep(current: UserPublic = Depends(get_current_user)) -> UserPublic:
        if not can(current.role, action):
            raise HTTPException(403, "You don't have permission to do this")
        return current
    return dep


view_user = _require("marketing.view")
manage_user = _require("marketing.manage")


# ------------------------- helpers -------------------------

def _today() -> date:
    return datetime.now(COMPANY_TZ).date()


def _to_dt(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _parse_day(value, field: str) -> str:
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be YYYY-MM-DD")


def derive_status(mode: str, start_date: str, end_date: str, today: Optional[date] = None) -> str:
    if mode != "live":
        return mode
    today = (today or _today()).isoformat()
    if today < start_date:
        return "scheduled"
    if today > end_date:
        return "completed"
    return "active"


def campaign_window(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """[start 00:00 IST, day after end 00:00 IST) as UTC instants."""
    start = datetime.combine(date.fromisoformat(start_date), time.min, COMPANY_TZ)
    end = datetime.combine(date.fromisoformat(end_date) + timedelta(days=1), time.min, COMPANY_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _norm_code(code) -> str:
    return str(code or "").strip().upper()


def _booking_coupon(b: dict) -> str:
    for f in BOOKING_COUPON_FIELDS:
        if b.get(f):
            return _norm_code(b[f])
    return ""


def attribution_metrics(spend: float, bookings: list[dict]) -> dict:
    """bookings = attributed bookings. Revenue counts revenue statuses only; cost per booking and ROI
    use revenue bookings. ROI = (revenue - spend) / spend, None when nothing was spent."""
    revenue_bookings = [b for b in bookings if b.get("status") in REVENUE_STATUSES]
    revenue = round(sum(float(b.get("amount") or 0) for b in revenue_bookings), 2)
    n = len(revenue_bookings)
    return {
        "bookings": n,
        "all_bookings": len(bookings),
        "revenue": revenue,
        "cost_per_booking": round(spend / n, 2) if n and spend else None,
        "roi": round((revenue - spend) / spend * 100, 1) if spend else None,
    }


async def attribution_supported(db) -> bool:
    q = {"$or": [{f: {"$exists": True, "$nin": [None, ""]}} for f in BOOKING_COUPON_FIELDS]}
    return await db.bookings.find_one(q, {"_id": 1}) is not None


async def _coupon_bookings(db) -> list[dict]:
    q = {"$or": [{f: {"$exists": True, "$nin": [None, ""]}} for f in BOOKING_COUPON_FIELDS]}
    proj = {"amount": 1, "status": 1, "created_at": 1, "start_time": 1, "city": 1, "customer_id": 1,
            **{f: 1 for f in BOOKING_COUPON_FIELDS}}
    return await db.bookings.find(q, proj).to_list(None)


def _attributed(c: dict, coupon_bookings: list[dict]) -> list[dict]:
    codes = {_norm_code(x) for x in c.get("coupon_codes") or []}
    if not codes:
        return []
    start, end = campaign_window(c["start_date"], c["end_date"])
    out = []
    for b in coupon_bookings:
        if _booking_coupon(b) not in codes:
            continue
        at = _to_dt(b.get("created_at")) or _to_dt(b.get("start_time"))
        if at and start <= at < end:
            out.append(b)
    return out


def _campaign_out(c: dict, supported: bool, coupon_bookings: list[dict], today: Optional[date] = None) -> dict:
    out = serialize(c)
    out["status"] = derive_status(c["mode"], c["start_date"], c["end_date"], today)
    spend = float(c.get("spend") or 0)
    budget = float(c.get("budget") or 0)
    out["budget_used_pct"] = round(spend / budget * 100, 1) if budget else None
    out["over_budget"] = spend > budget
    if supported:
        out["attribution"] = {"supported": True, **attribution_metrics(spend, _attributed(c, coupon_bookings))}
    else:
        out["attribution"] = {"supported": False, "bookings": None, "revenue": None,
                              "cost_per_booking": None, "roi": None}
    return out


async def _load_attribution(db) -> tuple[bool, list[dict]]:
    supported = await attribution_supported(db)
    return supported, (await _coupon_bookings(db) if supported else [])


# ------------------------- payloads -------------------------

class _CampaignFields(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data):
        if isinstance(data, dict):
            return {k: (None if isinstance(v, str) and not v.strip() else v) for k, v in data.items()}
        return data


class CampaignIn(_CampaignFields):
    name: str = Field(..., min_length=1, max_length=120)
    objective: Literal[OBJECTIVES] = "acquisition"  # type: ignore[valid-type]
    channels: list[Literal[CHANNELS]] = Field(..., min_length=1)  # type: ignore[valid-type]
    audience_segment_id: Optional[str] = None
    audience_note: Optional[str] = Field(None, max_length=500)
    city_targets: list[str] = Field(default_factory=list, max_length=50)
    budget: float = Field(..., ge=0)
    spend: float = Field(0, ge=0)
    start_date: str
    end_date: str
    mode: Literal[MODES] = "draft"  # type: ignore[valid-type]
    coupon_codes: list[str] = Field(default_factory=list, max_length=20)
    owner_id: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("start_date", "end_date")
    @classmethod
    def _day(cls, v, info):
        return _parse_day(v, info.field_name)

    @model_validator(mode="after")
    def _range(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date")
        self.channels = list(dict.fromkeys(self.channels))
        return self


class CampaignPatch(_CampaignFields):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    objective: Optional[Literal[OBJECTIVES]] = None  # type: ignore[valid-type]
    channels: Optional[list[Literal[CHANNELS]]] = Field(None, min_length=1)  # type: ignore[valid-type]
    audience_segment_id: Optional[str] = None
    audience_note: Optional[str] = Field(None, max_length=500)
    city_targets: Optional[list[str]] = Field(None, max_length=50)
    budget: Optional[float] = Field(None, ge=0)
    spend: Optional[float] = Field(None, ge=0)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    mode: Optional[Literal[MODES]] = None  # type: ignore[valid-type]
    coupon_codes: Optional[list[str]] = Field(None, max_length=20)
    owner_id: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("start_date", "end_date")
    @classmethod
    def _day(cls, v, info):
        return None if v is None else _parse_day(v, info.field_name)


NULLABLE = {"audience_segment_id", "audience_note", "notes"}


async def _validate_refs(db, data: dict, current: UserPublic, before: Optional[dict] = None) -> dict:
    """Resolve and validate references; returns the fields to store. On update (`before`), values the
    campaign already holds are kept even if their segment / city / coupon / owner has since been renamed
    or removed, so an unrelated edit never fails; the user can still clear or replace them."""
    before = before or {}
    out = {}
    if "audience_segment_id" in data:
        sid = data["audience_segment_id"]
        if sid and sid == before.get("audience_segment_id"):
            out["audience_segment_id"], out["audience_segment_name"] = sid, before.get("audience_segment_name")
        elif sid:
            seg = await db.crm_segments.find_one({"_id": ObjectId(sid)}) if ObjectId.is_valid(sid) else None
            if not seg:
                raise ValueError("Unknown CRM segment")
            out["audience_segment_id"], out["audience_segment_name"] = sid, seg.get("name")
        else:
            out["audience_segment_id"], out["audience_segment_name"] = None, None
    if data.get("city_targets") is not None:
        known = {c["name"].lower(): c["name"] for c in await db.cities.find({}, {"name": 1}).to_list(None) if c.get("name")}
        for old in before.get("city_targets") or []:
            known.setdefault(str(old).lower(), old)
        cities = []
        for city in data["city_targets"]:
            name = known.get(str(city).strip().lower())
            if not name:
                raise ValueError(f"Unknown city: {city}")
            if name not in cities:
                cities.append(name)
        out["city_targets"] = cities
    if data.get("coupon_codes") is not None:
        known = {_norm_code(c["code"]): c["code"] for c in await db.coupons.find({}, {"code": 1}).to_list(None) if c.get("code")}
        for old in before.get("coupon_codes") or []:
            known.setdefault(_norm_code(old), old)
        codes = []
        for code in data["coupon_codes"]:
            real = known.get(_norm_code(code))
            if not real:
                raise ValueError(f"Unknown coupon code: {code}")
            if real not in codes:
                codes.append(real)
        out["coupon_codes"] = codes
    if "owner_id" in data:
        owner_id = data["owner_id"] or current.id
        if owner_id == current.id:
            out["owner_id"], out["owner_name"] = current.id, current.name
        elif owner_id == before.get("owner_id"):
            out["owner_id"], out["owner_name"] = owner_id, before.get("owner_name")
        else:
            u = await db.users.find_one({"_id": ObjectId(owner_id)}) if ObjectId.is_valid(owner_id) else None
            if not u or u.get("status") == "deactivated" or u.get("is_active") is False:
                raise ValueError("Unknown owner")
            if not can(u.get("role"), "marketing.view"):
                raise ValueError("The owner must have access to Marketing")
            out["owner_id"], out["owner_name"] = str(u["_id"]), u.get("name")
    return out


def _campaign_oid(campaign_id: str) -> ObjectId:
    if not ObjectId.is_valid(campaign_id):
        raise HTTPException(404, "Campaign not found")
    return ObjectId(campaign_id)


# ------------------------- indexes -------------------------

async def ensure_indexes(db) -> None:
    """Indexes for campaigns. Idempotent."""
    await db.campaigns.create_index([("mode", 1), ("start_date", 1), ("end_date", 1)])
    await db.campaigns.create_index("owner_id")
    await db.campaigns.create_index("audience_segment_id")


# ------------------------- meta & overview -------------------------

@router.get("/meta")
async def marketing_meta(current: UserPublic = Depends(view_user)):
    db = get_db()
    coupons = await db.coupons.find({}, {"code": 1, "discount_pct": 1, "active": 1, "used_count": 1,
                                         "usage_limit": 1, "valid_from": 1, "valid_till": 1}).sort("code", 1).to_list(None)
    cities = sorted(c["name"] for c in await db.cities.find({}, {"name": 1}).to_list(None) if c.get("name"))
    segments = await db.crm_segments.find({}, {"name": 1}).sort("name_lower", 1).to_list(None)
    supported = await attribution_supported(db)
    return {
        "channels": list(CHANNELS),
        "objectives": list(OBJECTIVES),
        "statuses": list(STATUSES),
        "coupons": [serialize(c) for c in coupons],
        "cities": cities,
        "segments": [{"id": str(s["_id"]), "name": s.get("name")} for s in segments],
        "attribution": {"supported": supported, "reason": None if supported else ATTRIBUTION_UNSUPPORTED_REASON},
        "can_manage": can(current.role, "marketing.manage"),
    }


@router.get("/overview")
async def marketing_overview(current: UserPublic = Depends(view_user)):
    db = get_db()
    supported, coupon_bookings = await _load_attribution(db)
    today = _today()
    rows = [_campaign_out(c, supported, coupon_bookings, today) for c in await db.campaigns.find().to_list(None)]
    by_status = {s: 0 for s in STATUSES}
    for r in rows:
        by_status[r["status"]] += 1
    # Draft campaigns are plans, not commitments: they are left out of budget and spend totals.
    committed = [r for r in rows if r["status"] != "draft"]
    total_budget = round(sum(float(r.get("budget") or 0) for r in committed), 2)
    total_spend = round(sum(float(r.get("spend") or 0) for r in committed), 2)
    # A campaign's spend is split evenly across its channels (spend is not tracked per channel).
    by_channel: dict[str, float] = {}
    for r in committed:
        chans = r.get("channels") or []
        for ch in chans:
            by_channel[ch] = by_channel.get(ch, 0) + float(r.get("spend") or 0) / len(chans)
    top = []
    if supported:
        top = sorted((r for r in rows if (r["attribution"]["revenue"] or 0) > 0),
                     key=lambda r: r["attribution"]["revenue"], reverse=True)[:TOP_CAMPAIGNS]
    total_rev = sum(r["attribution"]["revenue"] or 0 for r in committed) if supported else None
    return {
        "totals": {
            "campaigns": len(rows),
            "active": by_status["active"],
            "scheduled": by_status["scheduled"],
            "total_budget": total_budget,
            "total_spend": total_spend,
            "budget_used_pct": round(total_spend / total_budget * 100, 1) if total_budget else None,
            "attributed_revenue": round(total_rev, 2) if total_rev is not None else None,
            "attributed_bookings": sum(r["attribution"]["bookings"] or 0 for r in committed) if supported else None,
        },
        "by_status": [{"status": s, "count": by_status[s]} for s in STATUSES],
        "spend_by_channel": sorted(({"channel": k, "spend": round(v, 2)} for k, v in by_channel.items() if v > 0),
                                   key=lambda x: x["spend"], reverse=True),
        "top_campaigns": [{"id": r["id"], "name": r["name"], "status": r["status"], "spend": r.get("spend", 0),
                           **{k: r["attribution"][k] for k in ("bookings", "revenue", "roi")}} for r in top],
        "attribution": {"supported": supported, "reason": None if supported else ATTRIBUTION_UNSUPPORTED_REASON},
    }


# ------------------------- campaigns -------------------------

@router.get("/campaigns")
async def list_campaigns(
    q: Optional[str] = Query(None, max_length=100),
    status: Optional[Literal["draft", "scheduled", "active", "paused", "completed"]] = None,
    channel: Optional[str] = None,
    owner: Optional[str] = None,
    current: UserPublic = Depends(view_user),
):
    db = get_db()
    query: dict = {}
    if q:
        query["name"] = {"$regex": re.escape(q), "$options": "i"}
    if channel:
        query["channels"] = channel
    if owner:
        query["owner_id"] = current.id if owner == "me" else owner
    supported, coupon_bookings = await _load_attribution(db)
    today = _today()
    docs = await db.campaigns.find(query).sort([("start_date", -1), ("_id", -1)]).to_list(1000)
    rows = [_campaign_out(c, supported, coupon_bookings, today) for c in docs]
    if status:
        rows = [r for r in rows if r["status"] == status]
    order = {"active": 0, "scheduled": 1, "paused": 2, "draft": 3, "completed": 4}
    rows.sort(key=lambda r: order[r["status"]])  # stable: keeps newest start first within a status
    return rows


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, current: UserPublic = Depends(view_user)):
    db = get_db()
    c = await db.campaigns.find_one({"_id": _campaign_oid(campaign_id)})
    if not c:
        raise HTTPException(404, "Campaign not found")
    supported, coupon_bookings = await _load_attribution(db)
    out = _campaign_out(c, supported, coupon_bookings)
    if not supported:
        out["attribution"]["reason"] = ATTRIBUTION_UNSUPPORTED_REASON

    # Context (not attribution): linked coupons' lifetime redemptions and market activity in the window.
    coupons = await db.coupons.find({"code": {"$in": c.get("coupon_codes") or []}}).to_list(None)
    out["coupons"] = [{"code": x["code"], "discount_pct": x.get("discount_pct"), "active": x.get("active"),
                       "used_count": x.get("used_count", 0), "usage_limit": x.get("usage_limit"),
                       "valid_from": x.get("valid_from"), "valid_till": x.get("valid_till")} for x in coupons]
    start, end = campaign_window(c["start_date"], c["end_date"])
    bq = {"status": {"$in": list(REVENUE_STATUSES)}}
    if c.get("city_targets"):
        bq["city"] = {"$in": c["city_targets"]}
    window = []
    async for b in db.bookings.find(bq, {"amount": 1, "created_at": 1, "start_time": 1}):
        at = _to_dt(b.get("created_at")) or _to_dt(b.get("start_time"))
        if at and start <= at < end:
            window.append(b)
    out["market_context"] = {
        "cities": c.get("city_targets") or [],
        "bookings": len(window),
        "revenue": round(sum(float(b.get("amount") or 0) for b in window), 2),
    }
    if c.get("audience_segment_id"):
        ids = await segment_customer_ids(db, c["audience_segment_id"])
        out["audience_size"] = len(ids) if ids is not None else None
    return out


def _changed_fields(before: dict, changes: dict) -> list[str]:
    return [k for k, v in changes.items() if k != "updated_at" and before.get(k) != v]


@router.post("/campaigns", status_code=201)
async def create_campaign(payload: CampaignIn, current: UserPublic = Depends(manage_user)):
    db = get_db()
    data = payload.model_dump()
    doc = {k: v for k, v in data.items() if k not in ("audience_segment_id", "city_targets", "coupon_codes", "owner_id")}
    doc.update(await _validate_refs(db, data, current))
    doc.update(created_by=current.id, created_by_name=current.name, created_at=utc_iso(), updated_at=utc_iso())
    res = await db.campaigns.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Created campaign", MODULE, target=doc["name"],
                       meta={"campaign_id": str(res.inserted_id), "budget": doc["budget"]})
    if doc["owner_id"] != current.id:
        await notify(db, doc["owner_id"], "Campaign assigned to you",
                     f"{current.name} made you the owner of \"{doc['name']}\".", kind="info",
                     link=f"/marketing?campaign={res.inserted_id}")
    supported, coupon_bookings = await _load_attribution(db)
    return _campaign_out(doc, supported, coupon_bookings)


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, payload: CampaignPatch, current: UserPublic = Depends(manage_user)):
    db = get_db()
    before = await db.campaigns.find_one({"_id": _campaign_oid(campaign_id)})
    if not before:
        raise HTTPException(404, "Campaign not found")
    data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None or k in NULLABLE}
    start = data.get("start_date", before["start_date"])
    end = data.get("end_date", before["end_date"])
    if end < start:
        raise ValueError("End date must be on or after the start date")
    changes = {k: v for k, v in data.items() if k not in ("audience_segment_id", "city_targets", "coupon_codes", "owner_id")}
    if "channels" in changes:
        changes["channels"] = list(dict.fromkeys(changes["channels"]))
    changes.update(await _validate_refs(db, data, current, before))
    changed = _changed_fields(before, changes)
    if not changed:
        supported, coupon_bookings = await _load_attribution(db)
        return _campaign_out(before, supported, coupon_bookings)
    changes["updated_at"] = utc_iso()
    await db.campaigns.update_one({"_id": before["_id"]}, {"$set": changes})
    doc = await db.campaigns.find_one({"_id": before["_id"]})

    old_status = derive_status(before["mode"], before["start_date"], before["end_date"])
    new_status = derive_status(doc["mode"], doc["start_date"], doc["end_date"])
    if changed == ["spend"]:
        action = "Updated campaign spend"
    elif "mode" in changed:
        action = {"live": "Launched campaign" if before["mode"] == "draft" else "Resumed campaign",
                  "paused": "Paused campaign", "completed": "Ended campaign", "draft": "Moved campaign to draft"}[doc["mode"]]
    else:
        action = "Updated campaign"
    await log_activity(db, current, action, MODULE, target=doc["name"],
                       meta={"campaign_id": campaign_id, "fields": changed, "status": new_status})
    link = f"/marketing?campaign={campaign_id}"
    if "owner_id" in changed and doc["owner_id"] != current.id:
        await notify(db, doc["owner_id"], "Campaign assigned to you",
                     f"{current.name} made you the owner of \"{doc['name']}\".", kind="info", link=link)
    elif old_status != new_status and doc.get("owner_id") and doc["owner_id"] != current.id:
        await notify(db, doc["owner_id"], f"Campaign {new_status}",
                     f"{current.name} changed \"{doc['name']}\" from {old_status} to {new_status}.",
                     kind="warning" if new_status == "paused" else "info", link=link)
    if "spend" in changed and float(doc.get("spend") or 0) > float(doc.get("budget") or 0) \
            and float(before.get("spend") or 0) <= float(before.get("budget") or 0) \
            and doc.get("owner_id") and doc["owner_id"] != current.id:
        await notify(db, doc["owner_id"], "Campaign over budget",
                     f"\"{doc['name']}\" has spent ₹{doc['spend']:,.0f} of a ₹{doc['budget']:,.0f} budget.",
                     kind="warning", link=link)
    supported, coupon_bookings = await _load_attribution(db)
    return _campaign_out(doc, supported, coupon_bookings)


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, current: UserPublic = Depends(manage_user)):
    db = get_db()
    c = await db.campaigns.find_one({"_id": _campaign_oid(campaign_id)})
    if not c:
        raise HTTPException(404, "Campaign not found")
    await db.campaigns.delete_one({"_id": c["_id"]})
    await log_activity(db, current, "Deleted campaign", MODULE, target=c.get("name"), meta={"campaign_id": campaign_id})
    if c.get("owner_id") and c["owner_id"] != current.id:
        await notify(db, c["owner_id"], "Campaign deleted", f"{current.name} deleted \"{c.get('name')}\".",
                     kind="warning", link="/marketing")
    return {"ok": True}
