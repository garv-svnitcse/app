from __future__ import annotations
import math
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, model_validator
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import OpportunityIn, OpportunityAssign, OpportunityStatusPatch, OpportunityType, OpportunityStatus
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify
from email_utils import notify_assignment_by_email

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

# Assignees (Employees) may only touch these fields of their own opportunities.
EMPLOYEE_FIELDS = ("status", "notes", "documents")


class OpportunityPatch(BaseModel):
    """Partial opportunity update; unknown keys (id, assignee_name, created_by, ...) are ignored."""
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(None, max_length=300)
    type: Optional[OpportunityType] = None
    description: Optional[str] = Field(None, max_length=5000)
    organisation: Optional[str] = Field(None, max_length=300)
    deadline: Optional[str] = Field(None, max_length=40)
    value_lakhs: Optional[float] = Field(None, ge=0, le=10_000_000, allow_inf_nan=False)
    status: Optional[OpportunityStatus] = None
    assignee_id: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=5000)
    documents: Optional[List[Annotated[str, Field(max_length=2000)]]] = Field(None, max_length=50)
    link: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _check_required(self):
        nulled = [f for f in ("title", "type", "status") if f in self.model_fields_set and getattr(self, f) is None]
        if nulled:
            raise ValueError(f"Fields cannot be null: {', '.join(nulled)}")
        if "title" in self.model_fields_set and not self.title.strip():
            raise ValueError("Title is required")
        return self


async def _dept_ids(db, department):
    if not department:
        return []
    return [str(u["_id"]) async for u in db.users.find({"department": department}, {"_id": 1})]


async def _manager_ids(db, current: UserPublic):
    """A Manager's department members, always including the Manager (who may have no department)."""
    ids = await _dept_ids(db, current.department)
    if current.id not in ids:
        ids.append(current.id)
    return ids


def _unassigned(doc) -> bool:
    return not doc.get("assignee_id")


async def _scope_filter(db, current: UserPublic):
    """Role visibility shared by list, stats and single reads.
    Managers: their department's opportunities plus the unassigned pool. Employees: their own."""
    if current.role == "Intern":
        raise HTTPException(403, "Interns do not have access to opportunities")
    if current.role == "Manager":
        ids = await _manager_ids(db, current)
        return {"$or": [{"assignee_id": {"$in": ids}}, {"assignee_id": None},
                        {"assignee_id": {"$exists": False}}, {"assignee_id": ""}]}
    if current.role == "Employee":
        return {"assignee_id": current.id}
    return None


async def _load_opp(db, opp_id: str, current: UserPublic):
    """Fetch one opportunity with the same visibility rules as the list."""
    if current.role == "Intern":
        raise HTTPException(403, "Interns do not have access to opportunities")
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    if current.role == "Employee" and doc.get("assignee_id") != current.id:
        raise HTTPException(403, "You can only access opportunities assigned to you")
    if current.role == "Manager" and not _unassigned(doc) and doc["assignee_id"] not in await _manager_ids(db, current):
        raise HTTPException(403, "Managers can only access opportunities in their department")
    return doc


async def _check_manager_write(db, doc, ids):
    """Managers act on their department's opportunities and on the unassigned pool,
    except unassigned ones that another department's Manager logged."""
    if not _unassigned(doc):
        if doc["assignee_id"] not in ids:
            raise HTTPException(403, "Managers can only edit opportunities in their department")
        return
    creator = doc.get("created_by")
    if creator and creator not in ids and ObjectId.is_valid(creator):
        u = await db.users.find_one({"_id": ObjectId(creator)}, {"role": 1})
        if u and u.get("role") == "Manager":
            raise HTTPException(403, "This opportunity belongs to another department")


async def _can_write(db, doc, current: UserPublic, ids, creator_is_manager: dict) -> bool:
    """Non-raising mirror of the write rules (for the `can_edit` flag on reads). Employees only ever
    see their own opportunities, which they may update (status / notes / documents)."""
    if current.role != "Manager":
        return True
    if not _unassigned(doc):
        return doc["assignee_id"] in ids
    creator = doc.get("created_by")
    if creator and creator not in ids and ObjectId.is_valid(creator):
        if creator not in creator_is_manager:
            u = await db.users.find_one({"_id": ObjectId(creator)}, {"role": 1})
            creator_is_manager[creator] = bool(u and u.get("role") == "Manager")
        return not creator_is_manager[creator]
    return True


async def _check_assignee(db, current: UserPublic, assignee_id: str, ids=None):
    """The assignee must be an existing user; Managers may only assign within their department."""
    if not ObjectId.is_valid(assignee_id) or not await db.users.find_one({"_id": ObjectId(assignee_id)}, {"_id": 1}):
        raise HTTPException(400, "Assignee not found")
    if current.role == "Manager" and assignee_id not in (ids if ids is not None else await _manager_ids(db, current)):
        raise HTTPException(403, "Managers can only assign opportunities within their department")


