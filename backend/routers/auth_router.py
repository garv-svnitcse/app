from __future__ import annotations
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from bson import ObjectId

from db import get_db, utc_now
from hub_utils import log_activity, notify
from email_utils import send_password_reset_link_email
from models import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    RefreshRequest,
    UserPublic,
)
from auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    require_roles,
    is_deactivated,
    session_id_from_request,
    DEACTIVATED_DETAIL,
    REFRESH_DAYS,
    REFRESH_DAYS_SHORT,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

COMPANY_TZ = ZoneInfo("Asia/Kolkata")


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


def _local_today() -> str:
    """Attendance dates are the company-local (IST) calendar date."""
    return datetime.now(COMPANY_TZ).date().isoformat()


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


async def _log_activity(
    db,
    user,
    action: str,
    module: str = "Auth",
    target: str | None = None,
):
    await log_activity(db, user, action, module, target)


# ============================================================
# LOGIN
# ============================================================

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request):
    db = get_db()

    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Deactivated accounts get no tokens, no attendance and are not marked online
    if is_deactivated(user):
        raise HTTPException(status_code=403, detail=DEACTIVATED_DETAIL)

    now = utc_now()
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"online": True, "last_login_at": now.isoformat()}})

    uid = str(user["_id"])

    # "Remember me" keeps the session for 30 days, otherwise for 1 day
    refresh_days = REFRESH_DAYS if payload.remember else REFRESH_DAYS_SHORT
    refresh, jti = create_refresh_token(uid, days=refresh_days)

    # --------------------------------------------------------
    # 4. Create login session
    # --------------------------------------------------------

    session_doc = {
        "user_id": uid,
        "refresh_token_id": jti,
        "remember": payload.remember,
        "user_agent": request.headers.get("user-agent"),
        "ip": request.client.host if request.client else None,
        "created_at": now.isoformat(),
        "last_used_at": now.isoformat(),
        "expires_at": (now + timedelta(days=refresh_days)).isoformat(),
        "revoked": False,
    }

    session_result = await db.sessions.insert_one(session_doc)

    session_id = str(session_result.inserted_id)

    access = create_access_token(
        uid,
        user["email"],
        user["role"],
        sid=session_id,
    )

    # --------------------------------------------------------
    # 5. AUTOMATIC ATTENDANCE CHECK-IN
    # --------------------------------------------------------

    today = _local_today()

    existing_attendance = await db.attendance.find_one({
        "employee_id": uid,
        "date": today,
    })

    # Create only one attendance record per employee per day;
    # repeated logins never overwrite the first check_in.
    if not existing_attendance:

        await db.attendance.insert_one({
            "employee_id": uid,
            "employee_name": user["name"],
            "date": today,
            "status": "present",
            "check_in": now.isoformat(),
            "check_out": None,
            "session_id": session_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })

    # --------------------------------------------------------
    # 6. Prepare public user
    # --------------------------------------------------------

    public = _to_public({
        **user,
        "online": True,
    })

    # --------------------------------------------------------
    # 7. Log activity
    # --------------------------------------------------------

    await _log_activity(
        db,
        public,
        "Signed in",
    )

    # --------------------------------------------------------
    # 8. Return login response
    # --------------------------------------------------------

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=public,
    )


# ============================================================
# REGISTER
# ============================================================
# Founder/Admin creates an account for someone else: no tokens,
# session, online flag or attendance are created for the new user.

