from __future__ import annotations
"""WavyGo Connect + Marketplace API tests — channel access control, group members, unread
cursors, marketplace payload validation, 404s, revenue and booking / vehicle status rules.

Runs against an isolated server and throwaway database (see local_harness.py).
"""
import uuid
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from local_harness import api, mongo, test_db, users, harness_env, call  # noqa: F401


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ------------------------- Connect helpers -------------------------

def _channel(api, user, **fields):
    r = call(api, user, "POST", "/connect/channels", json={"name": f"ch-{_uid()}", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _post(api, user, channel_id, body="hello"):
    r = call(api, user, "POST", f"/connect/channels/{channel_id}/messages", json={"body": body})
    assert r.status_code == 201, r.text
    return r.json()


def _listed(api, user, channel_id):
    r = call(api, user, "GET", "/connect/channels")
    assert r.status_code == 200, r.text
    return next((c for c in r.json() if c["id"] == channel_id), None)


# ------------------------- Connect: access control -------------------------

def test_private_group_cannot_be_joined_or_read(api, users):
    group = _channel(api, users["founder"], kind="group", members=[users["employee"]["id"]])
    outsider = users["employee2"]
    assert call(api, outsider, "POST", f"/connect/channels/{group['id']}/join").status_code == 403
    assert call(api, outsider, "GET", f"/connect/channels/{group['id']}/messages").status_code == 403
    r = call(api, outsider, "POST", f"/connect/channels/{group['id']}/messages", json={"body": "hi"})
    assert r.status_code == 403
    assert call(api, outsider, "POST", f"/connect/channels/{group['id']}/read").status_code == 403
    assert _listed(api, outsider, group["id"]) is None
    # members still have access
    assert call(api, users["employee"], "GET", f"/connect/channels/{group['id']}/messages").status_code == 200


def test_dm_cannot_be_joined(api, users):
    r = call(api, users["founder"], "POST", f"/connect/dm/{users['employee']['id']}")
    assert r.status_code == 201, r.text
    dm_id = r.json()["id"]
    assert call(api, users["employee2"], "POST", f"/connect/channels/{dm_id}/join").status_code == 403
    assert call(api, users["employee2"], "GET", f"/connect/channels/{dm_id}/messages").status_code == 403


def _legacy_channel(test_db, creator):
    """A pre-existing public channel (created before channels became members-only)."""
    return str(test_db.channels.insert_one({
        "name": f"legacy-{_uid()}", "kind": "channel", "description": None, "members": [creator["id"]],
        "created_by": creator["id"], "created_at": "2025-01-01T00:00:00+00:00",
        "last_message_at": "2025-01-01T00:00:00+00:00",
    }).inserted_id)


def test_public_channel_join_is_allowed_and_logged(api, users, test_db):
    ch = {"id": _legacy_channel(test_db, users["founder"])}
    r = call(api, users["intern"], "POST", f"/connect/channels/{ch['id']}/join")
    assert r.status_code == 200
    doc = test_db.channels.find_one({"_id": ObjectId(ch["id"])})
    assert users["intern"]["id"] in doc["members"]
    assert test_db.activity_logs.find_one({"action": "Joined channel", "user_id": users["intern"]["id"]})


def test_create_rejects_dm_kind(api, users):
    r = call(api, users["founder"], "POST", "/connect/channels", json={"name": "x", "kind": "dm"})
    assert r.status_code == 400


# ------------------------- Connect: members -------------------------

def test_create_group_validates_members(api, users):
    r = call(api, users["manager"], "POST", "/connect/channels",
             json={"name": "ghosts", "kind": "group", "members": [str(ObjectId())]})
    assert r.status_code == 422
    r = call(api, users["manager"], "POST", "/connect/channels",
             json={"name": "bad", "kind": "group", "members": ["not-an-id"]})
    assert r.status_code == 422


def test_channel_creator_can_edit_metadata(api, users):
    channel = _channel(api, users["manager"], kind="group", description="Old details",
                       members=[users["employee"]["id"]])
    path = f"/connect/channels/{channel['id']}"
    response = call(api, users["manager"], "PATCH", path,
                    json={"name": "  updated-name  ", "description": "  Updated details  "})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "updated-name"
    assert response.json()["description"] == "Updated details"
    assert response.json()["can_edit"] is True
    assert _listed(api, users["manager"], channel["id"])["name"] == "updated-name"


def test_channel_edit_requires_permission_and_valid_metadata(api, users):
    channel = _channel(api, users["manager"], kind="group", members=[users["employee"]["id"]])
    path = f"/connect/channels/{channel['id']}"
    assert call(api, users["employee"], "PATCH", path, json={"name": "unauthorized"}).status_code == 403
    assert call(api, users["manager"], "PATCH", path, json={"name": "   "}).status_code == 422
    assert call(api, users["manager"], "PATCH", path, json={"name": "x" * 81}).status_code == 422
    assert call(api, users["manager"], "PATCH", path, json={"description": "x" * 501}).status_code == 422
    assert call(api, users["manager"], "PATCH", path, json={}).status_code == 422


def test_create_group_with_members_notifies(api, users, test_db):
    group = _channel(api, users["manager"], kind="group",
                     members=[users["employee"]["id"], users["employee"]["id"], users["manager"]["id"]])
    assert group["members"] == [users["manager"]["id"], users["employee"]["id"]]
    assert test_db.notifications.find_one({"user_id": users["employee"]["id"], "title": "Added to group"})


def test_add_members_permissions(api, users, test_db):
    group = _channel(api, users["manager"], kind="group", members=[users["employee"]["id"]])
    path = f"/connect/channels/{group['id']}/members"
    # a plain member cannot add people
    r = call(api, users["employee"], "POST", path, json={"member_ids": [users["intern"]["id"]]})
    assert r.status_code == 403
    # unknown user
    r = call(api, users["manager"], "POST", path, json={"member_ids": [str(ObjectId())]})
    assert r.status_code == 422
    # empty list
    r = call(api, users["manager"], "POST", path, json={"member_ids": []})
    assert r.status_code == 422
    # creator adds
    r = call(api, users["manager"], "POST", path, json={"member_ids": [users["employee2"]["id"]]})
    assert r.status_code == 200, r.text
    assert users["employee2"]["id"] in r.json()["members"]
    assert test_db.notifications.find_one({"user_id": users["employee2"]["id"], "title": "Added to group"})
    assert test_db.activity_logs.find_one({"action": "Added group members", "target": group["name"]})
    # Founder / Admin can add to someone else's group
    r = call(api, users["admin"], "POST", path, json={"member_ids": [users["intern"]["id"]]})
    assert r.status_code == 200
    assert users["intern"]["id"] in r.json()["members"]
    # new member can now read
    assert call(api, users["intern"], "GET", f"/connect/channels/{group['id']}/messages").status_code == 200


def test_add_members_only_for_groups(api, users, test_db):
    legacy = _legacy_channel(test_db, users["founder"])
    ann = _channel(api, users["founder"], kind="announcement")
    for cid in (legacy, ann["id"]):
        r = call(api, users["founder"], "POST", f"/connect/channels/{cid}/members",
                 json={"member_ids": [users["employee"]["id"]]})
        assert r.status_code == 400
    r = call(api, users["founder"], "POST", f"/connect/channels/{ObjectId()}/members",
             json={"member_ids": [users["employee"]["id"]]})
    assert r.status_code == 404


def test_new_channel_is_members_only(api, users):
    ch = _channel(api, users["manager"], kind="channel", members=[users["employee"]["id"]])
    assert ch["members_only"] is True and ch["admins"] == [users["manager"]["id"]] and ch["can_manage"] is True
    outsider = users["intern"]
    assert _listed(api, outsider, ch["id"]) is None
    assert call(api, outsider, "GET", f"/connect/channels/{ch['id']}/messages").status_code == 403
    assert call(api, outsider, "POST", f"/connect/channels/{ch['id']}/messages", json={"body": "hi"}).status_code == 403
    assert call(api, outsider, "POST", f"/connect/channels/{ch['id']}/join").status_code == 403
    assert call(api, outsider, "GET", f"/connect/channels/{ch['id']}/members").status_code == 403
    # Founder is not an implicit reader of private conversations
    assert call(api, users["founder"], "GET", f"/connect/channels/{ch['id']}/messages").status_code == 403
    _post(api, users["employee"], ch["id"], "member can post")
    assert _listed(api, users["employee"], ch["id"])["can_manage"] is False


def test_legacy_public_channel_stays_open(api, users, test_db):
    cid = _legacy_channel(test_db, users["founder"])
    listed = _listed(api, users["intern"], cid)
    assert listed is not None and listed["members_only"] is False
    _post(api, users["intern"], cid, "still open")


def test_create_channel_with_departments(api, users):
    r = call(api, users["founder"], "GET", "/connect/departments")
    assert r.status_code == 200
    assert {"Tech", "Sales"} <= {d["name"] for d in r.json()}
    assert call(api, users["employee"], "GET", "/connect/departments").status_code == 403
    ch = _channel(api, users["founder"], kind="channel", departments=["tech"], members=[users["employee2"]["id"]])
    assert set(ch["members"]) >= {users["founder"]["id"], users["manager"]["id"], users["employee"]["id"],
                                  users["intern"]["id"], users["employee2"]["id"]}
    assert ch["members"][0] == users["founder"]["id"]
    r = call(api, users["founder"], "POST", "/connect/channels",
             json={"name": "nobody", "kind": "channel", "departments": ["No Such Dept"]})
    assert r.status_code == 422


def test_add_department_and_list_members(api, users):
    ch = _channel(api, users["manager"], kind="group")
    r = call(api, users["manager"], "POST", f"/connect/channels/{ch['id']}/members", json={"departments": ["Sales"]})
    assert r.status_code == 200, r.text
    assert users["employee2"]["id"] in r.json()["members"]
    r = call(api, users["employee2"], "GET", f"/connect/channels/{ch['id']}/members")
    assert r.status_code == 200
    members = r.json()
    assert members[0]["id"] == users["manager"]["id"] and members[0]["is_admin"] and members[0]["is_creator"]
    assert {m["id"] for m in members} == {users["manager"]["id"], users["employee2"]["id"]}


def test_remove_and_leave_members(api, users, test_db):
    mgr, emp, emp2 = users["manager"], users["employee"], users["employee2"]
    ch = _channel(api, mgr, kind="channel", members=[emp["id"], emp2["id"]])
    path = f"/connect/channels/{ch['id']}/members"
    # plain members cannot remove others
    assert call(api, emp, "DELETE", f"{path}/{emp2['id']}").status_code == 403
    # admin removes a member -> they lose access and are notified
    r = call(api, mgr, "DELETE", f"{path}/{emp2['id']}")
    assert r.status_code == 200, r.text
    assert emp2["id"] not in r.json()["members"]
    assert call(api, emp2, "GET", f"/connect/channels/{ch['id']}/messages").status_code == 403
    assert test_db.notifications.find_one({"user_id": emp2["id"], "title": "Removed from channel"})
    assert call(api, mgr, "DELETE", f"{path}/{emp2['id']}").status_code == 404
    # Admin can remove the creator; the remaining member is promoted so the channel keeps an admin
    r = call(api, users["admin"], "DELETE", f"{path}/{mgr['id']}")
    assert r.status_code == 200
    assert r.json()["admins"] == [emp["id"]]
    # a member can leave
    assert call(api, emp, "DELETE", f"{path}/{emp['id']}").status_code == 200
    assert call(api, emp, "GET", f"/connect/channels/{ch['id']}/messages").status_code == 403


def test_department_group_membership_rules(api, users, test_db):
    gid = str(test_db.channels.insert_one({
        "name": "Tech Group", "kind": "group", "department": "Tech", "description": None,
        "members": [users["manager"]["id"], users["employee"]["id"]], "created_by": "system",
        "created_at": "2025-01-01T00:00:00+00:00", "last_message_at": "2025-01-01T00:00:00+00:00",
    }).inserted_id)
    path = f"/connect/channels/{gid}/members"
    # scoped to the department: outsiders cannot read it
    assert call(api, users["employee2"], "GET", f"/connect/channels/{gid}/messages").status_code == 403
    # members (even Managers) cannot manage or leave it; Founder/Admin can
    assert call(api, users["manager"], "POST", path, json={"member_ids": [users["employee2"]["id"]]}).status_code == 403
    assert call(api, users["employee"], "DELETE", f"{path}/{users['employee']['id']}").status_code == 400
    assert call(api, users["founder"], "POST", path, json={"member_ids": [users["employee2"]["id"]]}).status_code == 200
    assert call(api, users["founder"], "DELETE", f"{path}/{users['employee2']['id']}").status_code == 200


# ------------------------- Connect: admins, conversion, manage-all -------------------------

def test_promote_and_demote_admins(api, users, test_db):
    mgr, emp, emp2 = users["manager"], users["employee"], users["employee2"]
    ch = _channel(api, mgr, kind="group", members=[emp["id"], emp2["id"]])
    base = f"/connect/channels/{ch['id']}/admins"
    # plain members cannot promote; non-members cannot be promoted
    assert call(api, emp, "POST", f"{base}/{emp2['id']}").status_code == 403
    assert call(api, mgr, "POST", f"{base}/{users['intern']['id']}").status_code == 404
    # creator promotes a member -> they can now manage, and are notified
    r = call(api, mgr, "POST", f"{base}/{emp['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["admins"] == [mgr["id"], emp["id"]]
    assert _listed(api, emp, ch["id"])["can_manage"] is True
    assert test_db.notifications.find_one({"user_id": emp["id"], "title": "You're now an admin"})
    assert test_db.activity_logs.find_one({"action": "Promoted channel admin", "target": ch["name"]})
    members = call(api, emp2, "GET", f"/connect/channels/{ch['id']}/members").json()
    assert {m["id"] for m in members if m["is_admin"]} == {mgr["id"], emp["id"]}
    # promoting twice is a no-op
    assert call(api, mgr, "POST", f"{base}/{emp['id']}").json()["admins"] == [mgr["id"], emp["id"]]
    # a promoted admin cannot demote the creator; Founder/Admin can
    assert call(api, emp, "DELETE", f"{base}/{mgr['id']}").status_code == 403
    assert call(api, emp, "DELETE", f"{base}/{emp2['id']}").status_code == 404  # not an admin
    r = call(api, users["admin"], "DELETE", f"{base}/{mgr['id']}")
    assert r.status_code == 200 and r.json()["admins"] == [emp["id"]]
    # the creator is still a member but no longer manages the group
    assert _listed(api, mgr, ch["id"])["can_manage"] is False
    # never zero admins: the last admin cannot step down, even via Founder
    assert call(api, emp, "DELETE", f"{base}/{emp['id']}").status_code == 400
    assert call(api, users["founder"], "DELETE", f"{base}/{emp['id']}").status_code == 400
    # an admin can demote themselves once someone else is admin
    assert call(api, emp, "POST", f"{base}/{emp2['id']}").status_code == 200
    r = call(api, emp, "DELETE", f"{base}/{emp['id']}")
    assert r.status_code == 200 and r.json()["admins"] == [emp2["id"]]
    # not for public channels
    legacy = _legacy_channel(test_db, users["founder"])
    r = call(api, users["founder"], "POST", f"/connect/channels/{legacy}/admins/{users['founder']['id']}")
    assert r.status_code == 400


def test_promote_in_legacy_admin_less_doc(api, users, test_db):
    """Groups stored before `admins` existed fall back to the creator; promoting keeps the creator."""
    mgr, emp = users["manager"], users["employee"]
    gid = str(test_db.channels.insert_one({
        "name": f"old-{_uid()}", "kind": "group", "members": [mgr["id"], emp["id"]], "created_by": mgr["id"],
        "created_at": "2025-01-01T00:00:00+00:00", "last_message_at": "2025-01-01T00:00:00+00:00",
    }).inserted_id)
    r = call(api, mgr, "POST", f"/connect/channels/{gid}/admins/{emp['id']}")
    assert r.status_code == 200 and r.json()["admins"] == [mgr["id"], emp["id"]]


def test_convert_legacy_channel_to_members_only(api, users, test_db):
    f, emp2, intern = users["founder"], users["employee2"], users["intern"]
    cid = str(test_db.channels.insert_one({
        "name": f"legacy-{_uid()}", "kind": "channel", "description": None, "members": [emp2["id"]],
        "created_by": users["manager"]["id"], "created_at": "2025-01-01T00:00:00+00:00",
        "last_message_at": "2025-01-01T00:00:00+00:00",
    }).inserted_id)
    path = f"/connect/channels/{cid}/members-only"
    # only Founder/Admin
    assert call(api, users["manager"], "POST", path).status_code == 403
    assert call(api, users["employee"], "POST", path).status_code == 403
    assert call(api, f, "POST", path, json={"departments": ["No Such Dept"]}).status_code == 422
    r = call(api, f, "POST", path, json={"departments": ["Sales"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["members_only"] is True and out["admins"] == [users["manager"]["id"]]
    assert out["members"][0] == users["manager"]["id"] and emp2["id"] in out["members"]
    assert f["id"] not in out["members"]  # converting doesn't make the Founder a member
    # outsiders lose access; members keep it
    assert _listed(api, intern, cid) is None
    assert call(api, intern, "POST", f"/connect/channels/{cid}/join").status_code == 403
    assert call(api, intern, "GET", f"/connect/channels/{cid}/messages").status_code == 403
    _post(api, emp2, cid, "still here")
    assert _listed(api, users["manager"], cid)["can_manage"] is True
    assert test_db.activity_logs.find_one({"action": "Made channel members-only"})
    # already members-only / wrong kinds / unknown
    assert call(api, f, "POST", path).status_code == 400
    ann = _channel(api, f, kind="announcement")
    assert call(api, users["admin"], "POST", f"/connect/channels/{ann['id']}/members-only").status_code == 400
    assert call(api, f, "POST", f"/connect/channels/{ObjectId()}/members-only").status_code == 404


def test_convert_system_channel_makes_converter_admin(api, users, test_db):
    cid = str(test_db.channels.insert_one({
        "name": f"general-{_uid()}", "kind": "channel", "members": [users["employee"]["id"]],
        "created_by": "system", "created_at": "2025-01-01T00:00:00+00:00",
        "last_message_at": "2025-01-01T00:00:00+00:00",
    }).inserted_id)
    r = call(api, users["admin"], "POST", f"/connect/channels/{cid}/members-only")
    assert r.status_code == 200, r.text
    assert r.json()["admins"] == [users["admin"]["id"]]
    assert set(r.json()["members"]) == {users["employee"]["id"], users["admin"]["id"]}


def test_manage_all_channels_is_metadata_only(api, users, test_db):
    f = users["founder"]
    ch = _channel(api, users["manager"], kind="group", members=[users["employee"]["id"]])
    _post(api, users["employee"], ch["id"], "secret plans")
    legacy = _legacy_channel(test_db, users["manager"])
    dm = call(api, users["manager"], "POST", f"/connect/dm/{users['employee']['id']}").json()
    for role in ("manager", "employee", "intern"):
        assert call(api, users[role], "GET", "/connect/manage/channels").status_code == 403
    r = call(api, f, "GET", "/connect/manage/channels")
    assert r.status_code == 200, r.text
    rows = {c["id"]: c for c in r.json()}
    assert dm["id"] not in rows
    row = rows[ch["id"]]
    assert row["is_member"] is False and row["can_manage"] is True and row["member_count"] == 2
    assert row["admins"] == [users["manager"]["id"]] and row["can_convert"] is False
    assert rows[legacy]["can_convert"] is True and rows[legacy]["members_only"] is False
    assert "secret plans" not in r.text and "last_body" not in row and "members" not in row
    # Founder can see the member list and change admins without being a member...
    members = call(api, f, "GET", f"/connect/channels/{ch['id']}/members")
    assert members.status_code == 200
    assert {m["id"] for m in members.json()} == {users["manager"]["id"], users["employee"]["id"]}
    r = call(api, f, "POST", f"/connect/channels/{ch['id']}/admins/{users['employee']['id']}")
    assert r.status_code == 200 and r.json()["can_manage"] is True
    assert "secret plans" not in r.text and "last_body" not in r.json()  # no preview for non-members
    # ...but still cannot read, post or mark read
    assert call(api, f, "GET", f"/connect/channels/{ch['id']}/messages").status_code == 403
    assert call(api, f, "POST", f"/connect/channels/{ch['id']}/messages", json={"body": "hi"}).status_code == 403
    assert call(api, f, "POST", f"/connect/channels/{ch['id']}/read").status_code == 403
    # outsiders still can't list members
    assert call(api, users["intern"], "GET", f"/connect/channels/{ch['id']}/members").status_code == 403


# ------------------------- Connect: unread -------------------------

def test_unread_counts_and_read_cursor(api, users):
    group = _channel(api, users["founder"], kind="group", members=[users["employee"]["id"]])
    emp = users["employee"]
    assert _listed(api, emp, group["id"])["unread"] == 0

    _post(api, users["founder"], group["id"], "one")
    _post(api, users["founder"], group["id"], "two")
    listed = _listed(api, emp, group["id"])
    assert listed["unread"] == 2
    assert listed["last_body"] == "two"
    # the sender's own messages never count as unread
    assert _listed(api, users["founder"], group["id"])["unread"] == 0

    assert call(api, emp, "POST", f"/connect/channels/{group['id']}/read").status_code == 200
    assert _listed(api, emp, group["id"])["unread"] == 0

    _post(api, emp, group["id"], "mine")
    assert _listed(api, emp, group["id"])["unread"] == 0
    _post(api, users["founder"], group["id"], "three")
    assert _listed(api, emp, group["id"])["unread"] == 1


# ------------------------- Marketplace helpers -------------------------

def _mk(api, users, resource, **fields):
    r = call(api, users["founder"], "POST", f"/marketplace/{resource}", json=fields)
    assert r.status_code == 201, r.text
    return r.json()


def _setup_fleet(api, users, city=None):
    city = city or f"City-{_uid()}"
    _mk(api, users, "cities", name=city)
    vendor = _mk(api, users, "vendors", name=f"Vendor {_uid()}", city=city)
    vehicle = _mk(api, users, "vehicles", model="Ather 450X", plate=f"BR{_uid()}", city=city,
                  vendor_id=vendor["id"])
    customer = _mk(api, users, "customers", name=f"Cust {_uid()}", email=f"c{_uid()}@example.com", city=city)
    return city, vendor, vehicle, customer


def _booking_body(city, vehicle, customer, hours=24, **extra):
    start = datetime.now(timezone.utc)
    return {"customer_id": customer["id"], "vehicle_id": vehicle["id"], "city": city,
            "start_time": start.isoformat(), "end_time": (start + timedelta(hours=hours)).isoformat(),
            "amount": 399, **extra}


def _vehicle_status(test_db, vehicle):
    return test_db.vehicles.find_one({"_id": ObjectId(vehicle["id"])})["status"]


# ------------------------- Marketplace: validation -------------------------

def test_marketplace_is_founder_only(api, users):
    for role in ("admin", "manager", "employee"):
        assert call(api, users[role], "GET", "/marketplace/cities").status_code == 403
    city = _mk(api, users, "cities", name=f"Del-{_uid()}")
    assert call(api, users["admin"], "DELETE", f"/marketplace/cities/{city['id']}").status_code == 403
    assert call(api, users["founder"], "DELETE", f"/marketplace/cities/{city['id']}").status_code == 200
    assert call(api, users["founder"], "DELETE", f"/marketplace/cities/{city['id']}").status_code == 404


def test_create_validates_and_drops_server_fields(api, users):
    r = call(api, users["founder"], "POST", "/marketplace/customers", json={"name": "No email", "city": "Patna"})
    assert r.status_code == 422
    r = call(api, users["founder"], "POST", "/marketplace/coupons", json={"code": "BAD", "discount_pct": 150})
    assert r.status_code == 422
    r = call(api, users["founder"], "POST", "/marketplace/vehicles",
             json={"model": "X", "plate": "P1", "city": "Patna", "kind": "car"})
    assert r.status_code == 422

    vendor = _mk(api, users, "vendors", name="Fresh Vendor", city="Patna", email="",
                 rating=4.9, kyc_status="approved", _id="abc", created_at="1999-01-01")
    assert vendor["rating"] is None
    assert vendor["kyc_status"] == "pending"
    assert vendor["email"] is None
    assert not vendor["created_at"].startswith("1999")

    customer = _mk(api, users, "customers", name="Kyc Skip", email="k@example.com", city="Patna",
                   kyc_status="approved")
    assert customer["kyc_status"] == "pending"

    coupon = _mk(api, users, "coupons", code=f"C{_uid()}", used_count=50)
    assert coupon["used_count"] == 0


def test_update_is_partial_and_allow_listed(api, users):
    coupon = _mk(api, users, "coupons", code=f"U{_uid()}", discount_pct=15)
    path = f"/marketplace/coupons/{coupon['id']}"
    r = call(api, users["founder"], "PATCH", path,
             json={**coupon, "used_count": 99, "discount_pct": 20, "created_at": "1999-01-01"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discount_pct"] == 20 and body["used_count"] == 0
    assert body["created_at"] == coupon["created_at"]
    assert body["code"] == coupon["code"]

    assert call(api, users["founder"], "PATCH", path, json={"discount_pct": 500}).status_code == 422
    assert call(api, users["founder"], "PATCH", path, json={"code": ""}).status_code == 422

    customer = _mk(api, users, "customers", name="Patchy", email="p@example.com", city="Patna")
    r = call(api, users["founder"], "PATCH", f"/marketplace/customers/{customer['id']}",
             json={"kyc_status": "approved", "phone": "+91 1"})
    assert r.status_code == 200
    assert r.json()["kyc_status"] == "pending" and r.json()["phone"] == "+91 1"

    vendor = _mk(api, users, "vendors", name="Rated", city="Patna")
    r = call(api, users["founder"], "PATCH", f"/marketplace/vendors/{vendor['id']}", json={"rating": 5})
    assert r.status_code == 200 and r.json()["rating"] is None

    assert call(api, users["founder"], "PATCH", f"/marketplace/vendors/{ObjectId()}",
                json={"name": "x"}).status_code == 404


def test_vendor_rating_follows_reviews(api, users):
    vendor = _mk(api, users, "vendors", name=f"Reviewed {_uid()}", city="Patna")
    r1 = _mk(api, users, "reviews", customer_name="A", vendor_name=vendor["name"], rating=4)
    _mk(api, users, "reviews", customer_name="B", vendor_id=vendor["id"], rating=5)
    got = call(api, users["founder"], "GET", f"/marketplace/vendors/{vendor['id']}").json()
    assert got["rating"] == 4.5
    assert call(api, users["founder"], "DELETE", f"/marketplace/reviews/{r1['id']}").status_code == 200
    got = call(api, users["founder"], "GET", f"/marketplace/vendors/{vendor['id']}").json()
    assert got["rating"] == 5


def test_search_query_is_escaped(api, users):
    _mk(api, users, "cities", name="Weird (city)+")
    r = call(api, users["founder"], "GET", "/marketplace/cities", params={"q": "(city)+"})
    assert r.status_code == 200
    assert [c["name"] for c in r.json()] == ["Weird (city)+"]
    assert call(api, users["founder"], "GET", "/marketplace/cities", params={"q": "[("}).status_code == 200


def test_kyc_and_support_patch_404(api, users):
    missing = str(ObjectId())
    assert call(api, users["founder"], "PATCH", f"/marketplace/kyc/{missing}", json={"status": "approved"}).status_code == 404
    assert call(api, users["founder"], "PATCH", f"/marketplace/support/{missing}", json={"status": "resolved"}).status_code == 404


def test_kyc_create_and_support_flow(api, users, test_db):
    _, _, _, customer = _setup_fleet(api, users)
    r = call(api, users["founder"], "POST", "/marketplace/kyc", json={
        "subject_type": "customer", "subject_id": customer["id"], "subject_name": "spoofed",
        "doc_type": "pan", "status": "approved"})
    assert r.status_code == 201, r.text
    kyc = r.json()
    assert kyc["status"] == "pending" and kyc["subject_name"] == customer["name"]
    r = call(api, users["founder"], "POST", "/marketplace/kyc", json={
        "subject_type": "vendor", "subject_id": str(ObjectId()), "subject_name": "x"})
    assert r.status_code == 400
    r = call(api, users["founder"], "PATCH", f"/marketplace/kyc/{kyc['id']}", json={"status": "approved"})
    assert r.status_code == 200
    assert test_db.customers.find_one({"_id": ObjectId(customer["id"])})["kyc_status"] == "approved"

    ticket = _mk(api, users, "support", subject="Help", description="Stuck", customer_id=customer["id"])
    assert ticket["customer_name"] == customer["name"]
    path = f"/marketplace/support/{ticket['id']}"
    assert call(api, users["founder"], "PATCH", path, json={"status": "bogus"}).status_code == 422
    r = call(api, users["founder"], "PATCH", path, json={"status": "resolved", "created_at": "x"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved" and r.json()["created_at"] == ticket["created_at"]


# ------------------------- Marketplace: revenue -------------------------

def test_revenue_excludes_pending_and_cancelled(api, users, test_db):
    base = call(api, users["founder"], "GET", "/marketplace/dashboard").json()["totals"]["revenue"]
    city = f"Rev-{_uid()}"
    for status, amount in (("completed", 100), ("active", 200), ("confirmed", 300),
                           ("pending", 5000), ("cancelled", 7000)):
        test_db.bookings.insert_one({"city": city, "status": status, "amount": amount,
                                     "created_at": datetime.now(timezone.utc).isoformat()})
    totals = call(api, users["founder"], "GET", "/marketplace/dashboard").json()["totals"]
    assert totals["revenue"] == base + 600
    analytics = call(api, users["founder"], "GET", "/marketplace/analytics").json()
    row = next((c for c in analytics["by_city"] if c["city"] == city), None)
    if row:  # only top-10 cities are returned
        assert row["revenue"] == 600 and row["bookings"] == 5


# ------------------------- Marketplace: bookings -------------------------

def test_booking_validation(api, users):
    city, _, vehicle, customer = _setup_fleet(api, users)
    r = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body("Elsewhere", vehicle, customer))
    assert r.status_code == 400 and "city" in r.text
    r = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, hours=-1))
    assert r.status_code == 400
    r = call(api, users["founder"], "POST", "/marketplace/bookings",
             json={**_booking_body(city, vehicle, customer), "start_time": "not-a-date"})
    assert r.status_code == 422
    r = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, amount=-5))
    assert r.status_code == 422
    call(api, users["founder"], "PATCH", f"/marketplace/vehicles/{vehicle['id']}", json={"status": "maintenance"})
    r = call(api, users["founder"], "POST", "/marketplace/bookings", json=_booking_body(city, vehicle, customer))
    assert r.status_code == 409


def test_booking_status_drives_vehicle_status(api, users, test_db):
    city, _, vehicle, customer = _setup_fleet(api, users)
    r = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, status="pending"))
    assert r.status_code == 201, r.text
    booking = r.json()
    assert _vehicle_status(test_db, vehicle) == "available"

    path = f"/marketplace/bookings/{booking['id']}/status"
    assert call(api, users["founder"], "PATCH", path, json={"status": "confirmed"}).status_code == 200
    assert _vehicle_status(test_db, vehicle) == "booked"
    # a booked vehicle cannot be booked again
    r = call(api, users["founder"], "POST", "/marketplace/bookings", json=_booking_body(city, vehicle, customer))
    assert r.status_code == 409

    assert call(api, users["founder"], "PATCH", path, json={"status": "active"}).status_code == 200
    assert _vehicle_status(test_db, vehicle) == "booked"
    assert call(api, users["founder"], "PATCH", path, json={"status": "completed"}).status_code == 200
    assert _vehicle_status(test_db, vehicle) == "available"
    # terminal states stay terminal
    assert call(api, users["founder"], "PATCH", path, json={"status": "active"}).status_code == 400

    r = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, status="confirmed"))
    assert r.status_code == 201
    assert _vehicle_status(test_db, vehicle) == "booked"
    r2 = call(api, users["founder"], "PATCH", f"/marketplace/bookings/{r.json()['id']}/status",
              json={"status": "cancelled"})
    assert r2.status_code == 200
    assert _vehicle_status(test_db, vehicle) == "available"


def test_second_pending_booking_cannot_take_held_vehicle(api, users, test_db):
    city, _, vehicle, customer = _setup_fleet(api, users)
    a = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, status="pending")).json()
    b = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, status="pending")).json()
    assert call(api, users["founder"], "PATCH", f"/marketplace/bookings/{a['id']}/status",
                json={"status": "confirmed"}).status_code == 200
    assert call(api, users["founder"], "PATCH", f"/marketplace/bookings/{b['id']}/status",
                json={"status": "confirmed"}).status_code == 409
    # maintenance vehicles keep their status when a booking ends
    test_db.vehicles.update_one({"_id": ObjectId(vehicle["id"])}, {"$set": {"status": "maintenance"}})
    assert call(api, users["founder"], "PATCH", f"/marketplace/bookings/{a['id']}/status",
                json={"status": "cancelled"}).status_code == 200
    assert _vehicle_status(test_db, vehicle) == "maintenance"