def _lakhs(value) -> float:
    """Legacy rows may hold strings or junk in value_lakhs; only real non-negative numbers count."""
    if isinstance(value, bool):
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) and f > 0 else 0.0


async def _enrich(db, doc):
    if doc.get("assignee_id"):
        try:
            u = await db.users.find_one({"_id": ObjectId(doc["assignee_id"])}, {"name": 1, "photo": 1, "role": 1})
            if u:
                doc["assignee_name"] = u["name"]
                doc["assignee_photo"] = u.get("photo")
        except Exception:
            pass
    return doc


@router.get("")
async def list_opps(status: str | None = None, type: str | None = None,
                    assignee_id: str | None = None,
                    limit: int = Query(200, ge=1, le=500),
                    current: UserPublic = Depends(get_current_user)):
    db = get_db()
    role_filter = await _scope_filter(db, current)
    q = {}
    if status: q["status"] = status
    if type: q["type"] = type
    if assignee_id: q["assignee_id"] = assignee_id

    if role_filter:
        q = {"$and": [q, role_filter]} if q else role_filter

    # Soonest deadline first; opportunities with no deadline go last (Mongo sorts missing values first).
    docs = await db.opportunities.aggregate([
        {"$match": q},
        {"$addFields": {"_no_deadline": {"$in": [{"$ifNull": ["$deadline", ""]}, ["", None]]}}},
        {"$sort": {"_no_deadline": 1, "deadline": 1, "_id": 1}},
        {"$limit": limit},
        {"$project": {"_no_deadline": 0}},
    ]).to_list(limit)
    ids = await _manager_ids(db, current) if current.role == "Manager" else None
    cache: dict = {}
    for d in docs:
        await _enrich(db, d)
        d["can_edit"] = await _can_write(db, d, current, ids, cache)
    return serialize_many(docs)


