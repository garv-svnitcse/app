from __future__ import annotations
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import ChannelIn, MessageIn
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify
from fastapi import File, UploadFile
import core.cloudinary_config  # loads Cloudinary settings
from services.image_service import upload_file, delete_file

router = APIRouter(prefix="/connect", tags=["connect"])

# Legacy kinds anyone can see and join. Channels created from now on carry `members_only: True`
# and behave like private groups (WhatsApp-style): only members list, read and post.
# Announcements stay company-wide broadcasts; groups and DMs have always been members-only.
PUBLIC_KINDS = ("channel", "announcement")
# Kinds whose membership is picked by the creator and managed by the channel's admins.
MEMBER_KINDS = ("channel", "group")
MANAGER_ROLES = ("Founder", "Admin")
# Senders can edit or delete their own message only this long after sending (Founder/Admin
# moderation deletes have no limit). 0 disables the limit.
MESSAGE_EDIT_WINDOW = timedelta(minutes=float(os.environ.get("MESSAGE_EDIT_WINDOW_MINUTES", "15")))
ACTIVE_USER = {"status": {"$ne": "deactivated"}, "is_active": {"$ne": False}}
KIND_NAME = {"channel": "channel", "group": "group", "announcement": "announcement channel"}


def _dedupe_names(names: list[str]) -> list[str]:
    seen, out = set(), []
    for n in names:
        n = (n or "").strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


class MembersIn(BaseModel):
    """Individual employees and/or whole departments (snapshot of their current active members)."""
    member_ids: List[str] = Field(default_factory=list)
    departments: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _not_empty(self):
        self.departments = _dedupe_names(self.departments)
        if not self.member_ids and not self.departments:
            raise ValueError("Pick at least one member or department")
        return self


class ConvertIn(BaseModel):
    """Optional departments whose current active members join when a legacy channel goes members-only."""
    departments: List[str] = Field(default_factory=list)


class ChannelCreate(ChannelIn):
    """Channel names must be non-blank; surrounding whitespace is trimmed."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    departments: List[str] = Field(default_factory=list)


class MessageCreate(MessageIn):
    """Blank (whitespace-only) messages are rejected."""
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)


def _is_public(ch: dict) -> bool:
    """Visible to / joinable by everyone: announcements and legacy channels without a member list."""
    return ch.get("kind") in PUBLIC_KINDS and not ch.get("members_only")


def _can_view(ch: dict, user_id: str) -> bool:
    return _is_public(ch) or user_id in ch.get("members", [])


def _channel_admins(ch: dict) -> list[str]:
    """Admins of a members-only channel/group. Legacy docs without `admins` fall back to the creator."""
    admins = ch.get("admins")
    if admins is None:
        admins = [ch["created_by"]] if ch.get("created_by") and ch["created_by"] != "system" else []
    return admins


def _can_manage(ch: dict, current: UserPublic) -> bool:
    """Who may add/remove members. Department groups follow the org chart, so only Founder/Admin."""
    if ch.get("kind") not in MEMBER_KINDS or _is_public(ch):
        return False
    if current.role in MANAGER_ROLES:
        return True
    if ch.get("department"):
        return False
    return current.id in _channel_admins(ch)


async def _get_channel(db, channel_id: str) -> dict:
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    return ch


async def _visible_channel(db, channel_id: str, current: UserPublic) -> dict:
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if not _can_view(ch, current.id):
        raise HTTPException(403, "Not a member")
    return ch


async def _validate_member_ids(db, ids: list[str]) -> list[str]:
    """Dedupe and ensure every id is an existing, active user (422 otherwise)."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    if not all(ObjectId.is_valid(i) for i in ids):
        raise HTTPException(422, "Invalid member id")
    found = await db.users.count_documents({"_id": {"$in": [ObjectId(i) for i in ids]}, **ACTIVE_USER})
    if found != len(ids):
        raise HTTPException(422, "One or more members do not exist")
    return ids


