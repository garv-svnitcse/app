from __future__ import annotations
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from db import get_db
from auth_utils import get_current_user
from models import UserPublic


async def _dept_ids(db, department):
    if not department:
        return []
    return [str(u["_id"]) async for u in db.users.find({"department": department}, {"_id": 1})]

async def _team_ids(db, current: UserPublic):
    """A Manager's department members, always including the Manager (who may have no department)."""
    ids = await _dept_ids(db, current.department)
    return ids if current.id in ids else ids + [current.id]

router = APIRouter(prefix="/activity", tags=["activity"])


def _serialize(doc):
    return {
        "id": str(doc["_id"]),
        "user_id": doc.get("user_id"),
        "user_name": doc.get("user_name"),
        "user_role": doc.get("user_role"),
        "action": doc.get("action"),
        "module": doc.get("module"),
        "target": doc.get("target"),
        "created_at": doc.get("created_at"),
    }


def _scope_check(current: UserPublic):
    if current.role in ("Employee", "Intern"):
        raise HTTPException(status_code=403, detail="Activity logs are not available for your role")


@router.get("/modules")
async def list_modules(current: UserPublic = Depends(get_current_user)):
    """Distinct module names in the caller's visible activity, for the module filter."""
    db = get_db()
    _scope_check(current)
    q = {}
    if current.role == "Manager":
        q["user_id"] = {"$in": await _team_ids(db, current)}
    return sorted(m for m in await db.activity_logs.distinct("module", q) if m)


def _cursor(doc) -> str:
    return f"{doc.get('created_at') or ''}|{doc['_id']}"


def _before_filter(before: str) -> dict:
    """Keyset cursor "<created_at>|<id>" (or a bare created_at): rows strictly older in
    (created_at desc, _id desc) order, so entries sharing a timestamp are never skipped."""
    created, _, oid = before.partition("|")
    if oid and ObjectId.is_valid(oid):
        return {"$or": [{"created_at": {"$lt": created}},
                        {"created_at": created, "_id": {"$lt": ObjectId(oid)}}]}
    return {"created_at": {"$lt": created}}


@router.get("")
async def list_activity(
    limit: int = Query(50, ge=1, le=200),
    module: str | None = None,
    before: str | None = Query(None, description="Cursor from a previous page's next_cursor"),
    paged: bool = Query(False, description="Return {items, has_more, next_cursor} instead of a bare list"),
    current: UserPublic = Depends(get_current_user),
):
    db = get_db()
    _scope_check(current)
    q = {}
    if module:
        q["module"] = module
    if current.role == "Manager":
        q["user_id"] = {"$in": await _team_ids(db, current)}
    if before:
        q = {"$and": [q, _before_filter(before)]} if q else _before_filter(before)
    docs = await db.activity_logs.find(q).sort([("created_at", -1), ("_id", -1)]).to_list(limit + 1)
    has_more = len(docs) > limit
    docs = docs[:limit]
    items = [_serialize(d) for d in docs]
    if not paged:
        return items
    return {"items": items, "has_more": has_more, "next_cursor": _cursor(docs[-1]) if has_more else None}
