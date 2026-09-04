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
    # Real founder account uses env-provided credentials.
    {"role": "Founder", "email_env": "FOUNDER_EMAIL", "password_env": "FOUNDER_PASSWORD",
     "name_env": "FOUNDER_NAME", "designation": "Founder & CEO", "department": "Executive"},
]


async def _ensure_user(db, email: str, password: str, name: str, role: str, designation: str, department: str) -> str:
    existing = await db.users.find_one({"role": "Founder"}) if role == "Founder" else await db.users.find_one({"email": email})
    doc = {
        "email": email,
        "name": name,
        "role": role,
        "designation": designation,
        "department": department,
        "online": role == "Founder",
        "updated_at": utc_now().isoformat(),
    }
    if existing is None:
        doc["password_hash"] = hash_password(password)
        doc["created_at"] = utc_now().isoformat()
        res = await db.users.insert_one(doc)
        return str(res.inserted_id)
    # Update password if changed, keep other fields fresh
    updates = dict(doc)
    from auth_utils import verify_password
    if not verify_password(password, existing.get("password_hash", "")):
        updates["password_hash"] = hash_password(password)
    await db.users.update_one({"_id": existing["_id"]}, {"$set": updates})
    return str(existing["_id"])


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
