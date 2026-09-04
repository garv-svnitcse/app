from __future__ import annotations
"""JWT + password hashing + FastAPI dependencies for role-based auth."""
import os
import uuid
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import Callable
from bson import ObjectId
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from db import get_db
from models import UserPublic

JWT_ALG = "HS256"
ACCESS_MIN = 60 * 12   # 12h
REFRESH_DAYS = 30


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MIN),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def create_refresh_token(user_id: str, jti: str | None = None) -> tuple[str, str]:
    jti = jti or str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "jti": jti,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG), jti


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALG])


bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> UserPublic:
    token = None
    if creds and creds.scheme.lower() == "bearer":
        token = creds.credentials
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    db = get_db()
    user_id = payload["sub"]
    try:
        user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user id")
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")

    if user_doc.get("status") == "deactivated" or user_doc.get("is_active") is False or user_doc.get("active") is False:
        raise HTTPException(status_code=403, detail="Account is deactivated. Please contact your Founder or Admin.")

    return UserPublic(
        id=str(user_doc["_id"]),
        email=user_doc["email"],
        name=user_doc["name"],
        role=user_doc["role"],
        photo=user_doc.get("photo"),
        online=user_doc.get("online", False),
        phone=user_doc.get("phone"),
        designation=user_doc.get("designation"),
        department=user_doc.get("department"),
        status=user_doc.get("status", "active"),
        is_active=user_doc.get("is_active", True),
    )


def require_roles(*allowed: str) -> Callable:
    async def _dep(user: UserPublic = Depends(get_current_user)) -> UserPublic:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail=f"Requires role in {list(allowed)}")
        return user
    return _dep
