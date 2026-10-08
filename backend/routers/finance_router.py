"""Finance module API (mounted at /api/finance): invoices, vendor payouts, statements.

Every figure is derived from the Marketplace collections (`bookings`, `vendors`,
`customers`, `cities`) plus Finance's own collections:

  finance_settings   single doc `_id: "default"` - commission %, GST %, invoice prefix, company details
  finance_counters   `_id: "invoice:<FY>"` - atomic invoice sequence per financial year (April-March)
  invoices           one live (non-void) invoice per booking, enforced by a unique index on
                     `active_booking_id` (removed when an invoice is voided so it can be re-issued)
  payouts            one doc per vendor per payout batch (`batch_id`), status pending / paid
  payout_items       one doc per booking included in a payout - unique `booking_id` guarantees a
                     booking can be paid out at most once
  finance_vendors    Finance's supplier / payee directory (contact, GSTIN, category, status). A finance
                     vendor may be linked to a Marketplace fleet vendor (`marketplace_vendor_id`) so its
                     booking payouts roll into the vendor's spend and history
  vendor_bills       bills / expenses owed to a finance vendor, status pending / paid / cancelled

Rules
- Revenue counts bookings with status confirmed, active or completed (never pending / cancelled),
  the same rule as the Founder dashboard. Bookings are dated by `created_at` (ISO string or date).
- Month / day boundaries use the company timezone, Asia/Kolkata.
- Vendor earnings = booking amount x (1 - commission %). Only completed bookings are paid out, so a
  booking that may still be cancelled never lands in a payout.
- Vendor bills (cancelled excluded) count by bill_date when recorded and by payment.paid_on when paid.
  Monthly statements report net_after_bills = platform commission - vendor bills paid in the month.
- Everything is Founder-only via `permissions.can` (finance.view / finance.manage).
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ReturnDocument
from pymongo.errors import BulkWriteError, DuplicateKeyError

from auth_utils import get_current_user
from db import get_db
from hub_utils import log_activity, notify, oid, serialize, utc_iso
from models import UserPublic
from permissions import can

router = APIRouter(prefix="/finance", tags=["finance"])

IST = ZoneInfo("Asia/Kolkata")
REVENUE_STATUSES = ["confirmed", "active", "completed"]
PAYABLE_STATUS = "completed"
MODULE = "Finance"
LINK = "/finance"
MONTH_RE = r"^\d{4}-(0[1-9]|1[0-2])$"
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
PAYMENT_METHODS = ("upi", "card", "cash", "bank_transfer", "cheque", "other")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{10}[0-9A-Z]{3}$")

DEFAULT_SETTINGS = {
    "commission_pct": 20.0,
    "gst_pct": 18.0,
    "invoice_prefix": "WG-INV",
    "prices_include_gst": True,
    "company_name": "WAVYGO MOBILITY SERVICES PRIVATE LIMITED",
    "company_gstin": None,
    "company_state": None,
    "billing_address": None,
}


# ------------------------------------------------------------------ RBAC

def _perm(action: str):
    async def dep(current: UserPublic = Depends(get_current_user)) -> UserPublic:
        if not can(current.role, action):
            raise HTTPException(403, "You do not have access to Finance")
        return current
    return dep


Viewer = Depends(_perm("finance.view"))
Manager = Depends(_perm("finance.manage"))


# ------------------------------------------------------------------ indexes

_indexes_ready = False


async def ensure_indexes(db) -> None:
    """Idempotent. Also run lazily before the first Finance write, so correctness never depends
    on the startup hook."""
    global _indexes_ready
    await db.invoices.create_index("active_booking_id", unique=True,
                                   partialFilterExpression={"active_booking_id": {"$exists": True}})
    await db.invoices.create_index("number", unique=True,
                                   partialFilterExpression={"number": {"$type": "string"}})
    await db.invoices.create_index([("invoice_date", -1), ("created_at", -1)])
    await db.invoices.create_index("status")
    await db.invoices.create_index("customer_id")
    await db.payout_items.create_index("booking_id", unique=True)
    await db.payout_items.create_index("payout_id")
    await db.payouts.create_index([("created_at", -1)])
    await db.payouts.create_index("batch_id")
    await db.payouts.create_index("vendor_id")
    await db.invoices.create_index("vendor_id")
    await db.finance_vendors.create_index("name_key", unique=True)
    await db.finance_vendors.create_index("marketplace_vendor_id")
    await db.vendor_bills.create_index([("vendor_id", 1), ("bill_date", -1)])
    await db.vendor_bills.create_index([("bill_date", -1), ("created_at", -1)])
    await db.vendor_bills.create_index("status")
    _indexes_ready = True


async def _ready(db):
    if not _indexes_ready:
        await ensure_indexes(db)


# ------------------------------------------------------------------ helpers

def _money(x) -> float:
    return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _as_utc(value) -> Optional[datetime]:
    """created_at may be an ISO string or a BSON datetime (naive = UTC)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _today() -> date:
    return datetime.now(IST).date()


def _ist_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=IST).astimezone(timezone.utc)


def _month_start(ym: str) -> date:
    return date(int(ym[:4]), int(ym[5:7]), 1)


