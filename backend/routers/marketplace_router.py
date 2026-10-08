from __future__ import annotations
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Annotated, Literal, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator, model_validator
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import BookingIn, KycIn, SupportIn
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify

# Whole module is Founder-only (permissions.py `marketplace.any`); endpoints add no extra role gates.
router = APIRouter(prefix="/marketplace", tags=["marketplace"],
                   dependencies=[Depends(require_roles("Founder"))])

# Bookings that hold a vehicle, and the ones that count towards revenue.
HOLDING_STATUSES = ("confirmed", "active")
REVENUE_STATUSES = ["confirmed", "active", "completed"]
STATUS_ORDER = ["pending", "confirmed", "active", "completed", "cancelled"]
# Allowed booking status moves; completed / cancelled are terminal.
BOOKING_TRANSITIONS = {
    "pending": {"confirmed", "active", "cancelled"},
    "confirmed": {"pending", "active", "cancelled"},
    "active": {"completed"},
}
# "Today" (bookings created today, coupon validity) follows the company's timezone.
IST = ZoneInfo("Asia/Kolkata")


def _ist_today() -> str:
    return datetime.now(IST).date().isoformat()


# -------- Client payload models (allow-lists; server-managed fields are absent) --------

Text = Annotated[str, Field(min_length=1, max_length=200)]
Money = Annotated[float, Field(ge=0)]


class _Payload(BaseModel):
    """Unknown or server-managed keys (id, created_at, rating, used_count, ...) are dropped;
    blank strings count as missing."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data):
        if isinstance(data, dict):
            return {k: (None if isinstance(v, str) and not v.strip() else v) for k, v in data.items()}
        return data


class CityPayload(_Payload):
    name: Text
    state: Text = "Bihar"
    status: Literal["active", "paused", "planned"] = "active"


class VendorPayload(_Payload):
    name: Text
    contact_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    city: Text
    active: bool = True
    notes: Optional[str] = None


class VehiclePayload(_Payload):
    model: Text
    kind: Literal["bike", "scooter", "ebike"] = "scooter"
    plate: Text
    vendor_id: Optional[str] = None
    city: Text
    hourly_rate: Money = 40.0
    daily_rate: Money = 399.0
    status: Literal["available", "booked", "maintenance", "retired"] = "available"


class CustomerPayload(_Payload):
    name: Text
    email: EmailStr
    phone: Optional[str] = None
    city: Text


class PricingPayload(_Payload):
    name: Text
    city: Text
    hourly: Money = 40.0
    daily: Money = 399.0
    weekly: Money = 1999.0
    monthly: Money = 6499.0
    active: bool = True


class CouponPayload(_Payload):
    code: Annotated[str, Field(min_length=1, max_length=40)]
    discount_pct: float = Field(10.0, gt=0, le=100)
    valid_from: Optional[str] = None
    valid_till: Optional[str] = None
    usage_limit: int = Field(100, ge=0)
    active: bool = True

    @field_validator("code")
    @classmethod
    def _upper_code(cls, v: str) -> str:
        # Codes are redeemed case-insensitively, so store one canonical spelling.
        return v.upper()

    @field_validator("valid_from", "valid_till")
    @classmethod
    def _iso_day(cls, v: Optional[str]) -> Optional[str]:
        # Validity is compared as YYYY-MM-DD text against today's IST date.
        if v is None:
            return v
        try:
            return datetime.strptime(v[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise ValueError("must be a date (YYYY-MM-DD)")

    @model_validator(mode="after")
    def _date_order(self):
        if self.valid_from and self.valid_till and self.valid_from > self.valid_till:
            raise ValueError("Valid from must be on or before valid till")
        return self


class ReviewPayload(_Payload):
    booking_id: Optional[str] = None
    customer_name: Text
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    rating: float = Field(5.0, ge=1, le=5)
    comment: Optional[str] = None


class SupportPayload(SupportIn):
    """Support tickets need a real subject and description (blank strings are rejected)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    subject: Text
    description: Annotated[str, Field(min_length=1, max_length=5000)]


