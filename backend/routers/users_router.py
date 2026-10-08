from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from bson import ObjectId
from db import get_db, utc_now
from hub_utils import log_activity
from models import UserPublic, UpdateProfileRequest, ChangePasswordRequest
from auth_utils import get_current_user, verify_password, hash_password, require_roles, session_id_from_request

router = APIRouter(prefix="/users", tags=["users"])
PHONE_MAX = 40  # same limit as the Employees profile


@router.get("", response_model=list[UserPublic])
async def list_users(_: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    docs = await db.users.find({}, {"password_hash": 0}).to_list(500)
    return [
        UserPublic(
            id=str(d["_id"]), email=d["email"], name=d["name"], role=d["role"],
            photo=d.get("photo"), online=d.get("online", False), phone=d.get("phone"),
            designation=d.get("designation"), department=d.get("department"),
        )
        for d in docs
    ]


@router.get("/directory")
async def directory(_: UserPublic = Depends(get_current_user)):
    """Minimal active-user directory for pickers; any signed-in user. No contact details."""
    db = get_db()
    q = {"status": {"$ne": "deactivated"}, "is_active": {"$ne": False}, "active": {"$ne": False}}
    proj = {"name": 1, "role": 1, "department": 1, "designation": 1, "photo": 1}
    docs = await db.users.find(q, proj).sort("name", 1).to_list(2000)
    return [
        {
            "id": str(d["_id"]), "name": d.get("name"), "role": d.get("role"),
            "department": d.get("department"), "designation": d.get("designation"), "photo": d.get("photo"),
        }
        for d in docs
    ]


@router.patch("/me", response_model=UserPublic)
async def update_me(payload: UpdateProfileRequest, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    allowed_fields = {"phone", "photo"}
    raw_updates = payload.model_dump(exclude_none=True)
    updates = {k: v for k, v in raw_updates.items() if k in allowed_fields}
    # Same rules as the Employees profile editor: trimmed, and an empty value clears the field.
    for key, value in list(updates.items()):
        value = value.strip() if isinstance(value, str) else value
        updates[key] = value or None
    if updates.get("phone") and len(updates["phone"]) > PHONE_MAX:
        raise HTTPException(status_code=422, detail=f"Phone number must be at most {PHONE_MAX} characters")
    if not updates:
        doc = await db.users.find_one({"_id": ObjectId(current.id)})
        return UserPublic(
            id=str(doc["_id"]), email=doc["email"], name=doc["name"], role=doc["role"],
            photo=doc.get("photo"), online=doc.get("online", False), phone=doc.get("phone"),
            designation=doc.get("designation"), department=doc.get("department"),
        )
    updates["updated_at"] = utc_now().isoformat()
    await db.users.update_one({"_id": ObjectId(current.id)}, {"$set": updates})
    doc = await db.users.find_one({"_id": ObjectId(current.id)})
    return UserPublic(
        id=str(doc["_id"]), email=doc["email"], name=doc["name"], role=doc["role"],
        photo=doc.get("photo"), online=doc.get("online", False), phone=doc.get("phone"),
        designation=doc.get("designation"), department=doc.get("department"),
    )


@router.post("/me/password")
async def change_password(payload: ChangePasswordRequest, request: Request, current: UserPublic = Depends(get_current_user)):
    if current.role not in ("Founder", "Admin", "Manager"):
        raise HTTPException(status_code=403, detail="Password change is not available for your role")
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(current.id)})
    if not verify_password(payload.current_password, doc.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if len(payload.new_password.encode("utf-8")) > 72:
        # bcrypt only uses the first 72 bytes; reject instead of silently truncating (same rule as reset)
        raise HTTPException(status_code=400, detail="New password is too long (maximum 72 bytes)")
    await db.users.update_one(
        {"_id": ObjectId(current.id)},
        {"$set": {"password_hash": hash_password(payload.new_password), "updated_at": utc_now().isoformat()}}
    )
    # Sign out every other session: their refresh tokens stop working
    revoke_q = {"user_id": current.id, "revoked": {"$ne": True}}
    sid = session_id_from_request(request)
    if sid and ObjectId.is_valid(sid):
        revoke_q["_id"] = {"$ne": ObjectId(sid)}
    res = await db.sessions.update_many(revoke_q, {"$set": {"revoked": True, "revoked_at": utc_now().isoformat()}})
    await log_activity(db, current, "Changed password", "Settings", target="Security",
                       meta={"sessions_revoked": res.modified_count})
    return {"ok": True}
