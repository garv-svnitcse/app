from __future__ import annotations
"""Employees API tests — invitations (no takeover, expiry, placeholders), profile edit
rules, attendance marking + one-click check-in/out, leave approval workflow,
performance reviews, departments and stats.

Runs against an isolated server and throwaway database (see local_harness.py).
Email is disabled (BREVO_API_KEY unset), so nothing is ever sent.
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests
from bson import ObjectId

from local_harness import api, mongo, test_db, users, harness_env, call, TEST_PASSWORD  # noqa: F401

from auth_utils import verify_password


@pytest.fixture(scope="module")
def harness_env():
    return {"BREVO_API_KEY": "", "BREVO_SENDER_EMAIL": ""}


def _today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def _email():
    return f"invitee.{uuid.uuid4().hex[:8]}@harness.wavygo.in"


@pytest.fixture(scope="module")
def depts(api, users):
    for name in ("Tech", "Sales"):
        r = call(api, users["founder"], "POST", "/employees/departments/list", json={"name": name})
        assert r.status_code == 201, r.text
    return ("Tech", "Sales")


def _invite(api, user, **fields):
    body = {"email": _email(), "name": "Invitee", "role": "Employee", **fields}
    return call(api, user, "POST", "/employees/invite", json=body)


def _login(api, email, password):
    return requests.post(f"{api}/auth/login", json={"email": email, "password": password}, timeout=15)


# ------------------------- invitations -------------------------

def test_invite_and_accept_flow(api, users, depts, test_db):
    email = _email()
    aadhaar_document_id = ObjectId()
    offer_letter_document_id = ObjectId()
    other_document_id = ObjectId()
    for document_id, title in (
        (aadhaar_document_id, "Aadhaar document"),
        (offer_letter_document_id, "Offer letter"),
        (other_document_id, "Other employee document"),
    ):
        test_db.vault_documents.insert_one({
            "_id": document_id,
            "title": title,
            "access": {"mode": "restricted", "roles": ["Founder", "Admin"]},
            "access_keys": ["role:Founder", "role:Admin"],
        })
    r = _invite(
        api,
        users["founder"],
        email=email,
        name="Invitee Example",
        department="tech",
        phone="+91 9876543210",
        joining_date="2026-10-15",
        aadhaar_number="1234 5678 9012",
        aadhaar_document_id=str(aadhaar_document_id),
        aadhaar_document_name="aadhaar.pdf",
        offer_letter_document_id=str(offer_letter_document_id),
        offer_letter_document_name="offer-letter.pdf",
        employee_documents=[{"id": str(other_document_id), "name": "certificate.pdf"}],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"] and body["email"] == email and body["role"] == "Employee"
    assert body["department"] == "Tech"  # canonical department name
    assert body["phone"] == "+91 9876543210"
    assert body["joining_date"] == "2026-10-15"
    assert body["aadhaar_number"] == "1234 5678 9012"
    assert body["aadhaar_document_id"] == str(aadhaar_document_id)
    assert body["offer_letter_document_id"] == str(offer_letter_document_id)
    assert body["employee_documents"] == [{"id": str(other_document_id), "name": "certificate.pdf"}]
    assert body["email_queued"] is False and "share the link" in body["message"]
    assert body["expires_at"]

    # Placeholder is hidden from the directory, stats and headcount.
    names = [u["email"] for u in call(api, users["founder"], "GET", "/employees").json()]
    assert email not in names
    tech = [d for d in call(api, users["founder"], "GET", "/employees/departments/list").json() if d["name"] == "Tech"][0]
    assert tech["headcount"] == test_db.users.count_documents({"department": "Tech", "password_hash": {"$nin": ["", None]}})

    r = requests.post(f"{api}/employees/accept-invite", json={"token": body["token"], "password": "short7!"})
    assert r.status_code == 400
    r = requests.post(f"{api}/employees/accept-invite", json={"token": body["token"], "password": "Wavygo@2026"})
    assert r.status_code == 200, r.text
    assert _login(api, email, "Wavygo@2026").status_code == 200
    employees = call(api, users["founder"], "GET", "/employees").json()
    invited = next(employee for employee in employees if employee["email"] == email)
    assert invited["name"] == "Invitee Example"
    assert invited["phone"] == "+91 9876543210"
    assert invited["joining_date"] == "2026-10-15"
    assert invited["aadhaar_number"] == "1234 5678 9012"
    assert invited["aadhaar_document_id"] == str(aadhaar_document_id)
    assert invited["offer_letter_document_id"] == str(offer_letter_document_id)
    assert invited["employee_documents"] == [{"id": str(other_document_id), "name": "certificate.pdf"}]
    manager_employee = next(
        employee
        for employee in call(api, users["manager"], "GET", "/employees").json()
        if employee["email"] == email
    )
    assert "aadhaar_number" not in manager_employee
    assert "aadhaar_document_id" not in manager_employee
    assert "offer_letter_document_id" not in manager_employee
    assert "employee_documents" not in manager_employee


def test_invite_refuses_existing_accounts(api, users, test_db):
    r = _invite(api, users["founder"], email=users["employee"]["email"].upper())
    assert r.status_code == 409
    deactivated = _email()
    test_db.users.insert_one({"email": deactivated, "name": "Old", "role": "Intern", "department": "Sales",
                              "password_hash": "x", "status": "deactivated", "is_active": False})
    r = _invite(api, users["founder"], email=deactivated, role="Manager")
    assert r.status_code == 409
    assert test_db.users.find_one({"email": deactivated})["role"] == "Intern"


def test_invite_role_matrix(api, users):
    assert _invite(api, users["admin"], role="Admin").status_code == 403
    assert _invite(api, users["admin"], phone="123").status_code == 403
    assert _invite(api, users["founder"], role="Founder").status_code == 403
    assert _invite(api, users["manager"]).status_code == 403
    assert _invite(api, users["founder"], department="Nowhere").status_code == 400


def test_accept_cannot_take_over_existing_account(api, users, test_db):
    # A stray pending invitation for the Founder's email must never overwrite that account.
    founder = test_db.users.find_one({"_id": ObjectId(users["founder"]["id"])})
    token = uuid.uuid4().hex
    test_db.invitations.insert_one({"token": token, "email": founder["email"], "name": "Evil", "role": "Intern",
                                    "status": "pending", "created_at": datetime.now(timezone.utc).isoformat()})
    r = requests.post(f"{api}/employees/accept-invite", json={"token": token, "password": "Hijack@2026"})
    assert r.status_code == 409
    after = test_db.users.find_one({"_id": founder["_id"]})
    assert after["role"] == "Founder" and after["name"] == founder["name"]
    assert verify_password(TEST_PASSWORD, after["password_hash"])


def test_expired_invitation_rejected(api, users, test_db):
    r = _invite(api, users["founder"])
    token = r.json()["token"]
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    test_db.invitations.update_one({"token": token}, {"$set": {"expires_at": past}})
    assert requests.get(f"{api}/employees/invite/{token}").status_code == 404
    r = requests.post(f"{api}/employees/accept-invite", json={"token": token, "password": "Wavygo@2026"})
    assert r.status_code == 404 and "expired" in r.json()["detail"]
    # Resending renews the link.
    inv = test_db.invitations.find_one({"token": token})
    r = call(api, users["founder"], "POST", f"/employees/invitations/{inv['_id']}/resend")
    assert r.status_code == 200 and r.json()["email_queued"] is False
    assert requests.get(f"{api}/employees/invite/{token}").status_code == 200


def test_manager_gets_no_tokens_and_delete_removes_placeholder(api, users, depts, test_db):
    email = _email()
    r = _invite(api, users["founder"], email=email, department="Tech")
    inv_id = r.json()["id"]
    rows = call(api, users["manager"], "GET", "/employees/invitations").json()
    assert rows and all("token" not in i for i in rows)
    assert call(api, users["manager"], "DELETE", f"/employees/invitations/{inv_id}").status_code == 403
    placeholder = test_db.users.find_one({"email": email})
    assert placeholder and placeholder["password_hash"] == ""
    # A placeholder cannot be activated, edited or reset.
    assert call(api, users["founder"], "PATCH", f"/employees/{placeholder['_id']}/status",
                json={"status": "active"}).status_code == 400
    assert call(api, users["founder"], "DELETE", f"/employees/invitations/{inv_id}").status_code == 200
    assert test_db.users.find_one({"email": email}) is None


# ------------------------- profile edits -------------------------

def test_patch_rules(api, users, depts, test_db):
    emp, founder = users["employee"], users["founder"]
    # Unknown / sensitive fields are rejected outright.
    assert call(api, users["admin"], "PATCH", f"/employees/{emp['id']}", json={"password_hash": "x"}).status_code == 422
    assert call(api, users["admin"], "PATCH", f"/employees/{emp['id']}", json={"status": "active"}).status_code == 422
    # Nobody but the Founder edits the Founder.
    assert call(api, users["admin"], "PATCH", f"/employees/{founder['id']}", json={"name": "X"}).status_code == 403
    # Admins cannot edit other Admins, nor promote to Admin.
    other_admin = ObjectId()
    test_db.users.insert_one({"_id": other_admin, "email": f"a2.{other_admin}@h.in", "name": "Admin Two",
                              "role": "Admin", "password_hash": "x", "status": "active"})
    assert call(api, users["admin"], "PATCH", f"/employees/{other_admin}", json={"phone": "1"}).status_code == 403
    assert call(api, users["admin"], "PATCH", f"/employees/{emp['id']}", json={"role": "Admin"}).status_code == 403
    # Employee profile information is managed by the Founder only.
    assert call(api, users["admin"], "PATCH", f"/employees/{users['admin']['id']}", json={"phone": "999"}).status_code == 403
    assert call(api, users["admin"], "PATCH", f"/employees/{users['admin']['id']}", json={"role": "Manager"}).status_code == 403
    # Managers cannot edit employee profile information.
    mgr = users["manager"]
    assert call(api, mgr, "PATCH", f"/employees/{users['employee2']['id']}", json={"designation": "x"}).status_code == 403
    assert call(api, mgr, "PATCH", f"/employees/{emp['id']}", json={"role": "Manager"}).status_code == 403
    assert call(api, mgr, "PATCH", f"/employees/{emp['id']}", json={"department": "Sales"}).status_code == 403
    r = call(api, mgr, "PATCH", f"/employees/{emp['id']}",
             json={"designation": "Engineer", "role": "Employee", "department": "Tech"})
    assert r.status_code == 403
    assert call(api, mgr, "PATCH", f"/employees/{emp['id']}",
                json={"aadhaar_number": "1234 5678 9012"}).status_code == 403
    assert call(api, users["admin"], "PATCH", f"/employees/{emp['id']}",
                json={"joining_date": "2026-01-15", "aadhaar_number": "1234 5678 9012"}).status_code == 403
    assert call(api, users["admin"], "PATCH", f"/employees/{emp['id']}",
                json={"joining_date": "not-a-date"}).status_code == 422
    founder_update = call(
        api,
        founder,
        "PATCH",
        f"/employees/{emp['id']}",
        json={"phone": "123", "joining_date": "2026-01-15", "aadhaar_number": "1234 5678 9012"},
    )
    assert founder_update.status_code == 200
    assert founder_update.json()["phone"] == "123"
    assert founder_update.json()["joining_date"] == "2026-01-15"
    # Founder may change roles; unknown departments are refused.
    assert call(api, founder, "PATCH", f"/employees/{emp['id']}", json={"department": "Nowhere"}).status_code == 400
    r = call(api, founder, "PATCH", f"/employees/{other_admin}", json={"role": "Manager"})
    assert r.status_code == 200 and r.json()["role"] == "Manager"


def test_no_self_deactivate_or_delete(api, users):
    a = users["admin"]
    assert call(api, a, "PATCH", f"/employees/{a['id']}/status", json={"status": "deactivated"}).status_code == 400
    assert call(api, a, "DELETE", f"/employees/{a['id']}").status_code == 400


def test_search_is_escaped(api, users):
    r = call(api, users["founder"], "GET", "/employees", params={"q": "(["})
    assert r.status_code == 200 and r.json() == []


def test_manager_directory_scope(api, users):
    assert call(api, users["manager"], "GET", "/employees", params={"department": "Sales"}).status_code == 403
    rows = call(api, users["manager"], "GET", "/employees").json()
    assert rows and all(u["department"] == "Tech" for u in rows)


# ------------------------- departments -------------------------

def test_department_create_validation(api, users, depts):
    assert call(api, users["founder"], "POST", "/employees/departments/list", json={"name": "  "}).status_code == 422
    assert call(api, users["founder"], "POST", "/employees/departments/list", json={"name": "tech"}).status_code == 409
    assert call(api, users["manager"], "POST", "/employees/departments/list", json={"name": "Ops"}).status_code == 403


# ------------------------- attendance -------------------------

def test_mark_attendance_rules(api, users, test_db):
    today = _today()
    intern = users["intern"]
    r = call(api, intern, "POST", "/employees/attendance/records",
             json={"employee_id": intern["id"], "date": today, "status": "leave"})
    assert r.status_code == 403
    r = call(api, intern, "POST", "/employees/attendance/records",
             json={"employee_id": users["employee"]["id"], "date": today, "status": "present"})
    assert r.status_code == 403
    r = call(api, users["manager"], "POST", "/employees/attendance/records",
             json={"employee_id": users["employee2"]["id"], "date": today, "status": "present"})
    assert r.status_code == 403
    r = call(api, users["founder"], "POST", "/employees/attendance/records",
             json={"employee_id": str(ObjectId()), "date": today, "status": "present"})
    assert r.status_code == 404
    r = call(api, users["founder"], "POST", "/employees/attendance/records",
             json={"employee_id": "", "date": today, "status": "present"})
    assert r.status_code == 400
    r = call(api, users["founder"], "POST", "/employees/attendance/records",
             json={"employee_id": intern["id"], "date": "2020-01-01", "status": "present"})
    assert r.status_code == 400


def test_check_in_out_and_manual_mark_keeps_times(api, users, test_db):
    emp = users["employee"]
    assert call(api, emp, "POST", "/employees/attendance/check-out").status_code == 400
    r1 = call(api, emp, "POST", "/employees/attendance/check-in")
    assert r1.status_code == 200, r1.text
    rec = r1.json()
    assert rec["date"] == _today() and rec["check_in"] and rec["already_checked_in"] is False
    r2 = call(api, emp, "POST", "/employees/attendance/check-in")
    assert r2.json()["check_in"] == rec["check_in"] and r2.json()["already_checked_in"] is True

    # Manual status change by the manager keeps the check-in.
    r = call(api, users["manager"], "POST", "/employees/attendance/records",
             json={"employee_id": emp["id"], "date": _today(), "status": "wfh"})
    assert r.status_code == 201, r.text
    doc = test_db.attendance.find_one({"employee_id": emp["id"], "date": _today()})
    assert doc["status"] == "wfh" and doc["check_in"] == rec["check_in"]

    # Backdate the check-in so the duration is measurable.
    earlier = (datetime.now(timezone.utc) - timedelta(minutes=95)).isoformat()
    test_db.attendance.update_one({"_id": doc["_id"]}, {"$set": {"check_in": earlier}})
    r = call(api, emp, "POST", "/employees/attendance/check-out")
    assert r.status_code == 200 and r.json()["check_out"]
    assert 94 <= r.json()["duration_minutes"] <= 96
    rows = call(api, emp, "GET", "/employees/attendance/records").json()
    today_row = [x for x in rows if x["date"] == _today()][0]
    assert today_row["duration_minutes"] is not None and today_row["employee_name"] == emp["name"]
    assert all(x["employee_id"] == emp["id"] for x in rows)


def test_lists_survive_bad_rows(api, users, test_db):
    test_db.attendance.insert_one({"employee_id": "not-an-id", "date": "2020-01-01", "status": "present"})
    test_db.leave_requests.insert_one({"employee_id": "not-an-id", "from_date": "2020-01-01", "to_date": "2020-01-01",
                                       "status": "pending", "kind": "casual", "reason": "x", "created_at": "2020"})
    test_db.performance_reviews.insert_one({"employee_id": "bad", "period": "Q1", "score": 3, "created_at": "2020"})
    for path in ("/employees/attendance/records", "/employees/leave/requests", "/employees/performance/reviews"):
        assert call(api, users["founder"], "GET", path).status_code == 200, path


# ------------------------- leave -------------------------

def _leave(api, user, employee_id, **fields):
    body = {"employee_id": employee_id, "from_date": "2031-02-01", "to_date": "2031-02-02",
            "kind": "casual", "reason": "pytest", **fields}
    return call(api, user, "POST", "/employees/leave/requests", json=body)


def test_leave_create_validation(api, users):
    emp = users["employee"]
    r = _leave(api, emp, emp["id"], status="approved")
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert _leave(api, emp, emp["id"], from_date="2031-02-05", to_date="2031-02-01").status_code == 422
    assert _leave(api, emp, emp["id"], reason="   ").status_code == 422
    assert _leave(api, emp, users["intern"]["id"]).status_code == 403


def test_leave_notifies_department_approvers_only(api, users, test_db):
    emp = users["employee"]
    lv = _leave(api, emp, emp["id"], reason="notify-check").json()
    body = f"from {lv['from_date']}"
    notified = {n["user_id"] for n in test_db.notifications.find({"title": "Leave request", "body": {"$regex": body}})}
    assert users["manager"]["id"] in notified and users["founder"]["id"] in notified
    other_mgr = ObjectId()
    test_db.users.insert_one({"_id": other_mgr, "email": f"m2.{other_mgr}@h.in", "name": "Sales Mgr", "role": "Manager",
                              "department": "Sales", "password_hash": "x", "status": "active"})
    lv2 = _leave(api, emp, emp["id"], from_date="2031-03-01", to_date="2031-03-01").json()
    notified = {n["user_id"] for n in test_db.notifications.find({"title": "Leave request", "body": {"$regex": lv2["from_date"]}})}
    assert str(other_mgr) not in notified and emp["id"] not in notified


def test_leave_decision_workflow(api, users, test_db):
    emp, mgr = users["employee"], users["manager"]
    lv = _leave(api, emp, emp["id"], from_date="2031-04-01", to_date="2031-04-03").json()
    path = f"/employees/leave/requests/{lv['id']}"
    assert call(api, emp, "PATCH", path, json={"status": "approved"}).status_code == 403
    assert call(api, mgr, "PATCH", path, json={"status": "maybe"}).status_code == 422
    r = call(api, mgr, "PATCH", path, json={"status": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert call(api, users["founder"], "PATCH", path, json={"status": "rejected"}).status_code == 409
    assert test_db.notifications.find_one({"user_id": emp["id"], "title": "Your leave was approved"})
    assert test_db.attendance.count_documents({"employee_id": emp["id"], "status": "leave",
                                               "date": {"$in": ["2031-04-01", "2031-04-02", "2031-04-03"]}}) == 3
    assert test_db.activity_logs.find_one({"action": "Leave approved", "user_id": mgr["id"]})

    # Managers cannot decide other departments' leave, nor their own.
    other = _leave(api, users["founder"], users["employee2"]["id"]).json()
    assert call(api, mgr, "PATCH", f"/employees/leave/requests/{other['id']}", json={"status": "approved"}).status_code == 403
    own = _leave(api, mgr, mgr["id"]).json()
    assert call(api, mgr, "PATCH", f"/employees/leave/requests/{own['id']}", json={"status": "approved"}).status_code == 403
    r = call(api, users["admin"], "PATCH", f"/employees/leave/requests/{own['id']}", json={"status": "rejected"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert call(api, mgr, "PATCH", "/employees/leave/requests/bad-id", json={"status": "approved"}).status_code == 400


# ------------------------- performance + stats -------------------------

def test_performance_rules(api, users):
    mgr = users["manager"]
    body = {"employee_id": mgr["id"], "period": "Q3-2026", "score": 4}
    assert call(api, mgr, "POST", "/employees/performance/reviews", json=body).status_code == 403
    body["employee_id"] = users["employee"]["id"]
    assert call(api, mgr, "POST", "/employees/performance/reviews", json={**body, "score": 7}).status_code == 422
    assert call(api, mgr, "POST", "/employees/performance/reviews", json={**body, "score": 0}).status_code == 422
    assert call(api, mgr, "POST", "/employees/performance/reviews", json=body).status_code == 201


def test_stats_scopes(api, users):
    s = call(api, users["intern"], "GET", "/employees/stats/overview").json()
    assert s["scope"] == "self" and "total" not in s and "present_this_month" in s
    s = call(api, users["manager"], "GET", "/employees/stats/overview").json()
    assert s["scope"] == "department" and s["departments"] == 1
    assert {r["role"] for r in s["by_role"]} <= {"Manager", "Employee", "Intern"}
    s = call(api, users["founder"], "GET", "/employees/stats/overview").json()
    assert s["scope"] == "company" and "pending_invites" in s


# ------------------------- messy department names, heads, presence -------------------------

def test_departments_include_unregistered_names_and_tolerant_matching(api, users, test_db):
    from bson import ObjectId as _Oid
    marker = uuid.uuid4().hex[:6]
    test_db.departments.insert_one({"name": f"Ops{marker}"})
    base = {"status": "active", "is_active": True, "password_hash": "x", "role": "Employee"}
    test_db.users.insert_many([
        {**base, "_id": _Oid(), "email": f"a{marker}@h.in", "name": "A", "department": f"  ops{marker} "},
        {**base, "_id": _Oid(), "email": f"b{marker}@h.in", "name": "B", "department": f"Field{marker}"},
        {**base, "_id": _Oid(), "email": f"c{marker}@h.in", "name": "C", "department": f"field{marker}  "},
    ])
    rows = call(api, users["founder"], "GET", "/employees/departments/list").json()
    ops = next(d for d in rows if d["name"] == f"Ops{marker}")
    assert ops["registered"] is True and ops["headcount"] == 1          # "  ops… " counted under Ops…
    field = next(d for d in rows if d["name"].casefold() == f"field{marker}")
    assert field["registered"] is False and field["headcount"] == 2      # never set up, still visible
    listed = call(api, users["founder"], "GET", "/employees", params={"department": f"Ops{marker}"}).json()
    names = [e["name"] for e in (listed["items"] if isinstance(listed, dict) else listed)]
    assert names == ["A"]


def test_update_department_head_description_and_rename(api, users, test_db):
    marker = uuid.uuid4().hex[:6]
    dept_id = str(test_db.departments.insert_one({"name": f"Ren{marker}"}).inserted_id)
    test_db.users.update_one({"_id": __import__("bson").ObjectId(users["employee2"]["id"])},
                             {"$set": {"department": f" ren{marker}"}})
    r = call(api, users["admin"], "PATCH", f"/employees/departments/{dept_id}",
             json={"head_id": users["manager"]["id"], "description": "  Keeps things running  ", "name": f"Renamed{marker}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["head_id"] == users["manager"]["id"] and body["description"] == "Keeps things running"
    moved = test_db.users.find_one({"_id": __import__("bson").ObjectId(users["employee2"]["id"])})
    assert moved["department"] == f"Renamed{marker}"
    assert call(api, users["manager"], "PATCH", f"/employees/departments/{dept_id}", json={"description": "x"}).status_code == 403
    assert call(api, users["admin"], "PATCH", f"/employees/departments/{dept_id}", json={"bogus": 1}).status_code == 422


def test_department_rename_renames_its_connect_group(api, users, test_db):
    from bson import ObjectId as _Oid
    marker = uuid.uuid4().hex[:6]
    old, new = f"Grp{marker}", f"GrpNew{marker}"
    dept_id = str(test_db.departments.insert_one({"name": old}).inserted_id)
    emp = users["employee2"]["id"]
    test_db.users.update_one({"_id": _Oid(emp)}, {"$set": {"department": old}})
    ch_id = test_db.channels.insert_one({"name": f"{old} Group", "kind": "group", "department": old,
                                         "members": ["legacy-member"]}).inserted_id
    r = call(api, users["founder"], "PATCH", f"/employees/departments/{dept_id}", json={"name": new})
    assert r.status_code == 200, r.text
    groups = list(test_db.channels.find({"kind": "group", "department": {"$in": [old, new]}}))
    assert [g["_id"] for g in groups] == [ch_id]  # same channel, no empty duplicate
    assert groups[0]["department"] == new and groups[0]["name"] == f"{new} Group"
    assert {"legacy-member", emp} <= set(groups[0]["members"])


def test_presence_marks_active_users_online(api, users, test_db):
    from bson import ObjectId as _Oid
    test_db.users.update_one({"_id": _Oid(users["intern"]["id"])}, {"$set": {"online": False}, "$unset": {"last_seen": ""}})
    assert call(api, users["intern"], "GET", "/auth/me").status_code == 200
    doc = test_db.users.find_one({"_id": _Oid(users["intern"]["id"])})
    assert doc["online"] is True and doc.get("last_seen") is not None