class BookingCreate(BookingIn):
    amount: Money
    # Coupon redeemed on this booking; lets Marketing attribute bookings to campaigns.
    coupon_code: Optional[str] = Field(default=None, max_length=40)


async def _release_coupon(db, code: str):
    """Give back one use of a coupon (booking cancelled); never below zero."""
    code = code.strip().upper()
    await db.coupons.update_one(
        {"code": {"$regex": f"^{re.escape(code)}$", "$options": "i"}, "used_count": {"$gt": 0}},
        {"$inc": {"used_count": -1}})


async def _redeem_coupon(db, code: str) -> dict:
    """Validate a coupon and count one use atomically (a limit of 0 means unlimited)."""
    code = code.strip().upper()
    coupon = await db.coupons.find_one({"code": {"$regex": f"^{re.escape(code)}$", "$options": "i"}})
    if not coupon or not coupon.get("active", True):
        raise HTTPException(400, f"Coupon {code} is not active")
    today = _ist_today()
    if (coupon.get("valid_from") or "") > today or (coupon.get("valid_till") or "9999") < today:
        raise HTTPException(400, f"Coupon {code} is not valid today")
    cond = {"_id": coupon["_id"]}
    limit = coupon.get("usage_limit") or 0
    if limit > 0:
        cond["$expr"] = {"$lt": [{"$ifNull": ["$used_count", 0]}, limit]}
    res = await db.coupons.update_one(cond, {"$inc": {"used_count": 1}})
    if res.modified_count == 0:
        raise HTTPException(409, f"Coupon {code} has reached its usage limit")
    return coupon


async def _notify_founders(db, title: str, body: str, kind: str = "info"):
    """Marketplace is Founder-only, so its alerts go to Founders rather than a company-wide broadcast."""
    async for u in db.users.find({"role": "Founder", "status": {"$ne": "deactivated"}}, {"_id": 1}):
        await notify(db, str(u["_id"]), title, body, kind=kind, link="/marketplace")


def _validate(model_cls, data: dict) -> dict:
    """Validate a raw body against a payload model, surfacing errors as a normal 422."""
    try:
        return model_cls.model_validate(data).model_dump()
    except ValidationError as e:
        raise RequestValidationError(e.errors(include_url=False, include_context=False))


def _validate_patch(model_cls, existing: dict, payload: dict) -> dict:
    """Partial update: only fields the model knows are writable. The merged document is validated
    with the full model so a patch cannot leave it invalid; returns just the patched fields."""
    fields = model_cls.model_fields
    patch = {k: v for k, v in payload.items() if k in fields}
    merged = {**{k: existing[k] for k in fields if k in existing}, **patch}
    clean = _validate(model_cls, merged)
    return {k: clean[k] for k in patch}


async def _refresh_vendor_rating(db, review: dict | None):
    """Vendor rating is the average of its reviews (None until the first review)."""
    if not review:
        return
    vendor = None
    if review.get("vendor_id") and ObjectId.is_valid(review["vendor_id"]):
        vendor = await db.vendors.find_one({"_id": ObjectId(review["vendor_id"])})
    if not vendor and review.get("vendor_name"):
        vendor = await db.vendors.find_one({"name": review["vendor_name"]})
    if not vendor:
        return
    pipe = [
        {"$match": {"$or": [{"vendor_id": str(vendor["_id"])}, {"vendor_name": vendor["name"]}]}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}}},
    ]
    r = await db.reviews.aggregate(pipe).to_list(1)
    rating = round(r[0]["avg"], 1) if r and r[0]["avg"] is not None else None
    await db.vendors.update_one({"_id": vendor["_id"]}, {"$set": {"rating": rating}})