# ------------------------- coupons on bookings -------------------------

def test_booking_coupon_redeemed_and_limited(api, users, test_db):
    from bson import ObjectId
    city = f"CouponCity{uuid.uuid4().hex[:5]}"
    test_db.cities.insert_one({"name": city, "state": "Bihar", "status": "active"})
    cust = test_db.customers.insert_one({"name": "Coupon Customer", "phone": "9000000000", "city": city}).inserted_id
    vehicles = [test_db.vehicles.insert_one({"model": "Activa", "plate": f"BR01C{i}{uuid.uuid4().hex[:3]}", "city": city,
                                             "status": "available", "type": "scooter"}).inserted_id for i in range(3)]
    code = f"T{uuid.uuid4().hex[:6].upper()}"
    test_db.coupons.insert_one({"code": code, "discount_pct": 10, "usage_limit": 1, "used_count": 0, "active": True})

    def book(vehicle_id, coupon):
        return call(api, users["founder"], "POST", "/marketplace/bookings", json={
            "customer_id": str(cust), "vehicle_id": str(vehicle_id), "city": city, "amount": 500,
            "status": "confirmed", "coupon_code": coupon,
            "start_time": "2031-01-01T10:00:00+05:30", "end_time": "2031-01-02T10:00:00+05:30"})

    r = book(vehicles[0], code.lower())
    assert r.status_code == 201, r.text
    saved = test_db.bookings.find_one({"_id": ObjectId(r.json()["id"])})
    assert saved["coupon_code"] == code
    # 10% off a ₹500 price: the customer pays ₹450, and that is the booking amount.
    assert (saved["gross_amount"], saved["discount_amount"], saved["amount"]) == (500, 50, 450)
    assert test_db.coupons.find_one({"code": code})["used_count"] == 1
    assert book(vehicles[1], code).status_code == 409          # limit reached
    assert book(vehicles[2], "NOPE123").status_code == 400      # unknown coupon


