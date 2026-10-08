from __future__ import annotations
"""Password reset by email: no account enumeration, hashed single-use tokens,
expiry, rate limiting, old-link invalidation, session revocation.

Runs against an isolated server and throwaway database (see local_harness.py).
Email is disabled (BREVO_API_KEY=""), so tests plant known token hashes directly.
"""
import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from local_harness import api, mongo, test_db, users, harness_env, call, TEST_PASSWORD, MONGO_URL  # noqa: F401
from auth_utils import hash_password, verify_password  # noqa: E402

GENERIC = "If an account exists for that email, a reset link has been sent. It expires in 30 minutes."


@pytest.fixture(scope="module")
def harness_env():
    return {"BREVO_API_KEY": "", "FRONTEND_URL": "http://localhost:3000"}


@pytest.fixture(autouse=True)
def _clear_throttle(test_db):
    # All requests come from 127.0.0.1; reset the per-IP budget for every test
    test_db.password_reset_throttle.delete_many({})
    yield


def _sha(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_user(test_db, **extra):
    _id = ObjectId()
    doc = {"_id": _id, "email": f"r.{_id}@harness.wavygo.in", "name": f"Reset {_id}", "role": "Employee",
           "status": "active", "is_active": True, "password_hash": hash_password(TEST_PASSWORD), **extra}
    test_db.users.insert_one(doc)
    return {"id": str(_id), "email": doc["email"]}


def _plant_token(test_db, user_id, minutes=30, **extra):
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    test_db.password_resets.insert_one({
        "user_id": user_id, "token_hash": _sha(raw), "created_at": now,
        "expires_at": now + timedelta(minutes=minutes), "used_at": None, "invalidated_at": None,
        "requested_ip": "127.0.0.1", **extra,
    })
    return raw


def _forgot(api, email):
    return call(api, None, "POST", "/auth/forgot-password", json={"email": email})


def _reset(api, token, password="NewPass#2026"):
    return call(api, None, "POST", "/auth/reset-password", json={"token": token, "password": password})


def _validate(api, token):
    return call(api, None, "GET", "/auth/reset-password/validate", params={"token": token}).json()


def _login(api, email, password):
    return call(api, None, "POST", "/auth/login", json={"email": email, "password": password, "remember": True})


# ------------------------- forgot-password -------------------------

def test_no_enumeration_and_hashed_record(api, users, test_db):
    u = _new_user(test_db)
    known = _forgot(api, u["email"].upper())
    unknown = _forgot(api, f"nobody.{ObjectId()}@harness.wavygo.in")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"ok": True, "message": GENERIC}

    recs = list(test_db.password_resets.find({"user_id": u["id"]}))
    assert len(recs) == 1
    rec = recs[0]
    assert len(rec["token_hash"]) == 64 and "token" not in rec
    assert rec["used_at"] is None and rec["requested_ip"]
    ttl = rec["expires_at"].replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(minutes=28) < ttl <= timedelta(minutes=30)
    # nothing is stored for the unknown address (not even in clear in the throttle log)
    assert test_db.password_resets.count_documents({"user_id": {"$not": {"$regex": "^[0-9a-f]{24}$"}}}) == 0
    assert test_db.password_reset_throttle.count_documents({"key": {"$regex": "nobody"}}) == 0


@pytest.mark.parametrize("flags", [{"status": "deactivated"}, {"is_active": False}, {"password_hash": ""}])
def test_deactivated_or_invite_placeholder_gets_no_token(api, users, test_db, flags):
    u = _new_user(test_db, **flags)
    r = _forgot(api, u["email"])
    assert r.status_code == 200 and r.json()["message"] == GENERIC
    assert test_db.password_resets.count_documents({"user_id": u["id"]}) == 0


def test_new_request_invalidates_older_tokens(api, users, test_db):
    u = _new_user(test_db)
    old = _plant_token(test_db, u["id"])
    assert _validate(api, old)["valid"] is True
    assert _forgot(api, u["email"]).status_code == 200
    assert _validate(api, old) == {"valid": False}
    assert _reset(api, old).status_code == 400
    live = test_db.password_resets.count_documents({"user_id": u["id"], "used_at": None, "invalidated_at": None})
    assert live == 1


