"""Company Vault API tests — RBAC (everyone views, Founder/Admin manage), per-item access
(roles / departments / people, folder cascade, 404 for hidden items), folders, upload/download
round trip, type and size validation, versions, metadata edits, deletes (GridFS cleanup), stats
and expiry reminders.

Runs against an isolated server and throwaway database (see local_harness.py).
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from bson import ObjectId

from local_harness import api, mongo, test_db, users, harness_env, call  # noqa: F401

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _upload(api, user, name="contract.pdf", data=PDF, **form):
    return call(api, user, "POST", "/vault/documents", files={"file": (name, data)}, data=form)


def _ok_upload(api, users, **kw):
    r = _upload(api, users["founder"], **kw)
    assert r.status_code == 201, r.text
    return r.json()


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _access(**kw) -> dict:
    return {"mode": "restricted", "roles": [], "departments": [], "user_ids": [], **kw}


def _uname(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:6]}"


def _list_ids(api, user, **params) -> set:
    r = call(api, user, "GET", "/vault/documents", params={"page_size": 100, **params})
    assert r.status_code == 200, r.text
    return {d["id"] for d in r.json()["items"]}


# ------------------------- RBAC -------------------------

@pytest.mark.parametrize("role", ["founder", "admin", "manager", "employee", "intern"])
@pytest.mark.parametrize("path", ["/vault/documents", "/vault/stats", "/vault/folders", "/vault/tags"])
def test_every_role_can_view(api, users, role, path):
    assert call(api, users[role], "GET", path).status_code == 200


@pytest.mark.parametrize("role", ["manager", "employee", "intern"])
def test_view_only_roles_cannot_manage(api, users, role):
    u = users[role]
    assert _upload(api, u).status_code == 403
    assert call(api, u, "POST", "/vault/folders", json={"name": _uname("Nope")}).status_code == 403
    assert call(api, u, "POST", "/vault/reminders/run").status_code == 403
    doc = _ok_upload(api, users, title="RBAC doc")
    assert call(api, u, "GET", f"/vault/documents/{doc['id']}").json()["can_edit"] is False
    assert call(api, u, "GET", f"/vault/documents/{doc['id']}/download").status_code == 200
    assert call(api, u, "DELETE", f"/vault/documents/{doc['id']}").status_code == 403
    assert call(api, u, "PATCH", f"/vault/documents/{doc['id']}", json={"title": "x"}).status_code == 403
    assert call(api, u, "POST", f"/vault/documents/{doc['id']}/versions",
                files={"file": ("x.pdf", PDF)}).status_code == 403


def test_admin_can_manage(api, users):
    a = users["admin"]
    r = _upload(api, a, title="Admin doc")
    assert r.status_code == 201, r.text
    assert r.json()["can_edit"] is True
    doc = _ok_upload(api, users, title="Founder doc")
    assert call(api, a, "PATCH", f"/vault/documents/{doc['id']}", json={"title": "Renamed"}).status_code == 200
    assert call(api, a, "POST", "/vault/reminders/run").status_code == 200


def test_owner_without_manage_permission_cannot_edit(api, users, test_db):
    """A document uploaded by someone whose role no longer has vault.manage is view-only for them."""
    m = users["manager"]
    doc = _ok_upload(api, users, title="Legacy manager upload")
    test_db.vault_documents.update_one({"_id": ObjectId(doc["id"])}, {"$set": {"uploaded_by": m["id"]}})
    assert call(api, m, "GET", f"/vault/documents/{doc['id']}").json()["can_edit"] is False
    assert call(api, m, "PATCH", f"/vault/documents/{doc['id']}", json={"title": "x"}).status_code == 403
    assert call(api, m, "DELETE", f"/vault/documents/{doc['id']}").status_code == 403


# ------------------------- per-item access -------------------------

def test_role_restricted_document_is_hidden(api, users):
    doc = _ok_upload(api, users, title="Managers only", tags="mgr-only-tag",
                     access=json.dumps(_access(roles=["Manager"])))
    assert doc["access"]["mode"] == "restricted" and doc["access"]["roles"] == ["Manager"]
    assert doc["id"] in _list_ids(api, users["manager"])
    assert doc["id"] in _list_ids(api, users["admin"])
    e = users["employee"]
    assert doc["id"] not in _list_ids(api, e)
    assert call(api, e, "GET", f"/vault/documents/{doc['id']}").status_code == 404
    assert call(api, e, "GET", f"/vault/documents/{doc['id']}/download").status_code == 404
    assert call(api, e, "GET", f"/vault/documents/{doc['id']}/versions/1/download").status_code == 404
    assert "mgr-only-tag" not in {t["tag"] for t in call(api, e, "GET", "/vault/tags").json()}
    assert "mgr-only-tag" in {t["tag"] for t in call(api, users["manager"], "GET", "/vault/tags").json()}


def test_department_and_person_access(api, users, test_db):
    dept_doc = _ok_upload(api, users, title="Tech handbook", access=json.dumps(_access(departments=["  Tech "])))
    assert dept_doc["access"]["departments"] == ["Tech"]
    assert dept_doc["id"] in _list_ids(api, users["employee"])       # Tech
    assert dept_doc["id"] not in _list_ids(api, users["employee2"])  # Sales

    e2 = users["employee2"]
    person_doc = _ok_upload(api, users, title="For employee2", access=json.dumps(_access(user_ids=[e2["id"]])))
    assert person_doc["id"] in _list_ids(api, e2)
    assert person_doc["id"] not in _list_ids(api, users["employee"])
    assert test_db.notifications.count_documents(
        {"user_id": e2["id"], "title": "Document shared with you", "link": f"/company-vault?doc={person_doc['id']}"}) == 1

    nobody = _ok_upload(api, users, title="Owner only", access=json.dumps(_access()))
    assert nobody["id"] not in _list_ids(api, users["manager"])
    assert nobody["id"] in _list_ids(api, users["admin"])


def test_restricted_folder_hides_its_documents(api, users, test_db):
    f, e, e2 = users["founder"], users["employee"], users["employee2"]
    folder = call(api, f, "POST", "/vault/folders",
                  json={"name": _uname("Board"), "access": _access(user_ids=[e2["id"]])}).json()
    doc = _ok_upload(api, users, title="Board minutes", folder_id=folder["id"])  # document itself: everyone
    assert doc["id"] in _list_ids(api, e2)
    assert folder["id"] in {x["id"] for x in call(api, e2, "GET", "/vault/folders").json()["folders"]}
    assert doc["id"] not in _list_ids(api, e)
    assert call(api, e, "GET", f"/vault/documents/{doc['id']}").status_code == 404
    assert folder["id"] not in {x["id"] for x in call(api, e, "GET", "/vault/folders").json()["folders"]}
    assert all(g["folder_id"] != folder["id"] for g in call(api, e, "GET", "/vault/stats").json()["by_folder"])

    # Sharing a document with someone the folder still hides does not notify them.
    shared = _ok_upload(api, users, title="Hidden share", folder_id=folder["id"],
                        access=json.dumps(_access(user_ids=[e["id"]])))
    assert test_db.notifications.count_documents({"user_id": e["id"], "link": f"/company-vault?doc={shared['id']}"}) == 0
    assert call(api, e, "GET", f"/vault/documents/{shared['id']}").status_code == 404


def test_document_in_deleted_folder_is_hidden(api, users, test_db):
    f, e = users["founder"], users["employee"]
    folder = call(api, f, "POST", "/vault/folders", json={"name": _uname("Gone")}).json()
    doc = _ok_upload(api, users, title="Orphan", folder_id=folder["id"])
    assert doc["id"] in _list_ids(api, e)
    test_db.vault_folders.delete_one({"_id": ObjectId(folder["id"])})
    assert doc["id"] not in _list_ids(api, e)
    assert call(api, e, "GET", f"/vault/documents/{doc['id']}").status_code == 404
    assert call(api, f, "GET", f"/vault/documents/{doc['id']}").status_code == 200


def test_access_change_logged_only_when_changed(api, users, test_db):
    f, e2 = users["founder"], users["employee2"]
    doc = _ok_upload(api, users, title=_uname("Access log"))

    def logs():
        return test_db.activity_logs.count_documents({"action": "Changed document access", "target": doc["title"]})

    r = call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={"access": doc["access"]})
    assert r.status_code == 200 and logs() == 0
    restricted = _access(user_ids=[e2["id"]])
    assert call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={"access": restricted}).status_code == 200
    assert logs() == 1
    link = f"/company-vault?doc={doc['id']}"
    assert test_db.notifications.count_documents({"user_id": e2["id"], "link": link}) == 1
    # Re-sending the same access with another edit: no new access log or notification.
    call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={"access": restricted, "description": "x"})
    assert logs() == 1
    assert test_db.notifications.count_documents({"user_id": e2["id"], "link": link}) == 1


def test_unauthenticated(api):
    assert call(api, None, "GET", "/vault/documents").status_code == 401


# ------------------------- folders -------------------------

def test_folder_crud(api, users, test_db):
    f = users["founder"]
    r = call(api, f, "POST", "/vault/folders", json={"name": "  Legal  "})
    assert r.status_code == 201, r.text
    folder = r.json()
    assert folder["name"] == "Legal"
    assert call(api, f, "POST", "/vault/folders", json={"name": "legal"}).status_code == 409
    r = call(api, f, "PATCH", f"/vault/folders/{folder['id']}", json={"name": "Legal & Compliance"})
    assert r.status_code == 200 and r.json()["name"] == "Legal & Compliance"

    doc = _ok_upload(api, users, title="In folder", folder_id=folder["id"])
    listed = call(api, f, "GET", "/vault/folders").json()
    assert next(x for x in listed["folders"] if x["id"] == folder["id"])["count"] == 1
    assert call(api, f, "DELETE", f"/vault/folders/{folder['id']}").status_code == 409

    call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={"folder_id": None})
    assert call(api, f, "DELETE", f"/vault/folders/{folder['id']}").status_code == 200
    assert test_db.vault_folders.count_documents({"_id": ObjectId(folder["id"])}) == 0
    assert call(api, f, "DELETE", f"/vault/folders/{folder['id']}").status_code == 404
    assert call(api, users["manager"], "POST", "/vault/folders", json={"name": "Nope"}).status_code == 403
    assert test_db.activity_logs.count_documents({"module": "Company Vault", "action": "Created vault folder"}) >= 1


def test_upload_rejects_unknown_folder(api, users):
    r = _upload(api, users["founder"], folder_id=str(ObjectId()))
    assert r.status_code == 422
    assert _upload(api, users["founder"], folder_id="not-an-id").status_code == 400


# ------------------------- upload / download -------------------------

def test_upload_download_round_trip(api, users, test_db):
    data = PDF + b"x" * 300_000
    doc = _ok_upload(api, users, name="Lease Agreement.pdf", data=data, tags="Lease, legal ,lease",
                     description="Office lease", expires_on=_day(200))
    assert doc["title"] == "Lease Agreement"
    assert doc["tags"] == ["lease", "legal"]
    assert doc["size"] == len(data)
    assert doc["checksum"] == hashlib.sha256(data).hexdigest()
    assert doc["content_type"] == "application/pdf"
    assert doc["version"] == 1 and len(doc["versions"]) == 1
    assert doc["uploaded_by"] == users["founder"]["id"]
    assert doc["expiry_status"] == "valid"
    assert "file_id" not in doc and "file_id" not in doc["versions"][0]

    r = call(api, users["founder"], "GET", f"/vault/documents/{doc['id']}/download")
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "Lease Agreement.pdf" in r.headers["content-disposition"]

    r = call(api, users["founder"], "GET", f"/vault/documents/{doc['id']}/download", params={"inline": "true"})
    assert r.headers["content-disposition"].startswith("inline;")
    assert r.headers["content-type"] == "application/pdf"
    assert test_db.activity_logs.count_documents({"action": "Uploaded document", "target": "Lease Agreement"}) == 1


def test_non_previewable_forced_attachment(api, users):
    doc = _ok_upload(api, users, name="notes.txt", data=b"<html><script>alert(1)</script>")
    r = call(api, users["founder"], "GET", f"/vault/documents/{doc['id']}/download", params={"inline": "true"})
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["content-type"] == "application/octet-stream"


def test_magic_byte_rejection(api, users):
    f = users["founder"]
    assert _upload(api, f, name="fake.pdf", data=b"MZ\x90\x00 not a pdf").status_code == 400
    assert _upload(api, f, name="fake.png", data=PDF).status_code == 400
    assert _upload(api, f, name="fake.jpg", data=PNG).status_code == 400
    assert _upload(api, f, name="fake.docx", data=b"plain text").status_code == 400
    assert _upload(api, f, name="evil.exe", data=b"MZ\x90\x00").status_code == 415
    assert _upload(api, f, name="noext", data=b"abc").status_code == 415
    assert _upload(api, f, name="empty.txt", data=b"").status_code == 400
    assert _upload(api, f, name="img.png", data=PNG).status_code == 201
    assert _upload(api, f, name="img.JPG", data=b"\xff\xd8\xff\xe0" + b"\x00" * 32).status_code == 201


def test_size_limit(api, users, test_db):
    before = test_db["vault.files"].count_documents({})
    r = _upload(api, users["founder"], name="big.pdf", data=PDF + b"0" * (25 * 1024 * 1024))
    assert r.status_code == 413
    assert test_db["vault.files"].count_documents({}) == before


def test_bad_expiry(api, users):
    assert _upload(api, users["founder"], expires_on="31/12/2030").status_code == 422


# ------------------------- versions -------------------------

def test_versions_restore_and_download(api, users, test_db):
    f = users["founder"]
    doc = _ok_upload(api, users, name="policy.pdf", data=PDF + b"v1")
    v2 = PNG + b"v2"
    r = call(api, f, "POST", f"/vault/documents/{doc['id']}/versions",
             files={"file": ("policy-scan.png", v2)}, data={"note": "Signed scan"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 2 and body["file_name"] == "policy-scan.png"
    assert body["content_type"] == "image/png"
    assert [v["version"] for v in body["versions"]] == [2, 1]
    assert body["versions"][0]["note"] == "Signed scan"

    assert call(api, f, "GET", f"/vault/documents/{doc['id']}/download").content == v2
    old = call(api, f, "GET", f"/vault/documents/{doc['id']}/versions/1/download")
    assert old.status_code == 200 and old.content == PDF + b"v1"
    assert call(api, f, "GET", f"/vault/documents/{doc['id']}/versions/9/download").status_code == 404

    r = call(api, f, "POST", f"/vault/documents/{doc['id']}/versions/1/restore")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 3 and r.json()["file_name"] == "policy.pdf"
    assert call(api, f, "GET", f"/vault/documents/{doc['id']}/download").content == PDF + b"v1"
    assert call(api, f, "POST", f"/vault/documents/{doc['id']}/versions/3/restore").status_code == 409

    bad = call(api, f, "POST", f"/vault/documents/{doc['id']}/versions", files={"file": ("x.pdf", b"nope")})
    assert bad.status_code == 400
    assert call(api, users["employee"], "POST", f"/vault/documents/{doc['id']}/versions",
                files={"file": ("x.pdf", PDF)}).status_code == 403


# ------------------------- metadata / delete -------------------------

def test_metadata_edit(api, users, test_db):
    f = users["founder"]
    doc = _ok_upload(api, users, name="gst.pdf")
    test_db.vault_documents.update_one({"_id": ObjectId(doc["id"])}, {"$set": {"reminders_sent": ["30d"]}})
    r = call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={
        "title": "GST Certificate", "tags": ["Tax", "gst"], "description": "Registration",
        "expires_on": _day(5)})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["title"] == "GST Certificate" and out["tags"] == ["tax", "gst"]
    assert out["expiry_status"] == "expiring" and out["days_to_expiry"] == 5
    assert test_db.vault_documents.find_one({"_id": ObjectId(doc["id"])})["reminders_sent"] == []
    assert call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={"title": "  "}).status_code == 422
    assert call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={"expires_on": "soon"}).status_code == 422
    r = call(api, f, "PATCH", f"/vault/documents/{doc['id']}", json={"expires_on": None})
    assert r.json()["expires_on"] is None
    assert test_db.activity_logs.count_documents({"action": "Edited document details", "target": "GST Certificate"}) >= 1


def test_delete_removes_gridfs_files(api, users, test_db):
    f = users["founder"]
    doc = _ok_upload(api, users, name="old.pdf")
    call(api, f, "POST", f"/vault/documents/{doc['id']}/versions", files={"file": ("old2.pdf", PDF + b"2")})
    call(api, f, "POST", f"/vault/documents/{doc['id']}/versions/1/restore")
    stored = test_db.vault_documents.find_one({"_id": ObjectId(doc["id"])})
    file_ids = {ObjectId(v["file_id"]) for v in stored["versions"]}
    assert len(file_ids) == 2
    assert test_db["vault.files"].count_documents({"_id": {"$in": list(file_ids)}}) == 2

    assert call(api, f, "DELETE", f"/vault/documents/{doc['id']}").status_code == 200
    assert test_db["vault.files"].count_documents({"_id": {"$in": list(file_ids)}}) == 0
    assert test_db["vault.chunks"].count_documents({"files_id": {"$in": list(file_ids)}}) == 0
    assert call(api, f, "GET", f"/vault/documents/{doc['id']}").status_code == 404
    assert call(api, f, "DELETE", f"/vault/documents/{doc['id']}").status_code == 404
    assert call(api, f, "GET", "/vault/documents/not-an-id").status_code == 400


# ------------------------- list / stats -------------------------

def test_list_filters_and_pagination(api, users):
    f = users["founder"]
    folder = call(api, f, "POST", "/vault/folders", json={"name": "Insurance"}).json()
    a = _ok_upload(api, users, name="policy-a.pdf", title="Fleet insurance (a+b)", folder_id=folder["id"],
                   tags="insurance", expires_on=_day(10))
    b = _ok_upload(api, users, name="policy-b.pdf", title="Office insurance", folder_id=folder["id"],
                   tags="insurance,office", expires_on=_day(-3))

    def ids(**params):
        r = call(api, f, "GET", "/vault/documents", params=params)
        assert r.status_code == 200, r.text
        return [d["id"] for d in r.json()["items"]]

    assert set(ids(folder_id=folder["id"])) == {a["id"], b["id"]}
    assert ids(folder_id=folder["id"], tag="office") == [b["id"]]
    assert ids(q="(a+b)") == [a["id"]]  # regex metacharacters are escaped
    assert a["id"] in ids(expiry="expiring") and b["id"] not in ids(expiry="expiring")
    assert b["id"] in ids(expiry="expired") and a["id"] not in ids(expiry="expired")
    assert a["id"] not in ids(folder_id="unfiled")

    page1 = call(api, f, "GET", "/vault/documents", params={"page_size": 1, "folder_id": folder["id"]}).json()
    page2 = call(api, f, "GET", "/vault/documents", params={"page_size": 1, "page": 2, "folder_id": folder["id"]}).json()
    assert page1["total"] == 2 and page1["pages"] == 2
    assert {page1["items"][0]["id"], page2["items"][0]["id"]} == {a["id"], b["id"]}

    tags = {t["tag"]: t["count"] for t in call(api, f, "GET", "/vault/tags").json()}
    assert tags["insurance"] >= 2


def test_expiry_sort_keeps_undated_documents_last(api, users):
    f = users["founder"]
    folder = call(api, f, "POST", "/vault/folders", json={"name": "Sort check"}).json()
    undated = _ok_upload(api, users, name="memo.pdf", folder_id=folder["id"])
    late = _ok_upload(api, users, name="late.pdf", folder_id=folder["id"], expires_on=_day(90))
    soon = _ok_upload(api, users, name="soon.pdf", folder_id=folder["id"], expires_on=_day(5))

    def page(n, size):
        return call(api, f, "GET", "/vault/documents",
                    params={"folder_id": folder["id"], "sort": "expiry", "page": n, "page_size": size}).json()

    full = page(1, 10)
    assert full["total"] == 3 and [d["id"] for d in full["items"]] == [soon["id"], late["id"], undated["id"]]
    assert [page(n, 2)["items"][i]["id"] for n, i in ((1, 0), (1, 1), (2, 0))] == [soon["id"], late["id"], undated["id"]]
    assert page(2, 2)["total"] == 3 and len(page(2, 2)["items"]) == 1


def test_stats(api, users, test_db):
    f = users["founder"]
    stats = call(api, f, "GET", "/vault/stats").json()
    docs = list(test_db.vault_documents.find({}))
    assert stats["count"] == len(docs)
    assert stats["total_size"] == sum(d["size"] for d in docs)
    today = TODAY.isoformat()
    horizon = _day(30)
    assert stats["expired"] == sum(1 for d in docs if d.get("expires_on") and d["expires_on"] < today)
    assert stats["expiring_30d"] == sum(1 for d in docs if d.get("expires_on") and today <= d["expires_on"] <= horizon)
    assert sum(g["count"] for g in stats["by_folder"]) == len(docs)
    assert stats["storage_size"] >= stats["total_size"] or stats["stored_files"] >= len(docs)


# ------------------------- expiry reminders -------------------------

def test_expiry_reminders_sent_once(api, users, test_db):
    f = users["founder"]
    test_db.vault_documents.update_many({}, {"$set": {"reminders_sent": ["30d", "7d", "expired"]}})
    d30 = _ok_upload(api, users, name="licence.pdf", title="Trade licence", expires_on=_day(25))
    d7 = _ok_upload(api, users, name="fitness.pdf", title="Fitness cert", expires_on=_day(6))
    dx = _ok_upload(api, users, name="permit.pdf", title="Road permit", expires_on=_day(-1))
    far = _ok_upload(api, users, name="deed.pdf", title="Deed", expires_on=_day(90))

    # Every active Founder and Admin is reminded (the owner is the Founder here, so no duplicate).
    recipients = test_db.users.count_documents({"role": {"$in": ["Founder", "Admin"]},
                                                "status": {"$ne": "deactivated"}, "is_active": {"$ne": False}})
    r = call(api, f, "POST", "/vault/reminders/run")
    assert r.status_code == 200 and r.json()["sent"] == 3 * recipients

    def notes(doc):
        return list(test_db.notifications.find({"user_id": f["id"], "link": f"/company-vault?doc={doc['id']}"}))

    assert len(notes(d30)) == 1 and "expires on" in notes(d30)[0]["body"]
    assert len(notes(d7)) == 1
    assert len(notes(dx)) == 1 and notes(dx)[0]["title"] == "Document expired"
    assert notes(far) == []
    admin_notes = list(test_db.notifications.find({"user_id": users["admin"]["id"],
                                                   "link": f"/company-vault?doc={dx['id']}"}))
    assert len(admin_notes) == 1
    assert set(test_db.vault_documents.find_one({"_id": ObjectId(d7["id"])})["reminders_sent"]) == {"30d", "7d"}

    # Idempotent: nothing new on a second run.
    assert call(api, f, "POST", "/vault/reminders/run").json()["sent"] == 0

    # Crossing into the 7-day window sends the next stage once.
    test_db.vault_documents.update_one({"_id": ObjectId(d30["id"])}, {"$set": {"expires_on": _day(7)}})
    assert call(api, f, "POST", "/vault/reminders/run").json()["sent"] == recipients
    assert len(notes(d30)) == 2

    # Changing the expiry through the API resets the reminders.
    call(api, f, "PATCH", f"/vault/documents/{d7['id']}", json={"expires_on": _day(20)})
    assert call(api, f, "POST", "/vault/reminders/run").json()["sent"] == recipients
    assert len(notes(d7)) == 2


def test_expiry_reminder_reaches_owner_once(api, users, test_db):
    f, mgr = users["founder"], users["manager"]
    test_db.vault_documents.update_many({}, {"$set": {"reminders_sent": ["30d", "7d", "expired"]}})
    doc = _ok_upload(api, users, name="owned.pdf", title="Owned by manager", expires_on=_day(3))
    # e.g. uploaded while the owner still held vault.manage; ownership keeps them in the loop
    test_db.vault_documents.update_one({"_id": ObjectId(doc["id"])}, {"$set": {"uploaded_by": mgr["id"]}})
    link = f"/company-vault?doc={doc['id']}"
    call(api, f, "POST", "/vault/reminders/run")
    owner_notes = list(test_db.notifications.find({"user_id": mgr["id"], "link": link}))
    assert len(owner_notes) == 1 and owner_notes[0]["title"] == "Document expiring soon"
    assert test_db.notifications.count_documents({"user_id": f["id"], "link": link}) == 1
    # other non-admins are not reminded; a second run sends nothing (dedupe)
    assert test_db.notifications.count_documents({"user_id": users["employee"]["id"], "link": link}) == 0
    assert call(api, f, "POST", "/vault/reminders/run").json()["sent"] == 0
    assert test_db.notifications.count_documents({"user_id": mgr["id"], "link": link}) == 1


def test_duplicate_folder_name_message(api, users):
    a = users["admin"]
    name = _uname("Board")
    r = call(api, users["founder"], "POST", "/vault/folders",
             json={"name": name, "access": _access(user_ids=[users["founder"]["id"]])})
    assert r.status_code == 201, r.text
    # Founder/Admin see every folder, so they get the explicit duplicate message
    r = call(api, a, "POST", "/vault/folders", json={"name": name.upper()})
    assert r.status_code == 409 and r.json()["detail"] == "A folder with this name already exists"
    # people without vault.manage are refused before any name check, so nothing leaks
    r = call(api, users["manager"], "POST", "/vault/folders", json={"name": name})
    assert r.status_code == 403 and "already exists" not in r.text