async def _ensure_unique(db, collection_name: str, field: str, value, exclude_id=None):
    """Case-insensitive uniqueness for a natural key (city name, plate, coupon code)."""
    if not isinstance(value, str):
        return
    q = {field: {"$regex": f"^{re.escape(value)}$", "$options": "i"}}
    if exclude_id is not None:
        q["_id"] = {"$ne": exclude_id}
    if await db[collection_name].find_one(q, {"_id": 1}):
        raise HTTPException(409, f"{field.replace('_', ' ').capitalize()} {value} already exists")


def _crud(collection_name: str, model_cls, module_name: str, title_field: str = "name",
          server_defaults: dict | None = None, on_change=None, unique: str | None = None,
          prepare=None, before_delete=None):
    """Generate a CRUD sub-router for a simple marketplace collection.
    `server_defaults` seeds server-managed fields on create; `on_change(db, doc)` runs after writes;
    `unique` names a field kept unique (case-insensitive); `prepare(db, changes, before)` may check or
    enrich validated fields before a write (`before` is None on create); `before_delete(db, doc)` may veto."""
    sub = APIRouter(prefix=f"/{collection_name}", tags=[f"marketplace-{collection_name}"])

    @sub.get("")
    async def list_items(q: str | None = None, limit: int = Query(200, ge=1, le=500),
                         current: UserPublic = Depends(get_current_user)):
        db = get_db()
        query = {}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            query = {"$or": [{"name": rx}, {title_field: rx}]}
        docs = await db[collection_name].find(query).sort("created_at", -1).to_list(limit)
        return serialize_many(docs)

    @sub.post("", status_code=201)
    async def create_item(payload: dict = Body(...), current: UserPublic = Depends(get_current_user)):
        db = get_db()
        doc = {**_validate(model_cls, payload), **(server_defaults or {})}
        if unique:
            await _ensure_unique(db, collection_name, unique, doc.get(unique))
        if prepare:
            await prepare(db, doc, None)
        doc["created_at"] = utc_iso()
        doc["updated_at"] = utc_iso()
        res = await db[collection_name].insert_one(doc)
        doc["_id"] = res.inserted_id
        if on_change:
            await on_change(db, doc)
        await log_activity(db, current, f"Created {module_name.rstrip('s')}", module_name, target=doc.get(title_field))
        return serialize(doc)

    @sub.get("/{item_id}")
    async def get_item(item_id: str, current: UserPublic = Depends(get_current_user)):
        db = get_db()
        doc = await db[collection_name].find_one({"_id": oid(item_id)})
        if not doc:
            raise HTTPException(404, "Not found")
        return serialize(doc)

    @sub.patch("/{item_id}")
    async def update_item(item_id: str, payload: dict = Body(...), current: UserPublic = Depends(get_current_user)):
        db = get_db()
        before = await db[collection_name].find_one({"_id": oid(item_id)})
        if not before:
            raise HTTPException(404, "Not found")
        changes = _validate_patch(model_cls, before, payload)
        if unique and unique in changes:
            await _ensure_unique(db, collection_name, unique, changes[unique], exclude_id=before["_id"])
        if prepare:
            await prepare(db, changes, before)
        changes["updated_at"] = utc_iso()
        await db[collection_name].update_one({"_id": before["_id"]}, {"$set": changes})
        doc = await db[collection_name].find_one({"_id": before["_id"]})
        if on_change:
            await on_change(db, before)
            await on_change(db, doc)
        await log_activity(db, current, f"Updated {module_name.rstrip('s')}", module_name, target=doc.get(title_field))
        return serialize(doc)

    @sub.delete("/{item_id}")
    async def delete_item(item_id: str, current: UserPublic = Depends(get_current_user)):
        db = get_db()
        doc = await db[collection_name].find_one({"_id": oid(item_id)})
        if not doc:
            raise HTTPException(404, "Not found")
        if before_delete:
            await before_delete(db, doc)
        await db[collection_name].delete_one({"_id": oid(item_id)})
        if on_change:
            await on_change(db, doc)
        await log_activity(db, current, f"Deleted {module_name.rstrip('s')}", module_name, target=doc.get(title_field))
        return {"ok": True}

    return sub