async def _department_member_ids(db, departments: list[str]) -> list[str]:
    """Active users currently in each named department (case-insensitive). 422 for an empty/unknown one."""
    out: list[str] = []
    for name in _dedupe_names(departments):
        rx = {"$regex": f"^\\s*{re.escape(name)}\\s*$", "$options": "i"}
        docs = await db.users.find({"department": rx, **ACTIVE_USER}, {"_id": 1}).to_list(1000)
        if not docs:
            raise HTTPException(422, f"Department '{name}' has no active members")
        out.extend(str(d["_id"]) for d in docs)
    return list(dict.fromkeys(out))


async def _resolve_members(db, member_ids: list[str], departments: list[str]) -> list[str]:
    ids = await _validate_member_ids(db, member_ids)
    return list(dict.fromkeys([*ids, *await _department_member_ids(db, departments)]))


async def _unread_counts(db, channels: list[dict], current_id: str) -> dict[str, int]:
    """Messages from others newer than the user's read cursor, per channel id (single aggregate).
    Without a cursor every message from others counts as unread."""
    if not channels:
        return {}
    ids = [str(c["_id"]) for c in channels]
    cursors = {r["channel_id"]: r["last_read_at"]
               for r in await db.channel_reads.find({"user_id": current_id, "channel_id": {"$in": ids}}).to_list(len(ids))}
    conds = [{"channel_id": cid, "created_at": {"$gt": cursors[cid]}} if cid in cursors else {"channel_id": cid}
             for cid in ids]
    pipe = [
        {"$match": {"sender_id": {"$ne": current_id}, "$or": conds}},
        {"$group": {"_id": "$channel_id", "n": {"$sum": 1}}},
    ]
    return {r["_id"]: r["n"] for r in await db.messages.aggregate(pipe).to_list(len(ids))}


async def _channel_meta(db, doc, current: UserPublic, unread: int | None = None):
    current_id = current.id
    if unread is None:
        unread = (await _unread_counts(db, [doc], current_id)).get(str(doc["_id"]), 0)
    doc["last_message_at"] = doc.get("last_message_at")
    doc["unread"] = unread
    doc["members_only"] = not _is_public(doc)
    doc["member_count"] = len(doc.get("members", []))
    if not _can_view(doc, current_id):
        # Founder/Admin managing a channel they're not in: membership metadata only, no message preview.
        doc.pop("last_body", None)
    if doc.get("kind") in MEMBER_KINDS:
        doc["admins"] = _channel_admins(doc)
        doc["can_manage"] = _can_manage(doc, current)
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
    # visible: public (legacy / announcement) channels + those the user belongs to
    q["$or"] = [{"kind": {"$in": list(PUBLIC_KINDS)}, "members_only": {"$ne": True}}, {"members": current.id}]
    docs = await db.channels.find(q).sort("last_message_at", -1).to_list(200)
    unread = await _unread_counts(db, docs, current.id)
    for d in docs:
        await _channel_meta(db, d, current, unread.get(str(d["_id"]), 0))
    return serialize_many(docs)