def _add_months(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def _month_range(first: str, last: str) -> tuple[datetime, datetime]:
    return _ist_midnight(_month_start(first)), _ist_midnight(_month_start(_add_months(last, 1)))


def _month_label(ym: str) -> str:
    return _month_start(ym).strftime("%b %Y")


def _current_month() -> str:
    return _today().strftime("%Y-%m")


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {field}: expected YYYY-MM-DD")


def financial_year(d: date) -> str:
    """Indian FY April-March: 2026-04-01..2027-03-31 -> '2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _ym_of(value) -> Optional[str]:
    dt = _as_utc(value)
    return dt.astimezone(IST).strftime("%Y-%m") if dt else None


def _ts_expr(field: str = "created_at") -> dict:
    return {"$convert": {"input": f"${field}", "to": "date", "onError": None, "onNull": None}}


def _oid_or_none(value):
    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else None


async def _settings(db) -> dict:
    doc = await db.finance_settings.find_one({"_id": "default"}) or {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k in DEFAULT_SETTINGS},
            "updated_at": doc.get("updated_at"), "updated_by": doc.get("updated_by")}


async def _bookings_between(db, start: datetime, end: datetime, extra: Optional[dict] = None,
                            fields: tuple = ("status", "amount", "vendor_id")) -> list[dict]:
    """Bookings whose created_at (string or date) falls in [start, end), with `_ym` (IST month)."""
    project = {f: 1 for f in fields}
    project["_ts"] = _ts_expr()
    pipe = []
    if extra:
        pipe.append({"$match": extra})
    pipe += [
        {"$project": project},
        {"$match": {"_ts": {"$gte": start, "$lt": end}}},
        {"$addFields": {"_ym": {"$dateToString": {"date": "$_ts", "format": "%Y-%m", "timezone": "Asia/Kolkata"}}}},
        {"$sort": {"_ts": 1, "_id": 1}},
    ]
    return await db.bookings.aggregate(pipe).to_list(None)


async def _live_invoice_booking_ids(db, booking_ids: Optional[list[str]] = None) -> set[str]:
    q: dict = {"active_booking_id": {"$exists": True}}
    if booking_ids is not None:
        q["active_booking_id"] = {"$in": booking_ids}
    return {d["active_booking_id"] async for d in db.invoices.find(q, {"active_booking_id": 1})}


async def _payout_items_for(db, booking_ids: Optional[list[str]] = None) -> dict[str, dict]:
    q = {} if booking_ids is None else {"booking_id": {"$in": booking_ids}}
    return {d["booking_id"]: d async for d in db.payout_items.find(q)}


async def _name_map(db, collection: str, ids) -> dict[str, str]:
    oids = [o for o in (_oid_or_none(i) for i in set(ids)) if o]
    if not oids:
        return {}
    return {str(d["_id"]): d.get("name") async for d in db[collection].find({"_id": {"$in": oids}}, {"name": 1})}


def _split(amount: float, pct: float) -> tuple[float, float]:
    commission = _money(Decimal(str(amount)) * Decimal(str(pct)) / 100)
    return commission, _money(Decimal(str(amount)) - Decimal(str(commission)))


def gst_breakup(amount: float, gst_pct: float, inclusive: bool, inter_state: bool) -> dict:
    """Taxable value, CGST/SGST (intra-state) or IGST (inter-state), total."""
    amt, rate = Decimal(str(amount or 0)), Decimal(str(gst_pct or 0))
    if inclusive:
        total = _money(amt)
        subtotal = _money(amt * 100 / (100 + rate))
        gst = _money(Decimal(str(total)) - Decimal(str(subtotal)))
    else:
        subtotal = _money(amt)
        gst = _money(amt * rate / 100)
        total = _money(Decimal(str(subtotal)) + Decimal(str(gst)))
    if inter_state:
        cgst = sgst = 0.0
        igst = gst
    else:
        cgst = _money(Decimal(str(gst)) / 2)
        sgst = _money(Decimal(str(gst)) - Decimal(str(cgst)))
        igst = 0.0
    return {"subtotal": subtotal, "cgst": cgst, "sgst": sgst, "igst": igst, "gst_total": gst, "total": total,
            "gst_type": "igst" if inter_state else "cgst_sgst"}


def _csv_cell(v):
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def _csv_response(filename: str, header: list[str], rows: list[list]) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_csv_cell(c) for c in r])
    data = "﻿" + buf.getvalue()  # BOM so Excel reads ₹ / Indian names correctly
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ------------------------------------------------------------------ settings

class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    commission_pct: float = Field(ge=0, le=100)
    gst_pct: float = Field(ge=0, le=100)
    invoice_prefix: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")
    prices_include_gst: bool = True
    company_name: str = Field(min_length=1, max_length=200)
    company_gstin: Optional[str] = Field(None, max_length=15)
    company_state: Optional[str] = Field(None, max_length=60)
    billing_address: Optional[str] = Field(None, max_length=500)

    @field_validator("company_gstin", "company_state", "billing_address", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("company_gstin")
    @classmethod
    def _gstin(cls, v):
        if v is None:
            return v
        v = v.upper()
        if not GSTIN_RE.match(v):
            raise ValueError("GSTIN must be 15 characters (e.g. 10ABCDE1234F1Z5)")
        return v


@router.get("/settings")
async def get_settings(current: UserPublic = Viewer):
    return await _settings(get_db())


@router.put("/settings")
async def update_settings(payload: SettingsIn, current: UserPublic = Manager):
    db = get_db()
    before = await _settings(db)
    data = payload.model_dump()
    changed = {k: v for k, v in data.items() if before.get(k) != v}
    await db.finance_settings.update_one(
        {"_id": "default"},
        {"$set": {**data, "updated_at": utc_iso(), "updated_by": current.name}}, upsert=True)
    if changed:
        await log_activity(db, current, "Updated finance settings", MODULE,
                           target=", ".join(sorted(changed)), meta={"changes": changed})
    return await _settings(db)


# ------------------------------------------------------------------ invoices

class GenerateIn(BaseModel):
    booking_id: str
    invoice_date: Optional[str] = Field(None, pattern=DATE_RE)
    issue: bool = True
    notes: Optional[str] = Field(None, max_length=500)


class BulkGenerateIn(BaseModel):
    month: Optional[str] = Field(None, pattern=MONTH_RE)
    invoice_date: Optional[str] = Field(None, pattern=DATE_RE)
    issue: bool = True


class PayIn(BaseModel):
    method: Literal["upi", "card", "cash", "bank_transfer", "cheque", "other"]
    paid_on: Optional[str] = Field(None, pattern=DATE_RE)
    reference: Optional[str] = Field(None, max_length=100)


class VoidIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=300)


async def _allocate_number(db, settings: dict, invoice_date: str) -> tuple[str, str]:
    fy = financial_year(date.fromisoformat(invoice_date))
    counter = await db.finance_counters.find_one_and_update(
        {"_id": f"invoice:{fy}"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return f"{settings['invoice_prefix']}/{fy}/{counter['seq']:04d}", fy


def _fmt_ist(value) -> str:
    dt = _as_utc(value)
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p") if dt else "-"


def _check_invoice_date(value: Optional[str]) -> None:
    """Invoices are never dated ahead: a future date would also consume the next FY's numbers."""
    if value and _parse_date(value, "invoice_date") > _today():
        raise HTTPException(400, "Invoice date cannot be in the future")


async def _create_invoice(db, booking: dict, settings: dict, current: UserPublic, invoice_date: Optional[str],
                          issue: bool, notes: Optional[str] = None) -> tuple[dict, bool]:
    """Returns (invoice, created). Idempotent: an existing live invoice for the booking is returned."""
    booking_id = str(booking["_id"])
    existing = await db.invoices.find_one({"active_booking_id": booking_id})
    if existing:
        return existing, False
    if booking.get("status") not in REVENUE_STATUSES:
        raise HTTPException(400, f"Booking is {booking.get('status')}; only confirmed, active or completed bookings can be invoiced")
    inv_date = invoice_date or _today().isoformat()
    _check_invoice_date(inv_date)

    customer = await db.customers.find_one({"_id": _oid_or_none(booking.get("customer_id"))}) if _oid_or_none(booking.get("customer_id")) else None
    vendor_name = None
    if _oid_or_none(booking.get("vendor_id")):
        v = await db.vendors.find_one({"_id": _oid_or_none(booking["vendor_id"])}, {"name": 1})
        vendor_name = v.get("name") if v else None
    city = booking.get("city")
    city_doc = await db.cities.find_one({"name": city}, {"state": 1}) if city else None
    place_state = (city_doc or {}).get("state")
    company_state = settings.get("company_state")
    inter_state = bool(company_state and place_state and company_state.strip().lower() != place_state.strip().lower())
    amount = _money(booking.get("amount"))
    b = gst_breakup(amount, settings["gst_pct"], settings["prices_include_gst"], inter_state)

    period = f"{_fmt_ist(booking.get('start_time'))} to {_fmt_ist(booking.get('end_time'))}"
    item = {"description": f"Two-wheeler rental - {booking.get('vehicle_label') or 'vehicle'}",
            "detail": f"{city or ''} - {period}".strip(" -"),
            "sac": "9966", "quantity": 1, "unit_price": b["subtotal"], "amount": b["subtotal"]}
    now = utc_iso()
    doc = {
        "booking_id": booking_id, "active_booking_id": booking_id,
        "number": None, "fy": None, "status": "draft", "invoice_date": inv_date,
        "customer_id": booking.get("customer_id"),
        "customer_name": (customer or {}).get("name") or booking.get("customer_name"),
        "customer_email": (customer or {}).get("email"), "customer_phone": (customer or {}).get("phone"),
        "customer_city": (customer or {}).get("city") or city,
        "vendor_id": booking.get("vendor_id"), "vendor_name": vendor_name,
        "city": city, "place_of_supply": place_state, "booking_status": booking.get("status"),
        "booking_created_at": booking.get("created_at"), "booking_amount": amount,
        "line_items": [item], "gst_pct": settings["gst_pct"], "prices_include_gst": settings["prices_include_gst"],
        **b,
        "company": {k: settings.get(k) for k in ("company_name", "company_gstin", "company_state", "billing_address")},
        "notes": notes, "payment": None, "paid_at": None, "void_reason": None, "voided_at": None,
        "created_by": current.name, "created_at": now, "updated_at": now,
    }
    try:
        res = await db.invoices.insert_one(doc)
    except DuplicateKeyError:  # raced with another request for the same booking
        return await db.invoices.find_one({"active_booking_id": booking_id}), False
    doc["_id"] = res.inserted_id
    if issue:
        doc = await _issue(db, doc, settings)
    return doc, True


async def _issue(db, inv: dict, settings: dict) -> dict:
    number, fy = await _allocate_number(db, settings, inv["invoice_date"])
    await db.invoices.update_one({"_id": inv["_id"], "status": "draft"},
                                 {"$set": {"number": number, "fy": fy, "status": "issued",
                                           "issued_at": utc_iso(), "updated_at": utc_iso()}})
    return await db.invoices.find_one({"_id": inv["_id"]})


def _invoice_query(status, month, customer_id, q, vendor_id=None) -> dict:
    query: dict = {}
    if status:
        if status not in ("draft", "issued", "paid", "void"):
            raise ValueError("Invalid status")
        query["status"] = status
    if month:
        if not re.match(MONTH_RE, month):
            raise ValueError("Invalid month: expected YYYY-MM")
        query["invoice_date"] = {"$regex": f"^{month}-"}
    if customer_id:
        query["customer_id"] = customer_id
    if vendor_id:
        query["vendor_id"] = vendor_id
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"number": rx}, {"customer_name": rx}, {"customer_email": rx}, {"booking_id": rx}]
    return query


@router.get("/invoices")
async def list_invoices(status: Optional[str] = None, month: Optional[str] = None, customer_id: Optional[str] = None,
                        q: Optional[str] = None, vendor_id: Optional[str] = None,
                        limit: int = Query(100, ge=1, le=500), skip: int = Query(0, ge=0),
                        current: UserPublic = Viewer):
    db = get_db()
    query = _invoice_query(status, month, customer_id, q, vendor_id)
    total = await db.invoices.count_documents(query)
    docs = await db.invoices.find(query).sort([("invoice_date", -1), ("created_at", -1)]).skip(skip).to_list(limit)
    agg = await db.invoices.aggregate([
        {"$match": query}, {"$group": {"_id": "$status", "n": {"$sum": 1}, "total": {"$sum": "$total"}}}]).to_list(None)
    summary = {s: {"count": 0, "total": 0.0} for s in ("draft", "issued", "paid", "void")}
    for a in agg:
        summary[a["_id"]] = {"count": a["n"], "total": _money(a["total"])}
    return {"items": [serialize(d) for d in docs], "total": total, "summary": summary}


@router.get("/invoices/export")
async def export_invoices(status: Optional[str] = None, month: Optional[str] = None, customer_id: Optional[str] = None,
                          q: Optional[str] = None, vendor_id: Optional[str] = None, current: UserPublic = Viewer):
    db = get_db()
    docs = await db.invoices.find(_invoice_query(status, month, customer_id, q, vendor_id)).sort(
        [("invoice_date", 1), ("number", 1)]).to_list(None)
    header = ["Invoice number", "Invoice date", "Status", "Customer", "Customer email", "Booking id", "City",
              "Place of supply", "Taxable value", "GST %", "CGST", "SGST", "IGST", "GST total", "Total",
              "Paid on", "Payment method", "Payment reference", "Void reason"]
    rows = []
    for d in docs:
        p = d.get("payment") or {}
        rows.append([d.get("number") or "(draft)", d.get("invoice_date"), d.get("status"), d.get("customer_name"),
                     d.get("customer_email"), d.get("booking_id"), d.get("city"), d.get("place_of_supply"),
                     d.get("subtotal"), d.get("gst_pct"), d.get("cgst"), d.get("sgst"), d.get("igst"),
                     d.get("gst_total"), d.get("total"), p.get("paid_on"), p.get("method"), p.get("reference"),
                     d.get("void_reason")])
    await log_activity(db, current, "Exported invoices CSV", MODULE, target=month or "all", meta={"rows": len(rows)})
    return _csv_response(f"wavygo-invoices-{month or 'all'}.csv", header, rows)


