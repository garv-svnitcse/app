from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from db import get_db, utc_now
from auth_utils import get_current_user
from models import UserPublic
from hub_utils import role_notification_filter

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _serialize(doc):
    return {
        "id": str(doc["_id"]),
        "title": doc["title"],
        "body": doc["body"],
        "kind": doc.get("kind", "info"),
        "read": doc.get("read", False),
        "link": doc.get("link"),
        "created_at": doc.get("created_at"),
    }


@router.get("")
async def list_notifications(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = role_notification_filter(current.role, current.id)
    docs = await db.notifications.find(q).sort("created_at", -1).to_list(200)
    return [_serialize(d) for d in docs]


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    try:
        oid = ObjectId(notif_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await db.notifications.update_one({"_id": oid}, {"$set": {"read": True}})
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = role_notification_filter(current.role, current.id)
    await db.notifications.update_many(
        q,
        {"$set": {"read": True}},
    )
    return {"ok": True}


@router.get("/unread-count")
async def unread_count(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    role_q = role_notification_filter(current.role, current.id)
    q = {"$and": [{"read": False}, role_q]}
    count = await db.notifications.count_documents(q)
    return {"count": count}
