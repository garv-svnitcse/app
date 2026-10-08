from __future__ import annotations
"""RBAC (v3) backend gate tests for WavyGo OS.

Covers: login for 5 roles, password policy, reset-password, marketplace gate,
task/opportunity/connect/activity gates, register gating, dashboard shape.
"""
# pyrefly: ignore [missing-import]
import pytest
import requests

# End-to-end suite against a running deployment. Opt in by pointing WAVYGO_E2E_URL at it
# (e.g. a staging backend); without it the suite is skipped so CI never hits production.
# Credentials come from the environment (FOUNDER_EMAIL / FOUNDER_PASSWORD, see e2e_accounts.py).
from e2e_accounts import API, E2E_SKIP, FOUNDER, ADMIN, MANAGER, EMPLOYEE, INTERN  # noqa: E402

pytestmark = E2E_SKIP
CREDS = {role: (c["email"], c["password"]) for role, c in
         (("Founder", FOUNDER), ("Admin", ADMIN), ("Manager", MANAGER), ("Employee", EMPLOYEE), ("Intern", INTERN))}
# Password for throwaway users this suite tries to register; not a real account's password.
NEW_USER_PASSWORD = "E2e-NewUser@2026"


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
                          json={"current_password": CREDS[role][1], "new_password": CREDS[role][1]})
        assert r.status_code == 403, f"{role} change_password expected 403 got {r.status_code}: {r.text}"

    # Manager -> 200
    r = requests.post(f"{API}/users/me/password",
                      headers=H(tokens, "Manager"),
                      json={"current_password": MANAGER["password"], "new_password": MANAGER["password"]})
    assert r.status_code == 200, f"Manager change_password expected 200 got {r.status_code}: {r.text}"


# ---------------- Reset password ----------------
def test_reset_password_endpoint(tokens):
    # Find an employee id (self of Employee)
    emp_id = tokens["Employee"]["user"].get("id")
    assert emp_id, "employee id missing from login response"

    # Founder -> 200 with temp_password
    r = requests.post(f"{API}/employees/{emp_id}/reset-password", headers=H(tokens, "Founder"))
    assert r.status_code == 200, f"Founder reset expected 200 got {r.status_code}: {r.text}"
    assert "temp_password" in r.json(), f"missing temp_password: {r.json()}"

    # Admin -> 200
    r = requests.post(f"{API}/employees/{emp_id}/reset-password", headers=H(tokens, "Admin"))
    assert r.status_code == 200, f"Admin reset expected 200 got {r.status_code}"
    temp_pwd = r.json().get("temp_password")
    assert temp_pwd

    # Manager/Employee/Intern -> 403
    for role in ("Manager", "Employee", "Intern"):
        r = requests.post(f"{API}/employees/{emp_id}/reset-password", headers=H(tokens, role))
        assert r.status_code == 403, f"{role} reset expected 403 got {r.status_code}"

    # Restore employee password so subsequent tests keep working
    requests.post(f"{API}/auth/login", json={"email": CREDS["Employee"][0], "password": temp_pwd})
    # Founder resets to make it deterministic; then we re-login via seed default won't work.
    # Instead, re-login employee with temp_pwd and self-change is 403; so use admin reset again — 
    # this leaves a random temp_password. Re-login employee & refresh token for downstream tests.
    r2 = requests.post(f"{API}/auth/login", json={"email": CREDS["Employee"][0], "password": temp_pwd}, timeout=15)
    assert r2.status_code == 200, f"post-reset employee login failed: {r2.status_code} {r2.text}"
    new_tok = r2.json().get("access_token") or r2.json().get("token")
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
                          json={"email": f"test_reg_{role}@wavygo.in", "password": NEW_USER_PASSWORD,
                                "name": "X", "role": "Employee"})
        assert r.status_code == 403, f"{role} register expected 403 got {r.status_code}: {r.text}"

    # Admin cannot create Admin
    r = requests.post(f"{API}/auth/register", headers=H(tokens, "Admin"),
                      json={"email": "test_admin_by_admin@wavygo.in", "password": NEW_USER_PASSWORD,
                            "name": "X", "role": "Admin"})
    assert r.status_code == 403, f"Admin creating Admin expected 403 got {r.status_code}: {r.text}"

    # Admin cannot create Founder
    r = requests.post(f"{API}/auth/register", headers=H(tokens, "Admin"),
                      json={"email": "test_founder_by_admin@wavygo.in", "password": NEW_USER_PASSWORD,
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
    assert r.status_code == 403, f"Admin invite Founder expected 403 got {r.status_code}: {r.text}"

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