@router.get("/invoices/eligible")
async def eligible_bookings(month: Optional[str] = Query(None, pattern=MONTH_RE), limit: int = Query(200, ge=1, le=1000),
                            current: UserPublic = Viewer):
    """Revenue bookings that do not have a live invoice yet."""
    db = get_db()
    q = {"status": {"$in": REVENUE_STATUSES}}
    if month:
        start, end = _month_range(month, month)
        docs = await _bookings_between(db, start, end, q, fields=(
            "status", "amount", "customer_name", "vehicle_label", "city", "created_at", "vendor_id"))
        docs.reverse()
    else:
        docs = await db.bookings.find(q, {"status": 1, "amount": 1, "customer_name": 1, "vehicle_label": 1,
                                          "city": 1, "created_at": 1, "vendor_id": 1}).to_list(None)
        docs.sort(key=lambda d: _as_utc(d.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    invoiced = await _live_invoice_booking_ids(db, [str(d["_id"]) for d in docs])
    rows = [d for d in docs if str(d["_id"]) not in invoiced]
    return {"total": len(rows), "amount": _money(sum(_money(d.get("amount")) for d in rows)),
            "items": [{"id": str(d["_id"]), "customer_name": d.get("customer_name"), "vehicle_label": d.get("vehicle_label"),
                       "city": d.get("city"), "status": d.get("status"), "amount": _money(d.get("amount")),
                       "created_at": d.get("created_at") if not isinstance(d.get("created_at"), datetime)
                       else _as_utc(d["created_at"]).isoformat()} for d in rows[:limit]]}


@router.post("/invoices", status_code=201)
async def generate_invoice(payload: GenerateIn, current: UserPublic = Manager):
    db = get_db()
    await _ready(db)
    _check_invoice_date(payload.invoice_date)
    booking = await db.bookings.find_one({"_id": oid(payload.booking_id)})
    if not booking:
        raise HTTPException(404, "Booking not found")
    settings = await _settings(db)
    inv, created = await _create_invoice(db, booking, settings, current, payload.invoice_date, payload.issue, payload.notes)
    if created:
        label = inv.get("number") or "Draft invoice"
        await log_activity(db, current, "Generated invoice", MODULE, target=f"{label} · {inv.get('customer_name')}",
                           meta={"invoice_id": str(inv["_id"]), "booking_id": inv["booking_id"], "total": inv["total"]})
        await notify(db, current.id, "Invoice generated",
                     f"{label} for {inv.get('customer_name')} · ₹{inv['total']:,.2f}", kind="success", link=LINK)
    return {**serialize(inv), "created": created}


@router.post("/invoices/bulk")
async def bulk_generate(payload: BulkGenerateIn, current: UserPublic = Manager):
    db = get_db()
    await _ready(db)
    _check_invoice_date(payload.invoice_date)
    settings = await _settings(db)
    q = {"status": {"$in": REVENUE_STATUSES}}
    if payload.month:
        start, end = _month_range(payload.month, payload.month)
    else:
        start, end = datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(9999, 1, 1, tzinfo=timezone.utc)
    ids = [d["_id"] for d in await _bookings_between(db, start, end, q, fields=("status",))]
    invoiced = await _live_invoice_booking_ids(db, [str(i) for i in ids])
    todo = [i for i in ids if str(i) not in invoiced]
    created, total = 0, 0.0
    for bid in todo[:1000]:
        booking = await db.bookings.find_one({"_id": bid})
        if not booking or booking.get("status") not in REVENUE_STATUSES:
            continue
        inv, was_created = await _create_invoice(db, booking, settings, current, payload.invoice_date, payload.issue)
        if was_created:
            created += 1
            total += inv["total"]
    remaining = max(len(todo) - 1000, 0)
    if created:
        await log_activity(db, current, "Bulk generated invoices", MODULE, target=payload.month or "all months",
                           meta={"created": created, "total": _money(total)})
        await notify(db, current.id, "Invoices generated",
                     f"{created} invoice{'s' if created != 1 else ''} generated · ₹{_money(total):,.2f}",
                     kind="success", link=LINK)
    return {"created": created, "total": _money(total), "remaining": remaining}


async def _get_invoice(db, invoice_id: str) -> dict:
    inv = await db.invoices.find_one({"_id": oid(invoice_id)})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, current: UserPublic = Viewer):
    db = get_db()
    inv = await _get_invoice(db, invoice_id)
    booking = await db.bookings.find_one({"_id": _oid_or_none(inv.get("booking_id"))}, {"status": 1}) \
        if _oid_or_none(inv.get("booking_id")) else None
    return {**serialize(inv), "current_booking_status": (booking or {}).get("status")}


@router.post("/invoices/{invoice_id}/issue")
async def issue_invoice(invoice_id: str, current: UserPublic = Manager):
    db = get_db()
    await _ready(db)
    inv = await _get_invoice(db, invoice_id)
    if inv["status"] != "draft":
        raise HTTPException(400, f"Invoice is already {inv['status']}")
    inv = await _issue(db, inv, await _settings(db))
    await log_activity(db, current, "Issued invoice", MODULE, target=f"{inv['number']} · {inv.get('customer_name')}")
    return serialize(inv)


@router.post("/invoices/{invoice_id}/pay")
async def mark_invoice_paid(invoice_id: str, payload: PayIn, current: UserPublic = Manager):
    db = get_db()
    inv = await _get_invoice(db, invoice_id)
    if inv["status"] != "issued":
        raise HTTPException(400, "Only issued invoices can be marked paid" if inv["status"] != "paid" else "Invoice is already paid")
    paid_on = payload.paid_on or _today().isoformat()
    if _parse_date(paid_on, "paid_on") > _today():
        raise HTTPException(400, "Payment date cannot be in the future")
    payment = {"paid_on": paid_on, "method": payload.method, "reference": (payload.reference or "").strip() or None,
               "recorded_by": current.name}
    res = await db.invoices.update_one({"_id": inv["_id"], "status": "issued"},
                                       {"$set": {"status": "paid", "payment": payment, "paid_at": utc_iso(), "updated_at": utc_iso()}})
    if not res.modified_count:
        raise HTTPException(409, "Invoice changed, reload and try again")
    inv = await db.invoices.find_one({"_id": inv["_id"]})
    await log_activity(db, current, "Marked invoice paid", MODULE, target=f"{inv['number']} · {inv.get('customer_name')}",
                       meta={"method": payload.method, "total": inv["total"]})
    await notify(db, current.id, "Invoice paid", f"{inv['number']} · ₹{inv['total']:,.2f} received via {payload.method.replace('_', ' ')}",
                 kind="success", link=LINK)
    return serialize(inv)


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(invoice_id: str, payload: VoidIn, current: UserPublic = Manager):
    db = get_db()
    inv = await _get_invoice(db, invoice_id)
    if inv["status"] == "void":
        raise HTTPException(400, "Invoice is already void")
    res = await db.invoices.update_one(
        {"_id": inv["_id"], "status": inv["status"]},
        {"$set": {"status": "void", "void_reason": payload.reason.strip(), "voided_at": utc_iso(),
                  "voided_from": inv["status"], "updated_at": utc_iso()},
         "$unset": {"active_booking_id": ""}})
    if not res.modified_count:
        raise HTTPException(409, "Invoice changed, reload and try again")
    inv = await db.invoices.find_one({"_id": inv["_id"]})
    label = inv.get("number") or "Draft invoice"
    await log_activity(db, current, "Voided invoice", MODULE, target=f"{label} · {inv.get('customer_name')}",
                       meta={"reason": inv["void_reason"], "was": inv["voided_from"]})
    await notify(db, current.id, "Invoice voided", f"{label}: {inv['void_reason']}", kind="warning", link=LINK)
    return serialize(inv)


# ------------------------------------------------------------------ payouts

class PayoutCreateIn(BaseModel):
    period_start: str = Field(pattern=DATE_RE)
    period_end: str = Field(pattern=DATE_RE)
    vendor_ids: Optional[list[str]] = None
    notes: Optional[str] = Field(None, max_length=300)


class PayoutPayIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reference: str = Field(min_length=1, max_length=100)
    paid_on: Optional[str] = Field(None, pattern=DATE_RE)


@router.get("/payouts/outstanding")
async def payouts_outstanding(current: UserPublic = Viewer):
    """Per vendor: earnings not yet in any payout (all revenue bookings), the payable part
    (completed bookings), and pending payout batches awaiting transfer."""
    db = get_db()
    settings = await _settings(db)
    pct = settings["commission_pct"]
    docs = await db.bookings.find({"status": {"$in": REVENUE_STATUSES}},
                                  {"status": 1, "amount": 1, "vendor_id": 1}).to_list(None)
    in_payout = await _payout_items_for(db, [str(d["_id"]) for d in docs])
    rows: dict[str, dict] = {}
    unassigned = {"bookings": 0, "gross": 0.0}

    def row(vid):
        return rows.setdefault(vid, {"vendor_id": vid, "earned_bookings": 0, "earned_gross": 0.0, "earned_net": 0.0,
                                     "payable_bookings": 0, "payable_gross": 0.0, "payable_commission": 0.0,
                                     "payable_net": 0.0, "pending_payouts": 0, "pending_net": 0.0, "paid_net": 0.0})
    for d in docs:
        if str(d["_id"]) in in_payout:
            continue
        amount = _money(d.get("amount"))
        if not d.get("vendor_id"):
            unassigned["bookings"] += 1
            unassigned["gross"] += amount
            continue
        commission, net = _split(amount, pct)
        r = row(d["vendor_id"])
        r["earned_bookings"] += 1
        r["earned_gross"] += amount
        r["earned_net"] += net
        if d.get("status") == PAYABLE_STATUS:
            r["payable_bookings"] += 1
            r["payable_gross"] += amount
            r["payable_commission"] += commission
            r["payable_net"] += net
    async for p in db.payouts.find({}, {"vendor_id": 1, "status": 1, "net": 1}):
        r = row(p["vendor_id"])
        if p["status"] == "pending":
            r["pending_payouts"] += 1
            r["pending_net"] += p["net"]
        else:
            r["paid_net"] += p["net"]
    names = await _name_map(db, "vendors", rows.keys())
    out = []
    for vid, r in rows.items():
        out.append({**{k: (_money(v) if isinstance(v, float) else v) for k, v in r.items()},
                    "vendor_name": names.get(vid) or "Unknown vendor"})
    out.sort(key=lambda r: (-(r["earned_net"] + r["pending_net"]), r["vendor_name"]))
    totals = {k: _money(sum(r[k] for r in out)) for k in
              ("earned_gross", "earned_net", "payable_gross", "payable_commission", "payable_net", "pending_net", "paid_net")}
    totals["payable_bookings"] = sum(r["payable_bookings"] for r in out)
    return {"commission_pct": pct, "vendors": out, "totals": totals,
            "unassigned": {"bookings": unassigned["bookings"], "gross": _money(unassigned["gross"])}}


@router.get("/payouts")
async def list_payouts(status: Optional[Literal["pending", "paid"]] = None, vendor_id: Optional[str] = None,
                       batch_id: Optional[str] = None, limit: int = Query(200, ge=1, le=500),
                       current: UserPublic = Viewer):
    db = get_db()
    q: dict = {}
    if status:
        q["status"] = status
    if vendor_id:
        q["vendor_id"] = vendor_id
    if batch_id:
        q["batch_id"] = batch_id
    docs = await db.payouts.find(q).sort([("created_at", -1), ("vendor_name", 1)]).to_list(limit)
    return [serialize(d) for d in docs]


@router.post("/payouts", status_code=201)
async def create_payout_batch(payload: PayoutCreateIn, current: UserPublic = Manager):
    db = get_db()
    await _ready(db)
    start_d = _parse_date(payload.period_start, "period_start")
    end_d = _parse_date(payload.period_end, "period_end")
    if end_d < start_d:
        raise HTTPException(400, "Period end must be on or after period start")
    if start_d > _today():
        raise HTTPException(400, "Period cannot start in the future")
    settings = await _settings(db)
    pct = settings["commission_pct"]
    q: dict = {"status": PAYABLE_STATUS, "vendor_id": {"$nin": [None, ""]}}
    if payload.vendor_ids:
        q["vendor_id"] = {"$in": payload.vendor_ids}
    docs = await _bookings_between(db, _ist_midnight(start_d), _ist_midnight(end_d + timedelta(days=1)), q,
                                   fields=("status", "amount", "vendor_id", "customer_name"))
    taken = await _payout_items_for(db, [str(d["_id"]) for d in docs])
    by_vendor: dict[str, list[dict]] = {}
    for d in docs:
        if str(d["_id"]) not in taken:
            by_vendor.setdefault(d["vendor_id"], []).append(d)
    if not by_vendor:
        raise HTTPException(400, "No completed bookings awaiting payout in this period")
    names = await _name_map(db, "vendors", by_vendor.keys())
    batch_id, now = uuid.uuid4().hex[:12], utc_iso()
    created = []
    for vid, bookings in by_vendor.items():
        payout_id = ObjectId()
        items = []
        for b in bookings:
            amount = _money(b.get("amount"))
            commission, net = _split(amount, pct)
            items.append({"booking_id": str(b["_id"]), "payout_id": payout_id, "vendor_id": vid, "amount": amount,
                          "commission_pct": pct, "commission": commission, "net": net, "created_at": now})
        try:
            await db.payout_items.insert_many(items, ordered=False)
            kept = items
        except BulkWriteError as e:  # concurrent batch grabbed some bookings first
            failed = {err["index"] for err in e.details.get("writeErrors", [])}
            kept = [it for i, it in enumerate(items) if i not in failed]
        if not kept:
            continue
        doc = {
            "_id": payout_id, "batch_id": batch_id, "vendor_id": vid, "vendor_name": names.get(vid) or "Unknown vendor",
            "period_start": payload.period_start, "period_end": payload.period_end,
            "booking_ids": [it["booking_id"] for it in kept], "bookings_count": len(kept),
            "gross": _money(sum(it["amount"] for it in kept)), "commission_pct": pct,
            "commission": _money(sum(it["commission"] for it in kept)), "net": _money(sum(it["net"] for it in kept)),
            "status": "pending", "reference": None, "paid_on": None, "paid_at": None, "notes": payload.notes,
            "created_by": current.name, "created_at": now, "updated_at": now,
        }
        await db.payouts.insert_one(doc)
        created.append(doc)
    if not created:
        raise HTTPException(409, "These bookings were just added to another payout")
    totals = {k: _money(sum(p[k] for p in created)) for k in ("gross", "commission", "net")}
    await log_activity(db, current, "Created payout batch", MODULE,
                       target=f"{payload.period_start} to {payload.period_end} · {len(created)} vendor(s)",
                       meta={"batch_id": batch_id, **totals})
    await notify(db, current.id, "Vendor payout batch created",
                 f"{len(created)} vendor payout(s) · ₹{totals['net']:,.2f} to transfer", kind="info", link=LINK)
    return {"batch_id": batch_id, "payouts": [serialize(p) for p in created], "totals": totals}


@router.post("/payouts/{payout_id}/pay")
async def mark_payout_paid(payout_id: str, payload: PayoutPayIn, current: UserPublic = Manager):
    db = get_db()
    p = await db.payouts.find_one({"_id": oid(payout_id)})
    if not p:
        raise HTTPException(404, "Payout not found")
    if p["status"] != "pending":
        raise HTTPException(400, "Payout is already paid")
    paid_on = payload.paid_on or _today().isoformat()
    if _parse_date(paid_on, "paid_on") > _today():
        raise HTTPException(400, "Payment date cannot be in the future")
    res = await db.payouts.update_one({"_id": p["_id"], "status": "pending"}, {"$set": {
        "status": "paid", "reference": payload.reference.strip(), "paid_on": paid_on, "paid_at": utc_iso(),
        "paid_by": current.name, "updated_at": utc_iso()}})
    if not res.modified_count:
        raise HTTPException(409, "Payout changed, reload and try again")
    p = await db.payouts.find_one({"_id": p["_id"]})
    await log_activity(db, current, "Marked vendor payout paid", MODULE, target=f"{p['vendor_name']} · ₹{p['net']:,.2f}",
                       meta={"reference": p["reference"], "batch_id": p["batch_id"]})
    await notify(db, current.id, "Vendor payout paid", f"{p['vendor_name']} · ₹{p['net']:,.2f} (ref {p['reference']})",
                 kind="success", link=LINK)
    return serialize(p)


@router.delete("/payouts/{payout_id}")
async def cancel_payout(payout_id: str, current: UserPublic = Manager):
    """Cancel a pending payout; its bookings become available for a future batch."""
    db = get_db()
    p = await db.payouts.find_one({"_id": oid(payout_id)})
    if not p:
        raise HTTPException(404, "Payout not found")
    res = await db.payouts.delete_one({"_id": p["_id"], "status": "pending"})
    if not res.deleted_count:
        raise HTTPException(400, "Only pending payouts can be cancelled")
    await db.payout_items.delete_many({"payout_id": p["_id"]})
    await log_activity(db, current, "Cancelled vendor payout", MODULE, target=f"{p['vendor_name']} · ₹{p['net']:,.2f}",
                       meta={"batch_id": p["batch_id"]})
    return {"ok": True}


# ------------------------------------------------------------------ statements

STAT_FIELDS = ("gross_revenue", "revenue_bookings", "platform_commission", "vendor_earnings", "vendor_paid",
               "vendor_owed", "gst_collected", "invoices_issued", "invoiced_amount", "invoices_paid", "paid_amount",
               "invoices_outstanding", "outstanding_amount", "invoices_void", "refunded_amount",
               "cancelled_bookings", "pending_bookings", "uninvoiced_bookings",
               "bills_recorded", "bills_recorded_amount", "bills_paid", "bills_paid_amount", "net_after_bills")


async def month_stats(db, first: str, last: str, settings: dict) -> dict[str, dict]:
    """Per-month (IST) figures for [first, last]. Bookings are dated by created_at, invoices by
    invoice_date, voids by voided_at. Commission uses the rate frozen in a payout when the booking
    has been paid out, otherwise the current setting."""
    months, m = [], first
    while m <= last:
        months.append(m)
        m = _add_months(m, 1)
    stats = {ym: {f: 0 for f in STAT_FIELDS} for ym in months}
    start, end = _month_range(first, last)
    pct = settings["commission_pct"]

    bookings = await _bookings_between(db, start, end)
    rev_ids = [str(b["_id"]) for b in bookings if b.get("status") in REVENUE_STATUSES]
    items = await _payout_items_for(db, rev_ids)
    payout_status = {p["_id"]: p["status"] async for p in db.payouts.find(
        {"_id": {"$in": list({i["payout_id"] for i in items.values()})}}, {"status": 1})}
    invoiced = await _live_invoice_booking_ids(db, rev_ids)
    for b in bookings:
        s = stats[b["_ym"]]
        status = b.get("status")
        if status == "cancelled":
            s["cancelled_bookings"] += 1
        elif status == "pending":
            s["pending_bookings"] += 1
        if status not in REVENUE_STATUSES:
            continue
        bid, amount = str(b["_id"]), _money(b.get("amount"))
        s["revenue_bookings"] += 1
        s["gross_revenue"] += amount
        item = items.get(bid)
        if item:
            commission, net = item["commission"], item["net"]
            if payout_status.get(item["payout_id"]) == "paid":
                s["vendor_paid"] += net
            else:
                s["vendor_owed"] += net
        else:
            commission, net = _split(amount, pct) if b.get("vendor_id") else (amount, 0.0)
            s["vendor_owed"] += net
        s["platform_commission"] += commission
        s["vendor_earnings"] += net
        if bid not in invoiced:
            s["uninvoiced_bookings"] += 1

    inv_q = {"$or": [
        {"invoice_date": {"$gte": f"{first}-01", "$lt": f"{_add_months(last, 1)}-01"}},
        {"voided_at": {"$ne": None}},
    ]}
    async for inv in db.invoices.find(inv_q, {"status": 1, "invoice_date": 1, "total": 1, "gst_total": 1,
                                              "voided_at": 1, "voided_from": 1, "payment": 1}):
        ym = (inv.get("invoice_date") or "")[:7]
        status = inv.get("status")
        if ym in stats:
            s = stats[ym]
            if status in ("issued", "paid"):
                s["gst_collected"] += inv.get("gst_total") or 0
                s["invoices_issued"] += 1
                s["invoiced_amount"] += inv.get("total") or 0
            if status == "paid":
                s["invoices_paid"] += 1
                s["paid_amount"] += inv.get("total") or 0
            elif status == "issued":
                s["invoices_outstanding"] += 1
                s["outstanding_amount"] += inv.get("total") or 0
        if status == "void":
            vym = _ym_of(inv.get("voided_at"))
            if vym in stats:
                stats[vym]["invoices_void"] += 1
                if inv.get("voided_from") == "paid":
                    stats[vym]["refunded_amount"] += inv.get("total") or 0
    # Vendor bills (cancelled excluded): recorded by bill_date, paid by payment.paid_on.
    lo, hi = f"{first}-01", f"{_add_months(last, 1)}-01"
    async for b in db.vendor_bills.find(
            {"status": {"$ne": "cancelled"},
             "$or": [{"bill_date": {"$gte": lo, "$lt": hi}}, {"payment.paid_on": {"$gte": lo, "$lt": hi}}]},
            {"bill_date": 1, "total": 1, "status": 1, "payment.paid_on": 1}):
        total = float(b.get("total") or 0)
        ym = (b.get("bill_date") or "")[:7]
        if ym in stats:
            stats[ym]["bills_recorded"] += 1
            stats[ym]["bills_recorded_amount"] += total
        pym = ((b.get("payment") or {}).get("paid_on") or "")[:7]
        if b.get("status") == "paid" and pym in stats:
            stats[pym]["bills_paid"] += 1
            stats[pym]["bills_paid_amount"] += total
    for s in stats.values():
        for k, v in s.items():
            if isinstance(v, float):
                s[k] = _money(v)
        s["net_after_bills"] = _money(Decimal(str(s["platform_commission"])) - Decimal(str(s["bills_paid_amount"])))
    return stats


async def _bills_breakdown(db, month: str) -> dict:
    """Vendor bills for one month, by vendor and by category: recorded (bill_date in month) and
    paid (payment.paid_on in month). Cancelled bills are excluded."""
    lo, hi = f"{month}-01", f"{_add_months(month, 1)}-01"
    by_vendor: dict[str, dict] = {}
    by_category: dict[str, dict] = {}

    def blank(**kw):
        return {**kw, "recorded": 0.0, "recorded_count": 0, "paid": 0.0, "paid_count": 0, "pending": 0.0}
    async for b in db.vendor_bills.find(
            {"status": {"$ne": "cancelled"},
             "$or": [{"bill_date": {"$gte": lo, "$lt": hi}}, {"payment.paid_on": {"$gte": lo, "$lt": hi}}]},
            {"vendor_id": 1, "vendor_name": 1, "category": 1, "bill_date": 1, "total": 1, "status": 1,
             "payment.paid_on": 1}):
        total = float(b.get("total") or 0)
        cat = b.get("category") or "other"
        rows = (by_vendor.setdefault(b.get("vendor_id"), blank(vendor_id=b.get("vendor_id"),
                                                                vendor_name=b.get("vendor_name") or "Unknown vendor")),
                by_category.setdefault(cat, blank(category=cat)))
        recorded = lo <= (b.get("bill_date") or "") < hi
        paid = b.get("status") == "paid" and lo <= ((b.get("payment") or {}).get("paid_on") or "") < hi
        for r in rows:
            if recorded:
                r["recorded"] += total
                r["recorded_count"] += 1
                if b.get("status") == "pending":
                    r["pending"] += total
            if paid:
                r["paid"] += total
                r["paid_count"] += 1

    def done(rows):
        out = [{k: (_money(v) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
        out.sort(key=lambda r: (-(r["paid"] + r["recorded"]), r.get("vendor_name") or r.get("category") or ""))
        return out
    return {"by_vendor": done(by_vendor.values()), "by_category": done(by_category.values())}


def _check_month(month: Optional[str]) -> str:
    month = month or _current_month()
    if not re.match(MONTH_RE, month):
        raise ValueError("Invalid month: expected YYYY-MM")
    return month


async def _statement(db, month: str) -> dict:
    settings = await _settings(db)
    first = _add_months(month, -11)
    stats = await month_stats(db, first, month, settings)
    trailing = [{"month": ym, "label": _month_label(ym), **stats[ym]} for ym in sorted(stats)]
    totals = {f: (_money(sum(t[f] for t in trailing)) if isinstance(trailing[0][f], float) else sum(t[f] for t in trailing))
              for f in STAT_FIELDS}
    totals["net_after_bills"] = _money(Decimal(str(totals["platform_commission"]))
                                       - Decimal(str(totals["bills_paid_amount"])))
    return {"month": month, "label": _month_label(month), "summary": stats[month], "trailing": trailing,
            "trailing_totals": totals, "commission_pct": settings["commission_pct"], "gst_pct": settings["gst_pct"],
            "vendor_bills": await _bills_breakdown(db, month)}


@router.get("/statements")
async def get_statement(month: Optional[str] = None, current: UserPublic = Viewer):
    return await _statement(get_db(), _check_month(month))


STAT_LABELS = {
    "gross_revenue": "Gross booking revenue", "revenue_bookings": "Revenue bookings",
    "platform_commission": "Platform commission", "vendor_earnings": "Vendor earnings",
    "vendor_paid": "Vendor payouts paid", "vendor_owed": "Vendor payouts owed", "gst_collected": "GST collected",
    "invoices_issued": "Invoices issued", "invoiced_amount": "Invoiced amount", "invoices_paid": "Invoices paid",
    "paid_amount": "Paid amount", "invoices_outstanding": "Invoices outstanding", "outstanding_amount": "Outstanding amount",
    "invoices_void": "Invoices voided", "refunded_amount": "Refunded (voided paid invoices)",
    "cancelled_bookings": "Cancelled bookings", "pending_bookings": "Pending bookings",
    "uninvoiced_bookings": "Uninvoiced revenue bookings",
    "bills_recorded": "Vendor bills recorded", "bills_recorded_amount": "Vendor bills recorded amount",
    "bills_paid": "Vendor bills paid", "bills_paid_amount": "Vendor bills paid amount",
    "net_after_bills": "Net (commission - paid vendor bills)",
}


@router.get("/statements/export")
async def export_statement(month: Optional[str] = None, current: UserPublic = Viewer):
    db = get_db()
    st = await _statement(db, _check_month(month))
    header = ["Month"] + [STAT_LABELS[f] for f in STAT_FIELDS]
    rows = [[t["month"]] + [t[f] for f in STAT_FIELDS] for t in st["trailing"]]
    rows.append(["Trailing 12 months"] + [st["trailing_totals"][f] for f in STAT_FIELDS])
    vb = st["vendor_bills"]
    if vb["by_vendor"]:
        rows += [[], [f"Vendor bills by vendor · {st['label']}", "Recorded", "Recorded amount", "Paid",
                      "Paid amount", "Still pending"]]
        rows += [[r["vendor_name"], r["recorded_count"], r["recorded"], r["paid_count"], r["paid"], r["pending"]]
                 for r in vb["by_vendor"]]
        rows += [[], [f"Vendor bills by category · {st['label']}", "Recorded", "Recorded amount", "Paid",
                      "Paid amount", "Still pending"]]
        rows += [[r["category"], r["recorded_count"], r["recorded"], r["paid_count"], r["paid"], r["pending"]]
                 for r in vb["by_category"]]
    await log_activity(db, current, "Exported finance statement", MODULE, target=st["month"])
    return _csv_response(f"wavygo-statement-{st['month']}.csv", header, rows)


# ------------------------------------------------------------------ overview

def _ist_date_of(value) -> Optional[str]:
    dt = _as_utc(value)
    return dt.astimezone(IST).date().isoformat() if dt else None


def _payout_charge_date(p: dict) -> Optional[str]:
    """A booking payout is owed from the end of its period (or when created / paid, if earlier)."""
    dates = [d for d in (_ist_date_of(p.get("created_at")), p.get("period_end"), p.get("paid_on")) if d]
    return min(dates) if dates else None


async def _top_vendors(db, days: int = 90, limit: int = 5) -> dict:
    """Finance vendors ranked by spend over the last `days` days (IST, today inclusive).
    spent = paid bills (by payment date) + paid linked booking payouts (by paid_on);
    billed = bills recorded (by bill date) + linked payouts falling due. Cancelled bills are excluded."""
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows: dict[str, dict] = {}

    def row(vid):
        return rows.setdefault(vid, {"spent": 0.0, "billed": 0.0, "bills": 0})
    async for b in db.vendor_bills.find(
            {"status": {"$ne": "cancelled"}, "$or": [{"bill_date": {"$gte": since}}, {"payment.paid_on": {"$gte": since}}]},
            {"vendor_id": 1, "bill_date": 1, "total": 1, "status": 1, "payment.paid_on": 1}):
        r = row(b.get("vendor_id"))
        if (b.get("bill_date") or "") >= since:
            r["billed"] += float(b.get("total") or 0)
            r["bills"] += 1
        if b.get("status") == "paid" and ((b.get("payment") or {}).get("paid_on") or "") >= since:
            r["spent"] += float(b.get("total") or 0)
    linked = {d["marketplace_vendor_id"]: str(d["_id"]) async for d in db.finance_vendors.find(
        {"marketplace_vendor_id": {"$nin": [None, ""]}}, {"marketplace_vendor_id": 1})}
    if linked:
        async for p in db.payouts.find({"vendor_id": {"$in": list(linked)}},
                                       {"vendor_id": 1, "status": 1, "net": 1, "paid_on": 1, "created_at": 1,
                                        "period_end": 1}):
            charged, paid_on = _payout_charge_date(p), p.get("paid_on")
            is_new = bool(charged and charged >= since)
            is_paid = bool(p.get("status") == "paid" and paid_on and paid_on >= since)
            if not (is_new or is_paid):
                continue
            r = row(linked[p["vendor_id"]])
            if is_new:
                r["billed"] += float(p.get("net") or 0)
            if is_paid:
                r["spent"] += float(p.get("net") or 0)
    ranked = sorted(((vid, r) for vid, r in rows.items() if r["spent"] or r["billed"]),
                    key=lambda x: (-x[1]["spent"], -x[1]["billed"]))[:limit]
    ids = [vid for vid, _ in ranked]
    oids = [o for o in (_oid_or_none(i) for i in ids) if o]
    vendors = {str(d["_id"]): d async for d in db.finance_vendors.find(
        {"_id": {"$in": oids}}, {"name": 1, "category": 1, "status": 1})}
    stats = await _bill_stats(db, ids)
    items = []
    for vid, r in ranked:
        v = vendors.get(vid) or {}
        st = stats.get(vid) or {}
        items.append({"vendor_id": vid, "name": v.get("name") or "Unknown vendor", "category": v.get("category"),
                      "status": v.get("status"), "spent": _money(r["spent"]), "billed": _money(r["billed"]),
                      "bills": r["bills"], "bills_outstanding": _money(st.get("pending")),
                      "overdue": _money(st.get("overdue"))})
    return {"days": days, "since": since, "items": items}


@router.get("/overview")
async def overview(current: UserPublic = Viewer):
    db = get_db()
    settings = await _settings(db)
    month = _current_month()
    stats = await month_stats(db, _add_months(month, -11), month, settings)
    cur, prev = stats[month], stats[_add_months(month, -1)]
    receivable = await db.invoices.aggregate([
        {"$match": {"status": "issued"}}, {"$group": {"_id": None, "n": {"$sum": 1}, "total": {"$sum": "$total"}}}]).to_list(1)
    drafts = await db.invoices.count_documents({"status": "draft"})
    pending_payouts = await db.payouts.aggregate([
        {"$match": {"status": "pending"}}, {"$group": {"_id": None, "n": {"$sum": 1}, "net": {"$sum": "$net"}}}]).to_list(1)
    rev = await db.bookings.find({"status": {"$in": REVENUE_STATUSES}}, {"_id": 1}).to_list(None)
    rev_ids = [str(b["_id"]) for b in rev]
    uninvoiced = len(rev_ids) - len(await _live_invoice_booking_ids(db, rev_ids))
    bills_pending = await db.vendor_bills.aggregate([
        {"$match": {"status": "pending"}},
        {"$group": {"_id": None, "n": {"$sum": 1}, "total": {"$sum": "$total"},
                    "overdue": {"$sum": {"$cond": [{"$and": [{"$gt": [{"$ifNull": ["$due_date", ""]}, ""]},
                                                              {"$lt": ["$due_date", _today().isoformat()]}]},
                                                   "$total", 0]}}}}]).to_list(1)
    return {
        "month": month, "label": _month_label(month),
        "commission_pct": settings["commission_pct"], "gst_pct": settings["gst_pct"],
        "cards": {
            "gross_mtd": cur["gross_revenue"], "gross_prev": prev["gross_revenue"],
            "commission_mtd": cur["platform_commission"], "commission_prev": prev["platform_commission"],
            "gst_mtd": cur["gst_collected"], "bookings_mtd": cur["revenue_bookings"],
            "receivable": _money(receivable[0]["total"]) if receivable else 0.0,
            "receivable_count": receivable[0]["n"] if receivable else 0,
            "draft_invoices": drafts, "uninvoiced_bookings": uninvoiced,
            "payouts_pending": _money(pending_payouts[0]["net"]) if pending_payouts else 0.0,
            "payouts_pending_count": pending_payouts[0]["n"] if pending_payouts else 0,
            "bills_pending": _money(bills_pending[0]["total"]) if bills_pending else 0.0,
            "bills_pending_count": bills_pending[0]["n"] if bills_pending else 0,
            "bills_overdue": _money(bills_pending[0]["overdue"]) if bills_pending else 0.0,
            "bills_paid_mtd": cur["bills_paid_amount"], "net_mtd": cur["net_after_bills"],
        },
        "top_vendors": await _top_vendors(db),
        "series": [{"month": ym, "label": _month_start(ym).strftime("%b"), "revenue": stats[ym]["gross_revenue"],
                    "commission": stats[ym]["platform_commission"], "gst": stats[ym]["gst_collected"]}
                   for ym in sorted(stats)],
    }


# ------------------------------------------------------------------ vendors (suppliers / payees)

VENDOR_CATEGORIES = ("fleet_partner", "maintenance", "fuel_charging", "insurance", "marketing", "software",
                     "rent_utilities", "logistics", "professional_services", "office_supplies", "other")
VendorCategory = Literal["fleet_partner", "maintenance", "fuel_charging", "insurance", "marketing", "software",
                         "rent_utilities", "logistics", "professional_services", "office_supplies", "other"]
BILL_STATUSES = ("pending", "paid", "cancelled")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TAX_ID_RE = re.compile(r"^[A-Z0-9/-]{5,20}$")


def _blank_to_none(v):
    return None if isinstance(v, str) and not v.strip() else v


class VendorIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)
    contact_person: Optional[str] = Field(None, max_length=120)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=20, pattern=r"^[0-9+()\- ]{6,20}$")
    tax_id: Optional[str] = Field(None, max_length=20)
    category: VendorCategory = "other"
    address: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=1000)
    status: Literal["active", "inactive"] = "active"
    payment_terms_days: Optional[int] = Field(None, ge=0, le=365)
    marketplace_vendor_id: Optional[str] = None

    @field_validator("contact_person", "email", "phone", "tax_id", "address", "notes", "marketplace_vendor_id",
                     "payment_terms_days", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v.lower() if v else v

    @field_validator("tax_id")
    @classmethod
    def _tax_id(cls, v):
        if v is None:
            return v
        v = v.upper().replace(" ", "")
        if not TAX_ID_RE.match(v):
            raise ValueError("GSTIN / tax id must be 5-20 letters or digits")
        if len(v) == 15 and not GSTIN_RE.match(v):
            raise ValueError("GSTIN must be 15 characters (e.g. 10ABCDE1234F1Z5)")
        return v


class BillIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    vendor_id: str
    bill_number: Optional[str] = Field(None, max_length=60)
    bill_date: str = Field(pattern=DATE_RE)
    due_date: Optional[str] = Field(None, pattern=DATE_RE)
    description: str = Field(min_length=2, max_length=300)
    category: Optional[VendorCategory] = None
    amount: float = Field(gt=0, le=1_000_000_000)
    gst_amount: float = Field(0, ge=0, le=1_000_000_000)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("bill_number", "due_date", "notes", "category", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)


def _name_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


async def _get_vendor(db, vendor_id: str) -> dict:
    v = await db.finance_vendors.find_one({"_id": oid(vendor_id)})
    if not v:
        raise HTTPException(404, "Vendor not found")
    return v


async def _check_marketplace_link(db, mp_id: Optional[str], exclude: Optional[ObjectId] = None) -> Optional[str]:
    """Validates the optional link to a Marketplace fleet vendor (one finance vendor per marketplace vendor)."""
    if not mp_id:
        return None
    mp = await db.vendors.find_one({"_id": oid(mp_id)}, {"name": 1})
    if not mp:
        raise HTTPException(400, "Marketplace vendor not found")
    q: dict = {"marketplace_vendor_id": mp_id}
    if exclude is not None:
        q["_id"] = {"$ne": exclude}
    other = await db.finance_vendors.find_one(q, {"name": 1})
    if other:
        raise HTTPException(409, f"That marketplace vendor is already linked to {other.get('name')}")
    return mp.get("name")


async def _bill_stats(db, vendor_ids: Optional[list[str]] = None) -> dict[str, dict]:
    """Per finance vendor: paid (spent), pending (outstanding), overdue, count, last bill date."""
    today = _today().isoformat()
    match: dict = {"status": {"$ne": "cancelled"}}
    if vendor_ids is not None:
        match["vendor_id"] = {"$in": vendor_ids}
    rows = await db.vendor_bills.aggregate([
        {"$match": match},
        {"$group": {
            "_id": "$vendor_id",
            "bills": {"$sum": 1},
            "paid": {"$sum": {"$cond": [{"$eq": ["$status", "paid"]}, "$total", 0]}},
            "pending": {"$sum": {"$cond": [{"$eq": ["$status", "pending"]}, "$total", 0]}},
            "pending_count": {"$sum": {"$cond": [{"$eq": ["$status", "pending"]}, 1, 0]}},
            "overdue": {"$sum": {"$cond": [{"$and": [{"$eq": ["$status", "pending"]},
                                                      {"$gt": [{"$ifNull": ["$due_date", ""]}, ""]},
                                                      {"$lt": ["$due_date", today]}]}, "$total", 0]}},
            "last_bill_date": {"$max": "$bill_date"},
        }}]).to_list(None)
    return {r["_id"]: r for r in rows}


async def _payout_stats(db, mp_ids: list[str]) -> dict[str, dict]:
    if not mp_ids:
        return {}
    rows = await db.payouts.aggregate([
        {"$match": {"vendor_id": {"$in": mp_ids}}},
        {"$group": {"_id": "$vendor_id",
                    "paid": {"$sum": {"$cond": [{"$eq": ["$status", "paid"]}, "$net", 0]}},
                    "pending": {"$sum": {"$cond": [{"$eq": ["$status", "pending"]}, "$net", 0]}},
                    "count": {"$sum": 1}}}]).to_list(None)
    return {r["_id"]: r for r in rows}


def _vendor_out(v: dict, bills: Optional[dict], payouts: Optional[dict]) -> dict:
    b, p = bills or {}, payouts or {}
    bills_paid, bills_pending = _money(b.get("paid")), _money(b.get("pending"))
    payouts_paid, payouts_pending = _money(p.get("paid")), _money(p.get("pending"))
    out = serialize(v)
    out.pop("name_key", None)
    out.update({
        "bills_count": b.get("bills", 0), "pending_bills": b.get("pending_count", 0),
        "bills_paid": bills_paid, "bills_pending": bills_pending, "overdue": _money(b.get("overdue")),
        "payouts_count": p.get("count", 0), "payouts_paid": payouts_paid, "payouts_pending": payouts_pending,
        "total_spent": _money(bills_paid + payouts_paid), "outstanding": _money(bills_pending + payouts_pending),
        "last_bill_date": b.get("last_bill_date"),
    })
    return out


@router.get("/vendors")
async def list_vendors(q: Optional[str] = None, status: Optional[Literal["active", "inactive"]] = None,
                       category: Optional[VendorCategory] = None, current: UserPublic = Viewer):
    db = get_db()
    query: dict = {}
    if status:
        query["status"] = status
    if category:
        query["category"] = category
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"name": rx}, {"contact_person": rx}, {"email": rx}, {"phone": rx}, {"tax_id": rx}]
    docs = await db.finance_vendors.find(query).sort("name_key", 1).to_list(1000)
    bills = await _bill_stats(db, [str(d["_id"]) for d in docs])
    payouts = await _payout_stats(db, [d["marketplace_vendor_id"] for d in docs if d.get("marketplace_vendor_id")])
    items = [_vendor_out(d, bills.get(str(d["_id"])), payouts.get(d.get("marketplace_vendor_id"))) for d in docs]
    totals = {k: _money(sum(i[k] for i in items)) for k in ("total_spent", "outstanding", "overdue")}
    totals["vendors"] = len(items)
    totals["active"] = sum(1 for i in items if i.get("status") == "active")
    return {"items": items, "totals": totals}