def test_rate_limit_per_email(api, users, test_db):
    u = _new_user(test_db)
    for _ in range(5):
        r = _forgot(api, u["email"])
        assert r.status_code == 200 and r.json()["message"] == GENERIC
    assert test_db.password_resets.count_documents({"user_id": u["id"]}) == 3


def test_rate_limit_per_ip(api, users, test_db):
    for _ in range(10):
        _forgot(api, f"nobody.{ObjectId()}@harness.wavygo.in")
    u = _new_user(test_db)
    r = _forgot(api, u["email"])
    assert r.status_code == 200 and r.json()["message"] == GENERIC
    assert test_db.password_resets.count_documents({"user_id": u["id"]}) == 0


# ------------------------- validate / reset -------------------------

def test_validate_masks_email_and_rejects_garbage(api, users, test_db):
    u = _new_user(test_db)
    raw = _plant_token(test_db, u["id"])
    body = _validate(api, raw)
    assert body == {"valid": True, "email": "r***@harness.wavygo.in"}
    assert _validate(api, "not-a-token") == {"valid": False}
    assert _validate(api, "") == {"valid": False}


def test_expired_token_rejected(api, users, test_db):
    u = _new_user(test_db)
    raw = _plant_token(test_db, u["id"], minutes=-1)
    assert _validate(api, raw) == {"valid": False}
    r = _reset(api, raw)
    assert r.status_code == 400
    assert verify_password(TEST_PASSWORD, test_db.users.find_one({"_id": ObjectId(u["id"])})["password_hash"])


def test_short_password_rejected_without_consuming_token(api, users, test_db):
    u = _new_user(test_db)
    raw = _plant_token(test_db, u["id"])
    r = _reset(api, raw, password="short7!")
    assert r.status_code == 400 and "8 characters" in r.json()["detail"]
    assert _validate(api, raw)["valid"] is True


def test_reset_is_single_use_revokes_sessions_and_allows_new_login(api, users, test_db):
    u = _new_user(test_db)
    session = _login(api, u["email"], TEST_PASSWORD).json()
    old_refresh = session["refresh_token"]
    other = _plant_token(test_db, u["id"])
    raw = _plant_token(test_db, u["id"])

    r = _reset(api, raw, "Fresh#Pass2026")
    assert r.status_code == 200, r.text
    assert "access_token" not in r.json() and "refresh_token" not in r.json()

    # single use + other outstanding links are void
    assert _reset(api, raw, "Another#Pass2026").status_code == 400
    assert _validate(api, other) == {"valid": False}
    rec = test_db.password_resets.find_one({"token_hash": _sha(raw)})
    assert rec["used_at"] is not None

    # every session revoked; the old refresh token no longer works
    assert test_db.sessions.count_documents({"user_id": u["id"], "revoked": {"$ne": True}}) == 0
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401

    # old password fails, new one works
    assert _login(api, u["email"], TEST_PASSWORD).status_code == 401
    assert _login(api, u["email"], "Fresh#Pass2026").status_code == 200

    # audit + notification
    assert test_db.activity_logs.find_one({"user_id": u["id"], "action": "Reset password via email link"})
    assert test_db.notifications.find_one({"user_id": u["id"], "title": "Password changed"})


def test_reset_rejected_for_user_deactivated_after_request(api, users, test_db):
    u = _new_user(test_db)
    raw = _plant_token(test_db, u["id"])
    test_db.users.update_one({"_id": ObjectId(u["id"])}, {"$set": {"status": "deactivated"}})
    assert _validate(api, raw) == {"valid": False}
    assert _reset(api, raw).status_code == 400


def test_ensure_indexes(test_db):
    from motor.motor_asyncio import AsyncIOMotorClient
    from routers.auth_router import ensure_password_reset_indexes

    async def run():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            await ensure_password_reset_indexes(client[test_db.name])
        finally:
            client.close()

    asyncio.run(run())
    idx = test_db.password_resets.index_information()
    assert any(i.get("unique") and i["key"] == [("token_hash", 1)] for i in idx.values())
    assert any(i["key"] == [("expires_at", 1)] and i.get("expireAfterSeconds", 0) > 0 for i in idx.values())