async def _vehicle_status_guard(db, changes: dict, before: dict | None):
    """Only bookings move a vehicle into / out of 'booked': a vehicle held by a confirmed or active
    booking keeps 'booked', and a free vehicle cannot be set to 'booked' by hand."""
    status = changes.get("status")
    if status is None or (before and status == before.get("status")):
        return
    if before is not None and await _vehicle_holder(db, str(before["_id"])):
        raise HTTPException(409, "Vehicle is held by a confirmed or active booking; complete or cancel it first")
    if status == "booked":
        raise HTTPException(400, "Vehicles become booked through a booking")


async def _vehicle_delete_guard(db, doc: dict):
    if await _vehicle_holder(db, str(doc["_id"])):
        raise HTTPException(409, "Vehicle is held by a confirmed or active booking; complete or cancel it first")


async def _review_vendor(db, changes: dict, before: dict | None):
    """A review picked by vendor id carries that vendor's current name (used for display and rating)."""
    if changes.get("vendor_id"):
        vendor = await db.vendors.find_one({"_id": oid(changes["vendor_id"])}, {"name": 1})
        if not vendor:
            raise HTTPException(400, "Unknown vendor")
        changes["vendor_name"] = vendor["name"]


router.include_router(_crud("cities",   CityPayload,     "Marketplace", "name", unique="name"))
router.include_router(_crud("vendors",  VendorPayload,   "Marketplace", "name",
                            server_defaults={"rating": None, "kyc_status": "pending"}))
router.include_router(_crud("vehicles", VehiclePayload,  "Marketplace", "plate", unique="plate",
                            prepare=_vehicle_status_guard, before_delete=_vehicle_delete_guard))
router.include_router(_crud("customers", CustomerPayload, "Marketplace", "name",
                            server_defaults={"kyc_status": "pending"}))
router.include_router(_crud("pricing",  PricingPayload,  "Marketplace", "name"))
router.include_router(_crud("coupons",  CouponPayload,   "Marketplace", "code",
                            server_defaults={"used_count": 0}, unique="code"))
router.include_router(_crud("reviews",  ReviewPayload,   "Marketplace", "customer_name",
                            on_change=_refresh_vendor_rating, prepare=_review_vendor))


# -------- Bookings (custom because of business logic) --------