@router.get("/vendors/marketplace-options")
async def marketplace_vendor_options(current: UserPublic = Viewer):
    """Marketplace (fleet) vendors, for linking a finance vendor and for filtering invoices / payouts."""
    db = get_db()
    linked = {d["marketplace_vendor_id"]: str(d["_id"]) async for d in db.finance_vendors.find(
        {"marketplace_vendor_id": {"$nin": [None, ""]}}, {"marketplace_vendor_id": 1})}
    docs = await db.vendors.find({}, {"name": 1, "active": 1}).sort("name", 1).to_list(2000)
    return [{"id": str(d["_id"]), "name": d.get("name") or "Unnamed vendor", "active": d.get("active", True),
             "finance_vendor_id": linked.get(str(d["_id"]))} for d in docs]


@router.post("/vendors", status_code=201)
async def create_vendor(payload: VendorIn, current: UserPublic = Manager):
    db = get_db()
    await _ready(db)
    data = payload.model_dump()
    mp_name = await _check_marketplace_link(db, data.get("marketplace_vendor_id"))
    now = utc_iso()
    doc = {**data, "name_key": _name_key(data["name"]), "marketplace_vendor_name": mp_name,
           "created_by": current.name, "created_at": now, "updated_at": now}
    try:
        res = await db.finance_vendors.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, f"A vendor named {data['name']} already exists")
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Added finance vendor", MODULE, target=doc["name"],
                       meta={"vendor_id": str(doc["_id"]), "category": doc["category"]})
    return _vendor_out(doc, None, None)


