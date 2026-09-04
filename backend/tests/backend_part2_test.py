from __future__ import annotations
"""WavyGo OS Part 2 backend API tests — Marketplace, Tasks, Employees,
Opportunities, WavyGo Connect + enhanced Dashboard. Uses only public backend
URL. Idempotent — extra rows created here are fine, seed is idempotent."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://app-eta-flax-97.vercel.app").rstrip("/")
API = f"{BASE_URL}/api"

FOUNDER  = {"email": "anilanand635@gmail.com", "password": "Wavygo@2026"}
ADMIN    = {"email": "admin@wavygo.in",        "password": "Wavygo@2026"}
MANAGER  = {"email": "manager@wavygo.in",      "password": "Wavygo@2026"}
EMPLOYEE = {"email": "employee@wavygo.in",     "password": "Wavygo@2026"}
INTERN   = {"email": "intern@wavygo.in",       "password": "Wavygo@2026"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password, "remember": True}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def founder_h():
    d = _login(**FOUNDER)
    return {"Authorization": f"Bearer {d['access_token']}"}


@pytest.fixture(scope="module")
def employee_h():
    d = _login(**EMPLOYEE)
    return {"Authorization": f"Bearer {d['access_token']}"}


@pytest.fixture(scope="module")
def intern_h():
    d = _login(**INTERN)
    return {"Authorization": f"Bearer {d['access_token']}"}


@pytest.fixture(scope="module")
def founder_user(founder_h):
    r = requests.get(f"{API}/auth/me", headers=founder_h)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def employee_user(employee_h):
    r = requests.get(f"{API}/auth/me", headers=employee_h)
    assert r.status_code == 200
    return r.json()


# ============ Part 1 Regression (quick) ============

def test_p1_login_founder():
    d = _login(**FOUNDER)
    assert d["user"]["role"] == "Founder"


def test_p1_live_kpis_public():
    r = requests.get(f"{API}/dashboard/live-kpis")
    assert r.status_code == 200
    assert len(r.json()["kpis"]) == 5


def test_p1_settings_activity_notifications(founder_h):
    for path in ("/settings/company", "/activity", "/notifications"):
        r = requests.get(f"{API}{path}", headers=founder_h)
        assert r.status_code == 200, f"{path} failed: {r.status_code}"


# ============ Enhanced Dashboard /stats ============

def test_dashboard_stats_shape(founder_h):
    r = requests.get(f"{API}/dashboard/stats", headers=founder_h)
    assert r.status_code == 200
    b = r.json()
    # 9 KPIs
    assert isinstance(b.get("kpis"), list) and len(b["kpis"]) == 9
    expected_keys = {"revenue", "revenue_today", "revenue_week", "bookings",
                     "bookings_today", "active_bookings", "customers", "vehicles", "vendors"}
    assert {k["key"] for k in b["kpis"]} == expected_keys
    # New widgets
    assert "vendor_perf" in b and isinstance(b["vendor_perf"], list)
    assert "company_health" in b
    ch = b["company_health"]
    assert "score" in ch and "signals" in ch and "flags" in ch
    assert "system_status" in b
    ss = b["system_status"]
    assert len(ss["services"]) == 5
    assert "recent_notifications" in b


# ============ Marketplace ============

def test_marketplace_dashboard(founder_h):
    r = requests.get(f"{API}/marketplace/dashboard", headers=founder_h)
    assert r.status_code == 200
    body = r.json()
    assert "totals" in body
    for k in ("vehicles", "vendors", "customers", "cities", "bookings"):
        assert k in body["totals"]


def test_marketplace_list_endpoints(founder_h):
    for path in ("cities", "vendors", "vehicles", "customers", "pricing", "coupons", "reviews",
                 "bookings", "kyc", "support"):
        r = requests.get(f"{API}/marketplace/{path}", headers=founder_h)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        assert isinstance(r.json(), list)


def test_marketplace_seeded_counts(founder_h):
    r = requests.get(f"{API}/marketplace/vendors", headers=founder_h)
    assert len(r.json()) >= 5, f"expected >=5 vendors, got {len(r.json())}"
    r2 = requests.get(f"{API}/marketplace/bookings", headers=founder_h)
    assert len(r2.json()) >= 30, f"expected many seeded bookings, got {len(r2.json())}"


def test_marketplace_analytics(founder_h):
    r = requests.get(f"{API}/marketplace/analytics", headers=founder_h)
    assert r.status_code == 200
    b = r.json()
    assert "by_city" in b and "by_status" in b and "top_vendors" in b


@pytest.fixture(scope="module")
def new_vendor(founder_h):
    payload = {
        "name": f"TEST_Vendor_{uuid.uuid4().hex[:6]}",
        "contact_name": "QA Bot",
        "email": f"qa_{uuid.uuid4().hex[:6]}@wavygo.in",
        "phone": "+919000000000",
        "city": "Patna",
        "kyc_status": "pending",
        "active": True,
        "rating": 4.7,
    }
    r = requests.post(f"{API}/marketplace/vendors", json=payload, headers=founder_h)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == payload["name"]
    assert "id" in data
    return data


def test_vendor_create_persists(founder_h, new_vendor):
    r = requests.get(f"{API}/marketplace/vendors/{new_vendor['id']}", headers=founder_h)
    assert r.status_code == 200
    assert r.json()["name"] == new_vendor["name"]


def test_vendor_list_includes_new(founder_h, new_vendor):
    r = requests.get(f"{API}/marketplace/vendors", headers=founder_h)
    ids = [v["id"] for v in r.json()]
    assert new_vendor["id"] in ids


def test_kyc_create_and_approve_cascades(founder_h, new_vendor):
    # Create a kyc request for the new vendor
    payload = {
        "subject_type": "vendor",
        "subject_id": new_vendor["id"],
        "subject_name": new_vendor["name"],
        "doc_type": "gst",
        "status": "pending",
    }
    r = requests.post(f"{API}/marketplace/kyc", json=payload, headers=founder_h)
    assert r.status_code == 201, r.text
    kyc = r.json()

    # Approve
    r2 = requests.patch(f"{API}/marketplace/kyc/{kyc['id']}",
                        json={"status": "approved"}, headers=founder_h)
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"

    # Verify cascade to vendor
    r3 = requests.get(f"{API}/marketplace/vendors/{new_vendor['id']}", headers=founder_h)
    assert r3.status_code == 200
    assert r3.json().get("kyc_status") == "approved", "vendor kyc_status did not cascade"


def test_booking_status_transition(founder_h):
    # Grab a booking to transition
    r = requests.get(f"{API}/marketplace/bookings?status=pending&limit=5", headers=founder_h)
    if r.status_code == 200 and r.json():
        booking_id = r.json()[0]["id"]
    else:
        # find any booking
        r = requests.get(f"{API}/marketplace/bookings?limit=1", headers=founder_h)
        assert r.status_code == 200 and r.json(), "no bookings seeded"
        booking_id = r.json()[0]["id"]

    for status in ("confirmed", "active", "completed"):
        rp = requests.patch(f"{API}/marketplace/bookings/{booking_id}/status",
                            json={"status": status}, headers=founder_h)
        assert rp.status_code == 200, f"{status}: {rp.text}"
        assert rp.json()["status"] == status


# ============ Tasks ============

def test_tasks_stats(founder_h):
    r = requests.get(f"{API}/tasks/stats/overview", headers=founder_h)
    assert r.status_code == 200
    b = r.json()
    for k in ("todo", "in_progress", "review", "completed", "cancelled", "mine"):
        assert k in b


def test_tasks_list_columns(founder_h):
    r = requests.get(f"{API}/tasks", headers=founder_h)
    assert r.status_code == 200
    assert isinstance(r.json(), list) and len(r.json()) > 0


@pytest.fixture(scope="module")
def new_task(founder_h, employee_user):
    payload = {
        "title": f"TEST_task_{uuid.uuid4().hex[:6]}",
        "description": "Automated pytest task",
        "status": "todo",
        "priority": "high",
        "assignee_id": employee_user["id"],
        "module": "General",
    }
    r = requests.post(f"{API}/tasks", json=payload, headers=founder_h)
    assert r.status_code == 201, r.text
    return r.json()


def test_task_created_and_in_column(founder_h, new_task):
    r = requests.get(f"{API}/tasks?status=todo", headers=founder_h)
    assert new_task["id"] in [t["id"] for t in r.json()]


def test_task_status_transition(founder_h, new_task):
    r = requests.patch(f"{API}/tasks/{new_task['id']}/status",
                       json={"status": "in_progress"}, headers=founder_h)
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


def test_task_comment(founder_h, new_task):
    r = requests.post(f"{API}/tasks/{new_task['id']}/comments",
                      json={"body": "pytest comment"}, headers=founder_h)
    assert r.status_code == 201
    assert r.json()["body"] == "pytest comment"
    # Verify persisted
    r2 = requests.get(f"{API}/tasks/{new_task['id']}", headers=founder_h)
    assert r2.status_code == 200
    assert any(c["body"] == "pytest comment" for c in r2.json().get("comments", []))


def test_task_assignee_receives_notification(employee_h, new_task):
    # employee (assignee) should have a notification about being assigned
    r = requests.get(f"{API}/notifications", headers=employee_h)
    assert r.status_code == 200
    titles = [n.get("title", "") for n in r.json()]
    assert any("assigned" in t.lower() or "task" in t.lower() for t in titles), \
        f"employee did not get task-assigned notification. titles={titles[:5]}"


# ============ Employees ============

def test_employees_stats(founder_h):
    r = requests.get(f"{API}/employees/stats/overview", headers=founder_h)
    assert r.status_code == 200
    b = r.json()
    for k in ("total", "online", "by_role", "pending_leave", "departments"):
        assert k in b
    assert b["total"] >= 5


def test_employees_directory(founder_h):
    r = requests.get(f"{API}/employees", headers=founder_h)
    assert r.status_code == 200
    assert len(r.json()) >= 5


def test_employees_departments(founder_h):
    r = requests.get(f"{API}/employees/departments/list", headers=founder_h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_employees_attendance_and_leave_list(founder_h):
    r = requests.get(f"{API}/employees/attendance/records", headers=founder_h)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/employees/leave/requests", headers=founder_h)
    assert r2.status_code == 200
    r3 = requests.get(f"{API}/employees/performance/reviews", headers=founder_h)
    assert r3.status_code == 200


def test_employees_attendance_date_restriction(founder_h):
    # Past date should fail
    past_payload = {"employee_id": "60d0fe4f5311236168a109ca", "date": "2020-01-01", "status": "present"}
    r_past = requests.post(f"{API}/employees/attendance/records", json=past_payload, headers=founder_h)
    assert r_past.status_code == 400

    # Future date should fail
    future_payload = {"employee_id": "60d0fe4f5311236168a109ca", "date": "2099-12-31", "status": "present"}
    r_future = requests.post(f"{API}/employees/attendance/records", json=future_payload, headers=founder_h)
    assert r_future.status_code == 400


def test_employees_invite_intern_forbidden(intern_h):
    payload = {"email": f"junk_{uuid.uuid4().hex[:6]}@wavygo.in",
               "name": "Should Fail", "role": "Employee"}
    r = requests.post(f"{API}/employees/invite", json=payload, headers=intern_h)
    assert r.status_code == 403


def test_employees_invite_by_founder(founder_h):
    email = f"test_{uuid.uuid4().hex[:8]}@wavygo.in"
    payload = {"email": email, "name": "TEST Invitee", "role": "Employee",
               "designation": "QA", "department": "Engineering"}
    r = requests.post(f"{API}/employees/invite", json=payload, headers=founder_h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == email
    assert body["role"] == "Employee"
    assert "token" in body
    token = body["token"]

    # Accept invitation
    r_accept = requests.post(f"{API}/employees/accept-invite", json={"token": token, "password": "Wavygo@2026"})
    assert r_accept.status_code == 200, r_accept.text

    # Verify login with new user after acceptance
    d = _login(email, "Wavygo@2026")
    assert d["user"]["email"] == email


def test_employees_leave_workflow_notifies_requester(founder_h, employee_h, employee_user):
    # Employee creates a leave request
    payload = {"employee_id": employee_user["id"], "from_date": "2026-02-01",
               "to_date": "2026-02-03", "kind": "casual", "reason": "pytest"}
    r = requests.post(f"{API}/employees/leave/requests", json=payload, headers=employee_h)
    assert r.status_code == 201, r.text
    leave = r.json()
    # Founder approves
    r2 = requests.patch(f"{API}/employees/leave/requests/{leave['id']}",
                        json={"status": "approved"}, headers=founder_h)
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"
    # Employee should have a notification
    time.sleep(0.5)
    r3 = requests.get(f"{API}/notifications", headers=employee_h)
    assert r3.status_code == 200
    titles = [n.get("title", "").lower() for n in r3.json()]
    assert any("leave" in t for t in titles), f"no leave notification. titles={titles[:5]}"


# ============ Opportunities ============

def test_opp_stats(founder_h):
    r = requests.get(f"{API}/opportunities/stats/overview", headers=founder_h)
    assert r.status_code == 200
    b = r.json()
    for k in ("open", "assigned", "in_progress", "won", "lost", "mine"):
        assert k in b


def test_opp_create_and_assign_notifies(founder_h, employee_h, employee_user):
    payload = {
        "title": f"TEST_opp_{uuid.uuid4().hex[:6]}",
        "type": "Grant",
        "description": "pytest opp",
        "value_lakhs": 12.5,
        "deadline": "2026-06-30",
        "status": "open",
    }
    r = requests.post(f"{API}/opportunities", json=payload, headers=founder_h)
    assert r.status_code == 201, r.text
    opp = r.json()
    assert opp["title"] == payload["title"]

    r2 = requests.post(f"{API}/opportunities/{opp['id']}/assign",
                       json={"assignee_id": employee_user["id"]}, headers=founder_h)
    assert r2.status_code == 200
    assert r2.json()["assignee_id"] == employee_user["id"]
    assert r2.json()["status"] == "assigned"

    # Verify notification for employee
    time.sleep(0.5)
    r3 = requests.get(f"{API}/notifications", headers=employee_h)
    assert r3.status_code == 200
    titles = " | ".join(n.get("title", "") for n in r3.json()[:10]).lower()
    assert "opportunity" in titles, f"no opportunity notification: {titles}"


# ============ WavyGo Connect ============

def test_connect_channels_list(founder_h):
    r = requests.get(f"{API}/connect/channels", headers=founder_h)
    assert r.status_code == 200
    channels = r.json()
    assert len(channels) >= 5
    names = {c["name"] for c in channels}
    # spec expects: announcements, general, operations, product, founders
    expected = {"announcements", "general", "operations", "product", "founders"}
    missing = expected - {n.lower() for n in names}
    assert not missing, f"missing seeded channels: {missing}. Got: {names}"


def test_connect_general_channel_messages(founder_h):
    r = requests.get(f"{API}/connect/channels", headers=founder_h)
    general = next((c for c in r.json() if c["name"].lower() == "general"), None)
    assert general
    r2 = requests.get(f"{API}/connect/channels/{general['id']}/messages", headers=founder_h)
    assert r2.status_code == 200

    body_text = f"pytest_msg_{uuid.uuid4().hex[:6]}"
    r3 = requests.post(f"{API}/connect/channels/{general['id']}/messages",
                       json={"body": body_text}, headers=founder_h)
    assert r3.status_code == 201, r3.text
    assert r3.json()["body"] == body_text

    r4 = requests.get(f"{API}/connect/channels/{general['id']}/messages", headers=founder_h)
    assert body_text in [m["body"] for m in r4.json()]


def test_connect_dm_open(founder_h, employee_user):
    r = requests.post(f"{API}/connect/dm/{employee_user['id']}", headers=founder_h)
    assert r.status_code in (200, 201), r.text
    dm = r.json()
    assert dm["kind"] == "dm"
    # idempotent — same DM returned on second call
    r2 = requests.post(f"{API}/connect/dm/{employee_user['id']}", headers=founder_h)
    assert r2.status_code in (200, 201)
    assert r2.json()["id"] == dm["id"]


def test_connect_dm_users_department_and_high_designation(employee_h):
    r = requests.get(f"{API}/connect/dm-users", headers=employee_h)
    assert r.status_code == 200, r.text
    users = r.json()
    assert len(users) >= 1
    me = requests.get(f"{API}/auth/me", headers=employee_h).json()
    emp_dept = (me.get("department") or "").strip().lower()
    for u in users:
        u_dept = (u.get("department") or "").strip().lower()
        is_same_dept = bool(emp_dept) and bool(u_dept) and (emp_dept == u_dept)
        is_high = u.get("role") in ("Founder", "Admin", "Manager") or any(
            k in (u.get("designation") or "").lower()
            for k in ["founder", "ceo", "cto", "coo", "cfo", "director", "head", "manager", "lead", "chief"]
        )
        assert is_same_dept or is_high, f"User {u['name']} (role={u['role']}, dept={u.get('department')}) should not be visible to employee in {emp_dept}"


# ============ Activity trail integration ============

def test_activity_captures_task_and_opp(founder_h):
    # Create a task, then verify activity feed includes recent Task Board entry
    payload = {"title": f"TEST_activity_{uuid.uuid4().hex[:5]}", "priority": "low"}
    r = requests.post(f"{API}/tasks", json=payload, headers=founder_h)
    assert r.status_code == 201
    time.sleep(0.4)
    a = requests.get(f"{API}/activity", headers=founder_h)
    assert a.status_code == 200
    modules = {row.get("module") for row in a.json()[:50]}
    assert "Task Board" in modules, f"Task Board not in activity modules: {modules}"
