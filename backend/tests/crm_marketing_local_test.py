"""CRM + Marketing API tests: RBAC, customer metrics (LTV, lifecycle), customer 360 timeline,
notes / tags / follow-ups, segments with live counts, campaign validation, derived status and
coupon attribution.

Runs against an isolated server and throwaway database (see local_harness.py).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from local_harness import api, mongo, test_db, users, harness_env, call  # noqa: F401

NOW = datetime.now(timezone.utc)
IST = timezone(timedelta(hours=5, minutes=30))


def _ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _day(offset: int) -> str:
    return (datetime.now(IST).date() + timedelta(days=offset)).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _customer(test_db, city, name=None, kyc="approved", created_days=30):
    _id = ObjectId()
    test_db.customers.insert_one({"_id": _id, "name": name or f"Cust {_uid()}", "email": f"{_uid()}@x.in",
                                  "phone": "+91 90000 00000", "city": city, "kyc_status": kyc,
                                  "created_at": _ago(created_days), "updated_at": _ago(created_days)})
    return str(_id)


def _booking(test_db, cid, days_ago, amount, status="completed", city="X", as_datetime=False, **extra):
    at = NOW - timedelta(days=days_ago)
    _id = ObjectId()
    test_db.bookings.insert_one({"_id": _id, "customer_id": cid, "customer_name": "n", "vehicle_label": "Ather · BR01",
                                 "city": city, "amount": amount, "status": status,
                                 "start_time": at.isoformat(), "end_time": (at + timedelta(hours=4)).isoformat(),
                                 "created_at": at if as_datetime else at.isoformat(), **extra})
    return str(_id)


@pytest.fixture(scope="module")
def city():
    return f"Harness-{_uid()}"


@pytest.fixture(scope="module")
def crowd(test_db, city):
    """lead / new / active / at_risk / churned customers in one city."""
    ids = {k: _customer(test_db, city, name=f"{k.title()} {_uid()}") for k in ("lead", "new", "active", "at_risk", "churned")}
    _booking(test_db, ids["new"], 10, 500)
    _booking(test_db, ids["new"], 5, 999, status="cancelled")          # ignored entirely
    _booking(test_db, ids["active"], 40, 1000)
    _booking(test_db, ids["active"], 3, 700, status="confirmed", as_datetime=True)
    _booking(test_db, ids["active"], 1, 300, status="pending")         # counts as booking, not LTV
    _booking(test_db, ids["at_risk"], 90, 400)
    _booking(test_db, ids["churned"], 200, 250)
    return ids


def _row(api, user, city, cid):
    r = call(api, user, "GET", "/crm/customers", params={"city": city, "page_size": 100})
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["items"] if x["id"] == cid)


# ------------------------- RBAC -------------------------

@pytest.mark.parametrize("who", ["employee", "intern"])
@pytest.mark.parametrize("method,path", [
    ("GET", "/crm/overview"), ("GET", "/crm/customers"), ("GET", "/crm/segments"), ("GET", "/crm/followups"),
    ("POST", "/crm/segments"), ("GET", "/marketing/overview"), ("GET", "/marketing/campaigns"),
    ("GET", "/marketing/meta"), ("POST", "/marketing/campaigns"),
])
def test_rbac_denied(api, users, who, method, path):
    r = call(api, users[who], method, path, json={})
    assert r.status_code == 403, (path, r.text)


@pytest.mark.parametrize("who", ["founder", "admin", "manager"])
def test_rbac_allowed(api, users, who):
    for path in ("/crm/overview", "/crm/customers", "/crm/meta", "/marketing/overview", "/marketing/campaigns"):
        assert call(api, users[who], "GET", path).status_code == 200, path


def test_unauthenticated(api):
    assert call(api, None, "GET", "/crm/customers").status_code == 401


# ------------------------- metrics -------------------------

def test_ltv_and_lifecycle(api, users, city, crowd):
    u = users["manager"]
    lead = _row(api, u, city, crowd["lead"])
    assert (lead["bookings"], lead["ltv"], lead["lifecycle"], lead["last_booking"]) == (0, 0, "lead", None)
    new = _row(api, u, city, crowd["new"])
    assert (new["bookings"], new["ltv"], new["lifecycle"]) == (1, 500, "new")
    active = _row(api, u, city, crowd["active"])
    assert (active["bookings"], active["ltv"], active["lifecycle"]) == (3, 1700, "active")
    assert active["days_since_last_booking"] == 1
    assert active["first_booking"] < active["last_booking"]
    assert _row(api, u, city, crowd["at_risk"])["lifecycle"] == "at_risk"
    assert _row(api, u, city, crowd["churned"])["lifecycle"] == "churned"


def test_filters_sort_pagination(api, users, city, crowd):
    u = users["admin"]
    r = call(api, u, "GET", "/crm/customers", params={"city": city, "sort": "ltv", "order": "desc"}).json()
    assert r["total"] == 5
    assert [x["id"] for x in r["items"]][:2] == [crowd["active"], crowd["new"]]
    r = call(api, u, "GET", "/crm/customers", params={"city": city, "sort": "last_booking", "order": "desc"}).json()
    assert r["items"][0]["id"] == crowd["active"] and r["items"][-1]["id"] == crowd["lead"]  # missing dates last
    r = call(api, u, "GET", "/crm/customers", params={"city": city, "lifecycle": "at_risk"}).json()
    assert [x["id"] for x in r["items"]] == [crowd["at_risk"]]
    r = call(api, u, "GET", "/crm/customers", params={"city": city, "page_size": 2, "page": 3}).json()
    assert (r["pages"], len(r["items"])) == (3, 1)
    # Search input is treated literally.
    r = call(api, u, "GET", "/crm/customers", params={"q": ".*("})
    assert r.status_code == 200 and r.json()["total"] == 0


def test_overview(api, users, crowd):
    body = call(api, users["founder"], "GET", "/crm/overview").json()
    stages = {s["stage"]: s["count"] for s in body["by_lifecycle"]}
    assert all(stages[k] >= 1 for k in ("lead", "new", "active", "at_risk", "churned"))
    assert len(body["new_customers"]) == 12
    assert body["totals"]["repeat_rate"] is not None
    assert body["top_customers"][0]["ltv"] >= body["top_customers"][-1]["ltv"]


# ------------------------- customer 360 -------------------------

def test_customer_360_timeline(api, users, test_db, city):
    u = users["manager"]
    cid = _customer(test_db, city, name=f"Timeline {_uid()}")
    bid = _booking(test_db, cid, 20, 800)
    test_db.support_tickets.insert_one({"subject": "Flat tyre", "description": "d", "priority": "high",
                                        "status": "open", "customer_id": cid, "created_at": _ago(15)})
    test_db.kyc_requests.insert_one({"subject_type": "customer", "subject_id": cid, "subject_name": "x",
                                     "doc_type": "aadhaar", "status": "approved",
                                     "created_at": _ago(12), "updated_at": _ago(11)})
    test_db.reviews.insert_one({"booking_id": bid, "customer_name": "someone else", "vendor_name": "V",
                                "rating": 4.0, "comment": "ok", "created_at": _ago(8)})
    r = call(api, u, "POST", f"/crm/customers/{cid}/notes", json={"body": "Called about renewal"})
    assert r.status_code == 201

    body = call(api, u, "GET", f"/crm/customers/{cid}").json()
    types = [i["type"] for i in body["timeline"]]
    assert types == ["note", "review", "kyc", "kyc", "ticket", "booking"]
    ats = [i["at"] for i in body["timeline"]]
    assert ats == sorted(ats, reverse=True)
    assert body["kpis"]["open_tickets"] == 1 and body["kpis"]["avg_rating"] == 4.0
    assert body["metrics"]["ltv"] == 800
    assert call(api, u, "GET", f"/crm/customers/{ObjectId()}").status_code == 404
    assert call(api, u, "GET", "/crm/customers/not-an-id").status_code == 404
    # Follow-ups show a readable due date in the timeline.
    assert call(api, u, "POST", f"/crm/customers/{cid}/followups",
                json={"title": "Check in", "due_date": "2030-01-05"}).status_code == 201
    fu = next(i for i in call(api, u, "GET", f"/crm/customers/{cid}").json()["timeline"] if i["type"] == "followup")
    assert fu["detail"].startswith("Due 5 Jan 2030 · ")


def test_notes_crud_and_ownership(api, users, test_db, city):
    cid = _customer(test_db, city)
    r = call(api, users["manager"], "POST", f"/crm/customers/{cid}/notes", json={"body": "  first  "})
    note = r.json()
    assert note["body"] == "first" and note["author_id"] == users["manager"]["id"] and note["pinned"] is False
    assert note["updated_at"] == note["created_at"]  # a new note is not "edited"
    assert call(api, users["manager"], "POST", f"/crm/customers/{cid}/notes", json={"body": ""}).status_code == 422
    r = call(api, users["manager"], "PATCH", f"/crm/notes/{note['id']}", json={"pinned": True})
    assert r.status_code == 200 and r.json()["pinned"] is True
    # Pinning (or saving an unchanged body) is not an edit: updated_at, which the UI shows as "edited", stays put.
    assert r.json()["updated_at"] == note["updated_at"]
    r = call(api, users["manager"], "PATCH", f"/crm/notes/{note['id']}", json={"body": "first"})
    assert r.status_code == 200 and r.json()["updated_at"] == note["updated_at"]
    assert test_db.activity_logs.find_one({"module": "CRM", "action": "Pinned customer note"})
    call(api, users["manager"], "POST", f"/crm/customers/{cid}/notes", json={"body": "second"})
    notes = call(api, users["admin"], "GET", f"/crm/customers/{cid}").json()["notes"]
    assert notes[0]["id"] == note["id"]  # pinned first
    # Another manager may not edit; an admin may.
    other = ObjectId()
    test_db.users.insert_one({"_id": other, "email": f"m2{other}@h.in", "name": "M2", "role": "Manager",
                              "status": "active", "is_active": True, "password_hash": "x"})
    from auth_utils import create_access_token
    m2 = {"headers": {"Authorization": f"Bearer {create_access_token(str(other), 'm2@h.in', 'Manager')}"}}
    assert call(api, m2, "PATCH", f"/crm/notes/{note['id']}", json={"body": "hack"}).status_code == 403
    edited = call(api, users["admin"], "PATCH", f"/crm/notes/{note['id']}", json={"body": "edited"}).json()
    assert edited["body"] == "edited" and edited["updated_at"] != note["updated_at"] and edited["pinned"] is True
    assert call(api, users["employee"], "DELETE", f"/crm/notes/{note['id']}").status_code == 403
    assert call(api, users["manager"], "DELETE", f"/crm/notes/{note['id']}").status_code == 200
    assert test_db.crm_notes.count_documents({"_id": ObjectId(note["id"])}) == 0
    assert test_db.activity_logs.count_documents({"module": "CRM", "action": "Deleted customer note"}) >= 1


def test_tags(api, users, test_db, city):
    cid = _customer(test_db, city)
    r = call(api, users["manager"], "PUT", f"/crm/customers/{cid}/tags", json={"tags": ["VIP", " vip ", "Corporate", ""]})
    assert r.json()["tags"] == ["VIP", "Corporate"]
    assert test_db.customers.find_one({"_id": ObjectId(cid)}).get("tags") is None  # marketplace doc untouched
    r = call(api, users["manager"], "GET", "/crm/customers", params={"tag": "vip", "city": city}).json()
    assert [x["id"] for x in r["items"]] == [cid]
    assert "VIP" in call(api, users["manager"], "GET", "/crm/meta").json()["tags"]
    assert call(api, users["manager"], "PUT", f"/crm/customers/{cid}/tags", json={"tags": ["x" * 40]}).status_code == 400


def test_followups(api, users, test_db, city):
    cid = _customer(test_db, city, name=f"Follow {_uid()}")
    admin, mgr = users["admin"], users["manager"]
    r = call(api, admin, "POST", f"/crm/customers/{cid}/followups",
             json={"title": "Renewal call", "due_date": _day(-1), "owner_id": mgr["id"]})
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["owner_name"] == mgr["name"] and f["overdue"] is True and f["done"] is False
    assert test_db.notifications.count_documents({"user_id": mgr["id"], "title": "CRM follow-up assigned",
                                                  "link": f"/crm?customer={cid}"}) == 1
    # Owners must have CRM access; dates must be valid.
    assert call(api, admin, "POST", f"/crm/customers/{cid}/followups",
                json={"title": "x", "due_date": _day(1), "owner_id": users["employee"]["id"]}).status_code == 400
    assert call(api, admin, "POST", f"/crm/customers/{cid}/followups",
                json={"title": "x", "due_date": "31-12-2030"}).status_code == 422
    mine = call(api, mgr, "GET", "/crm/followups", params={"mine": True}).json()
    assert f["id"] in [x["id"] for x in mine]
    r = call(api, mgr, "PATCH", f"/crm/followups/{f['id']}", json={"done": True})
    assert r.json()["done"] is True and r.json()["overdue"] is False
    assert test_db.notifications.count_documents({"user_id": admin["id"], "title": "CRM follow-up completed"}) == 1
    done = call(api, mgr, "GET", "/crm/followups", params={"status": "done"}).json()
    assert f["id"] in [x["id"] for x in done]
    timeline = call(api, mgr, "GET", f"/crm/customers/{cid}").json()["timeline"]
    assert [i["title"].split(":")[0] for i in timeline[:2]] == ["Follow-up completed", "Follow-up scheduled"]
    assert call(api, users["intern"], "PATCH", f"/crm/followups/{f['id']}", json={"done": False}).status_code == 403
    assert call(api, mgr, "DELETE", f"/crm/followups/{f['id']}").status_code == 200


# ------------------------- segments -------------------------

def test_segments_live_counts(api, users, test_db, city, crowd):
    u = users["manager"]
    name = f"Active {city}"
    r = call(api, u, "POST", "/crm/segments", json={"name": name, "filters": {"city": city, "lifecycle": "active"}})
    assert r.status_code == 201, r.text
    seg = r.json()
    assert seg["count"] == 1 and seg["ltv"] == 1700
    assert call(api, u, "POST", "/crm/segments", json={"name": name.upper(), "filters": {"city": city}}).status_code == 409
    assert call(api, u, "POST", "/crm/segments", json={"name": "Empty", "filters": {}}).status_code == 400
    # Live: a new active customer shows up without touching the segment.
    cid = _customer(test_db, city)
    _booking(test_db, cid, 2, 100)
    _booking(test_db, cid, 1, 100)
    listed = next(s for s in call(api, u, "GET", "/crm/segments").json() if s["id"] == seg["id"])
    assert listed["count"] == 2
    r = call(api, u, "GET", "/crm/customers", params={"segment_id": seg["id"]}).json()
    assert {x["id"] for x in r["items"]} == {crowd["active"], cid}
    r = call(api, u, "PATCH", f"/crm/segments/{seg['id']}", json={"filters": {"city": city, "lifecycle": "lead"}})
    assert r.json()["count"] >= 1
    assert call(api, u, "DELETE", f"/crm/segments/{seg['id']}").status_code == 200


# ------------------------- marketing: campaigns -------------------------

def _campaign(api, user, **fields):
    body = {"name": f"Camp {_uid()}", "objective": "acquisition", "channels": ["social"], "budget": 10000,
            "start_date": _day(-5), "end_date": _day(5), "mode": "live", **fields}
    r = call(api, user, "POST", "/marketing/campaigns", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="module")
def market(test_db):
    city = f"MktCity-{_uid()}"
    test_db.cities.insert_one({"name": city, "state": "Bihar", "status": "active"})
    code = f"SAVE{_uid()}".upper()
    test_db.coupons.insert_one({"code": code, "discount_pct": 10, "used_count": 7, "usage_limit": 100, "active": True})
    return {"city": city, "code": code}


def test_campaign_validation(api, users, market):
    u = users["manager"]
    base = {"name": "V", "channels": ["email"], "budget": 100, "start_date": _day(0), "end_date": _day(1)}
    post = lambda **kw: call(api, u, "POST", "/marketing/campaigns", json={**base, **kw})
    assert post(end_date=_day(-1)).status_code == 422
    assert post(budget=-1).status_code == 422
    assert post(channels=[]).status_code == 422
    assert post(channels=["telepathy"]).status_code == 422
    assert post(start_date="tomorrow").status_code == 422
    assert post(coupon_codes=["NOPE-XYZ"]).status_code == 400
    assert post(city_targets=["Atlantis"]).status_code == 400
    assert post(audience_segment_id=str(ObjectId())).status_code == 400
    assert post(owner_id=users["employee"]["id"]).status_code == 400
    c = _campaign(api, u, coupon_codes=[market["code"].lower()], city_targets=[market["city"].upper()])
    assert c["coupon_codes"] == [market["code"]] and c["city_targets"] == [market["city"]]
    assert c["owner_id"] == u["id"]
    r = call(api, u, "PATCH", f"/marketing/campaigns/{c['id']}", json={"end_date": _day(-10)})
    assert r.status_code == 400
    assert call(api, users["employee"], "PATCH", f"/marketing/campaigns/{c['id']}", json={"spend": 1}).status_code == 403


def test_campaign_derived_status(api, users, test_db):
    u = users["admin"]
    assert _campaign(api, u, start_date=_day(3), end_date=_day(9))["status"] == "scheduled"
    assert _campaign(api, u, start_date=_day(-9), end_date=_day(-1))["status"] == "completed"
    assert _campaign(api, u, start_date=_day(0), end_date=_day(0))["status"] == "active"
    assert _campaign(api, u, mode="draft")["status"] == "draft"
    c = _campaign(api, u, owner_id=users["manager"]["id"])
    assert test_db.notifications.count_documents({"user_id": users["manager"]["id"], "title": "Campaign assigned to you"}) >= 1
    r = call(api, u, "PATCH", f"/marketing/campaigns/{c['id']}", json={"mode": "paused"})
    assert r.json()["status"] == "paused"
    assert test_db.notifications.count_documents({"user_id": users["manager"]["id"], "title": "Campaign paused"}) == 1
    assert test_db.activity_logs.count_documents({"module": "Marketing", "action": "Paused campaign"}) >= 1
    r = call(api, u, "PATCH", f"/marketing/campaigns/{c['id']}", json={"spend": 12000})
    assert r.json()["over_budget"] is True and r.json()["budget_used_pct"] == 120.0
    listed = call(api, u, "GET", "/marketing/campaigns", params={"status": "paused"}).json()
    assert c["id"] in [x["id"] for x in listed] and all(x["status"] == "paused" for x in listed)


def test_attribution_unsupported_without_coupon_data(api, users, market):
    c = _campaign(api, users["manager"], coupon_codes=[market["code"]], spend=500)
    detail = call(api, users["manager"], "GET", f"/marketing/campaigns/{c['id']}").json()
    assert detail["attribution"]["supported"] is False and detail["attribution"]["revenue"] is None
    assert detail["attribution"]["reason"]
    assert detail["coupons"][0]["used_count"] == 7
    assert call(api, users["manager"], "GET", "/marketing/overview").json()["attribution"]["supported"] is False


def test_attribution_math(api, users, test_db, market):
    u = users["founder"]
    c = _campaign(api, u, coupon_codes=[market["code"]], city_targets=[market["city"]], spend=1000,
                  channels=["social", "email"], start_date=_day(-10), end_date=_day(0))
    cid = _customer(test_db, market["city"])
    _booking(test_db, cid, 2, 1500, city=market["city"], coupon_code=market["code"].lower())
    _booking(test_db, cid, 3, 2500, status="active", city=market["city"], coupon=market["code"])
    _booking(test_db, cid, 4, 900, status="cancelled", city=market["city"], coupon_code=market["code"])  # no revenue
    _booking(test_db, cid, 30, 5000, city=market["city"], coupon_code=market["code"])  # before window
    _booking(test_db, cid, 2, 7000, city=market["city"], coupon_code="OTHER")           # other coupon
    _booking(test_db, cid, 1, 600, city=market["city"])                                # no coupon
    d = call(api, u, "GET", f"/marketing/campaigns/{c['id']}").json()
    a = d["attribution"]
    assert a["supported"] is True
    assert (a["bookings"], a["all_bookings"], a["revenue"]) == (2, 3, 4000)
    assert a["cost_per_booking"] == 500 and a["roi"] == 300.0
    # Market context counts every revenue booking in the target city and window, coupon or not.
    assert d["market_context"]["bookings"] == 4 and d["market_context"]["revenue"] == 11600
    ov = call(api, u, "GET", "/marketing/overview").json()
    assert {"id": c["id"], "revenue": 4000} in [{"id": x["id"], "revenue": x["revenue"]} for x in ov["top_campaigns"]]
    by_channel = {x["channel"]: x["spend"] for x in ov["spend_by_channel"]}
    assert by_channel["email"] >= 500  # 1000 split evenly across two channels
    assert call(api, u, "DELETE", f"/marketing/campaigns/{c['id']}").status_code == 200
    assert call(api, u, "GET", f"/marketing/campaigns/{c['id']}").status_code == 404


def test_segment_in_use_cannot_be_deleted(api, users, city):
    u = users["manager"]
    seg = call(api, u, "POST", "/crm/segments", json={"name": f"Aud {_uid()}", "filters": {"city": city}}).json()
    c = _campaign(api, u, audience_segment_id=seg["id"])
    assert c["audience_segment_name"] == seg["name"]
    assert call(api, u, "GET", f"/marketing/campaigns/{c['id']}").json()["audience_size"] == seg["count"]
    assert call(api, u, "DELETE", f"/crm/segments/{seg['id']}").status_code == 409


def test_ensure_indexes_idempotent(mongo, test_db):
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from local_harness import MONGO_URL
    from routers import crm_router, marketing_router

    async def run():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[mongo.harness_db_name]
        for _ in range(2):
            await crm_router.ensure_indexes(db)
            await marketing_router.ensure_indexes(db)
        client.close()

    asyncio.run(run())
    assert "customer_id_1" in test_db.crm_profiles.index_information()
    assert "owner_id_1" in test_db.campaigns.index_information()
