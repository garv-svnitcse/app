
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
    {
        "role": "Founder",
        "email_env": "FOUNDER_EMAIL",
        "password_env": "FOUNDER_PASSWORD",
        "name_env": "FOUNDER_NAME",
        "designation": "Founder & CEO",
        "department": "Executive",
    },
]


async def _ensure_user(
    db,
    email: str,
    password: str,
    name: str,
    role: str,
    designation: str,
    department: str,
) -> str:
    existing = await db.users.find_one({"email": email})

    # Never create a second Founder if another Founder already exists.
    if role == "Founder":
        existing_founder = await db.users.find_one({"role": "Founder"})

        if existing_founder and (
            existing is None
            or str(existing_founder["_id"]) != str(existing["_id"])
        ):
            raise ValueError(
                "Configured FOUNDER_EMAIL does not match the existing Founder account. "
                "Refusing to create or modify a second Founder."
            )

    now = utc_now().isoformat()
    doc = {
        "email": email,
        "name": name,
        "role": role,
        "designation": designation,
        "department": department,
        "online": role == "Founder",
        "status": "active",
        "is_active": True,
        "updated_at": now,
    }

    if existing is None:
        doc["password_hash"] = hash_password(password)
        doc["created_at"] = now

        result = await db.users.insert_one(doc)
        return str(result.inserted_id)

    # Preserve the existing password; update profile fields only.
    await db.users.update_one(
        {"_id": existing["_id"]},
        {"$set": doc},
    )

    return str(existing["_id"])


async def seed_all():
    db = get_db()

    # Indexes
    await db.users.create_index("email", unique=True)
    await db.users.create_index(
        "role",
        unique=True,
        partialFilterExpression={"role": "Founder"},
        name="unique_founder",
    )
    await db.notifications.create_index(
        [("user_id", 1), ("created_at", -1)]
    )
    await db.activity_logs.create_index([("created_at", -1)])
    await db.sessions.create_index("refresh_token_id")

    # Safety: warn if more than one Founder somehow exists.
    founder_count = await db.users.count_documents({"role": "Founder"})

    if founder_count > 1:
        import logging

        logging.getLogger("wavygo").critical(
            "RBAC invariant violated: %d Founder accounts exist "
            "(expected exactly 1).",
            founder_count,
        )

    for spec in ROLE_ACCOUNTS:
        email = os.environ.get(spec["email_env"])
        password = os.environ.get(spec["password_env"])
        name = os.environ.get(spec["name_env"])

        if not email or not password or not name:
            raise ValueError(
                f"Missing required environment variable for {spec['role']} account"
            )

        await _ensure_user(
            db,
            email,
            password,
            name,
            spec["role"],
            spec["designation"],
            spec["department"],
        )