@router.post("/register", response_model=UserPublic)
async def register(
    payload: RegisterRequest,
    current: UserPublic = Depends(
        require_roles("Founder", "Admin")
    ),
):
    if payload.role == "Founder":
        raise HTTPException(
            status_code=403,
            detail="Cannot create another Founder",
        )

    if payload.role == "Admin" and current.role != "Founder":
        raise HTTPException(
            status_code=403,
            detail="Only the Founder can create an Admin",
        )

    db = get_db()

    email = payload.email.lower().strip()

    # Check duplicate email
    if await db.users.find_one({"email": email}):
        raise HTTPException(
            status_code=409,
            detail="Email already registered",
        )

    now = utc_now()

    # --------------------------------------------------------
    # Create user
    # --------------------------------------------------------

    doc = {
        "email": email,
        "name": payload.name.strip(),
        "role": payload.role,
        "password_hash": hash_password(payload.password),
        "online": False,
        "status": "active",
        "is_active": True,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    res = await db.users.insert_one(doc)

    doc["_id"] = res.inserted_id

    public = _to_public(doc)

    await _log_activity(
        db,
        current,
        "Account created",
        target=f"{public.name} ({public.role})",
    )

    return public


# ============================================================
# REFRESH TOKEN
# ============================================================

@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    db = get_db()

    try:
        data = decode_token(payload.refresh_token)

        if data.get("type") != "refresh":
            raise HTTPException(
                status_code=401,
                detail="Invalid refresh token",
            )

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token",
        )

    uid = data.get("sub")
    jti = data.get("jti")

    if not uid or not jti or not ObjectId.is_valid(uid):
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token",
        )

    user = await db.users.find_one({
        "_id": ObjectId(uid)
    })

    if not user:
        raise HTTPException(
            status_code=401,
            detail="User not found",
        )

    if is_deactivated(user):
        raise HTTPException(status_code=403, detail=DEACTIVATED_DETAIL)

    # --------------------------------------------------------
    # Rotate: the presented refresh token id must belong to a
    # live session; it is swapped for a new one so the old
    # refresh token can never be used again.
    # --------------------------------------------------------

    session = await db.sessions.find_one({
        "refresh_token_id": jti,
        "user_id": uid,
        "revoked": {"$ne": True},
    })

    if not session:
        raise HTTPException(
            status_code=401,
            detail="Session expired or revoked",
        )

    refresh_days = REFRESH_DAYS if session.get("remember", True) else REFRESH_DAYS_SHORT
    new_refresh, new_jti = create_refresh_token(uid, days=refresh_days)
    now = utc_now()

    rotated = await db.sessions.update_one(
        {"_id": session["_id"], "refresh_token_id": jti, "revoked": {"$ne": True}},
        {"$set": {
            "refresh_token_id": new_jti,
            "last_used_at": now.isoformat(),
            "expires_at": (now + timedelta(days=refresh_days)).isoformat(),
        }},
    )

    # Lost a race with a concurrent refresh / logout of the same token
    if rotated.modified_count != 1:
        raise HTTPException(
            status_code=401,
            detail="Session expired or revoked",
        )

    access = create_access_token(
        uid,
        user["email"],
        user["role"],
        sid=str(session["_id"]),
    )

    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        user=_to_public(user),
    )


# ============================================================
# LOGOUT
# ============================================================