# ------------------------- QA sweep regressions -------------------------

def test_connect_rejects_blank_names_and_messages(api, users):
    r = call(api, users["manager"], "POST", "/connect/channels", json={"name": "   ", "kind": "channel"})
    assert r.status_code == 422
    ch = _channel(api, users["manager"], name="  trimmed-name  ", kind="channel", description="  ")
    assert ch["name"] == "trimmed-name" and ch["description"] is None
    r = call(api, users["manager"], "POST", f"/connect/channels/{ch['id']}/messages", json={"body": "  \n "})
    assert r.status_code == 422
    msg = _post(api, users["manager"], ch["id"], "  padded  ")
    assert msg["body"] == "padded"


def test_dm_with_deactivated_user_is_refused(api, users, test_db):
    uid = test_db.users.insert_one({"email": f"gone{_uid()}@example.com", "name": "Gone User", "role": "Manager",
                                    "status": "deactivated", "is_active": False}).inserted_id
    assert call(api, users["founder"], "POST", f"/connect/dm/{uid}").status_code == 404


def test_natural_keys_are_unique_and_coupon_codes_uppercased(api, users):
    name = f"Uniq-{_uid()}"
    _mk(api, users, "cities", name=name)
    assert call(api, users["founder"], "POST", "/marketplace/cities", json={"name": name.lower()}).status_code == 409
    other = _mk(api, users, "cities", name=f"Other-{_uid()}")
    r = call(api, users["founder"], "PATCH", f"/marketplace/cities/{other['id']}", json={"name": name.upper()})
    assert r.status_code == 409
    # re-saving a document with its own key is fine
    assert call(api, users["founder"], "PATCH", f"/marketplace/cities/{other['id']}",
                json={"name": other["name"]}).status_code == 200

    coupon = _mk(api, users, "coupons", code=f"lower{_uid()}")
    assert coupon["code"] == coupon["code"].upper()
    assert call(api, users["founder"], "POST", "/marketplace/coupons",
                json={"code": coupon["code"].lower()}).status_code == 409

    _, _, vehicle, _ = _setup_fleet(api, users)
    r = call(api, users["founder"], "POST", "/marketplace/vehicles",
             json={"model": "Dup", "plate": vehicle["plate"].lower(), "city": vehicle["city"]})
    assert r.status_code == 409


