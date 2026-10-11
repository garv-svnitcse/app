from __future__ import annotations
"""RBAC (v3) backend gate tests for WavyGo OS.

Covers: login for 5 roles, password policy, reset-password, marketplace gate,
task/opportunity/connect/activity gates, register gating, dashboard shape.
"""
import os
# pyrefly: ignore [missing-import]
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE_URL}/api"

TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "Wavygo@2026")

CREDS = {
    "Founder": (
        os.environ.get("FOUNDER_EMAIL", "founder@wavygo.in"),
        os.environ.get("FOUNDER_PASSWORD", TEST_PASSWORD),
    ),
    "Admin": (
        os.environ.get("ADMIN_EMAIL", "admin@wavygo.in"),
        os.environ.get("ADMIN_PASSWORD", TEST_PASSWORD),
    ),
    "Manager": (
        os.environ.get("MANAGER_EMAIL", "manager@wavygo.in"),
        os.environ.get("MANAGER_PASSWORD", TEST_PASSWORD),
    ),
    "Employee": (
        os.environ.get("EMPLOYEE_EMAIL", "employee@wavygo.in"),
        os.environ.get("EMPLOYEE_PASSWORD", TEST_PASSWORD),
    ),
    "Intern": (
        os.environ.get("INTERN_EMAIL", "intern@wavygo.in"),
        os.environ.get("INTERN_PASSWORD", TEST_PASSWORD),
    ),
}

def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


@pytest.fixture(scope="module")
def tokens():
    out = {}
    for role, (email, pwd) in CREDS.items():
        r = _login(email, pwd)
        assert r.status_code == 200, f"login failed for {role}: {r.status_code} {r.text}"
        data = r.json()
        tok = data.get("access_token") or data.get("token")
        assert tok, f"no token for {role}: {data}"
        out[role] = {"token": tok, "user": data.get("user", {})}
    return out


def H(tokens, role):
    return {"Authorization": f"Bearer {tokens[role]['token']}"}


# ---------------- Login sanity ----------------
def test_login_all_roles(tokens):
    for role in CREDS:
        assert tokens[role]["token"]
        assert tokens[role]["user"].get("role") == role, f"{role} user.role mismatch: {tokens[role]['user']}"


# ---------------- Password policy ----------------
def test_change_own_password_gates(tokens):
    # Employee/Intern -> 403
    for role in ("Employee", "Intern"):
        r = requests.post(f"{API}/users/me/password",
                          headers=H(tokens, role),
                          json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD})
        assert r.status_code == 403, f"{role} change_password expected 403 got {r.status_code}: {r.text}"

    # Manager -> 200
    r = requests.post(f"{API}/users/me/password",
                      headers=H(tokens, "Manager"),
                      json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD})
    assert r.status_code == 200, f"Manager change_password expected 200 got {r.status_code}: {r.text}"