@router.post("/logout")
async def logout(
    request: Request,
    payload: Optional[LogoutRequest] = None,
    current: UserPublic = Depends(get_current_user),
):
    db = get_db()

    now = utc_now()

    # --------------------------------------------------------
    # 1. AUTOMATIC ATTENDANCE CHECK-OUT
    # --------------------------------------------------------
    # Close the most recent open record (checked in, not yet
    # checked out); it may belong to an earlier IST day when
    # the session spanned midnight.

    open_record = await db.attendance.find_one(
        {
            "employee_id": current.id,
            "check_in": {"$ne": None},
            "check_out": None,
        },
        sort=[("date", -1), ("check_in", -1)],
    )

    if open_record:
        await db.attendance.update_one(
            {"_id": open_record["_id"]},
            {
                "$set": {
                    "check_out": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            },
        )

    # --------------------------------------------------------
    # 2. Revoke the session of the presented refresh token
    # --------------------------------------------------------

    if payload and payload.refresh_token:
        try:
            data = decode_token(payload.refresh_token)
        except Exception:
            data = {}
        if data.get("type") == "refresh" and data.get("sub") == current.id and data.get("jti"):
            await db.sessions.update_one(
                {"refresh_token_id": data["jti"], "user_id": current.id},
                {"$set": {"revoked": True, "revoked_at": now.isoformat()}},
            )

    # The access token's own session too: after a refresh the client's refresh token may have
    # rotated past the one it sent, but the session id in the access token stays the same.
    sid = session_id_from_request(request)
    if sid and ObjectId.is_valid(sid):
        await db.sessions.update_one(
            {"_id": ObjectId(sid), "user_id": current.id, "revoked": {"$ne": True}},
            {"$set": {"revoked": True, "revoked_at": now.isoformat()}},
        )

    # --------------------------------------------------------
    # 3. Mark user offline
    # --------------------------------------------------------

    await db.users.update_one(
        {
            "_id": ObjectId(current.id)
        },
        {
            "$set": {
                "online": False
            }
        },
    )

    # --------------------------------------------------------
    # 4. Log activity
    # --------------------------------------------------------

    await _log_activity(
        db,
        current,
        "Signed out",
    )

    return {
        "ok": True
    }


# ============================================================
# CURRENT USER
# ============================================================

@router.get("/me", response_model=UserPublic)
async def me(
    current: UserPublic = Depends(get_current_user),
):
    return current


# ============================================================
# ATTENDANCE (FOUNDER VIEW)
# ============================================================

@router.get("/attendance", response_model=list[dict])
async def list_attendance(
    current: UserPublic = Depends(require_roles("Founder")),
):
    db = get_db()

    records = await db.attendance.find().sort("date", -1).to_list(500)

    return [
        {
            "employee": r["employee_name"],
            "date": r["date"],
            "check_in": r.get("check_in"),
            "check_out": r.get("check_out"),
        }
        for r in records
    ]


# ============================================================
# PASSWORD RESET BY EMAIL
# ============================================================
# Only the SHA-256 hash of a reset token is stored; the raw token exists
# solely in the emailed link. /forgot-password answers identically for
# every email so it cannot be used to discover accounts.

RESET_TOKEN_TTL = timedelta(minutes=30)
RESET_TTL_MARGIN_SECONDS = 24 * 3600      # keep used/expired records a day for auditing
RESET_WINDOW = timedelta(hours=1)
RESET_MAX_PER_EMAIL = 3
RESET_MAX_PER_IP = 10
MIN_PASSWORD = 8                          # same rule as invite acceptance / password change
FORGOT_RESPONSE = {
    "ok": True,
    "message": "If an account exists for that email, a reset link has been sent. It expires in 30 minutes.",
}
INVALID_RESET_DETAIL = "This reset link is invalid or has expired. Please request a new one."


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., max_length=256)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain}" if local and domain else "***"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _reset_link_base(request: Request) -> str | None:
    """FRONTEND_URL, else the request Origin only when it is an explicit CORS origin."""
    configured = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    allowed = {o.strip().rstrip("/") for o in (os.environ.get("CORS_ORIGINS") or "").split(",")}
    allowed.discard("")
    allowed.discard("*")
    return origin if origin and origin in allowed else None


async def ensure_password_reset_indexes(db) -> None:
    """Indexes for password reset tokens and request throttling. Call once at startup."""
    await db.password_resets.create_index("token_hash", unique=True)
    await db.password_resets.create_index([("user_id", 1), ("used_at", 1)])
    await db.password_resets.create_index("expires_at", expireAfterSeconds=RESET_TTL_MARGIN_SECONDS)
    await db.password_reset_throttle.create_index([("key", 1), ("created_at", 1)])
    await db.password_reset_throttle.create_index(
        "created_at", expireAfterSeconds=int(RESET_WINDOW.total_seconds()))


async def _reset_rate_limited(db, email: str, ip: str | None, now: datetime) -> bool:
    """Record this request, then report whether the email or IP exceeded its hourly budget."""
    email_key = f"email:{_sha256(email)}"          # unknown addresses are never stored in clear
    ip_key = f"ip:{ip or 'unknown'}"
    await db.password_reset_throttle.insert_many([
        {"key": email_key, "created_at": now},
        {"key": ip_key, "created_at": now},
    ])
    since = now - RESET_WINDOW
    email_count = await db.password_reset_throttle.count_documents(
        {"key": email_key, "created_at": {"$gt": since}})
    ip_count = await db.password_reset_throttle.count_documents(
        {"key": ip_key, "created_at": {"$gt": since}})
    return email_count > RESET_MAX_PER_EMAIL or ip_count > RESET_MAX_PER_IP