def test_vehicle_status_is_owned_by_bookings(api, users, test_db):
    city, _, vehicle, customer = _setup_fleet(api, users)
    path = f"/marketplace/vehicles/{vehicle['id']}"
    # a free vehicle cannot be marked booked by hand (nor created booked)
    assert call(api, users["founder"], "PATCH", path, json={"status": "booked"}).status_code == 400
    r = call(api, users["founder"], "POST", "/marketplace/vehicles",
             json={"model": "X", "plate": f"BK{_uid()}", "city": city, "status": "booked"})
    assert r.status_code == 400
    booking = call(api, users["founder"], "POST", "/marketplace/bookings",
                   json=_booking_body(city, vehicle, customer, status="confirmed")).json()
    assert _vehicle_status(test_db, vehicle) == "booked"
    # while held: no manual status change, no delete; other edits still work
    assert call(api, users["founder"], "PATCH", path, json={"status": "available"}).status_code == 409
    assert call(api, users["founder"], "PATCH", path, json={"status": "maintenance"}).status_code == 409
    assert call(api, users["founder"], "DELETE", path).status_code == 409
    r = call(api, users["founder"], "PATCH", path, json={"daily_rate": 500, "status": "booked"})
    assert r.status_code == 200 and r.json()["daily_rate"] == 500
    assert call(api, users["founder"], "PATCH", f"/marketplace/bookings/{booking['id']}/status",
                json={"status": "cancelled"}).status_code == 200
    assert _vehicle_status(test_db, vehicle) == "available"
    assert call(api, users["founder"], "PATCH", path, json={"status": "maintenance"}).status_code == 200
    assert call(api, users["founder"], "DELETE", path).status_code == 200


