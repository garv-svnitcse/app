from __future__ import annotations
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from bson import ObjectId

from db import get_db, utc_now
from models import LoginRequest, RegisterRequest, TokenResponse, RefreshRequest, UserPublic
from auth_utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, require_roles,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_public(doc) -> UserPublic:
    return UserPublic(
        id=str(doc["_id"]),
        email=doc["email"],
        name=doc["name"],
        role=doc["role"],
        photo=doc.get("photo"),
        online=doc.get("online", False),
        phone=doc.get("phone"),
        designation=doc.get("designation"),
        department=doc.get("department"),
        status=doc.get("status", "active"),
        is_active=doc.get("is_active", True),
    )


async def _log_activity(db, user, action: str, module: str = "Auth", target: str | None = None):
    await db.activity_logs.insert_one({
        "user_id": user["id"] if isinstance(user, dict) else user.id,
        "user_name": user["name"] if isinstance(user, dict) else user.name,
        "user_role": user["role"] if isinstance(user, dict) else user.role,
        "action": action,
        "module": module,
        "target": target,
        "created_at": utc_now().isoformat(),
    })


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request):
    db = get_db()
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.get("status") == "deactivated" or user.get("is_active") is False or user.get("active") is False:
        raise HTTPException(status_code=403, detail="Your account has been deactivated. Please contact your Founder or Admin to reactivate your access.")

    await db.users.update_one({"_id": user["_id"]}, {"$set": {"online": True, "last_login_at": utc_now().isoformat()}})

    uid = str(user["_id"])
    access = create_access_token(uid, user["email"], user["role"])
    refresh, jti = create_refresh_token(uid)

    await db.sessions.insert_one({
        "user_id": uid,
        "refresh_token_id": jti,
        "user_agent": request.headers.get("user-agent"),
        "ip": request.client.host if request.client else None,
        "created_at": utc_now().isoformat(),
        "last_used_at": utc_now().isoformat(),
        "revoked": False,
    })

    public = _to_public({**user, "online": True})
    await _log_activity(db, public, "Signed in")

    return TokenResponse(access_token=access, refresh_token=refresh, user=public)


@router.post("/register", response_model=TokenResponse)
async def register(payload: RegisterRequest, request: Request,
                   current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    if payload.role == "Founder":
        raise HTTPException(status_code=403, detail="Cannot create another Founder")
    if payload.role == "Admin" and current.role != "Founder":
        raise HTTPException(status_code=403, detail="Only the Founder can create an Admin")
    db = get_db()
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Email already registered")
    doc = {
        "email": email,
        "name": payload.name.strip(),
        "role": payload.role,
        "password_hash": hash_password(payload.password),
        "online": True,
        "created_at": utc_now().isoformat(),
        "updated_at": utc_now().isoformat(),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    uid = str(res.inserted_id)
    access = create_access_token(uid, email, payload.role)
    refresh, _ = create_refresh_token(uid)
    public = _to_public(doc)
    await _log_activity(db, public, "Account created")
    return TokenResponse(access_token=access, refresh_token=refresh, user=public)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    db = get_db()
    try:
        data = decode_token(payload.refresh_token)
        if data.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    uid = data["sub"]
    user = await db.users.find_one({"_id": ObjectId(uid)})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access = create_access_token(uid, user["email"], user["role"])
    new_refresh, _ = create_refresh_token(uid)
    return TokenResponse(access_token=access, refresh_token=new_refresh, user=_to_public(user))


@router.post("/logout")
async def logout(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    await db.users.update_one({"_id": ObjectId(current.id)}, {"$set": {"online": False}})
    await _log_activity(db, current, "Signed out")
    return {"ok": True}


@router.get("/me", response_model=UserPublic)
async def me(current: UserPublic = Depends(get_current_user)):
    return current
