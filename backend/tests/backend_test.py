from __future__ import annotations
"""WavyGo OS backend API tests."""
# pyrefly: ignore [missing-import]
import pytest
import requests

# End-to-end suite against a running deployment. Opt in by pointing WAVYGO_E2E_URL at it
# (e.g. a staging backend); without it the suite is skipped so CI never hits production.
# Credentials come from the environment (FOUNDER_EMAIL / FOUNDER_PASSWORD, see e2e_accounts.py).
from e2e_accounts import API, E2E_SKIP, FOUNDER, ADMIN, MANAGER, EMPLOYEE, INTERN  # noqa: E402

pytestmark = E2E_SKIP


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _login(s, creds):
    r = s.post(f"{API}/auth/login", json={**creds, "remember": True}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data and "refresh_token" in data and "user" in data
    return data


# ---------- Health & Public ----------
def test_health(s):
    r = s.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_live_kpis_is_public(s):
    r = s.get(f"{API}/dashboard/live-kpis")
    assert r.status_code == 200
    b = r.json()
    for k in ("revenue_mtd", "bookings_today", "active_vehicles", "active_vendors", "satisfaction_score"):
        assert k in b


# ---------- Auth ----------
def test_login_founder_success(s):
    d = _login(s, FOUNDER)
    assert d["user"]["role"] == "Founder"


def test_login_all_roles(s):
    for role, creds in [("Founder", FOUNDER), ("Admin", ADMIN), ("Manager", MANAGER), ("Employee", EMPLOYEE), ("Intern", INTERN)]:
        d = _login(s, creds)
        assert d["user"]["role"] == role


def test_login_wrong_password(s):
    r = s.post(f"{API}/auth/login", json={"email": FOUNDER["email"], "password": "WrongPassword!1"}, timeout=30)
    assert r.status_code == 401


def test_me_invalid_token(s):
    r = s.get(f"{API}/users/me", headers={"Authorization": "Bearer invalid_token_here"})
    assert r.status_code == 401


def test_me_valid(s):
    d = _login(s, FOUNDER)
    r = s.get(f"{API}/users/me", headers={"Authorization": f"Bearer {d['access_token']}"})
    assert r.status_code == 200
    assert r.json()["email"] == FOUNDER["email"]


def test_refresh_flow(s):
    d = _login(s, FOUNDER)
    r = s.post(f"{API}/auth/refresh", json={"refresh_token": d["refresh_token"]})
    assert r.status_code == 200
    b = r.json()
    assert "access_token" in b and "refresh_token" in b


def test_refresh_invalid(s):
    r = s.post(f"{API}/auth/refresh", json={"refresh_token": "bad_token"})
    assert r.status_code == 401


# ---------- RBAC Basic Gates ----------
def test_users_list_founder_200(s):
    d = _login(s, FOUNDER)
    r = s.get(f"{API}/users", headers={"Authorization": f"Bearer {d['access_token']}"})
    assert r.status_code == 200
    assert len(r.json()) >= 5


def test_users_list_intern_403(s):
    d = _login(s, INTERN)
    r = s.get(f"{API}/users", headers={"Authorization": f"Bearer {d['access_token']}"})
    assert r.status_code == 403


def test_users_list_employee_403(s):
    d = _login(s, EMPLOYEE)
    r = s.get(f"{API}/users", headers={"Authorization": f"Bearer {d['access_token']}"})
    assert r.status_code == 403


def test_users_list_manager_200(s):
    d = _login(s, MANAGER)
    r = s.get(f"{API}/users", headers={"Authorization": f"Bearer {d['access_token']}"})
    assert r.status_code == 200


# ---------- Dashboard stats (authed) ----------
def test_dashboard_stats_requires_auth(s):
    r = s.get(f"{API}/dashboard/stats")
    assert r.status_code == 401


def test_dashboard_stats_authed(s):
    d = _login(s, FOUNDER)
    r = s.get(f"{API}/dashboard/stats", headers={"Authorization": f"Bearer {d['access_token']}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["kpis"]) >= 5
    keys = {k["key"] for k in body["kpis"]}
    assert {"revenue", "bookings", "customers", "vehicles", "vendors"}.issubset(keys)


# ---------- Notifications & Activity ----------
def test_notifications_endpoints(s):
    d = _login(s, FOUNDER)
    h = {"Authorization": f"Bearer {d['access_token']}"}
    r = s.get(f"{API}/notifications", headers=h)
    assert r.status_code == 200
    r2 = s.get(f"{API}/notifications/unread-count", headers=h)
    assert r2.status_code == 200
    assert "count" in r2.json() or "unread" in r2.json()


def test_activity(s):
    d = _login(s, FOUNDER)
    h = {"Authorization": f"Bearer {d['access_token']}"}
    r = s.get(f"{API}/activity", headers=h)
    assert r.status_code == 200


# ---------- Settings ----------
def test_settings_company(s):
    d = _login(s, FOUNDER)
    h = {"Authorization": f"Bearer {d['access_token']}"}
    r = s.get(f"{API}/settings/company", headers=h)
    assert r.status_code == 200


# ---------- Profile update + password reset roundtrip ----------
def test_update_profile_and_password_roundtrip(s):
    d = _login(s, EMPLOYEE)
    h = {"Authorization": f"Bearer {d['access_token']}"}
    # update profile
    r = s.patch(f"{API}/users/me", json={"phone": "+919999999999", "designation": "QA Tester"}, headers=h)
    assert r.status_code == 200
    assert r.json()["phone"] == "+919999999999"
    assert r.json()["designation"] != "QA Tester"

    # change password to new
    new_pwd = EMPLOYEE["password"] + "_TMP"
    r = s.post(f"{API}/users/me/password", json={"current_password": EMPLOYEE["password"], "new_password": new_pwd}, headers=h)
    assert r.status_code == 200

    # re-login with new
    d2 = _login(s, {"email": EMPLOYEE["email"], "password": new_pwd})
    h2 = {"Authorization": f"Bearer {d2['access_token']}"}

    # restore
    r = s.post(f"{API}/users/me/password", json={"current_password": new_pwd, "new_password": EMPLOYEE["password"]}, headers=h2)
    assert r.status_code == 200

    # confirm restored
    _login(s, EMPLOYEE)