@router.get("/departments")
async def list_departments(current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    """Departments with their active headcount, for picking whole departments as channel members."""
    db = get_db()
    pipe = [
        {"$match": {"department": {"$type": "string", "$ne": ""}, **ACTIVE_USER}},
        {"$group": {"_id": {"$toLower": {"$trim": {"input": "$department"}}},
                    "name": {"$first": {"$trim": {"input": "$department"}}}, "member_count": {"$sum": 1}}},
        {"$sort": {"name": 1}},
    ]
    return [{"name": r["name"], "member_count": r["member_count"]}
            for r in await db.users.aggregate(pipe).to_list(500) if r["name"]]


@router.post("/channels", status_code=201)
async def create_channel(payload: ChannelCreate,
                         current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    if payload.kind == "announcement" and current.role not in ("Founder", "Admin"):
        raise HTTPException(403, "Only Founder or Admin can create announcement channels")
    if payload.kind == "dm":
        raise HTTPException(400, "Use /connect/dm/{peer_id} to start a direct message")
    doc = payload.model_dump(exclude={"departments"})
    doc["description"] = doc.get("description") or None
    resolved = await _resolve_members(db, doc["members"], payload.departments)
    added = [m for m in resolved if m != current.id]
    doc["members"] = [current.id, *added]
    doc["created_by"] = current.id
    if doc["kind"] in MEMBER_KINDS:
        doc["members_only"] = True
        doc["admins"] = [current.id]
    doc["created_at"] = utc_iso()
    doc["last_message_at"] = utc_iso()
    res = await db.channels.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _channel_meta(db, doc, current)
    await log_activity(db, current, f"Created {doc['kind']}", "WavyGo Connect", target=doc["name"],
                       meta={"members": len(doc["members"]), "departments": _dedupe_names(payload.departments)})
    if doc.get("members_only"):
        label = KIND_NAME.get(doc["kind"], "group")
        for uid in added:
            await notify(db, uid, f"Added to {label}", f"{current.name} added you to {doc['name']}.",
                         kind="info", link="/wavygo-connect")
    return serialize(doc)


@router.get("/channels/{channel_id}/members")
async def list_members(channel_id: str, current: UserPublic = Depends(get_current_user)):
    """Member profiles of a channel the caller can see or manage, admins first."""
    db = get_db()
    ch = await _get_channel(db, channel_id)
    # Founder/Admin may see who is in a channel to manage it without being a member themselves.
    # This never grants access to its messages.
    if not (_can_view(ch, current.id) or _can_manage(ch, current)):
        raise HTTPException(403, "Not a member")
    ids = [m for m in ch.get("members", []) if ObjectId.is_valid(m)]
    admins = set(_channel_admins(ch)) if ch.get("kind") in MEMBER_KINDS else set()
    proj = {"name": 1, "email": 1, "role": 1, "photo": 1, "online": 1, "designation": 1, "department": 1,
            "status": 1, "is_active": 1}
    docs = await db.users.find({"_id": {"$in": [ObjectId(i) for i in ids]}}, proj).to_list(len(ids) or 1)
    out = []
    for d in docs:
        uid = str(d["_id"])
        out.append({
            "id": uid, "name": d.get("name"), "email": d.get("email"), "role": d.get("role"),
            "photo": d.get("photo"), "online": d.get("online", False), "designation": d.get("designation"),
            "department": d.get("department"), "is_admin": uid in admins,
            "is_creator": uid == ch.get("created_by"),
            "active": d.get("status") != "deactivated" and d.get("is_active") is not False,
        })
    out.sort(key=lambda m: (not m["is_admin"], (m["name"] or "").lower()))
    return out


@router.post("/channels/{channel_id}/members")
async def add_members(channel_id: str, payload: MembersIn, current: UserPublic = Depends(get_current_user)):
    """Add employees and/or whole departments to a members-only channel or group.
    Allowed for the channel's admins (creator), Founder and Admin."""
    db = get_db()
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if ch["kind"] not in MEMBER_KINDS or _is_public(ch):
        raise HTTPException(400, "Members can only be added to private channels and groups")
    if not _can_manage(ch, current):
        raise HTTPException(403, "Only the channel's admins, Founder or Admin can add members")
    existing = set(ch.get("members", []))
    resolved = await _resolve_members(db, payload.member_ids, payload.departments)
    added = [m for m in resolved if m not in existing]
    if added:
        await db.channels.update_one({"_id": ch["_id"]}, {"$addToSet": {"members": {"$each": added}}})
        await log_activity(db, current, "Added group members", "WavyGo Connect", target=ch["name"],
                           meta={"added": added, "departments": payload.departments})
        label = KIND_NAME.get(ch["kind"], "group")
        for uid in added:
            await notify(db, uid, f"Added to {label}", f"{current.name} added you to {ch['name']}.",
                         kind="info", link="/wavygo-connect")
    doc = await db.channels.find_one({"_id": ch["_id"]})
    await _channel_meta(db, doc, current)
    return serialize(doc)


@router.delete("/channels/{channel_id}/members/{user_id}")
async def remove_member(channel_id: str, user_id: str, current: UserPublic = Depends(get_current_user)):
    """Remove a member (channel admins / Founder / Admin), or leave (any member removing themselves).
    Channel admins cannot remove the creator; only Founder/Admin can. Department-group membership
    follows the employee's department, so members cannot leave those themselves."""
    db = get_db()
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if ch["kind"] not in MEMBER_KINDS or _is_public(ch):
        raise HTTPException(400, "Members can only be removed from private channels and groups")
    members = ch.get("members", [])
    leaving = user_id == current.id
    if leaving:
        if current.id not in members:
            raise HTTPException(403, "Not a member")
        if ch.get("department") and current.role not in MANAGER_ROLES:
            raise HTTPException(400, "Department group membership follows your department")
    else:
        if not _can_manage(ch, current):
            raise HTTPException(403, "Only the channel's admins, Founder or Admin can remove members")
        if user_id == ch.get("created_by") and current.role not in MANAGER_ROLES:
            raise HTTPException(403, "The channel creator can only be removed by Founder or Admin")
        if user_id not in members:
            raise HTTPException(404, "Not a member of this channel")
    remaining = [m for m in members if m != user_id]
    admins = [a for a in _channel_admins(ch) if a != user_id]
    if not admins and remaining and not ch.get("department"):
        admins = [remaining[0]]  # never leave a group without an admin
    await db.channels.update_one({"_id": ch["_id"]}, {"$set": {"members": remaining, "admins": admins}})
    await log_activity(db, current, "Left group" if leaving else "Removed group member", "WavyGo Connect",
                       target=ch["name"], meta={"user_id": user_id})
    if not leaving:
        await notify(db, user_id, f"Removed from {KIND_NAME.get(ch['kind'], 'group')}",
                     f"{current.name} removed you from {ch['name']}.", kind="info", link="/wavygo-connect")
    doc = await db.channels.find_one({"_id": ch["_id"]})
    await _channel_meta(db, doc, current)
    return serialize(doc)


async def _member_channel(db, channel_id: str) -> dict:
    ch = await _get_channel(db, channel_id)
    if ch["kind"] not in MEMBER_KINDS or _is_public(ch):
        raise HTTPException(400, "Admins can only be managed in private channels and groups")
    return ch


@router.post("/channels/{channel_id}/admins/{user_id}")
async def promote_admin(channel_id: str, user_id: str, current: UserPublic = Depends(get_current_user)):
    """Make a member a channel admin (channel admins, Founder, Admin)."""
    db = get_db()
    ch = await _member_channel(db, channel_id)
    if not _can_manage(ch, current):
        raise HTTPException(403, "Only the channel's admins, Founder or Admin can change admins")
    if user_id not in ch.get("members", []):
        raise HTTPException(404, "Not a member of this channel")
    admins = _channel_admins(ch)
    if user_id not in admins:
        await db.channels.update_one({"_id": ch["_id"]}, {"$set": {"admins": [*admins, user_id]}})
        await log_activity(db, current, "Promoted channel admin", "WavyGo Connect", target=ch["name"],
                           meta={"user_id": user_id})
        if user_id != current.id:
            await notify(db, user_id, "You're now an admin", f"{current.name} made you an admin of {ch['name']}.",
                         kind="info", link="/wavygo-connect")
    doc = await db.channels.find_one({"_id": ch["_id"]})
    await _channel_meta(db, doc, current)
    return serialize(doc)


@router.delete("/channels/{channel_id}/admins/{user_id}")
async def demote_admin(channel_id: str, user_id: str, current: UserPublic = Depends(get_current_user)):
    """Remove a member's admin rights (channel admins, Founder, Admin). The creator can only be demoted by
    Founder/Admin, and a channel is never left without an admin (department groups excepted: they are
    managed by Founder/Admin and have no admins by default)."""
    db = get_db()
    ch = await _member_channel(db, channel_id)
    if not _can_manage(ch, current):
        raise HTTPException(403, "Only the channel's admins, Founder or Admin can change admins")
    admins = _channel_admins(ch)
    if user_id not in admins:
        raise HTTPException(404, "Not an admin of this channel")
    if user_id == ch.get("created_by") and current.role not in MANAGER_ROLES:
        raise HTTPException(403, "The channel creator can only be demoted by Founder or Admin")
    remaining = [a for a in admins if a != user_id]
    if not remaining and not ch.get("department"):
        raise HTTPException(400, "A channel needs at least one admin. Promote someone else first")
    await db.channels.update_one({"_id": ch["_id"]}, {"$set": {"admins": remaining}})
    await log_activity(db, current, "Demoted channel admin", "WavyGo Connect", target=ch["name"],
                       meta={"user_id": user_id})
    doc = await db.channels.find_one({"_id": ch["_id"]})
    await _channel_meta(db, doc, current)
    return serialize(doc)


@router.post("/channels/{channel_id}/members-only")
async def make_members_only(channel_id: str, payload: Optional[ConvertIn] = None,
                            current: UserPublic = Depends(require_roles(*MANAGER_ROLES))):
    """Convert a legacy public channel to members-only (Founder/Admin). Members become its current
    member list plus the creator, plus everyone currently in any named department. The creator is its
    admin (or the converting user, when there is no usable creator)."""
    db = get_db()
    departments = payload.departments if payload else []
    ch = await _get_channel(db, channel_id)
    if ch.get("kind") != "channel" or not _is_public(ch):
        raise HTTPException(400, "Only public (legacy) channels can be made members-only")
    existing = [m for m in ch.get("members", []) if m]
    creator = ch.get("created_by")
    creator = creator if creator and ObjectId.is_valid(creator) else None
    dept_ids = await _department_member_ids(db, departments)
    members = list(dict.fromkeys([*([creator] if creator else []), *existing, *dept_ids]))
    admins = [creator] if creator else [current.id]
    if current.id in admins and current.id not in members:
        members.append(current.id)
    await db.channels.update_one({"_id": ch["_id"]}, {"$set": {"members_only": True, "members": members,
                                                                 "admins": admins}})
    await log_activity(db, current, "Made channel members-only", "WavyGo Connect", target=ch["name"],
                       meta={"members": len(members), "departments": _dedupe_names(departments)})
    for uid in [m for m in dept_ids if m not in existing and m != current.id]:
        await notify(db, uid, "Added to channel", f"{current.name} added you to {ch['name']}.",
                     kind="info", link="/wavygo-connect")
    doc = await db.channels.find_one({"_id": ch["_id"]})
    await _channel_meta(db, doc, current)
    return serialize(doc)


@router.get("/manage/channels")
async def manage_channels(current: UserPublic = Depends(require_roles(*MANAGER_ROLES))):
    """Every channel, group and announcement channel (not DMs), for Founder/Admin membership management.
    Metadata only: no message previews, and reading messages stays members-only."""
    db = get_db()
    docs = await db.channels.find({"kind": {"$in": [*MEMBER_KINDS, "announcement"]}},
                                  {"last_body": 0}).sort("name", 1).to_list(1000)
    out = []
    for d in docs:
        public = _is_public(d)
        out.append({
            "id": str(d["_id"]), "name": d.get("name"), "kind": d.get("kind"),
            "description": d.get("description"), "department": d.get("department"),
            "members_only": not public, "member_count": len(d.get("members", [])),
            "admins": _channel_admins(d) if d.get("kind") in MEMBER_KINDS else [],
            "created_by": d.get("created_by"), "is_member": current.id in d.get("members", []),
            "can_manage": _can_manage(d, current),
            "can_convert": d.get("kind") == "channel" and public,
        })
    return out


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
        {"name": 1, "role": 1, "department": 1, "designation": 1, "status": 1, "is_active": 1}
    )
    if not peer or peer.get("status") == "deactivated" or peer.get("is_active") is False:
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
        await _channel_meta(db, existing, current)
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
    await _channel_meta(db, doc, current)
    return serialize(doc)

@router.post("/upload")
async def upload_chat_file(
    file: UploadFile = File(...),
    current: UserPublic = Depends(get_current_user),
):
    """Upload a chat file (image, pdf, doc...) to Cloudinary and remember who uploaded it."""
    db = get_db()
    uploaded = await upload_file(file)
    await db.uploads.insert_one({**uploaded, "owner_id": current.id, "created_at": utc_iso()})
    return uploaded

@router.delete("/messages/{message_id}")
async def delete_message(message_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    msg = await db.messages.find_one({"_id": oid(message_id)})
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg["sender_id"] != current.id and current.role not in ("Founder", "Admin"):
        raise HTTPException(403, "You can only delete your own messages")

    for a in msg.get("attachments", []):
        if isinstance(a, dict) and a.get("public_id"):
            await delete_file(a["public_id"], a.get("resource_type", "image"))
            await db.uploads.delete_one({"public_id": a["public_id"]})

    await db.messages.delete_one({"_id": msg["_id"]})
    return {"ok": True}

@router.get("/channels/{channel_id}/messages")
async def list_messages(channel_id: str, limit: int = Query(100, ge=1, le=500),
                        current: UserPublic = Depends(get_current_user)):
    db = get_db()
    await _visible_channel(db, channel_id, current)
    docs = await db.messages.find({"channel_id": channel_id}).sort("created_at", -1).to_list(limit)
    docs.reverse()
    return [_with_window(d) for d in docs]


@router.post("/channels/{channel_id}/messages", status_code=201)
async def send_message(
    channel_id: str,
    payload: MessageCreate,
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()

    ch = await _visible_channel(db, channel_id, current)

    if ch["kind"] == "announcement" and current.role not in ("Founder", "Admin"):
        raise HTTPException(
            403,
            "Only Founder or Admin can post in announcement channels"
        )

    # IMPORTANT:
    # Keep the attachment URLs sent by the frontend.
    attachments = payload.attachments or []

    doc = {
        "channel_id": channel_id,
        "channel_name": ch["name"],
        "sender_id": current.id,
        "sender_name": current.name,
        "sender_role": current.role,
        "sender_photo": current.photo,
        "body": payload.body,
        "attachments": attachments,
        "created_at": utc_iso(),
    }

    res = await db.messages.insert_one(doc)
    doc["_id"] = res.inserted_id

    await db.channels.update_one(
        {"_id": oid(channel_id)},
        {
            "$set": {
                "last_message_at": doc["created_at"],
                "last_body": payload.body[:120] or "📎 Attachment",
            }
        }
    )

    if ch["kind"] == "announcement":
        await notify(
            db,
            None,
            f"Announcement · {ch['name']}",
            payload.body[:180],
            kind="info",
            link="/wavygo-connect",
        )

    return _with_window(doc)

class MessageEdit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)


async def _own_message(db, channel_id: str, message_id: str, current: UserPublic) -> tuple[dict, dict]:
    """The channel (visible to the caller) and a live message in it, else 404."""
    ch = await _visible_channel(db, channel_id, current)
    if not ObjectId.is_valid(message_id):
        raise HTTPException(404, "Message not found")
    msg = await db.messages.find_one({"_id": ObjectId(message_id), "channel_id": channel_id})
    if not msg or msg.get("deleted"):
        raise HTTPException(404, "Message not found")
    return ch, msg


def _within_edit_window(msg: dict) -> bool:
    if not MESSAGE_EDIT_WINDOW:
        return True
    try:
        sent = datetime.fromisoformat(msg["created_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - sent <= MESSAGE_EDIT_WINDOW


def _window_label() -> str:
    minutes = MESSAGE_EDIT_WINDOW.total_seconds() / 60
    return f"{minutes:g} minute{'s' if minutes != 1 else ''}"


def _with_window(doc: dict) -> dict:
    """Serialize a message and add when its sender's edit/delete window closes (null = no limit)."""
    out = serialize(doc)
    if MESSAGE_EDIT_WINDOW and not doc.get("deleted"):
        try:
            sent = datetime.fromisoformat(doc["created_at"])
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=timezone.utc)
            out["editable_until"] = (sent + MESSAGE_EDIT_WINDOW).isoformat()
        except (KeyError, TypeError, ValueError):
            out["editable_until"] = None
    else:
        out["editable_until"] = None
    return out


async def _refresh_preview(db, channel_id: str, message: dict) -> None:
    """Keep the channel list preview in step when its latest message is edited or deleted."""
    latest = await db.messages.find_one({"channel_id": channel_id}, sort=[("created_at", -1)])
    if latest and latest["_id"] == message["_id"]:
        preview = "Message deleted" if message.get("deleted") else message["body"][:120]
        await db.channels.update_one({"_id": oid(channel_id)}, {"$set": {"last_body": preview}})


@router.patch("/channels/{channel_id}/messages/{message_id}")
async def edit_message(channel_id: str, message_id: str, payload: MessageEdit,
                       current: UserPublic = Depends(get_current_user)):
    """Only the sender can edit their message; it is marked as edited."""
    db = get_db()
    _, msg = await _own_message(db, channel_id, message_id, current)
    if msg.get("sender_id") != current.id:
        raise HTTPException(403, "You can only edit your own messages")
    if not _within_edit_window(msg):
        raise HTTPException(403, f"Messages can only be edited within {_window_label()} of sending")
    if payload.body == msg.get("body"):
        return _with_window(msg)
    now = utc_iso()
    await db.messages.update_one({"_id": msg["_id"]}, {"$set": {"body": payload.body, "edited_at": now, "updated_at": now}})
    msg.update(body=payload.body, edited_at=now, updated_at=now)
    await _refresh_preview(db, channel_id, msg)
    return _with_window(msg)


@router.delete("/channels/{channel_id}/messages/{message_id}")
async def delete_message(channel_id: str, message_id: str, current: UserPublic = Depends(get_current_user)):
    """The sender can delete their message; Founder/Admin can remove any message (moderation).
    The message stays in place as "This message was deleted" so the conversation still reads."""
    db = get_db()
    ch, msg = await _own_message(db, channel_id, message_id, current)
    own = msg.get("sender_id") == current.id
    moderator = current.role in MANAGER_ROLES
    if not own and not moderator:
        raise HTTPException(403, "You can only delete your own messages")
    if own and not moderator and not _within_edit_window(msg):
        raise HTTPException(403, f"Messages can only be deleted within {_window_label()} of sending")
    now = utc_iso()
    fields = {"deleted": True, "body": "", "attachments": [], "deleted_at": now, "deleted_by": current.id, "updated_at": now}
    await db.messages.update_one({"_id": msg["_id"]}, {"$set": fields})
    msg.update(fields)
    await _refresh_preview(db, channel_id, msg)
    if not own:
        await log_activity(db, current, "Deleted message", "WavyGo Connect",
                           target=f"{msg.get('sender_name')} in {ch['name']}")
    return _with_window(msg)

@router.post("/channels/{channel_id}/join")
async def join_channel(channel_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    ch = await db.channels.find_one({"_id": oid(channel_id)})
    if not ch:
        raise HTTPException(404, "Channel not found")
    if not _is_public(ch):
        raise HTTPException(403, "Private groups and direct messages cannot be joined")
    if current.id not in ch.get("members", []):
        await db.channels.update_one({"_id": oid(channel_id)}, {"$addToSet": {"members": current.id}})
        await log_activity(db, current, "Joined channel", "WavyGo Connect", target=ch["name"])
    return {"ok": True}


@router.post("/channels/{channel_id}/read")
async def mark_read(channel_id: str, current: UserPublic = Depends(get_current_user)):
    """Move the user's read cursor for this channel to now (clears its unread count)."""
    db = get_db()
    await _visible_channel(db, channel_id, current)
    now = utc_iso()
    await db.channel_reads.update_one({"channel_id": channel_id, "user_id": current.id},
                                      {"$set": {"last_read_at": now}}, upsert=True)
    return {"ok": True, "last_read_at": now}
