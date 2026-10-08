from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from db import get_db, utc_now
from auth_utils import get_current_user
from models import UserPublic
from hub_utils import role_notification_filter

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Personal notifications (user_id set) keep a single `read` flag.
# Broadcasts (user_id None) are shared, so read state is tracked per
# user in a `read_by` array of user ids.


def _is_read(doc, user_id: str) -> bool:
    if doc.get("user_id") is None:
        return user_id in (doc.get("read_by") or [])
    return bool(doc.get("read", False))


def _unread_q(user_id: str) -> dict:
    return {"$or": [
        {"user_id": user_id, "read": {"$ne": True}},
        {"user_id": None, "read_by": {"$ne": user_id}},
    ]}


def _serialize(doc, user_id: str):
    return {
        "id": str(doc["_id"]),
        "title": doc["title"],
        "body": doc["body"],
        "kind": doc.get("kind", "info"),
        "read": _is_read(doc, user_id),
        "link": doc.get("link"),
        "created_at": doc.get("created_at"),
    }


@router.get("")
async def list_notifications(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = role_notification_filter(current.role, current.id)
    docs = await db.notifications.find(q).sort("created_at", -1).to_list(200)
    return [_serialize(d, current.id) for d in docs]


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    try:
        oid = ObjectId(notif_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    # Only notifications the caller can see (same filter as the list)
    role_q = role_notification_filter(current.role, current.id)
    doc = await db.notifications.find_one({"$and": [{"_id": oid}, role_q]}, {"user_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Notification not found")
    if doc.get("user_id") is None:
        update = {"$addToSet": {"read_by": current.id}}
    else:
        update = {"$set": {"read": True, "read_at": utc_now().isoformat()}}
    await db.notifications.update_one({"_id": oid}, update)
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = role_notification_filter(current.role, current.id)
    await db.notifications.update_many(
        {"$and": [q, {"user_id": current.id}, {"read": {"$ne": True}}]},
        {"$set": {"read": True, "read_at": utc_now().isoformat()}},
    )
    await db.notifications.update_many(
        {"$and": [q, {"user_id": None}, {"read_by": {"$ne": current.id}}]},
        {"$addToSet": {"read_by": current.id}},
    )
    return {"ok": True}


@router.get("/unread-count")
async def unread_count(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    role_q = role_notification_filter(current.role, current.id)
    q = {"$and": [_unread_q(current.id), role_q]}
    count = await db.notifications.count_documents(q)
    return {"count": count}