def test_booking_transitions_are_enforced(api, users, test_db):
    city, _, vehicle, customer = _setup_fleet(api, users)
    b = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, status="active")).json()
    path = f"/marketplace/bookings/{b['id']}/status"
    # an active (started) booking can only complete
    for bad in ("pending", "confirmed", "cancelled"):
        assert call(api, users["founder"], "PATCH", path, json={"status": bad}).status_code == 400
    assert _vehicle_status(test_db, vehicle) == "booked"
    assert call(api, users["founder"], "PATCH", path, json={"status": "completed"}).status_code == 200
    # a pending booking cannot be confirmed onto a vehicle that went into maintenance
    p = call(api, users["founder"], "POST", "/marketplace/bookings",
             json=_booking_body(city, vehicle, customer, status="pending")).json()
    assert call(api, users["founder"], "PATCH", f"/marketplace/vehicles/{vehicle['id']}",
                json={"status": "maintenance"}).status_code == 200
    r = call(api, users["founder"], "PATCH", f"/marketplace/bookings/{p['id']}/status", json={"status": "confirmed"})
    assert r.status_code == 409 and "maintenance" in r.text
    assert _vehicle_status(test_db, vehicle) == "maintenance"
    assert call(api, users["founder"], "PATCH", f"/marketplace/bookings/{p['id']}/status",
                json={"status": "cancelled"}).status_code == 200


