from __future__ import annotations
"""Shared helpers for Part 2+ modules: activity logs, notifications, doc serialisation."""
from datetime import datetime, timezone
from typing import Any, Iterable
from bson import ObjectId


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def oid(value: str) -> ObjectId:
    """Coerce a string to ObjectId with a friendly error."""
    if not ObjectId.is_valid(value):
        raise ValueError(f"Invalid id: {value}")
    return ObjectId(value)


def serialize(doc: dict | None, drop: Iterable[str] = ("password_hash",)) -> dict | None:
    if doc is None:
        return None
    out = {}
    for k, v in doc.items():
        if k in drop:
            continue
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, ObjectId):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def serialize_many(docs, drop: Iterable[str] = ("password_hash",)) -> list[dict]:
    return [serialize(d, drop) for d in docs]


async def log_activity(db, user, action: str, module: str, target: str | None = None, meta: dict | None = None):
    """user can be UserPublic or dict; must have id, name, role."""
    uid = getattr(user, "id", None) or user.get("id") if isinstance(user, dict) else user.id
    name = getattr(user, "name", None) or (user.get("name") if isinstance(user, dict) else None)
    role = getattr(user, "role", None) or (user.get("role") if isinstance(user, dict) else None)
    entry: dict[str, Any] = {
        "user_id": uid,
        "user_name": name,
        "user_role": role,
        "action": action,
        "module": module,
        "target": target,
        "created_at": utc_iso(),
    }
    if meta:
        entry["meta"] = meta
    await db.activity_logs.insert_one(entry)


async def notify(db, user_id: str | None, title: str, body: str, kind: str = "info", link: str | None = None):
    """user_id=None sends a broadcast notification visible to everyone."""
    await db.notifications.insert_one({
        "user_id": user_id,
        "title": title,
        "body": body,
        "kind": kind,
        "read": False,
        "link": link,
        "created_at": utc_iso(),
    })


def role_notification_filter(user_role: str, user_id: str) -> dict:
    """Filter notifications by role so employee-specific details are kept private.
    
    - Employees & Interns:
      Can only see:
      1. Notifications explicitly targeted to them (user_id == user_id)
      2. General company announcements or teammate joined notices (user_id == None),
         never other employees' leave requests or private details.
    - Managers:
      Can see notifications targeted to them and general broadcasts (excluding cross-department leave requests).
    - Founders & Admins:
      Can see all notifications targeted to them or general system broadcasts.
    """
    if user_role in ("Employee", "Intern"):
        return {
            "$or": [
                {"user_id": user_id},
                {
                    "user_id": None,
                    "title": {"$regex": "^(New teammate joined|Announcement)", "$options": "i"},
                },
            ]
        }
    elif user_role == "Manager":
        return {
            "$or": [
                {"user_id": user_id},
                {
                    "user_id": None,
                    "title": {"$not": {"$regex": "^Leave request", "$options": "i"}},
                },
            ]
        }
    else:
        return {"$or": [{"user_id": user_id}, {"user_id": None}]}