async def _vendor_history(db, v: dict, limit: int = 300) -> list[dict]:
    """Bills plus (for a linked marketplace vendor) booking payouts, newest first."""
    rows = []
    async for b in db.vendor_bills.find({"vendor_id": str(v["_id"])}).sort("bill_date", -1).limit(limit):
        rows.append({"type": "bill", "id": str(b["_id"]), "date": b.get("bill_date"),
                     "reference": b.get("bill_number"), "description": b.get("description"),
                     "amount": b.get("total"), "status": b.get("status"), "due_date": b.get("due_date"),
                     "paid_on": (b.get("payment") or {}).get("paid_on"),
                     "overdue": bool(b.get("status") == "pending" and b.get("due_date")
                                     and b["due_date"] < _today().isoformat())})
    if v.get("marketplace_vendor_id"):
        async for p in db.payouts.find({"vendor_id": v["marketplace_vendor_id"]}).sort("created_at", -1).limit(limit):
            rows.append({"type": "payout", "id": str(p["_id"]),
                         "date": p.get("paid_on") or str(p.get("created_at") or "")[:10],
                         "reference": p.get("reference") or f"batch {p.get('batch_id')}",
                         "description": f"Booking payout {p.get('period_start')} to {p.get('period_end')} · "
                                        f"{p.get('bookings_count')} booking(s)",
                         "amount": p.get("net"), "status": p.get("status"), "due_date": None,
                         "paid_on": p.get("paid_on"), "overdue": False})
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows[:limit]


