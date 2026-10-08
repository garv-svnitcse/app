from __future__ import annotations
"""Auth / session / notifications / users / settings tests — login gating,
refresh rotation and revocation, remember-me lifetimes, admin register,
per-user broadcast read state, directory and company settings.

Runs against an isolated server and throwaway database (see local_harness.py).
"""
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import jwt
import pytest
from bson import ObjectId

from local_harness import api, mongo, test_db, users, harness_env, call, TEST_PASSWORD  # noqa: F401
from auth_utils import create_access_token, create_refresh_token, hash_password  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def _login(api, user, remember=True, password=TEST_PASSWORD):
    return call(api, None, "POST", "/auth/login",
                json={"email": user["email"], "password": password, "remember": remember})


def _claims(token):
    return jwt.decode(token, options={"verify_signature": False})


def _bearer(token):
    return {"headers": {"Authorization": f"Bearer {token}"}}


def _new_user(test_db, role="Employee", **extra):
    _id = ObjectId()
    doc = {"_id": _id, "email": f"u.{_id}@harness.wavygo.in", "name": f"Temp {_id}", "role": role,
           "status": "active", "is_active": True, "password_hash": hash_password(TEST_PASSWORD), **extra}
    test_db.users.insert_one(doc)
    return {"id": str(_id), "email": doc["email"], "name": doc["name"], "role": role}


# ------------------------- 1. deactivated login -------------------------

@pytest.mark.parametrize("flags", [{"status": "deactivated"}, {"is_active": False}, {"active": False}])
def test_login_rejects_deactivated(api, users, test_db, flags):
    u = _new_user(test_db, **flags)
    r = _login(api, u)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Account is deactivated. Please contact your Founder or Admin."
    assert test_db.sessions.count_documents({"user_id": u["id"]}) == 0
    assert test_db.attendance.count_documents({"employee_id": u["id"]}) == 0
    assert not test_db.users.find_one({"_id": ObjectId(u["id"])}).get("online")


def test_login_wrong_password_still_401(api, users):
    assert _login(api, users["employee"], password="nope").status_code == 401


# ------------------------- 3. remember me -------------------------

def test_remember_controls_refresh_lifetime(api, users):
    long = _claims(_login(api, users["manager"], remember=True).json()["refresh_token"])
    short = _claims(_login(api, users["manager"], remember=False).json()["refresh_token"])
    assert 29 * 86400 < long["exp"] - long["iat"] <= 30 * 86400
    assert short["exp"] - short["iat"] <= 86400


# ------------------------- 2. refresh rotation / logout -------------------------