@router.post("", status_code=201)
async def create_opp(payload: OpportunityIn,
                     background_tasks: BackgroundTasks,
                     current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    doc = payload.model_dump()
    doc["title"] = (doc.get("title") or "").strip()
    if not doc["title"]:
        raise HTTPException(422, "Title is required")
    doc["assignee_id"] = doc.get("assignee_id") or None
    if doc["assignee_id"]:
        await _check_assignee(db, current, doc["assignee_id"])
        # Same rule as POST /{id}/assign: an assigned opportunity is no longer "open".
        if doc.get("status") == "open":
            doc["status"] = "assigned"
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    doc["created_by"] = current.id
    res = await db.opportunities.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _enrich(db, doc)
    await log_activity(db, current, "Logged opportunity", "Opportunity Hub", target=doc["title"])
    if doc.get("assignee_id") and doc["assignee_id"] != current.id:
        await notify(db, doc["assignee_id"], "Opportunity assigned",
                     f"{current.name} assigned you: {doc['title']}", kind="info", link=f"/opportunity-hub?opp={doc['_id']}")
    if doc.get("assignee_id"):
        await notify_assignment_by_email(
            db=db,
            assignee_id=doc["assignee_id"],
            item_type="opportunity",
            item_title=doc.get("title", "Untitled Opportunity"),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("type"),
            deadline=doc.get("deadline"),
            item_id=str(doc["_id"]),
            background_tasks=background_tasks,
        )
    return serialize(doc)


@router.get("/stats/overview")
async def opp_stats(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = await _scope_filter(db, current) or {}

    async def c(status_val):
        query = {"$and": [q, {"status": status_val}]} if q else {"status": status_val}
        return await db.opportunities.count_documents(query)

    mine_query = {"assignee_id": current.id, "status": {"$nin": ["won", "lost", "closed"]}}

    active_q = {"$and": [q, {"status": {"$in": ["open", "assigned", "in_progress"]}}]} if q else {"status": {"$in": ["open", "assigned", "in_progress"]}}
    pipeline_cursor = db.opportunities.find(active_q, {"value_lakhs": 1})
    pipeline_lakhs = sum([_lakhs(doc.get("value_lakhs")) async for doc in pipeline_cursor])

    won_q = {"$and": [q, {"status": "won"}]} if q else {"status": "won"}
    won_cursor = db.opportunities.find(won_q, {"value_lakhs": 1})
    won_lakhs = sum([_lakhs(doc.get("value_lakhs")) async for doc in won_cursor])

    return {
        "open":        await c("open"),
        "assigned":    await c("assigned"),
        "in_progress": await c("in_progress"),
        "won":         await c("won"),
        "lost":        await c("lost"),
        "closed":      await c("closed"),
        "mine":        await db.opportunities.count_documents(mine_query),
        "pipeline_lakhs": round(pipeline_lakhs, 2),
        "won_lakhs": round(won_lakhs, 2),
    }


@router.get("/{opp_id}")
async def get_opp(opp_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    doc = await _load_opp(db, opp_id, current)
    await _enrich(db, doc)
    ids = await _manager_ids(db, current) if current.role == "Manager" else None
    doc["can_edit"] = await _can_write(db, doc, current, ids, {})
    return serialize(doc)


@router.patch("/{opp_id}")
async def update_opp(opp_id: str, payload: OpportunityPatch,
                     background_tasks: BackgroundTasks,
                     current: UserPublic = Depends(get_current_user)):
    db = get_db()
    existing = await _load_opp(db, opp_id, current)
    changes = payload.model_dump(exclude_unset=True)
    ids = None
    if current.role == "Employee":
        changes = {k: v for k, v in changes.items() if k in EMPLOYEE_FIELDS}
        if not changes:
            raise HTTPException(403, "You can only edit status, notes or documents")
    elif current.role == "Manager":
        ids = await _manager_ids(db, current)
        await _check_manager_write(db, existing, ids)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
    if "assignee_id" in changes:
        changes["assignee_id"] = changes["assignee_id"] or None
        if changes["assignee_id"] == existing.get("assignee_id"):
            changes.pop("assignee_id")
        elif changes["assignee_id"]:
            await _check_assignee(db, current, changes["assignee_id"], ids)
    new_assignee = changes.get("assignee_id")
    # Same rule as POST /{id}/assign: an assigned opportunity is no longer "open";
    # clearing the assignee puts an "assigned" one back in the open pool.
    if new_assignee and changes.get("status", existing.get("status")) == "open":
        changes["status"] = "assigned"
    elif "assignee_id" in changes and not new_assignee             and changes.get("status", existing.get("status")) == "assigned":
        changes["status"] = "open"
    changes["updated_at"] = utc_iso()
    res = await db.opportunities.update_one({"_id": oid(opp_id)}, {"$set": changes})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    await _enrich(db, doc)
    if new_assignee and new_assignee != current.id:
        await notify(db, new_assignee, "Opportunity assigned",
                     f"{current.name} assigned you: {doc['title']}", kind="info", link=f"/opportunity-hub?opp={opp_id}")
    if new_assignee:
        await notify_assignment_by_email(
            db=db,
            assignee_id=new_assignee,
            item_type="opportunity",
            item_title=doc.get("title", existing.get("title", "Untitled Opportunity")),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("type", existing.get("type")),
            deadline=doc.get("deadline", existing.get("deadline")),
            item_id=opp_id,
            background_tasks=background_tasks,
        )
    await log_activity(db, current, "Updated opportunity", "Opportunity Hub", target=doc["title"],
                       meta={"fields": sorted(k for k in changes if k != "updated_at")})
    return serialize(doc)


@router.post("/{opp_id}/assign")
async def assign_opp(opp_id: str, payload: OpportunityAssign,
                     background_tasks: BackgroundTasks,
                     current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    existing = await db.opportunities.find_one({"_id": oid(opp_id)})
    if not existing:
        raise HTTPException(404, "Not found")
    ids = None
    if current.role == "Manager":
        ids = await _manager_ids(db, current)
        await _check_manager_write(db, existing, ids)
    await _check_assignee(db, current, payload.assignee_id, ids)
    upd = {"assignee_id": payload.assignee_id, "updated_at": utc_iso()}
    if existing.get("status") in (None, "open"):
        upd["status"] = "assigned"  # never downgrade in_progress / won / lost / closed
    await db.opportunities.update_one({"_id": oid(opp_id)}, {"$set": upd})
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    await _enrich(db, doc)
    await log_activity(db, current, "Assigned opportunity", "Opportunity Hub",
                       target=f"{doc['title']} → {doc.get('assignee_name')}")
    changed = payload.assignee_id != existing.get("assignee_id")
    if changed and payload.assignee_id != current.id:
        await notify(db, payload.assignee_id, "Opportunity assigned",
                     f"{current.name} assigned you: {doc['title']}", kind="info", link=f"/opportunity-hub?opp={opp_id}")
    if changed:
        await notify_assignment_by_email(
            db=db,
            assignee_id=payload.assignee_id,
            item_type="opportunity",
            item_title=doc.get("title", "Untitled Opportunity"),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("type"),
            deadline=doc.get("deadline"),
            item_id=opp_id,
            background_tasks=background_tasks,
        )
    return serialize(doc)


@router.patch("/{opp_id}/status")
async def update_opp_status(opp_id: str, payload: OpportunityStatusPatch, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    existing = await _load_opp(db, opp_id, current)
    if current.role == "Manager":
        await _check_manager_write(db, existing, await _manager_ids(db, current))
    await db.opportunities.update_one({"_id": oid(opp_id)}, {"$set": {"status": payload.status, "updated_at": utc_iso()}})
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    await _enrich(db, doc)
    await log_activity(db, current, f"Opportunity → {payload.status}", "Opportunity Hub", target=doc["title"])
    return serialize(doc)


@router.delete("/{opp_id}")
async def delete_opp(opp_id: str, current: UserPublic = Depends(require_roles("Founder"))):
    db = get_db()
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    await db.opportunities.delete_one({"_id": oid(opp_id)})
    await log_activity(db, current, "Deleted opportunity", "Opportunity Hub", target=doc["title"])
    return {"ok": True}