@router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str, current: UserPublic = Viewer):
    db = get_db()
    v = await _get_vendor(db, vendor_id)
    bills = await _bill_stats(db, [str(v["_id"])])
    mp = v.get("marketplace_vendor_id")
    payouts = await _payout_stats(db, [mp] if mp else [])
    out = _vendor_out(v, bills.get(str(v["_id"])), payouts.get(mp))
    out["history"] = await _vendor_history(db, v)
    return out


def _statement_period(month: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> tuple[date, date]:
    if date_from or date_to:
        if not (date_from and date_to):
            raise HTTPException(400, "Provide both from and to dates")
        start, end = _parse_date(date_from, "from"), _parse_date(date_to, "to")
        if end < start:
            raise HTTPException(400, "The to date must be on or after the from date")
        if (end - start).days > 3700:
            raise HTTPException(400, "Statement range cannot exceed 10 years")
        return start, end
    m = _check_month(month)
    return _month_start(m), _month_start(_add_months(m, 1)) - timedelta(days=1)


def _ledger_entry(date_, kind, id_, reference, description, category, charge, payment, status,
                  due_date=None, overdue=False) -> dict:
    return {"date": date_, "kind": kind, "id": id_, "reference": reference, "description": description,
            "category": category, "charge": charge, "payment": payment, "status": status,
            "due_date": due_date, "overdue": overdue}


async def _vendor_ledger(db, v: dict) -> list[dict]:
    """Every charge (bill, linked booking payout) and payment for a vendor, oldest first.
    Cancelled bills are left out entirely, as if never owed."""
    today = _today().isoformat()
    entries = []
    async for b in db.vendor_bills.find({"vendor_id": str(v["_id"]), "status": {"$ne": "cancelled"}}):
        total, ref, bid = _money(b.get("total")), b.get("bill_number"), str(b["_id"])
        entries.append(_ledger_entry(
            b.get("bill_date"), "bill", bid, ref, b.get("description"), b.get("category"), total, 0.0, b.get("status"),
            b.get("due_date"), bool(b.get("status") == "pending" and b.get("due_date") and b["due_date"] < today)))
        pay = b.get("payment") or {}
        if b.get("status") == "paid" and pay.get("paid_on"):
            method = (pay.get("method") or "").replace("_", " ")
            desc = "Payment" + (f" for bill {ref}" if ref else "") + (f" via {method}" if method else "")
            entries.append(_ledger_entry(pay["paid_on"], "bill_payment", bid, pay.get("reference"), desc,
                                         b.get("category"), 0.0, total, "paid"))
    if v.get("marketplace_vendor_id"):
        async for p in db.payouts.find({"vendor_id": v["marketplace_vendor_id"]}):
            net, pid = _money(p.get("net")), str(p["_id"])
            desc = f"Booking payout {p.get('period_start')} to {p.get('period_end')} · {p.get('bookings_count')} booking(s)"
            entries.append(_ledger_entry(_payout_charge_date(p), "payout", pid,
                                         f"batch {p.get('batch_id')}", desc, "fleet_partner", net, 0.0, p.get("status")))
            if p.get("status") == "paid" and p.get("paid_on"):
                entries.append(_ledger_entry(p["paid_on"], "payout_payment", pid, p.get("reference"),
                                             f"Payout transfer · {desc}", "fleet_partner", 0.0, net, "paid"))
    order = {"bill": 0, "payout": 0, "bill_payment": 1, "payout_payment": 1}
    entries.sort(key=lambda e: (e["date"] or "", order[e["kind"]], e["id"]))
    return entries


async def _vendor_statement(db, v: dict, start: date, end: date) -> dict:
    lo, hi = start.isoformat(), end.isoformat()
    ledger = await _vendor_ledger(db, v)
    opening = sum((Decimal(str(e["charge"])) - Decimal(str(e["payment"])) for e in ledger if (e["date"] or "") < lo),
                  Decimal("0"))
    balance, charges, payments, charges_n, payments_n, lines = opening, Decimal("0"), Decimal("0"), 0, 0, []
    for e in ledger:
        if not (lo <= (e["date"] or "") <= hi):
            continue
        balance += Decimal(str(e["charge"])) - Decimal(str(e["payment"]))
        if e["charge"]:
            charges += Decimal(str(e["charge"]))
            charges_n += 1
        if e["payment"]:
            payments += Decimal(str(e["payment"]))
            payments_n += 1
        lines.append({**e, "balance": _money(balance)})
    settings = await _settings(db)
    vendor = {k: v.get(k) for k in ("name", "category", "contact_person", "email", "phone", "tax_id", "address",
                                    "status", "payment_terms_days", "marketplace_vendor_id", "marketplace_vendor_name")}
    vendor["id"] = str(v["_id"])
    whole_month = start.day == 1 and end == _month_start(_add_months(start.strftime("%Y-%m"), 1)) - timedelta(days=1)
    label = start.strftime("%b %Y") if whole_month else f"{start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}"
    return {
        "vendor": vendor, "from": lo, "to": hi, "label": label,
        "opening_balance": _money(opening), "charges": _money(charges), "charges_count": charges_n,
        "payments": _money(payments), "payments_count": payments_n, "closing_balance": _money(balance),
        "lines": lines, "generated_at": utc_iso(),
        "company": {k: settings.get(k) for k in ("company_name", "company_gstin", "company_state", "billing_address")},
    }


@router.get("/vendors/{vendor_id}/statement")
async def vendor_statement(vendor_id: str, month: Optional[str] = None,
                           date_from: Optional[str] = Query(None, alias="from"),
                           date_to: Optional[str] = Query(None, alias="to"), current: UserPublic = Viewer):
    """One vendor's account for a month (default: current) or a from/to range: opening outstanding,
    charges (bills and linked booking payouts) and payments in the period, closing outstanding and
    a running ledger."""
    db = get_db()
    v = await _get_vendor(db, vendor_id)
    start, end = _statement_period(month, date_from, date_to)
    return await _vendor_statement(db, v, start, end)


LEDGER_KINDS = {"bill": "Bill", "bill_payment": "Bill payment", "payout": "Booking payout",
                "payout_payment": "Payout transfer"}


@router.get("/vendors/{vendor_id}/statement/export")
async def export_vendor_statement(vendor_id: str, month: Optional[str] = None,
                                  date_from: Optional[str] = Query(None, alias="from"),
                                  date_to: Optional[str] = Query(None, alias="to"), current: UserPublic = Viewer):
    db = get_db()
    v = await _get_vendor(db, vendor_id)
    start, end = _statement_period(month, date_from, date_to)
    st = await _vendor_statement(db, v, start, end)
    header = ["Date", "Type", "Reference", "Description", "Charges", "Payments", "Balance"]
    rows = [[st["from"], "Opening balance", "", "", "", "", st["opening_balance"]]]
    rows += [[ln["date"], LEDGER_KINDS[ln["kind"]], ln["reference"], ln["description"], ln["charge"] or "",
              ln["payment"] or "", ln["balance"]] for ln in st["lines"]]
    rows.append([st["to"], "Closing balance", "", f"{st['charges_count']} charge(s), {st['payments_count']} payment(s)",
                 st["charges"], st["payments"], st["closing_balance"]])
    slug = re.sub(r"[^A-Za-z0-9]+", "-", v.get("name") or "").strip("-").lower()[:40] or "vendor"
    await log_activity(db, current, "Exported vendor statement", MODULE, target=f"{v['name']} · {st['label']}",
                       meta={"vendor_id": str(v["_id"]), "from": st["from"], "to": st["to"]})
    return _csv_response(f"wavygo-vendor-statement-{slug}-{st['from']}-to-{st['to']}.csv", header, rows)


@router.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, payload: VendorIn, current: UserPublic = Manager):
    db = get_db()
    await _ready(db)
    v = await _get_vendor(db, vendor_id)
    data = payload.model_dump()
    mp_name = await _check_marketplace_link(db, data.get("marketplace_vendor_id"), exclude=v["_id"])
    changed = sorted(k for k, val in data.items() if v.get(k) != val)
    try:
        await db.finance_vendors.update_one({"_id": v["_id"]}, {"$set": {
            **data, "name_key": _name_key(data["name"]), "marketplace_vendor_name": mp_name,
            "updated_at": utc_iso(), "updated_by": current.name}})
    except DuplicateKeyError:
        raise HTTPException(409, f"A vendor named {data['name']} already exists")
    if data["name"] != v.get("name"):
        await db.vendor_bills.update_many({"vendor_id": str(v["_id"])}, {"$set": {"vendor_name": data["name"]}})
    if changed:
        await log_activity(db, current, "Updated finance vendor", MODULE, target=data["name"], meta={"fields": changed})
    return await get_vendor(vendor_id, current)


