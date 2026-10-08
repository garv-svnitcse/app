from __future__ import annotations
"""Idempotent seed for role accounts, sample notifications & activity logs."""
import os
from datetime import timedelta
from bson import ObjectId
from dotenv import load_dotenv
load_dotenv()

from db import get_db, utc_now
from auth_utils import hash_password


ROLE_ACCOUNTS = [
    # The founder account is created from env-provided credentials (FOUNDER_*) on first start only.
    {"role": "Founder", "email_env": "FOUNDER_EMAIL", "password_env": "FOUNDER_PASSWORD",
     "name_env": "FOUNDER_NAME", "designation": "Founder & CEO", "department": "Executive"},
]


async def _ensure_user(db, email: str, password: str, name: str, role: str, designation: str, department: str) -> str:
    """Create the account on first start only. An existing account is left untouched, so a
    password or profile the user changed in the app survives restarts."""
    existing = await db.users.find_one({"role": "Founder"}) if role == "Founder" else await db.users.find_one({"email": email})
    if existing is not None:
        return str(existing["_id"])
    now = utc_now().isoformat()
    res = await db.users.insert_one({
        "email": email,
        "name": name,
        "role": role,
        "designation": designation,
        "department": department,
        "password_hash": hash_password(password),
        "online": False,
        "status": "active",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    })
    return str(res.inserted_id)


async def seed_all():
    db = get_db()

    # Indexes
    await db.users.create_index("email", unique=True)
    await db.users.create_index(
        "role", unique=True,
        partialFilterExpression={"role": "Founder"}, name="unique_founder",
    )
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.activity_logs.create_index([("created_at", -1)])
    await db.sessions.create_index("refresh_token_id")

    # Safety: warn (never crash) if more than one Founder somehow exists.
    founder_count = await db.users.count_documents({"role": "Founder"})
    if founder_count > 1:
        import logging
        logging.getLogger("wavygo").critical(
            "RBAC invariant violated: %d Founder accounts exist (expected exactly 1).", founder_count
        )

    for spec in ROLE_ACCOUNTS:
        email = os.environ.get(spec.get("email_env", ""), spec.get("email", "anil@wavygo.in"))
        password = os.environ.get(spec.get("password_env", ""), spec.get("password", "Wavygo@2026"))
        name = os.environ.get(spec.get("name_env", ""), spec.get("name", "Anil Anand"))
        await _ensure_user(db, email, password, name, spec["role"], spec["designation"], spec["department"])
