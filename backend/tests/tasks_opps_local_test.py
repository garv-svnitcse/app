from __future__ import annotations
"""Task Board + Opportunity Hub API tests — task files (upload / list without blobs /
download / delete / legacy inline data), task and opportunity visibility, partial-update
validation, role rules for assignment and the reassignment / completion notifications.

Runs against an isolated server and throwaway database (see local_harness.py).
"""
import base64
import uuid

import pytest
from bson import ObjectId

from auth_utils import create_access_token
from local_harness import api, mongo, test_db, users, harness_env, call  # noqa: F401

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
PDF_B64 = base64.b64encode(PDF).decode()


def _uid():
    return uuid.uuid4().hex[:6]


def _extra_user(test_db, role, department):
    """A user outside the harness set (e.g. a Sales Manager), with request headers."""
    _id = ObjectId()
    email = f"extra.{_id}@harness.wavygo.in"
    test_db.users.insert_one({"_id": _id, "email": email, "name": f"Extra {role}", "role": role,
                              "department": department, "status": "active", "is_active": True})
    token = create_access_token(str(_id), email, role)
    return {"id": str(_id), "email": email, "role": role, "department": department,
            "headers": {"Authorization": f"Bearer {token}"}}


def _task(api, user, **fields):
    r = call(api, user, "POST", "/tasks", json={"title": f"Task {_uid()}", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _opp(api, user, **fields):
    r = call(api, user, "POST", "/opportunities", json={"title": f"Opp {_uid()}", "type": "Grant", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _notes(test_db, user_id, title):
    return list(test_db.notifications.find({"user_id": user_id, "title": title}))


# ------------------------- 1. task files -------------------------

def test_upload_list_download_and_delete(api, users, test_db):
    emp = users["employee"]
    t = _task(api, users["founder"], assignee_id=emp["id"])

    r = call(api, emp, "POST", f"/tasks/{t['id']}/files",
             json={"name": "Quarterly plan (v2).pdf", "data": f"data:application/pdf;base64,{PDF_B64}"})
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["name"] == "Quarterly plan (v2).pdf" and meta["size"] == len(PDF)
    assert meta["content_type"] == "application/pdf" and meta["uploaded_by"] == emp["id"]
    assert "data" not in meta

    stored = test_db.task_files.find_one({"_id": ObjectId(meta["id"])})
    assert stored["task_id"] == t["id"] and bytes(stored["data"]) == PDF
    raw = test_db.tasks.find_one({"_id": ObjectId(t["id"])})
    assert raw["attachments"] == [{k: meta[k] for k in meta}]

    listed = call(api, users["founder"], "GET", "/tasks", params={"limit": 500})
    assert listed.status_code == 200
    assert PDF_B64 not in listed.text and "data:application" not in listed.text
    row = next(x for x in listed.json() if x["id"] == t["id"])
    assert row["attachments"][0]["id"] == meta["id"]

    d = call(api, emp, "GET", f"/tasks/{t['id']}/files/{meta['id']}")
    assert d.status_code == 200 and d.content == PDF
    assert d.headers["content-type"] == "application/pdf"
    assert "Quarterly%20plan%20%28v2%29.pdf" in d.headers["content-disposition"]

    # Download follows task visibility.
    assert call(api, users["employee2"], "GET", f"/tasks/{t['id']}/files/{meta['id']}").status_code == 403
    assert call(api, users["intern"], "GET", f"/tasks/{t['id']}/files/{meta['id']}").status_code == 403
    assert call(api, users["manager"], "GET", f"/tasks/{t['id']}/files/{meta['id']}").status_code == 200

    # Only the uploader (or task.edit_any) removes it.
    other = _extra_user(test_db, "Employee", "Tech")
    call(api, users["founder"], "PATCH", f"/tasks/{t['id']}", json={"reporter_id": other["id"]})
    assert call(api, other, "DELETE", f"/tasks/{t['id']}/files/{meta['id']}").status_code == 403
    assert call(api, emp, "DELETE", f"/tasks/{t['id']}/files/{meta['id']}").status_code == 200
    assert test_db.task_files.count_documents({"_id": ObjectId(meta["id"])}) == 0
    assert call(api, emp, "GET", f"/tasks/{t['id']}").json()["attachments"] == []
    assert test_db.activity_logs.count_documents({"action": "Removed file from task"}) >= 1


def test_upload_rejects_non_pdf_and_intern_task_level(api, users):
    t = _task(api, users["founder"], assignee_id=users["intern"]["id"])
    bad = base64.b64encode(b"<html><script>alert(1)</script></html>").decode()
    r = call(api, users["founder"], "POST", f"/tasks/{t['id']}/files", json={"name": "x.pdf", "data": bad})
    assert r.status_code == 422
    r = call(api, users["founder"], "POST", f"/tasks/{t['id']}/files", json={"name": "x.pdf", "data": "!!notbase64!!"})
    assert r.status_code == 422
    r = call(api, users["intern"], "POST", f"/tasks/{t['id']}/files", json={"name": "a.pdf", "data": PDF_B64})
    assert r.status_code == 403


def test_comment_attachment_by_intern(api, users, test_db):
    intern = users["intern"]
    t = _task(api, users["founder"], assignee_id=intern["id"])
    c = call(api, intern, "POST", f"/tasks/{t['id']}/comments", json={"body": "See attached"}).json()
    r = call(api, intern, "POST", f"/tasks/{t['id']}/files",
             json={"name": "notes.pdf", "data": PDF_B64, "comment_id": c["id"]})
    assert r.status_code == 201, r.text
    doc = call(api, intern, "GET", f"/tasks/{t['id']}").json()
    assert doc["comments"][0]["attachments"][0]["name"] == "notes.pdf"
    assert test_db.task_files.find_one({"_id": ObjectId(r.json()["id"])})["comment_id"] == c["id"]
    # Someone else's comment is off limits for a non-editor.
    c2 = call(api, users["founder"], "POST", f"/tasks/{t['id']}/comments", json={"body": "hi"}).json()
    r = call(api, intern, "POST", f"/tasks/{t['id']}/files",
             json={"name": "n.pdf", "data": PDF_B64, "comment_id": c2["id"]})
    assert r.status_code == 403


def test_legacy_inline_attachments_are_migrated(api, users, test_db):
    emp = users["employee"]
    data_url = f"data:application/pdf;base64,{PDF_B64}"
    cid = str(ObjectId())
    _id = test_db.tasks.insert_one({
        "title": "Legacy task", "status": "todo", "priority": "low", "module": "General",
        "assignee_id": emp["id"], "reporter_id": users["founder"]["id"], "created_at": "2020-01-01T00:00:00+00:00",
        "attachments": [data_url, "https://example.com/spec.pdf"],
        "comments": [{"id": cid, "body": "old", "author_id": emp["id"], "author_name": "E",
                      "attachments": [data_url], "attachment_name": "Old comment.pdf"}],
    }).inserted_id
    tid = str(_id)

    listed = call(api, emp, "GET", "/tasks")
    assert PDF_B64 not in listed.text
    row = next(x for x in listed.json() if x["id"] == tid)
    first, link = row["attachments"]
    assert first["name"] == "Task_Document_1.pdf" and first["size"] == len(PDF)
    assert link["url"] == "https://example.com/spec.pdf"
    assert row["comments"][0]["attachments"][0]["name"] == "Old comment.pdf"

    raw = test_db.tasks.find_one({"_id": _id})
    assert all(isinstance(a, dict) for a in raw["attachments"])
    assert isinstance(raw["comments"][0]["attachments"][0], dict)
    assert test_db.task_files.count_documents({"task_id": tid}) == 2

    # Idempotent: a second read does not duplicate files, ids stay stable.
    again = call(api, emp, "GET", f"/tasks/{tid}").json()
    assert again["attachments"][0]["id"] == first["id"]
    assert test_db.task_files.count_documents({"task_id": tid}) == 2

    d = call(api, emp, "GET", f"/tasks/{tid}/files/{first['id']}")
    assert d.status_code == 200 and d.content == PDF


def test_legacy_comment_payload_goes_to_task_files(api, users, test_db):
    t = _task(api, users["founder"])
    r = call(api, users["founder"], "POST", f"/tasks/{t['id']}/comments", json={
        "body": "old client", "attachments": [f"data:application/pdf;base64,{PDF_B64}"], "attachment_name": "c.pdf"})
    assert r.status_code == 201
    att = r.json()["attachments"][0]
    assert att["name"] == "c.pdf" and PDF_B64 not in r.text
    assert bytes(test_db.task_files.find_one({"_id": ObjectId(att["id"])})["data"]) == PDF


def test_delete_task_removes_files(api, users, test_db):
    t = _task(api, users["founder"])
    call(api, users["founder"], "POST", f"/tasks/{t['id']}/files", json={"name": "a.pdf", "data": PDF_B64})
    assert call(api, users["founder"], "DELETE", f"/tasks/{t['id']}").status_code == 200
    assert test_db.task_files.count_documents({"task_id": t["id"]}) == 0


# ------------------------- 2. single task visibility -------------------------

def test_get_task_is_scoped(api, users, test_db):
    emp, emp2 = users["employee"], users["employee2"]
    t = _task(api, users["founder"], assignee_id=emp["id"])
    assert call(api, emp, "GET", f"/tasks/{t['id']}").status_code == 200
    assert call(api, emp2, "GET", f"/tasks/{t['id']}").status_code == 403
    assert call(api, users["intern"], "GET", f"/tasks/{t['id']}").status_code == 403
    assert call(api, users["manager"], "GET", f"/tasks/{t['id']}").status_code == 200

    sales = _task(api, users["founder"], assignee_id=emp2["id"])
    assert call(api, users["manager"], "GET", f"/tasks/{sales['id']}").status_code == 403
    assert call(api, users["manager"], "GET", f"/tasks/{ObjectId()}").status_code == 404
    assert call(api, users["manager"], "GET", "/tasks/not-an-id").status_code == 400


# ------------------------- 3. PATCH rules -------------------------

def test_patch_validates_enums_and_nulls(api, users):
    t = _task(api, users["founder"])
    for body in ({"status": "done"}, {"priority": "critical"}, {"title": "   "}, {"status": None}):
        r = call(api, users["founder"], "PATCH", f"/tasks/{t['id']}", json=body)
        assert r.status_code == 422, (body, r.text)
    r = call(api, users["founder"], "PATCH", f"/tasks/{t['id']}",
             json={"title": " Renamed ", "priority": "urgent", "id": "x", "comments": [], "attachments": ["data:x"]})
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed" and r.json()["priority"] == "urgent"
    assert r.json()["attachments"] == [] and r.json()["id"] == t["id"]


def test_patch_employee_and_intern_limits(api, users):
    emp, intern = users["employee"], users["intern"]
    t = _task(api, emp)
    # Echoing the unchanged assignee is fine; changing it needs task.assign.
    assert call(api, emp, "PATCH", f"/tasks/{t['id']}", json={"assignee_id": None, "title": "Mine"}).status_code == 200
    assert call(api, emp, "PATCH", f"/tasks/{t['id']}", json={"assignee_id": users["employee2"]["id"]}).status_code == 403
    assert call(api, emp, "PATCH", f"/tasks/{t['id']}", json={"reporter_id": users["founder"]["id"]}).status_code == 403

    ti = _task(api, users["founder"], assignee_id=intern["id"])
    assert call(api, intern, "PATCH", f"/tasks/{ti['id']}", json={"title": "Hacked"}).status_code == 403
    assert call(api, intern, "PATCH", f"/tasks/{ti['id']}", json={"assignee_id": intern["id"], "status": "review"}).status_code == 200
    r = call(api, intern, "PATCH", f"/tasks/{ti['id']}", json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    other = _task(api, users["founder"])
    assert call(api, intern, "PATCH", f"/tasks/{other['id']}", json={"status": "review"}).status_code == 403


def test_patch_manager_department_scope(api, users, test_db):
    mgr, emp, emp2 = users["manager"], users["employee"], users["employee2"]
    sales = _task(api, users["founder"], assignee_id=emp2["id"])
    assert call(api, mgr, "PATCH", f"/tasks/{sales['id']}", json={"priority": "high"}).status_code == 403
    assert call(api, mgr, "PATCH", f"/tasks/{sales['id']}/status", json={"status": "review"}).status_code == 403

    tech = _task(api, users["founder"], assignee_id=emp["id"])
    assert call(api, mgr, "PATCH", f"/tasks/{tech['id']}", json={"priority": "high"}).status_code == 200
    # Cannot hand a department task to someone outside the department.
    assert call(api, mgr, "PATCH", f"/tasks/{tech['id']}", json={"assignee_id": emp2["id"]}).status_code == 403
    assert call(api, mgr, "PATCH", f"/tasks/{tech['id']}", json={"assignee_id": users["intern"]["id"]}).status_code == 200


def test_manager_without_department_sees_own_tasks(api, users, test_db):
    lone = _extra_user(test_db, "Manager", None)
    mine = _task(api, lone)
    assigned = _task(api, users["founder"], assignee_id=lone["id"])
    ids = [x["id"] for x in call(api, lone, "GET", "/tasks").json()]
    assert mine["id"] in ids and assigned["id"] in ids
    assert call(api, lone, "GET", f"/tasks/{assigned['id']}").status_code == 200
    assert call(api, lone, "GET", "/tasks/stats/overview").json()["mine"] >= 1


# ------------------------- 4. create rules -------------------------

def test_create_rules(api, users):
    emp = users["employee"]
    r = call(api, emp, "POST", "/tasks", json={"title": "Spoof", "reporter_id": users["founder"]["id"]})
    assert r.status_code == 201 and r.json()["reporter_id"] == emp["id"]
    assert call(api, emp, "POST", "/tasks", json={"title": "Self", "assignee_id": emp["id"]}).status_code == 201
    assert call(api, emp, "POST", "/tasks", json={"title": "Other", "assignee_id": users["employee2"]["id"]}).status_code == 403
    assert call(api, emp, "POST", "/tasks", json={"title": "   "}).status_code == 422
    assert call(api, users["manager"], "POST", "/tasks", json={"title": "X", "assignee_id": users["employee2"]["id"]}).status_code == 403
    r = call(api, users["founder"], "POST", "/tasks", json={"title": "Blob", "attachments": ["data:application/pdf;base64,AAAA"]})
    assert r.status_code == 201 and r.json()["attachments"] == []


def test_empty_due_date_is_stored_as_null(api, users, test_db):
    founder = users["founder"]
    t = _task(api, founder, due_date="")
    assert t["due_date"] is None
    assert test_db.tasks.find_one({"_id": ObjectId(t["id"])})["due_date"] is None

    call(api, founder, "PATCH", f"/tasks/{t['id']}", json={"due_date": "2031-05-01"})
    r = call(api, founder, "PATCH", f"/tasks/{t['id']}", json={"due_date": "  "})
    assert r.status_code == 200, r.text
    assert test_db.tasks.find_one({"_id": ObjectId(t["id"])})["due_date"] is None

    # Legacy "" reads as empty: echoing an empty due date back is not an edit.
    test_db.tasks.update_one({"_id": ObjectId(t["id"])}, {"$set": {"due_date": "", "updated_at": "legacy"}})
    assert call(api, founder, "PATCH", f"/tasks/{t['id']}", json={"due_date": ""}).status_code == 200
    doc = test_db.tasks.find_one({"_id": ObjectId(t["id"])})
    assert doc["updated_at"] == "legacy"
    assert call(api, founder, "PATCH", f"/tasks/{t['id']}", json={"due_date": None}).status_code == 200
    assert test_db.tasks.find_one({"_id": ObjectId(t["id"])})["updated_at"] == "legacy"


# ------------------------- 5. notifications -------------------------

def test_reassign_notification_only_on_change(api, users, test_db):
    emp = users["employee"]
    t = _task(api, users["founder"], assignee_id=emp["id"])
    before = len(_notes(test_db, emp["id"], "Task reassigned to you"))
    call(api, users["founder"], "PATCH", f"/tasks/{t['id']}", json={"assignee_id": emp["id"], "title": "Same person"})
    assert len(_notes(test_db, emp["id"], "Task reassigned to you")) == before

    t2 = _task(api, users["founder"])
    call(api, users["founder"], "PATCH", f"/tasks/{t2['id']}", json={"assignee_id": emp["id"]})
    assert len(_notes(test_db, emp["id"], "Task reassigned to you")) == before + 1


def test_completion_notifies_reporter_unless_self(api, users, test_db):
    emp, founder = users["employee"], users["founder"]
    t = _task(api, emp, assignee_id=emp["id"])
    call(api, emp, "PATCH", f"/tasks/{t['id']}/status", json={"status": "completed"})
    assert not any(n["link"].endswith(t["id"]) for n in _notes(test_db, emp["id"], "Task completed"))

    t2 = _task(api, founder, assignee_id=emp["id"])
    call(api, emp, "PATCH", f"/tasks/{t2['id']}/status", json={"status": "completed"})
    call(api, emp, "PATCH", f"/tasks/{t2['id']}/status", json={"status": "completed"})
    assert len([n for n in _notes(test_db, founder["id"], "Task completed") if n["link"].endswith(t2["id"])]) == 1

    t3 = _task(api, founder, assignee_id=emp["id"])
    call(api, emp, "PATCH", f"/tasks/{t3['id']}", json={"status": "completed"})
    assert any(n["link"].endswith(t3["id"]) for n in _notes(test_db, founder["id"], "Task completed"))


# ------------------------- 7. single opportunity visibility -------------------------

def test_get_opportunity_is_scoped(api, users):
    emp, emp2, mgr = users["employee"], users["employee2"], users["manager"]
    mine = _opp(api, users["founder"], assignee_id=emp["id"])
    sales = _opp(api, users["founder"], assignee_id=emp2["id"])
    pool = _opp(api, users["founder"])
    assert call(api, emp, "GET", f"/opportunities/{mine['id']}").status_code == 200
    assert call(api, emp2, "GET", f"/opportunities/{mine['id']}").status_code == 403
    assert call(api, emp, "GET", f"/opportunities/{pool['id']}").status_code == 403
    assert call(api, users["intern"], "GET", f"/opportunities/{mine['id']}").status_code == 403
    assert call(api, mgr, "GET", f"/opportunities/{mine['id']}").status_code == 200
    assert call(api, mgr, "GET", f"/opportunities/{pool['id']}").status_code == 200
    assert call(api, mgr, "GET", f"/opportunities/{sales['id']}").status_code == 403
    assert call(api, mgr, "GET", f"/opportunities/{ObjectId()}").status_code == 404


# ------------------------- 8. assign / status / manager scope -------------------------

def test_assign_validation_and_scope(api, users, test_db):
    mgr, emp, emp2 = users["manager"], users["employee"], users["employee2"]
    assert call(api, users["founder"], "POST", f"/opportunities/{ObjectId()}/assign",
                json={"assignee_id": emp["id"]}).status_code == 404
    pool = _opp(api, users["founder"])
    assert call(api, users["founder"], "POST", f"/opportunities/{pool['id']}/assign",
                json={"assignee_id": str(ObjectId())}).status_code == 400
    assert call(api, mgr, "POST", f"/opportunities/{pool['id']}/assign",
                json={"assignee_id": emp2["id"]}).status_code == 403
    r = call(api, mgr, "POST", f"/opportunities/{pool['id']}/assign", json={"assignee_id": emp["id"]})
    assert r.status_code == 200 and r.json()["status"] == "assigned"
    assert _notes(test_db, emp["id"], "Opportunity assigned")

    sales = _opp(api, users["founder"], assignee_id=emp2["id"])
    assert call(api, mgr, "POST", f"/opportunities/{sales['id']}/assign",
                json={"assignee_id": emp["id"]}).status_code == 403
    assert call(api, mgr, "PATCH", f"/opportunities/{sales['id']}/status", json={"status": "won"}).status_code == 403
    assert call(api, mgr, "PATCH", f"/opportunities/{sales['id']}", json={"notes": "x"}).status_code == 403


def test_manager_edit_scope(api, users, test_db):
    mgr, emp, emp2 = users["manager"], users["employee"], users["employee2"]
    tech = _opp(api, users["founder"], assignee_id=emp["id"])
    assert call(api, mgr, "PATCH", f"/opportunities/{tech['id']}", json={"assignee_id": emp2["id"]}).status_code == 403
    assert call(api, mgr, "PATCH", f"/opportunities/{tech['id']}", json={"value_lakhs": 3}).status_code == 200

    sales_mgr = _extra_user(test_db, "Manager", "Sales")
    theirs = _opp(api, sales_mgr)
    assert call(api, mgr, "PATCH", f"/opportunities/{theirs['id']}", json={"title": "Mine now"}).status_code == 403
    assert call(api, mgr, "PATCH", f"/opportunities/{theirs['id']}/status", json={"status": "lost"}).status_code == 403
    assert call(api, mgr, "POST", f"/opportunities/{theirs['id']}/assign", json={"assignee_id": emp["id"]}).status_code == 403
    founder_pool = _opp(api, users["founder"])
    assert call(api, mgr, "PATCH", f"/opportunities/{founder_pool['id']}", json={"title": "Claimed"}).status_code == 200


# ------------------------- 9. PATCH model + stats -------------------------

def test_patch_opportunity_validation(api, users, test_db):
    o = _opp(api, users["founder"])
    for body in ({"status": "done"}, {"type": "Lottery"}, {"value_lakhs": -1}, {"value_lakhs": "lots"},
                 {"title": ""}, {"title": "x" * 301}, {"status": None}):
        r = call(api, users["founder"], "PATCH", f"/opportunities/{o['id']}", json=body)
        assert r.status_code == 422, (body, r.text)
    r = call(api, users["founder"], "PATCH", f"/opportunities/{o['id']}", json={
        "value_lakhs": 4.5, "id": "zzz", "assignee_name": "Fake", "created_by": "someone", "updated_at": "never"})
    assert r.status_code == 200
    raw = test_db.opportunities.find_one({"_id": ObjectId(o["id"])})
    assert raw["value_lakhs"] == 4.5 and "assignee_name" not in raw and raw["created_by"] == users["founder"]["id"]


def test_employee_patch_and_reassign_notification(api, users, test_db):
    emp, emp2 = users["employee"], users["employee2"]
    o = _opp(api, users["founder"], assignee_id=emp["id"])
    r = call(api, emp, "PATCH", f"/opportunities/{o['id']}", json={"status": "in_progress", "notes": "Called them", "title": "Nope"})
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress" and r.json()["notes"] == "Called them" and r.json()["title"] == o["title"]
    assert call(api, emp, "PATCH", f"/opportunities/{o['id']}", json={"title": "Nope"}).status_code == 403

    before = len(_notes(test_db, emp2["id"], "Opportunity assigned"))
    assert call(api, users["founder"], "PATCH", f"/opportunities/{o['id']}", json={"assignee_id": emp2["id"]}).status_code == 200
    assert len(_notes(test_db, emp2["id"], "Opportunity assigned")) == before + 1
    call(api, users["founder"], "PATCH", f"/opportunities/{o['id']}", json={"assignee_id": emp2["id"], "notes": "again"})
    assert len(_notes(test_db, emp2["id"], "Opportunity assigned")) == before + 1


def test_stats_tolerate_bad_legacy_values(api, users, test_db):
    base = call(api, users["founder"], "GET", "/opportunities/stats/overview").json()
    test_db.opportunities.insert_many([
        {"title": "junk1", "type": "Grant", "status": "open", "value_lakhs": "abc"},
        {"title": "junk2", "type": "Grant", "status": "open", "value_lakhs": None},
        {"title": "junk3", "type": "Grant", "status": "won", "value_lakhs": "2.5"},
        {"title": "junk4", "type": "Grant", "status": "closed", "value_lakhs": {"x": 1}},
        {"title": "ok", "type": "Grant", "status": "open", "value_lakhs": 10},
    ])
    r = call(api, users["founder"], "GET", "/opportunities/stats/overview")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["pipeline_lakhs"] == round(base["pipeline_lakhs"] + 10, 2)
    assert s["won_lakhs"] == round(base["won_lakhs"] + 2.5, 2)
    assert s["closed"] == base["closed"] + 1


# ------------------------- 10. sweep regressions -------------------------

def test_same_status_is_a_noop(api, users, test_db):
    t = _task(api, users["founder"], status="review")
    before = test_db.activity_logs.count_documents({"target": t["title"]})
    stamp = test_db.tasks.find_one({"_id": ObjectId(t["id"])})["updated_at"]
    r = call(api, users["founder"], "PATCH", f"/tasks/{t['id']}/status", json={"status": "review"})
    assert r.status_code == 200 and r.json()["status"] == "review"
    assert test_db.activity_logs.count_documents({"target": t["title"]}) == before
    assert test_db.tasks.find_one({"_id": ObjectId(t["id"])})["updated_at"] == stamp


def test_empty_comment_rejected(api, users):
    t = _task(api, users["founder"])
    for body in ("", "   "):
        assert call(api, users["founder"], "POST", f"/tasks/{t['id']}/comments", json={"body": body}).status_code == 422
    r = call(api, users["founder"], "POST", f"/tasks/{t['id']}/comments", json={"body": "  hello  "})
    assert r.status_code == 201 and r.json()["body"] == "hello"


def test_task_assignee_must_be_an_active_user(api, users, test_db):
    ghost = str(ObjectId())
    r = call(api, users["founder"], "POST", "/tasks", json={"title": f"T {_uid()}", "assignee_id": ghost})
    assert r.status_code == 400
    gone = _extra_user(test_db, "Employee", "Tech")
    test_db.users.update_one({"_id": ObjectId(gone["id"])}, {"$set": {"status": "deactivated"}})
    t = _task(api, users["founder"])
    assert call(api, users["founder"], "PATCH", f"/tasks/{t['id']}", json={"assignee_id": gone["id"]}).status_code == 400
    assert call(api, users["founder"], "PATCH", f"/tasks/{t['id']}", json={"assignee_id": users["employee"]["id"]}).status_code == 200


def test_create_opportunity_validates_title_and_assignee(api, users, test_db):
    for title in ("", "   "):
        r = call(api, users["founder"], "POST", "/opportunities", json={"title": title, "type": "Grant"})
        assert r.status_code == 422, r.text
    r = call(api, users["founder"], "POST", "/opportunities", json={"title": "Ghost", "type": "Grant", "assignee_id": str(ObjectId())})
    assert r.status_code == 400
    # A Manager cannot log an opportunity straight onto another department's teammate.
    r = call(api, users["manager"], "POST", "/opportunities", json={"title": "X-dept", "type": "Grant", "assignee_id": users["employee2"]["id"]})
    assert r.status_code == 403
    o = _opp(api, users["manager"], title=f"  Mine {_uid()}  ", assignee_id=users["employee"]["id"])
    assert o["title"] == o["title"].strip() and o["assignee_id"] == users["employee"]["id"]
    o = _opp(api, users["founder"], assignee_id="")
    assert test_db.opportunities.find_one({"_id": ObjectId(o["id"])})["assignee_id"] is None