def test_refresh_rotates_and_old_token_rejected(api, users, test_db):
    body = _login(api, users["employee"], remember=False).json()
    old = body["refresh_token"]
    r = call(api, None, "POST", "/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200, r.text
    new = r.json()["refresh_token"]
    assert _claims(new)["jti"] != _claims(old)["jti"]
    # rotated token keeps the non-remember lifetime and the session id
    assert _claims(new)["exp"] - _claims(new)["iat"] <= 86400
    assert _claims(r.json()["access_token"])["sid"] == _claims(body["access_token"])["sid"]
    # the old refresh token is now dead, the new one works once
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": old}).status_code == 401
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": new}).status_code == 200
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": new}).status_code == 401


def test_refresh_rejects_unknown_session(api, users):
    forged, _ = create_refresh_token(users["employee"]["id"], jti=str(uuid.uuid4()))
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": forged}).status_code == 401


def test_refresh_rejects_deactivated(api, users, test_db):
    u = _new_user(test_db)
    rt = _login(api, u).json()["refresh_token"]
    test_db.users.update_one({"_id": ObjectId(u["id"])}, {"$set": {"status": "deactivated"}})
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": rt}).status_code == 403


def test_logout_revokes_session_and_checks_out(api, users, test_db):
    u = _new_user(test_db)
    body = _login(api, u).json()
    rec = test_db.attendance.find_one({"employee_id": u["id"]})
    ist_today = datetime.now(IST).date()
    assert rec["date"] == ist_today.isoformat() and rec["check_out"] is None
    first_check_in = rec["check_in"]
    # second login the same day keeps the first check_in
    body = _login(api, u).json()
    assert test_db.attendance.count_documents({"employee_id": u["id"]}) == 1
    assert test_db.attendance.find_one({"employee_id": u["id"]})["check_in"] == first_check_in

    r = call(api, None, "POST", "/auth/logout", json={"refresh_token": body["refresh_token"]},
             **_bearer(body["access_token"]))
    assert r.status_code == 200, r.text
    assert call(api, None, "POST", "/auth/refresh",
                json={"refresh_token": body["refresh_token"]}).status_code == 401
    assert test_db.attendance.find_one({"employee_id": u["id"]})["check_out"] is not None
    # The access token of the revoked session stops working at once, not after 12 hours.
    assert call(api, None, "GET", "/auth/me", **_bearer(body["access_token"])).status_code == 401


def test_logout_closes_open_record_from_previous_day(api, users, test_db):
    u = _new_user(test_db)
    test_db.attendance.insert_one({"employee_id": u["id"], "employee_name": u["name"], "date": "2020-01-01",
                                   "status": "present", "check_in": "2020-01-01T17:00:00+00:00", "check_out": None})
    token = create_access_token(u["id"], u["email"], u["role"])
    assert call(api, None, "POST", "/auth/logout", **_bearer(token)).status_code == 200
    assert test_db.attendance.find_one({"employee_id": u["id"], "date": "2020-01-01"})["check_out"] is not None


# ------------------------- 4. register -------------------------

def test_register_returns_user_without_tokens(api, users, test_db):
    email = f"new.{uuid.uuid4().hex[:8]}@harness.wavygo.in"
    r = call(api, users["admin"], "POST", "/auth/register",
             json={"email": email, "password": "Wavygo@2026", "name": "New Hire", "role": "Employee"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" not in data and "refresh_token" not in data
    assert data["email"] == email and data["role"] == "Employee" and data["online"] is False
    assert test_db.sessions.count_documents({"user_id": data["id"]}) == 0
    assert test_db.attendance.count_documents({"employee_id": data["id"]}) == 0
    log = test_db.activity_logs.find_one({"action": "Account created", "user_id": users["admin"]["id"]})
    assert log is not None
    # the new user can sign in themselves
    assert _login(api, {"email": email}, password="Wavygo@2026").status_code == 200


# ------------------------- 6. notifications -------------------------

def _notif(test_db, user_id, title="Announcement: hello", **extra):
    return str(test_db.notifications.insert_one({
        "user_id": user_id, "title": title, "body": "b", "kind": "info", "read": False,
        "link": None, "created_at": datetime.now(timezone.utc).isoformat(), **extra}).inserted_id)


def _read_state(api, user, nid):
    items = call(api, user, "GET", "/notifications").json()
    return next(n["read"] for n in items if n["id"] == nid)


def test_mark_read_requires_visibility(api, users, test_db):
    private = _notif(test_db, users["employee2"]["id"], title="Your task")
    r = call(api, users["employee"], "POST", f"/notifications/{private}/read")
    assert r.status_code == 404
    assert test_db.notifications.find_one({"_id": ObjectId(private)})["read"] is False
    # broadcast hidden from employees by the role filter
    leave = _notif(test_db, None, title="Leave request from X")
    assert call(api, users["employee"], "POST", f"/notifications/{leave}/read").status_code == 404
    assert call(api, users["employee2"], "POST", f"/notifications/{private}/read").status_code == 200
    assert _read_state(api, users["employee2"], private) is True


def test_broadcast_read_is_per_user(api, users, test_db):
    nid = _notif(test_db, None)
    before = call(api, users["intern"], "GET", "/notifications/unread-count").json()["count"]
    assert call(api, users["employee"], "POST", f"/notifications/{nid}/read").status_code == 200
    assert _read_state(api, users["employee"], nid) is True
    assert _read_state(api, users["intern"], nid) is False
    assert call(api, users["intern"], "GET", "/notifications/unread-count").json()["count"] == before


def test_mark_all_is_per_user(api, users, test_db):
    b = _notif(test_db, None)
    mine = _notif(test_db, users["manager"]["id"], title="Mine")
    other = _notif(test_db, users["employee"]["id"], title="Theirs")
    assert call(api, users["manager"], "POST", "/notifications/read-all").status_code == 200
    assert call(api, users["manager"], "GET", "/notifications/unread-count").json()["count"] == 0
    assert _read_state(api, users["manager"], b) is True
    assert _read_state(api, users["manager"], mine) is True
    assert _read_state(api, users["admin"], b) is False
    assert test_db.notifications.find_one({"_id": ObjectId(other)})["read"] is False


# ------------------------- 7. password change -------------------------

def test_change_password_revokes_other_sessions(api, users, test_db):
    u = _new_user(test_db, role="Manager")
    a = _login(api, u).json()
    b = _login(api, u).json()
    r = call(api, None, "POST", "/users/me/password", **_bearer(a["access_token"]),
             json={"current_password": TEST_PASSWORD, "new_password": "Changed@2026"})
    assert r.status_code == 200, r.text
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 401
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 200
    assert _login(api, u, password="Changed@2026").status_code == 200


def test_logout_revokes_access_token_session_after_rotation(api, users, test_db):
    # The client refreshed (rotating its refresh token) and then logs out sending the stale one:
    # the session named by the access token is still revoked.
    u = _new_user(test_db)
    a = _login(api, u).json()
    rotated = call(api, None, "POST", "/auth/refresh", json={"refresh_token": a["refresh_token"]}).json()
    r = call(api, None, "POST", "/auth/logout", **_bearer(rotated["access_token"]),
             json={"refresh_token": a["refresh_token"]})
    assert r.status_code == 200, r.text
    assert call(api, None, "POST", "/auth/refresh", json={"refresh_token": rotated["refresh_token"]}).status_code == 401
    assert call(api, None, "GET", "/auth/me", **_bearer(rotated["access_token"])).status_code == 401


def test_change_password_rejects_over_72_bytes(api, users, test_db):
    u = _new_user(test_db, role="Manager")
    a = _login(api, u).json()
    r = call(api, None, "POST", "/users/me/password", **_bearer(a["access_token"]),
             json={"current_password": TEST_PASSWORD, "new_password": "x" * 73})
    assert r.status_code == 400 and "72" in r.json()["detail"]


def test_update_me_trims_and_clears_phone(api, users, test_db):
    u = _new_user(test_db, phone="+91 99999 00000")
    token = _login(api, u).json()["access_token"]
    r = call(api, None, "PATCH", "/users/me", **_bearer(token), json={"phone": "  +91 12345 67890 "})
    assert r.status_code == 200 and r.json()["phone"] == "+91 12345 67890"
    r = call(api, None, "PATCH", "/users/me", **_bearer(token), json={"phone": "   "})
    assert r.status_code == 200 and r.json()["phone"] is None
    assert call(api, None, "PATCH", "/users/me", **_bearer(token), json={"phone": "9" * 41}).status_code == 422
    # Fields outside phone/photo are ignored.
    r = call(api, None, "PATCH", "/users/me", **_bearer(token), json={"name": "Hacker", "phone": "1"})
    assert r.json()["name"] == u["name"]


# ------------------------- 8. directory -------------------------

def test_directory(api, users, test_db):
    gone = _new_user(test_db, status="deactivated")
    r = call(api, users["intern"], "GET", "/users/directory")
    assert r.status_code == 200, r.text
    rows = r.json()
    ids = [x["id"] for x in rows]
    assert users["founder"]["id"] in ids and gone["id"] not in ids
    assert all(set(x) == {"id", "name", "role", "department", "designation", "photo"} for x in rows)
    names = [x["name"] for x in rows]
    assert names == sorted(names)
    assert call(api, None, "GET", "/users/directory").status_code == 401


# ------------------------- 11. settings -------------------------

def test_roles_admin_has_no_finance(api, users):
    roles = {x["name"]: x["description"] for x in call(api, users["employee"], "GET", "/settings/roles").json()["roles"]}
    assert "finance" not in roles["Admin"].lower()
    assert "Finance" in roles["Founder"]


def test_company_edit(api, users, test_db):
    base = call(api, users["employee"], "GET", "/settings/company").json()
    assert base["cin"] == "U77100BR2025PTC077095"
    for key in ("admin", "manager", "employee"):
        assert call(api, users[key], "PATCH", "/settings/company", json={"hq": "X"}).status_code == 403
    assert call(api, users["founder"], "PATCH", "/settings/company", json={"hq": ""}).status_code == 422
    assert call(api, users["founder"], "PATCH", "/settings/company", json={"bogus": "x"}).status_code == 422
    r = call(api, users["founder"], "PATCH", "/settings/company", json={"hq": "  Bengaluru, India "})
    assert r.status_code == 200, r.text
    assert r.json()["hq"] == "Bengaluru, India" and r.json()["name"] == base["name"]
    assert call(api, users["intern"], "GET", "/settings/company").json()["hq"] == "Bengaluru, India"
    assert test_db.activity_logs.find_one({"action": "Updated company profile"}) is not None