@router.delete("/vendors/{vendor_id}")
async def delete_vendor(vendor_id: str, current: UserPublic = Manager):
    db = get_db()
    v = await _get_vendor(db, vendor_id)
    n = await db.vendor_bills.count_documents({"vendor_id": str(v["_id"])})
    if n:
        raise HTTPException(400, f"{v['name']} has {n} bill(s). Mark the vendor inactive instead.")
    await db.finance_vendors.delete_one({"_id": v["_id"]})
    await log_activity(db, current, "Deleted finance vendor", MODULE, target=v["name"])
    return {"ok": True}


# ------------------------------------------------------------------ vendor bills (expenses)

def _bill_query(vendor_id, status, month, category, q) -> dict:
    query: dict = {}
    if vendor_id:
        query["vendor_id"] = vendor_id
    if status == "overdue":
        query["status"] = "pending"
        query["due_date"] = {"$gt": "", "$lt": _today().isoformat()}
    elif status:
        if status not in BILL_STATUSES:
            raise ValueError("Invalid status")
        query["status"] = status
    if month:
        if not re.match(MONTH_RE, month):
            raise ValueError("Invalid month: expected YYYY-MM")
        query["bill_date"] = {"$regex": f"^{month}-"}
    if category:
        if category not in VENDOR_CATEGORIES:
            raise ValueError("Invalid category")
        query["category"] = category
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"bill_number": rx}, {"description": rx}, {"vendor_name": rx}]
    return query