def _valid_reset_filter(token: str, now: datetime) -> dict:
    return {
        "token_hash": _sha256(token),
        "used_at": None,
        "invalidated_at": None,
        "expires_at": {"$gt": now},
    }


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, request: Request, background: BackgroundTasks):
    db = get_db()
    now = utc_now()
    email = payload.email.lower().strip()
    ip = _client_ip(request)

    # Same work for every address: throttle bookkeeping, user lookup, token hashing
    # and the invalidation write. Only eligible accounts get a stored token, and the
    # email itself is sent after the response has gone out.
    limited = await _reset_rate_limited(db, email, ip, now)
    user = await db.users.find_one({"email": email}) if email else None
    raw_token = secrets.token_urlsafe(32)
    token_hash = _sha256(raw_token)

    eligible = bool(
        not limited
        and user
        and (user.get("password_hash") or "")
        and not is_deactivated(user)
    )
    uid = str(user["_id"]) if eligible else f"none:{token_hash}"

    # A new request voids every earlier unused link of the account
    await db.password_resets.update_many(
        {"user_id": uid, "used_at": None, "invalidated_at": None},
        {"$set": {"invalidated_at": now}},
    )

    if not eligible:
        if limited:
            logger.warning("[Auth] Password reset request throttled (ip=%s)", ip)
        return FORGOT_RESPONSE

    base = _reset_link_base(request)
    if not base:
        logger.warning("[Auth] FRONTEND_URL not set and Origin not trusted; password reset email not sent")
        return FORGOT_RESPONSE

    await db.password_resets.insert_one({
        "user_id": uid,
        "token_hash": token_hash,
        "created_at": now,
        "expires_at": now + RESET_TOKEN_TTL,
        "used_at": None,
        "invalidated_at": None,
        "requested_ip": ip,
    })
    background.add_task(
        send_password_reset_link_email,
        recipient_email=user["email"],
        recipient_name=user.get("name") or "",
        reset_url=f"{base}/reset-password?token={raw_token}",
        expires_minutes=int(RESET_TOKEN_TTL.total_seconds() // 60),
    )
    await _log_activity(
        db,
        {"id": uid, "name": user.get("name"), "role": user.get("role")},
        "Requested password reset",
        target=user["email"],
    )
    return FORGOT_RESPONSE


async def _reset_user(db, record):
    """The active, password-holding user a reset record belongs to, else None."""
    if not record or not ObjectId.is_valid(record.get("user_id") or ""):
        return None
    user = await db.users.find_one({"_id": ObjectId(record["user_id"])})
    if not user or is_deactivated(user) or not user.get("password_hash"):
        return None
    return user


@router.get("/reset-password/validate")
async def validate_reset_token(token: str = ""):
    db = get_db()
    if not token or len(token) > 256:
        return {"valid": False}
    record = await db.password_resets.find_one(_valid_reset_filter(token, utc_now()))
    user = await _reset_user(db, record)
    if not user:
        return {"valid": False}
    return {"valid": True, "email": _mask_email(user["email"])}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    db = get_db()
    password = payload.password
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD} characters long")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password is too long (maximum 72 bytes)")

    now = utc_now()
    # Atomically consume the token so it can only ever be used once
    record = await db.password_resets.find_one_and_update(
        _valid_reset_filter(payload.token, now),
        {"$set": {"used_at": now}},
    )
    user = await _reset_user(db, record)
    if not user:
        raise HTTPException(status_code=400, detail=INVALID_RESET_DETAIL)

    uid = record["user_id"]
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(password), "online": False, "updated_at": now.isoformat()}},
    )
    # Sign out everywhere: every refresh token of this user stops working
    revoked = await db.sessions.update_many(
        {"user_id": uid, "revoked": {"$ne": True}},
        {"$set": {"revoked": True, "revoked_at": now.isoformat()}},
    )
    # Any other outstanding reset links for this user are now void
    await db.password_resets.update_many(
        {"user_id": uid, "used_at": None, "invalidated_at": None},
        {"$set": {"invalidated_at": now}},
    )

    actor = {"id": uid, "name": user.get("name"), "role": user.get("role")}
    await log_activity(db, actor, "Reset password via email link", "Auth", target="Security",
                       meta={"sessions_revoked": revoked.modified_count})
    await notify(
        db, uid, "Password changed",
        "Your password was reset using an email link and all sessions were signed out. "
        "If this wasn't you, contact your Founder or Admin immediately.",
        kind="warning",
    )
    return {"ok": True, "message": "Password updated. Please sign in with your new password."}