def test_review_by_vendor_id_carries_vendor_name(api, users):
    vendor = _mk(api, users, "vendors", name=f"Named {_uid()}", city="Patna")
    review = _mk(api, users, "reviews", customer_name="C", vendor_id=vendor["id"], vendor_name="typo", rating=3)
    assert review["vendor_name"] == vendor["name"]
    r = call(api, users["founder"], "POST", "/marketplace/reviews",
             json={"customer_name": "C", "vendor_id": str(ObjectId()), "rating": 4})
    assert r.status_code == 400
    assert call(api, users["founder"], "GET", f"/marketplace/vendors/{vendor['id']}").json()["rating"] == 3


def test_support_ticket_requires_subject_and_description(api, users):
    for body in ({"subject": "  ", "description": "x"}, {"subject": "x", "description": ""}, {"description": "x"}):
        assert call(api, users["founder"], "POST", "/marketplace/support", json=body).status_code == 422
    t = _mk(api, users, "support", subject=" Trim ", description="d")
    assert t["subject"] == "Trim"
    assert call(api, users["founder"], "PATCH", f"/marketplace/support/{t['id']}",
                json={"subject": " "}).status_code == 422


def test_today_bookings_use_ist_and_status_order(api, users, test_db):
    base = call(api, users["founder"], "GET", "/marketplace/dashboard").json()["totals"]["today_bookings"]
    ist = timezone(timedelta(hours=5, minutes=30))
    ist_midnight = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
    # just after IST midnight is "today" even though the UTC date is still yesterday
    for minutes in (1, -1):
        created = (ist_midnight + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat()
        test_db.bookings.insert_one({"status": "pending", "amount": 0, "city": "IST", "created_at": created})
    assert call(api, users["founder"], "GET", "/marketplace/dashboard").json()["totals"]["today_bookings"] == base + 1
    order = [s["status"] for s in call(api, users["founder"], "GET", "/marketplace/analytics").json()["by_status"]]
    lifecycle = ["pending", "confirmed", "active", "completed", "cancelled"]
    assert order == [s for s in lifecycle if s in order]


# ------------------------- Connect: edit / delete messages -------------------------

def _group_with(api, owner, *members):
    return _channel(api, owner, kind="group", members=[m["id"] for m in members])


def test_sender_can_edit_message(api, users):
    ch = _group_with(api, users["manager"], users["employee"])
    msg = _post(api, users["employee"], ch["id"], "helo")
    r = call(api, users["employee"], "PATCH", f"/connect/channels/{ch['id']}/messages/{msg['id']}", json={"body": " hello "})
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "hello" and r.json()["edited_at"]
    listed = call(api, users["manager"], "GET", f"/connect/channels/{ch['id']}/messages").json()
    assert listed[-1]["body"] == "hello" and listed[-1]["edited_at"]
    assert _listed(api, users["manager"], ch["id"])["last_body"] == "hello"


def test_only_sender_can_edit_and_body_required(api, users):
    ch = _group_with(api, users["manager"], users["employee"])
    msg = _post(api, users["employee"], ch["id"])
    path = f"/connect/channels/{ch['id']}/messages/{msg['id']}"
    assert call(api, users["manager"], "PATCH", path, json={"body": "hijack"}).status_code == 403
    assert call(api, users["founder"], "PATCH", path, json={"body": "hijack"}).status_code == 403
    assert call(api, users["employee"], "PATCH", path, json={"body": "   "}).status_code == 422
    # Outsiders can't even see the channel.
    assert call(api, users["employee2"], "PATCH", path, json={"body": "x"}).status_code in (403, 404)


def test_sender_can_delete_message(api, users):
    ch = _group_with(api, users["manager"], users["employee"])
    msg = _post(api, users["employee"], ch["id"], "oops secret")
    path = f"/connect/channels/{ch['id']}/messages/{msg['id']}"
    assert call(api, users["manager"], "DELETE", path).status_code == 403
    r = call(api, users["employee"], "DELETE", path)
    assert r.status_code == 200, r.text
    listed = call(api, users["manager"], "GET", f"/connect/channels/{ch['id']}/messages").json()
    assert listed[-1]["deleted"] is True and listed[-1]["body"] == ""
    assert _listed(api, users["manager"], ch["id"])["last_body"] == "Message deleted"
    # Deleted messages can't be edited or deleted again.
    assert call(api, users["employee"], "PATCH", path, json={"body": "back"}).status_code == 404
    assert call(api, users["employee"], "DELETE", path).status_code == 404


def test_founder_can_moderate_delete(api, users, test_db):
    ch = _group_with(api, users["founder"], users["employee"])
    msg = _post(api, users["employee"], ch["id"], "off-topic")
    r = call(api, users["founder"], "DELETE", f"/connect/channels/{ch['id']}/messages/{msg['id']}")
    assert r.status_code == 200, r.text
    assert test_db.activity_logs.find_one({"action": "Deleted message", "user_id": users["founder"]["id"]})


def test_edit_delete_unknown_message(api, users):
    ch = _group_with(api, users["manager"], users["employee"])
    for bad in ("nope", "0" * 24):
        assert call(api, users["employee"], "DELETE", f"/connect/channels/{ch['id']}/messages/{bad}").status_code == 404


def _backdate(test_db, message_id, minutes):
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    test_db.messages.update_one({"_id": ObjectId(message_id)}, {"$set": {"created_at": old}})


def test_messages_report_edit_window(api, users):
    ch = _group_with(api, users["manager"], users["employee"])
    msg = _post(api, users["employee"], ch["id"])
    assert msg["editable_until"] > msg["created_at"]


def test_edit_and_delete_blocked_after_window(api, users, test_db):
    ch = _group_with(api, users["founder"], users["employee"])
    msg = _post(api, users["employee"], ch["id"], "old news")
    _backdate(test_db, msg["id"], 16)
    path = f"/connect/channels/{ch['id']}/messages/{msg['id']}"
    r = call(api, users["employee"], "PATCH", path, json={"body": "rewrite"})
    assert r.status_code == 403 and "15 minutes" in r.text
    assert call(api, users["employee"], "DELETE", path).status_code == 403
    # Founder/Admin moderation has no time limit.
    assert call(api, users["founder"], "DELETE", path).status_code == 200


def test_edit_allowed_just_inside_window(api, users, test_db):
    ch = _group_with(api, users["manager"], users["employee"])
    msg = _post(api, users["employee"], ch["id"], "fresh")
    _backdate(test_db, msg["id"], 14)
    r = call(api, users["employee"], "PATCH", f"/connect/channels/{ch['id']}/messages/{msg['id']}", json={"body": "fresher"})
    assert r.status_code == 200, r.text
