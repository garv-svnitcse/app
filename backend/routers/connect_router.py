from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import ChannelIn, MessageIn
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify

router = APIRouter(prefix="/connect", tags=["connect"])


async def _channel_meta(db, doc, current_id: str):
    last = None
    if doc.get("last_message_at"):
        last = doc["last_message_at"]
    unread = 0  # future: track per-user read cursor
    doc["last_message_at"] = last
    doc["unread"] = unread
    # For DMs, resolve peer name
    if doc.get("kind") == "dm":
        peer_id = next((m for m in doc.get("members", []) if m != current_id), None)
        if peer_id:
            u = await db.users.find_one({"_id": ObjectId(peer_id)}, {"name": 1, "photo": 1, "role": 1, "online": 1})
            if u:
                doc["display_name"] = u["name"]
                doc["peer_photo"] = u.get("photo")
                doc["peer_role"] = u.get("role")
                doc["peer_online"] = u.get("online", False)
    return doc


@router.get("/channels")
async def list_channels(kind: str | None = None, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if kind:
        q["kind"] = kind
    # visible: public channels + those the user belongs to
    q["$or"] = [{"kind": {"$in": ["channel", "announcement"]}}, {"members": current.id}]
    docs = await db.channels.find(q).sort("last_message_at", -1).to_list(200)
    for d in docs:
        await _channel_meta(db, d, current.id)
    return serialize_many(docs)


@router.post("/channels", status_code=201)
async def create_channel(payload: ChannelIn,
                         current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    if payload.kind == "announcement" and current.role not in ("Founder", "Admin"):
        raise HTTPException(403, "Only Founder or Admin can create announcement channels")
    doc = payload.model_dump()
    if current.id not in doc["members"]:
        doc["members"].append(current.id)
    doc["created_by"] = current.id
    doc["created_at"] = utc_iso()
    doc["last_message_at"] = utc_iso()
    res = await db.channels.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _channel_meta(db, doc, current.id)
    await log_activity(db, current, f"Created {doc['kind']}", "WavyGo Connect", target=doc["name"])
    return serialize(doc)


HIGH_ROLES = {"Founder", "Admin", "Manager"}
HIGH_DESIGNATION_KEYWORDS = {
    "founder", "ceo", "cto", "coo", "cfo", "chief", "director", "head",
    "president", "vp", "vice president", "manager", "lead", "general manager"
}


def is_high_designation_user(user_dict_or_obj) -> bool:
    role = getattr(user_dict_or_obj, "role", None) or (user_dict_or_obj.get("role") if isinstance(user_dict_or_obj, dict) else None)
    if role in HIGH_ROLES:
        return True
    designation = (
        getattr(user_dict_or_obj, "designation", None) or
        (user_dict_or_obj.get("designation") if isinstance(user_dict_or_obj, dict) else None) or ""
    ).lower()
    return any(k in designation for k in HIGH_DESIGNATION_KEYWORDS)


@router.get("/dm-users", response_model=list[UserPublic])
@router.get("/users", response_model=list[UserPublic])
async def list_dm_eligible_users(current: UserPublic = Depends(get_current_user)):
    """List users that the current user is eligible to DM.
    
    Respective department members can connect with members of their same department
    as well as company leadership / high designation personnel.
    Founders and Admins can connect with anyone across the company.
    """
    db = get_db()
    q = {
        "_id": {"$ne": oid(current.id)},
        "status": {"$ne": "deactivated"},
        "is_active": {"$ne": False},
    }
    docs = await db.users.find(q, {"password_hash": 0}).to_list(500)

    if current.role in ("Founder", "Admin"):
        eligible = docs
    else:
        curr_dept = (current.department or "").strip().lower()
        eligible = []
        for d in docs:
            dept = (d.get("department") or "").strip().lower()
            is_same_dept = bool(curr_dept) and bool(dept) and (dept == curr_dept)
            is_high_desig = is_high_designation_user(d)
            if is_same_dept or is_high_desig:
                eligible.append(d)

    return [
        UserPublic(
            id=str(d["_id"]),
            email=d["email"],
            name=d["name"],
            role=d["role"],
            photo=d.get("photo"),
            online=d.get("online", False),
            phone=d.get("phone"),
            designation=d.get("designation"),
            department=d.get("department"),
            status=d.get("status", "active"),
            is_active=d.get("is_active", True),
        )
        for d in eligible
    ]


@router.post("/dm/{peer_id}", status_code=201)
async def open_dm(peer_id: str, current: UserPublic = Depends(get_current_user)):
    """Get or create a 1-on-1 DM channel with permission enforcement."""
    db = get_db()
    if peer_id == current.id:
        raise HTTPException(400, "Cannot DM yourself")
    peer = await db.users.find_one(
        {"_id": oid(peer_id)},
        {"name": 1, "role": 1, "department": 1, "designation": 1, "status": 1}
    )
    if not peer:
        raise HTTPException(404, "User not found")

    # Respective department members connect with same department and high designation personnel
    if current.role not in ("Founder", "Admin"):
        curr_dept = (current.department or "").strip().lower()
        peer_dept = (peer.get("department") or "").strip().lower()
        is_same_dept = bool(curr_dept) and bool(peer_dept) and (curr_dept == peer_dept)
        is_high_desig = is_high_designation_user(peer)
        if not (is_same_dept or is_high_desig):
            raise HTTPException(403, "You can only message members of your department or company leadership.")

    existing = await db.channels.find_one({
        "kind": "dm",
        "members": {"$all": [current.id, peer_id], "$size": 2},
    })
    if existing:
        await _channel_meta(db, existing, current.id)
        return serialize(existing)
    doc = {
        "name": peer["name"],
        "kind": "dm",
        "description": None,
        "members": [current.id, peer_id],
        "created_by": current.id,
        "created_at": utc_iso(),
        "last_message_at": utc_iso(),
    }
    res = await db.channels.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _channel_meta(db, doc, current.id)
    return serialize(doc)


@router.get("/channels/{channel_id}/messages")
async def list_messages(channel_id: str, limit: int = Query(100, ge=1, le=500),
                        current: UserPublic = Depends(get_current_user)):
    db = get_db()
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if ch["kind"] in ("dm", "group") and current.id not in ch.get("members", []):
        raise HTTPException(403, "Not a member")
    docs = await db.messages.find({"channel_id": channel_id}).sort("created_at", -1).to_list(limit)
    docs.reverse()
    return serialize_many(docs)


@router.post("/channels/{channel_id}/messages", status_code=201)
async def send_message(channel_id: str, payload: MessageIn, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if ch["kind"] == "announcement" and current.role not in ("Founder", "Admin"):
        raise HTTPException(403, "Only Founder or Admin can post in announcement channels")
    if ch["kind"] in ("dm", "group") and current.id not in ch.get("members", []):
        raise HTTPException(403, "Not a member")
    doc = {
        "channel_id": channel_id,
        "channel_name": ch["name"],
        "sender_id": current.id,
        "sender_name": current.name,
        "sender_role": current.role,
        "sender_photo": current.photo,
        "body": payload.body,
        "attachments": payload.attachments,
        "created_at": utc_iso(),
    }
    res = await db.messages.insert_one(doc)
    doc["_id"] = res.inserted_id
    await db.channels.update_one({"_id": oid(channel_id)}, {"$set": {"last_message_at": doc["created_at"], "last_body": payload.body[:120]}})
    if ch["kind"] == "announcement":
        await notify(db, None, f"Announcement · {ch['name']}", payload.body[:180], kind="info", link="/wavygo-connect")
    return serialize(doc)


@router.post("/channels/{channel_id}/join")
async def join_channel(channel_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if current.id not in ch.get("members", []):
        await db.channels.update_one({"_id": oid(channel_id)}, {"$push": {"members": current.id}})
    return {"ok": True}