def _parse_dt(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise HTTPException(422, f"Invalid {field}")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _vehicle_holder(db, vehicle_id: str, exclude_id=None):
    """Another booking currently holding the vehicle (confirmed / active), if any."""
    q = {"vehicle_id": vehicle_id, "status": {"$in": list(HOLDING_STATUSES)}}
    if exclude_id is not None:
        q["_id"] = {"$ne": exclude_id}
    return await db.bookings.find_one(q)


async def _sync_vehicle_status(db, vehicle_id: str | None, booking_status: str):
    """Vehicle is 'booked' while a booking holds it and 'available' once none does.
    Vehicles in maintenance / retired keep their status."""
    if not vehicle_id or not ObjectId.is_valid(vehicle_id):
        return
    if booking_status in HOLDING_STATUSES:
        await db.vehicles.update_one({"_id": ObjectId(vehicle_id), "status": "available"},
                                     {"$set": {"status": "booked", "updated_at": utc_iso()}})
    elif not await _vehicle_holder(db, vehicle_id):
        await db.vehicles.update_one({"_id": ObjectId(vehicle_id), "status": "booked"},
                                     {"$set": {"status": "available", "updated_at": utc_iso()}})


@router.get("/bookings")
async def list_bookings(status: str | None = None, city: str | None = None,
                        limit: int = Query(200, ge=1, le=500),
                        current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if status: q["status"] = status
    if city: q["city"] = city
    docs = await db.bookings.find(q).sort("created_at", -1).to_list(limit)
    return serialize_many(docs)


@router.post("/bookings", status_code=201)
async def create_booking(payload: BookingCreate, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    customer = await db.customers.find_one({"_id": oid(payload.customer_id)})
    vehicle = await db.vehicles.find_one({"_id": oid(payload.vehicle_id)})
    if not customer or not vehicle:
        raise HTTPException(400, "Invalid customer or vehicle")
    if payload.status not in ("pending", *HOLDING_STATUSES):
        raise HTTPException(400, "New bookings must be pending, confirmed or active")
    if payload.city != vehicle.get("city"):
        raise HTTPException(400, f"Booking city must match the vehicle's city ({vehicle.get('city')})")
    if vehicle.get("status") != "available" or await _vehicle_holder(db, payload.vehicle_id):
        raise HTTPException(409, f"Vehicle is not available ({vehicle.get('status')})")
    start = _parse_dt(payload.start_time, "start_time")
    end = _parse_dt(payload.end_time, "end_time")
    if end <= start:
        raise HTTPException(400, "End time must be after start time")
    doc = payload.model_dump()
    if doc.get("coupon_code"):
        coupon = await _redeem_coupon(db, doc["coupon_code"])
        # Staff enter the price before discount; the booking amount is what the customer pays,
        # so revenue, invoices and payouts all count the discounted figure.
        pct = float(coupon.get("discount_pct") or 0)
        gross = float(doc["amount"])
        discount = round(gross * pct / 100, 2)
        doc.update({
            "coupon_code": coupon["code"],
            "gross_amount": gross,
            "discount_pct": pct,
            "discount_amount": discount,
            "amount": round(gross - discount, 2),
        })
    else:
        doc.pop("coupon_code", None)
    doc["start_time"] = start.astimezone(timezone.utc).isoformat()
    doc["end_time"] = end.astimezone(timezone.utc).isoformat()
    doc["customer_name"] = customer["name"]
    doc["vehicle_label"] = f"{vehicle['model']} · {vehicle['plate']}"
    doc["vendor_id"] = vehicle.get("vendor_id")
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    res = await db.bookings.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _sync_vehicle_status(db, payload.vehicle_id, doc["status"])
    await log_activity(db, current, "Created booking", "Marketplace", target=f"{doc['customer_name']} · {doc['vehicle_label']}")
    await _notify_founders(db, "New booking created", f"{doc['customer_name']} booked {doc['vehicle_label']} in {doc['city']}.", kind="success")
    return serialize(doc)


@router.patch("/bookings/{booking_id}/status")
async def update_booking_status(booking_id: str, payload: dict, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    status = payload.get("status")
    if status not in {"pending", "confirmed", "active", "completed", "cancelled"}:
        raise HTTPException(400, "Invalid status")
    booking = await db.bookings.find_one({"_id": oid(booking_id)})
    if not booking:
        raise HTTPException(404, "Not found")
    current_status = booking.get("status")
    if current_status in ("completed", "cancelled") and status != current_status:
        raise HTTPException(400, f"Booking is already {current_status}")
    if status != current_status and status not in BOOKING_TRANSITIONS.get(current_status, set()):
        raise HTTPException(400, f"A {current_status} booking cannot move to {status}")
    if status in HOLDING_STATUSES and await _vehicle_holder(db, booking.get("vehicle_id"), exclude_id=booking["_id"]):
        raise HTTPException(409, "Vehicle is already held by another booking")
    if (status in HOLDING_STATUSES and current_status not in HOLDING_STATUSES
            and ObjectId.is_valid(booking.get("vehicle_id") or "")):
        vehicle = await db.vehicles.find_one({"_id": ObjectId(booking["vehicle_id"])}, {"status": 1})
        if vehicle and vehicle.get("status") in ("maintenance", "retired"):
            raise HTTPException(409, f"Vehicle is not available ({vehicle['status']})")
    res = await db.bookings.update_one({"_id": booking["_id"], "status": current_status},
                                       {"$set": {"status": status, "updated_at": utc_iso()}})
    # Cancelling returns the coupon use it redeemed; the status-guarded update makes a repeat
    # (or concurrent) cancel a no-op, so the use is given back once.
    if (status == "cancelled" and current_status != "cancelled" and res.modified_count
            and booking.get("coupon_code")):
        await _release_coupon(db, booking["coupon_code"])
    await _sync_vehicle_status(db, booking.get("vehicle_id"), status)
    doc = await db.bookings.find_one({"_id": booking["_id"]})
    await log_activity(db, current, f"Booking → {status}", "Marketplace", target=doc.get("customer_name"))
    return serialize(doc)


# -------- KYC (workflow) --------

@router.get("/kyc")
async def list_kyc(status: str | None = None, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if status: q["status"] = status
    docs = await db.kyc_requests.find(q).sort("created_at", -1).to_list(300)
    return serialize_many(docs)


@router.post("/kyc", status_code=201)
async def create_kyc(payload: KycIn, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    subject_col = "vendors" if payload.subject_type == "vendor" else "customers"
    subject = await db[subject_col].find_one({"_id": oid(payload.subject_id)})
    if not subject:
        raise HTTPException(400, f"Unknown {payload.subject_type}")
    doc = payload.model_dump()
    doc["subject_name"] = subject["name"]
    doc["status"] = "pending"  # decisions go through PATCH /kyc/{id}
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    res = await db.kyc_requests.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "KYC submitted", "Marketplace", target=doc["subject_name"])
    return serialize(doc)


@router.patch("/kyc/{kyc_id}")
async def update_kyc(kyc_id: str, payload: dict, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    status = payload.get("status")
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(400, "Invalid status")
    res = await db.kyc_requests.update_one({"_id": oid(kyc_id)}, {"$set": {"status": status, "updated_at": utc_iso()}})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.kyc_requests.find_one({"_id": oid(kyc_id)})
    # cascade to subject
    subject_col = "vendors" if doc["subject_type"] == "vendor" else "customers"
    if ObjectId.is_valid(doc.get("subject_id") or ""):
        await db[subject_col].update_one({"_id": ObjectId(doc["subject_id"])}, {"$set": {"kyc_status": status}})
    await log_activity(db, current, f"KYC {status}", "Marketplace", target=doc["subject_name"])
    await _notify_founders(db, f"KYC {status}", f"{doc['subject_name']} KYC marked {status}.",
                           kind="success" if status == "approved" else ("warning" if status == "rejected" else "info"))
    return serialize(doc)


# -------- Support --------

@router.get("/support")
async def list_support(status: str | None = None, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if status: q["status"] = status
    docs = await db.support_tickets.find(q).sort("created_at", -1).to_list(300)
    return serialize_many(docs)


@router.post("/support", status_code=201)
async def create_support(payload: SupportPayload, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    doc = payload.model_dump()
    if doc.get("customer_id"):
        customer = await db.customers.find_one({"_id": oid(doc["customer_id"])})
        if not customer:
            raise HTTPException(400, "Unknown customer")
        doc["customer_name"] = customer["name"]
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    res = await db.support_tickets.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Support ticket opened", "Marketplace", target=doc["subject"])
    await _notify_founders(db, "New support ticket", doc["subject"], kind="warning")
    return serialize(doc)


@router.patch("/support/{tid}")
async def update_support(tid: str, payload: dict, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    before = await db.support_tickets.find_one({"_id": oid(tid)})
    if not before:
        raise HTTPException(404, "Not found")
    changes = _validate_patch(SupportPayload, before, payload)
    changes.pop("customer_id", None); changes.pop("customer_name", None)  # fixed at creation
    changes["updated_at"] = utc_iso()
    await db.support_tickets.update_one({"_id": before["_id"]}, {"$set": changes})
    doc = await db.support_tickets.find_one({"_id": before["_id"]})
    action = f"Support → {changes['status']}" if changes.get("status") else "Updated support ticket"
    await log_activity(db, current, action, "Marketplace", target=doc["subject"])
    return serialize(doc)


# -------- Dashboard & analytics --------

@router.get("/dashboard")
async def marketplace_dashboard(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    # created_at is stored as UTC ISO text; "today" starts at midnight IST.
    ist_midnight = datetime.combine(datetime.now(IST).date(), datetime.min.time(), IST)
    today_start = ist_midnight.astimezone(timezone.utc).isoformat()

    async def count(col, q=None): return await db[col].count_documents(q or {})

    total_bookings = await count("bookings")
    active_bookings = await count("bookings", {"status": {"$in": ["confirmed", "active"]}})
    today_bookings = await count("bookings", {"created_at": {"$gte": today_start}})
    completed_bookings = await count("bookings", {"status": "completed"})

    # Revenue = confirmed + active + completed bookings (pending and cancelled excluded)
    pipeline = [{"$match": {"status": {"$in": REVENUE_STATUSES}}},
                {"$group": {"_id": None, "sum": {"$sum": "$amount"}}}]
    revenue_agg = await db.bookings.aggregate(pipeline).to_list(1)
    total_revenue = revenue_agg[0]["sum"] if revenue_agg else 0

    return {
        "totals": {
            "vehicles": await count("vehicles"),
            "vendors": await count("vendors"),
            "customers": await count("customers"),
            "cities": await count("cities"),
            "bookings": total_bookings,
            "active_bookings": active_bookings,
            "today_bookings": today_bookings,
            "completed_bookings": completed_bookings,
            "revenue": total_revenue,
            "pending_kyc": await count("kyc_requests", {"status": "pending"}),
            "open_tickets": await count("support_tickets", {"status": {"$in": ["open", "in_progress"]}}),
        }
    }


@router.get("/analytics")
async def marketplace_analytics(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    # Bookings by city (revenue counts confirmed + active + completed only)
    city_pipe = [
        {"$group": {"_id": "$city", "bookings": {"$sum": 1},
                    "revenue": {"$sum": {"$cond": [{"$in": ["$status", REVENUE_STATUSES]}, "$amount", 0]}}}},
        {"$sort": {"bookings": -1}},
        {"$limit": 10},
    ]
    by_city = await db.bookings.aggregate(city_pipe).to_list(20)
    # Bookings by status
    status_pipe = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    by_status = await db.bookings.aggregate(status_pipe).to_list(10)
    # Top vendors (by vehicles owned)
    vendor_pipe = [{"$group": {"_id": "$vendor_id", "vehicles": {"$sum": 1}}}, {"$sort": {"vehicles": -1}}, {"$limit": 6}]
    top_vendor_ids = await db.vehicles.aggregate(vendor_pipe).to_list(6)
    vendor_map = {}
    for v in top_vendor_ids:
        if v["_id"] and ObjectId.is_valid(v["_id"]):
            vdoc = await db.vendors.find_one({"_id": ObjectId(v["_id"])})
            if vdoc:
                vendor_map[str(vdoc["_id"])] = {"name": vdoc["name"], "city": vdoc.get("city"), "rating": vdoc.get("rating"), "vehicles": v["vehicles"]}
    return {
        "by_city": [{"city": c["_id"], "bookings": c["bookings"], "revenue": c["revenue"]} for c in by_city],
        # lifecycle order, so charts don't reshuffle between loads
        "by_status": sorted(({"status": s["_id"], "count": s["count"]} for s in by_status),
                            key=lambda s: STATUS_ORDER.index(s["status"]) if s["status"] in STATUS_ORDER else len(STATUS_ORDER)),
        "top_vendors": list(vendor_map.values()),
    }
