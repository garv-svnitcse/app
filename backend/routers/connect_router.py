from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import ChannelIn, MessageIn
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify
from dept_groups import ensure_department_groups, get_or_create_department_channel, is_department_group_member

router = APIRouter(prefix="/connect", tags=["connect"])

MEMBER_FIELDS = {
    "name": 1, "email": 1, "role": 1, "photo": 1, "online": 1,
    "phone": 1, "designation": 1, "department": 1, "status": 1,
    "is_active": 1,
}


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


async def _can_access_channel(db, channel: dict, current: UserPublic) -> bool:
    """Authorize the channel types while keeping department groups data-derived."""
    if channel.get("kind") != "group":
        return channel.get("kind") not in ("dm",) or current.id in channel.get("members", [])
    if channel.get("department_group"):
        # Department groups deliberately do not use the cached members array
        # for authorization.  A department transfer takes effect immediately.
        return is_department_group_member(channel, current.department)
    # Preserve access semantics for any pre-existing non-department groups.
    return current.id in channel.get("members", [])


@router.get("/channels")
async def list_channels(kind: str | None = None, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    await ensure_department_groups(db)
    # Fetch department groups so their access can be evaluated from the
    # current employee department instead of a copied membership list.
    q = {"$or": [{"kind": {"$in": ["channel", "announcement", "group"]}}, {"members": current.id}]}
    if kind:
        q["kind"] = kind
    docs = await db.channels.find(q).sort("last_message_at", -1).to_list(200)
    docs = [doc for doc in docs if await _can_access_channel(db, doc, current)]
    for d in docs:
        await _channel_meta(db, d, current.id)
    return serialize_many(docs)


@router.get("/department-group")
async def my_department_group(current: UserPublic = Depends(get_current_user)):
    """Return the caller's one department group and its live employee roster."""
    if not (current.department or "").strip():
        raise HTTPException(404, "No department group is available because your employee record has no department")
    db = get_db()
    await ensure_department_groups(db)
    channel = await get_or_create_department_channel(db, current.department)
    if not channel or not is_department_group_member(channel, current.department):
        raise HTTPException(404, "No department group is configured for your department")
    await _channel_meta(db, channel, current.id)
    members = await db.users.find(
        {"department": channel["department"], "status": {"$ne": "deactivated"}, "is_active": {"$ne": False}},
        MEMBER_FIELDS,
    ).sort("name", 1).to_list(500)
    return {"channel": serialize(channel), "members": serialize_many(members)}


@router.post("/channels", status_code=201)
async def create_channel(payload: ChannelIn,
                         current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    if payload.kind == "group":
        raise HTTPException(403, "Department groups are created automatically from the employee department list")
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
    if not await _can_access_channel(db, ch, current):
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
    if not await _can_access_channel(db, ch, current):
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


@router.get("/channels/{channel_id}/members")
async def list_channel_members(channel_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    channel = await db.channels.find_one({"_id": oid(channel_id)})
    if not channel:
        raise HTTPException(404, "Channel not found")
    if not await _can_access_channel(db, channel, current):
        raise HTTPException(403, "Not a member")
    if channel.get("kind") == "group" and channel.get("department_group"):
        users = await db.users.find(
            {"department": channel["department"], "status": {"$ne": "deactivated"}, "is_active": {"$ne": False}},
            MEMBER_FIELDS,
        ).sort("name", 1).to_list(500)
        return serialize_many(users)
    users = []
    for user_id in channel.get("members", []):
        try:
            user = await db.users.find_one({"_id": ObjectId(user_id)}, MEMBER_FIELDS)
        except Exception:
            user = None
        if user:
            users.append(user)
    return serialize_many(users)


@router.post("/channels/{channel_id}/join")
async def join_channel(channel_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if ch.get("kind") == "group" and ch.get("department_group"):
        raise HTTPException(403, "Department group membership is managed by your employee department")
    if current.id not in ch.get("members", []):
        await db.channels.update_one({"_id": oid(channel_id)}, {"$push": {"members": current.id}})
    return {"ok": True}