def _bill_out(b: dict) -> dict:
    out = serialize(b)
    out["overdue"] = bool(b.get("status") == "pending" and b.get("due_date") and b["due_date"] < _today().isoformat())
    return out


def _check_bill_dates(bill_date: str, due_date: Optional[str]) -> None:
    if _parse_date(bill_date, "bill_date") > _today():
        raise HTTPException(400, "Bill date cannot be in the future")
    if due_date and _parse_date(due_date, "due_date") < date.fromisoformat(bill_date):
        raise HTTPException(400, "Due date must be on or after the bill date")


async def _bill_fields(db, payload: BillIn, current_vendor_id: Optional[str] = None) -> dict:
    v = await _get_vendor(db, payload.vendor_id)
    if v.get("status") == "inactive" and str(v["_id"]) != current_vendor_id:
        raise HTTPException(400, f"{v['name']} is inactive; reactivate the vendor to record bills")
    _check_bill_dates(payload.bill_date, payload.due_date)
    due = payload.due_date
    if not due and v.get("payment_terms_days") is not None:
        due = (date.fromisoformat(payload.bill_date) + timedelta(days=v["payment_terms_days"])).isoformat()
    amount, gst = _money(payload.amount), _money(payload.gst_amount)
    return {"vendor_id": str(v["_id"]), "vendor_name": v["name"], "bill_number": payload.bill_number,
            "bill_date": payload.bill_date, "due_date": due, "description": payload.description,
            "category": payload.category or v.get("category") or "other", "amount": amount, "gst_amount": gst,
            "total": _money(Decimal(str(amount)) + Decimal(str(gst))), "notes": payload.notes}


async def _get_bill(db, bill_id: str) -> dict:
    b = await db.vendor_bills.find_one({"_id": oid(bill_id)})
    if not b:
        raise HTTPException(404, "Bill not found")
    return b


@router.get("/bills")
async def list_bills(vendor_id: Optional[str] = None, status: Optional[str] = None, month: Optional[str] = None,
                     category: Optional[str] = None, q: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=500), skip: int = Query(0, ge=0),
                     current: UserPublic = Viewer):
    db = get_db()
    query = _bill_query(vendor_id, status, month, category, q)
    total = await db.vendor_bills.count_documents(query)
    docs = await db.vendor_bills.find(query).sort([("bill_date", -1), ("created_at", -1)]).skip(skip).to_list(limit)
    agg = await db.vendor_bills.aggregate([
        {"$match": query}, {"$group": {"_id": "$status", "n": {"$sum": 1}, "total": {"$sum": "$total"}}}]).to_list(None)
    summary = {s: {"count": 0, "total": 0.0} for s in BILL_STATUSES}
    for a in agg:
        summary[a["_id"]] = {"count": a["n"], "total": _money(a["total"])}
    od = await db.vendor_bills.aggregate([
        {"$match": {**query, "status": "pending", "due_date": {"$gt": "", "$lt": _today().isoformat()}}},
        {"$group": {"_id": None, "n": {"$sum": 1}, "total": {"$sum": "$total"}}}]).to_list(1)
    summary["overdue"] = {"count": od[0]["n"], "total": _money(od[0]["total"])} if od else {"count": 0, "total": 0.0}
    return {"items": [_bill_out(d) for d in docs], "total": total, "summary": summary}


@router.get("/bills/export")
async def export_bills(vendor_id: Optional[str] = None, status: Optional[str] = None, month: Optional[str] = None,
                       category: Optional[str] = None, q: Optional[str] = None, current: UserPublic = Viewer):
    db = get_db()
    docs = await db.vendor_bills.find(_bill_query(vendor_id, status, month, category, q)).sort(
        [("bill_date", 1), ("created_at", 1)]).to_list(None)
    header = ["Bill date", "Bill number", "Vendor", "Category", "Description", "Amount", "GST", "Total", "Status",
              "Due date", "Paid on", "Payment method", "Payment reference", "Cancel reason"]
    rows = []
    for d in docs:
        p = d.get("payment") or {}
        rows.append([d.get("bill_date"), d.get("bill_number"), d.get("vendor_name"), d.get("category"),
                     d.get("description"), d.get("amount"), d.get("gst_amount"), d.get("total"), d.get("status"),
                     d.get("due_date"), p.get("paid_on"), p.get("method"), p.get("reference"), d.get("cancel_reason")])
    await log_activity(db, current, "Exported vendor bills CSV", MODULE, target=month or "all", meta={"rows": len(rows)})
    return _csv_response(f"wavygo-vendor-bills-{month or 'all'}.csv", header, rows)


@router.post("/bills", status_code=201)
async def create_bill(payload: BillIn, current: UserPublic = Manager):
    db = get_db()
    await _ready(db)
    fields = await _bill_fields(db, payload)
    now = utc_iso()
    doc = {**fields, "status": "pending", "payment": None, "paid_at": None, "cancel_reason": None,
           "created_by": current.name, "created_at": now, "updated_at": now}
    res = await db.vendor_bills.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Recorded vendor bill", MODULE, target=f"{doc['vendor_name']} · ₹{doc['total']:,.2f}",
                       meta={"bill_id": str(doc["_id"]), "vendor_id": doc["vendor_id"], "total": doc["total"]})
    return _bill_out(doc)


@router.put("/bills/{bill_id}")
async def update_bill(bill_id: str, payload: BillIn, current: UserPublic = Manager):
    db = get_db()
    b = await _get_bill(db, bill_id)
    if b["status"] != "pending":
        raise HTTPException(400, f"Only pending bills can be edited; this bill is {b['status']}")
    fields = await _bill_fields(db, payload, current_vendor_id=b["vendor_id"])
    res = await db.vendor_bills.update_one({"_id": b["_id"], "status": "pending"},
                                           {"$set": {**fields, "updated_at": utc_iso(), "updated_by": current.name}})
    if not res.matched_count:
        raise HTTPException(409, "Bill changed, reload and try again")
    b = await db.vendor_bills.find_one({"_id": b["_id"]})
    await log_activity(db, current, "Updated vendor bill", MODULE, target=f"{b['vendor_name']} · ₹{b['total']:,.2f}")
    return _bill_out(b)


@router.post("/bills/{bill_id}/pay")
async def pay_bill(bill_id: str, payload: PayIn, current: UserPublic = Manager):
    db = get_db()
    b = await _get_bill(db, bill_id)
    if b["status"] != "pending":
        raise HTTPException(400, "Bill is already paid" if b["status"] == "paid" else "Cancelled bills cannot be paid")
    paid_on = payload.paid_on or _today().isoformat()
    if _parse_date(paid_on, "paid_on") > _today():
        raise HTTPException(400, "Payment date cannot be in the future")
    if paid_on < b["bill_date"]:
        raise HTTPException(400, "Payment date cannot be before the bill date")
    payment = {"paid_on": paid_on, "method": payload.method, "reference": (payload.reference or "").strip() or None,
               "recorded_by": current.name}
    res = await db.vendor_bills.update_one({"_id": b["_id"], "status": "pending"}, {"$set": {
        "status": "paid", "payment": payment, "paid_at": utc_iso(), "updated_at": utc_iso()}})
    if not res.modified_count:
        raise HTTPException(409, "Bill changed, reload and try again")
    b = await db.vendor_bills.find_one({"_id": b["_id"]})
    await log_activity(db, current, "Paid vendor bill", MODULE, target=f"{b['vendor_name']} · ₹{b['total']:,.2f}",
                       meta={"method": payload.method, "bill_id": str(b["_id"])})
    await notify(db, current.id, "Vendor bill paid",
                 f"{b['vendor_name']} · ₹{b['total']:,.2f} via {payload.method.replace('_', ' ')}", kind="success", link=LINK)
    return _bill_out(b)


@router.post("/bills/{bill_id}/cancel")
async def cancel_bill(bill_id: str, payload: VoidIn, current: UserPublic = Manager):
    db = get_db()
    b = await _get_bill(db, bill_id)
    if b["status"] == "cancelled":
        raise HTTPException(400, "Bill is already cancelled")
    res = await db.vendor_bills.update_one({"_id": b["_id"], "status": b["status"]}, {"$set": {
        "status": "cancelled", "cancel_reason": payload.reason, "cancelled_from": b["status"],
        "cancelled_at": utc_iso(), "updated_at": utc_iso()}})
    if not res.modified_count:
        raise HTTPException(409, "Bill changed, reload and try again")
    b = await db.vendor_bills.find_one({"_id": b["_id"]})
    await log_activity(db, current, "Cancelled vendor bill", MODULE, target=f"{b['vendor_name']} · ₹{b['total']:,.2f}",
                       meta={"reason": payload.reason, "was": b["cancelled_from"]})
    return _bill_out(b)


@router.delete("/bills/{bill_id}")
async def delete_bill(bill_id: str, current: UserPublic = Manager):
    """Only pending bills can be deleted (e.g. entered by mistake); paid bills are cancelled instead."""
    db = get_db()
    b = await _get_bill(db, bill_id)
    res = await db.vendor_bills.delete_one({"_id": b["_id"], "status": "pending"})
    if not res.deleted_count:
        raise HTTPException(400, "Only pending bills can be deleted; cancel it instead")
    await log_activity(db, current, "Deleted vendor bill", MODULE, target=f"{b['vendor_name']} · ₹{b['total']:,.2f}")
    return {"ok": True}