# ---------------- Reset password ----------------
def test_reset_password_endpoint(tokens):
    # Find an employee id
    emp_id = tokens["Employee"]["user"].get("id")
    assert emp_id, "employee id missing from login response"

    employee_email = CREDS["Employee"][0]

    # Founder -> 200 with temporary password
    r = requests.post(
        f"{API}/employees/{emp_id}/reset-password",
        headers=H(tokens, "Founder"),
        timeout=15,
    )
    assert r.status_code == 200, (
        f"Founder reset expected 200 got {r.status_code}: {r.text}"
    )
    assert r.json().get("temp_password")

    # Admin -> 200, explicitly set the expected test password.
    # This keeps subsequent test runs deterministic.
    r = requests.post(
        f"{API}/employees/{emp_id}/reset-password",
        headers=H(tokens, "Admin"),
        json={"new_password": TEST_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, (
        f"Admin reset expected 200 got {r.status_code}: {r.text}"
    )
    assert r.json().get("temp_password") == TEST_PASSWORD

    # Manager/Employee/Intern -> 403
    for role in ("Manager", "Employee", "Intern"):
        r = requests.post(
            f"{API}/employees/{emp_id}/reset-password",
            headers=H(tokens, role),
            timeout=15,
        )
        assert r.status_code == 403, (
            f"{role} reset expected 403 got {r.status_code}: {r.text}"
        )

    # Verify Employee can log in with the restored test password.
    r = requests.post(
        f"{API}/auth/login",
        json={"email": employee_email, "password": TEST_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, (
        f"Employee login after password restoration failed: "
        f"{r.status_code} {r.text}"
    )

    new_tok = r.json().get("access_token") or r.json().get("token")
    assert new_tok, "Employee login did not return an access token"
    tokens["Employee"]["token"] = new_tok

# ---------------- Marketplace ----------------
def test_marketplace_founder_only(tokens):
    r = requests.get(f"{API}/marketplace/cities", headers=H(tokens, "Founder"))
    assert r.status_code == 200, f"Founder marketplace expected 200 got {r.status_code}"

    for role in ("Admin", "Manager", "Employee", "Intern"):
        r = requests.get(f"{API}/marketplace/cities", headers=H(tokens, role))
        assert r.status_code == 403, f"{role} marketplace expected 403 got {r.status_code}"


# ---------------- Tasks ----------------
def test_tasks_gates(tokens):
    # Intern POST /tasks -> 403
    r = requests.post(f"{API}/tasks", headers=H(tokens, "Intern"),
                      json={"title": "TEST_intern_task", "status": "todo"})
    assert r.status_code == 403, f"Intern task create expected 403 got {r.status_code}: {r.text}"

    # Employee POST /tasks -> 201
    r = requests.post(f"{API}/tasks", headers=H(tokens, "Employee"),
                      json={"title": "TEST_emp_task_rbac", "status": "todo"})
    assert r.status_code in (200, 201), f"Employee task create expected 201 got {r.status_code}: {r.text}"
    task_id = r.json().get("id")

    # DELETE /tasks/{id} — Manager/Employee/Intern -> 403
    if task_id:
        for role in ("Manager", "Employee", "Intern"):
            rd = requests.delete(f"{API}/tasks/{task_id}", headers=H(tokens, role))
            assert rd.status_code == 403, f"{role} task delete expected 403 got {rd.status_code}"
        # Founder -> 200/204
        rd = requests.delete(f"{API}/tasks/{task_id}", headers=H(tokens, "Founder"))
        assert rd.status_code in (200, 204), f"Founder delete task expected 2xx got {rd.status_code}"


# ---------------- Opportunities ----------------
def test_opportunities_gates(tokens):
    # Intern GET -> 403
    r = requests.get(f"{API}/opportunities", headers=H(tokens, "Intern"))
    assert r.status_code == 403, f"Intern opps GET expected 403 got {r.status_code}"

    # Employee GET -> 200
    r = requests.get(f"{API}/opportunities", headers=H(tokens, "Employee"))
    assert r.status_code == 200, f"Employee opps GET expected 200 got {r.status_code}"

    # Founder creates one
    r = requests.post(f"{API}/opportunities", headers=H(tokens, "Founder"),
                      json={"title": "TEST_opp_rbac", "type": "Grant"})
    assert r.status_code in (200, 201), f"Founder opp create failed {r.status_code}: {r.text}"
    opp_id = r.json().get("id")

    if opp_id:
        # Delete by Admin -> 403
        rd = requests.delete(f"{API}/opportunities/{opp_id}", headers=H(tokens, "Admin"))
        assert rd.status_code == 403, f"Admin opp delete expected 403 got {rd.status_code}"
        # Delete by Founder -> ok
        rd = requests.delete(f"{API}/opportunities/{opp_id}", headers=H(tokens, "Founder"))
        assert rd.status_code in (200, 204), f"Founder opp delete expected 2xx got {rd.status_code}"


# ---------------- Connect ----------------
def test_connect_channel_gates(tokens):
    # Employee POST /connect/channels -> 403
    r = requests.post(f"{API}/connect/channels", headers=H(tokens, "Employee"),
                      json={"name": "TEST_emp_channel", "kind": "channel"})
    assert r.status_code == 403, f"Employee create channel expected 403 got {r.status_code}: {r.text}"

    # Manager POST /connect/channels -> 201
    r = requests.post(f"{API}/connect/channels", headers=H(tokens, "Manager"),
                      json={"name": "TEST_mgr_channel_rbac", "kind": "channel"})
    assert r.status_code in (200, 201), f"Manager create channel expected 201 got {r.status_code}: {r.text}"

    # Manager creating announcement channel -> 403
    r = requests.post(f"{API}/connect/channels", headers=H(tokens, "Manager"),
                      json={"name": "TEST_mgr_ann", "kind": "announcement"})
    assert r.status_code == 403, f"Manager announcement create expected 403 got {r.status_code}: {r.text}"


# ---------------- Activity ----------------
def test_activity_gates(tokens):
    for role in ("Employee", "Intern"):
        r = requests.get(f"{API}/activity", headers=H(tokens, role))
        assert r.status_code == 403, f"{role} activity expected 403 got {r.status_code}"
    for role in ("Founder", "Admin", "Manager"):
        r = requests.get(f"{API}/activity", headers=H(tokens, role))
        assert r.status_code == 200, f"{role} activity expected 200 got {r.status_code}"


# ---------------- Auth register gating ----------------
def test_register_gating(tokens):
    # Employee/Intern -> 403
    for role in ("Employee", "Intern", "Manager"):
        r = requests.post(f"{API}/auth/register", headers=H(tokens, role),
                          json={"email": f"test_reg_{role}@wavygo.in", "password": TEST_PASSWORD,
                                "name": "X", "role": "Employee"})
        assert r.status_code == 403, f"{role} register expected 403 got {r.status_code}: {r.text}"

    # Admin cannot create Admin
    r = requests.post(f"{API}/auth/register", headers=H(tokens, "Admin"),
                      json={"email": "test_admin_by_admin@wavygo.in", "password": TEST_PASSWORD,
                            "name": "X", "role": "Admin"})
    assert r.status_code == 403, f"Admin creating Admin expected 403 got {r.status_code}: {r.text}"

    # Admin cannot create Founder
    r = requests.post(f"{API}/auth/register", headers=H(tokens, "Admin"),
                      json={"email": "test_founder_by_admin@wavygo.in", "password": TEST_PASSWORD,
                            "name": "X", "role": "Founder"})
    assert r.status_code == 403, f"Admin creating Founder expected 403 got {r.status_code}: {r.text}"


# ---------------- Employees invite ----------------
def test_employees_invite_gates(tokens):
    r = requests.post(f"{API}/employees/invite", headers=H(tokens, "Manager"),
                      json={"email": "test_inv_by_mgr@wavygo.in", "name": "X", "role": "Employee"})
    assert r.status_code == 403, f"Manager invite expected 403 got {r.status_code}: {r.text}"

    # Admin cannot invite Founder
    r = requests.post(f"{API}/employees/invite", headers=H(tokens, "Admin"),
                      json={"email": "test_founder_inv@wavygo.in", "name": "X", "role": "Founder"})
    assert r.status_code == 400, f"Admin invite Founder expected 400 got {r.status_code}: {r.text}"
    # Admin cannot invite Admin
    r = requests.post(f"{API}/employees/invite", headers=H(tokens, "Admin"),
                      json={"email": "test_admin_inv@wavygo.in", "name": "X", "role": "Admin"})
    assert r.status_code == 403, f"Admin invite Admin expected 403 got {r.status_code}: {r.text}"


# ---------------- Dashboard shape for Employee/Intern ----------------
def test_dashboard_employee_intern_shape(tokens):
    expected_keys = {"kpis", "cities", "tasks_today", "opportunities", "recent_notifications", "vendor_perf"}
    for role in ("Employee", "Intern"):
        r = requests.get(f"{API}/dashboard/stats", headers=H(tokens, role))
        assert r.status_code == 200, f"{role} dashboard expected 200 got {r.status_code}: {r.text}"
        data = r.json()
        missing = expected_keys - set(data.keys())
        assert not missing, f"{role} dashboard missing keys: {missing}. Got keys: {list(data.keys())}"


# ---------------- Employees list gates ----------------
def test_employees_directory_gate(tokens):
    # Employees list - directory access
    r = requests.get(f"{API}/employees", headers=H(tokens, "Founder"))
    assert r.status_code == 200
    r = requests.get(f"{API}/employees", headers=H(tokens, "Employee"))
    # Employee should either 403 or see only self
    assert r.status_code in (200, 403), f"Employee /employees got {r.status_code}"
