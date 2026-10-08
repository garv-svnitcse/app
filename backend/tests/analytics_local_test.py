from __future__ import annotations
"""Analytics API tests — RBAC and scoping (marketplace analytics Founder-only, Managers
locked to their department), cohort / retention math on a hand-built dataset, IST month
boundaries, period-over-period KPIs, utilisation, city drill-down, funnel, heatmap,
operations aggregates and CSV export.

Runs against an isolated server and throwaway database (see local_harness.py).
"""
import csv
import io
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from bson import ObjectId

from local_harness import api, mongo, test_db, users, harness_env, call  # noqa: F401

IST = ZoneInfo("Asia/Kolkata")
MARCH = {"from": "2026-03-01", "to": "2026-03-31"}


def ist(y, m, d, h=0, mi=0) -> str:
    """ISO string (UTC) for an IST wall-clock time — how the app stores timestamps."""
    return datetime(y, m, d, h, mi, tzinfo=IST).astimezone(timezone.utc).isoformat()


def booking(customer, created, status, amount, city, vehicle=None, vendor=None, start=None, end=None):
    return {"customer_id": customer, "customer_name": customer, "city": city, "status": status,
            "amount": amount, "created_at": created, "updated_at": created,
            "vehicle_id": vehicle, "vendor_id": vendor,
            "start_time": start or created, "end_time": end or created}


@pytest.fixture(scope="module")
def data(test_db, users):
    for c in ("bookings", "vehicles", "vendors", "customers", "cities", "tasks", "opportunities",
              "attendance", "leave_requests", "calendar_events"):
        test_db[c].delete_many({})

    vendor_a, vendor_b = ObjectId(), ObjectId()
    test_db.vendors.insert_many([
        {"_id": vendor_a, "name": "Vendor A", "city": "Gaya", "rating": 4.5},
        {"_id": vendor_b, "name": "Vendor B", "city": "Gaya", "rating": 4.1},
    ])
    v1, v2, v3 = ObjectId(), ObjectId(), ObjectId()
    test_db.vehicles.insert_many([
        {"_id": v1, "model": "Ather", "plate": "BR01", "kind": "scooter", "city": "Gaya", "vendor_id": str(vendor_a),
         "status": "available", "created_at": ist(2026, 1, 1)},
        {"_id": v2, "model": "Hero", "plate": "BR02", "kind": "bike", "city": "Gaya", "vendor_id": str(vendor_b),
         "status": "available", "created_at": ist(2026, 3, 16)},
        {"_id": v3, "model": "Old", "plate": "BR03", "kind": "bike", "city": "Gaya", "vendor_id": str(vendor_b),
         "status": "retired", "created_at": ist(2025, 1, 1)},
    ])
    test_db.cities.insert_many([{"name": "Gaya"}, {"name": "Patna"}, {"name": "Purnia"}])
    V1, V2, A, B = str(v1), str(v2), str(vendor_a), str(vendor_b)

    test_db.bookings.insert_many([
        # --- Gaya: period-over-period / utilisation / drill-down (March vs 29 Jan–28 Feb) ---
        booking("g1", ist(2026, 3, 5), "completed", 1000, "Gaya", V1, A, ist(2026, 3, 5), ist(2026, 3, 7)),
        booking("g1", ist(2026, 3, 20), "confirmed", 500, "Gaya", V2, B, ist(2026, 3, 30), ist(2026, 4, 3)),
        booking("g2", ist(2026, 3, 10), "pending", 300, "Gaya", V1, A, ist(2026, 3, 10, 9, 30), ist(2026, 3, 10, 12)),
        booking("g2", ist(2026, 3, 12), "cancelled", 800, "Gaya", V1, A, ist(2026, 3, 12, 18), ist(2026, 3, 13)),
        booking("g9", ist(2026, 4, 2), "completed", 9999, "Gaya", V1, A, ist(2026, 4, 2), ist(2026, 4, 3)),
        booking("g3", ist(2026, 2, 10), "completed", 1000, "Gaya", V1, A, ist(2026, 2, 27), ist(2026, 3, 2)),
        # --- Patna: cohorts (paid statuses only; IST month boundaries) ---
        booking("c1", ist(2026, 1, 15), "completed", 100, "Patna"),
        booking("c1", ist(2026, 2, 10), "completed", 100, "Patna"),
        booking("c1", ist(2026, 4, 5), "active", 100, "Patna"),
        booking("c2", ist(2026, 1, 20), "completed", 100, "Patna"),
        booking("c2", ist(2026, 3, 3), "confirmed", 100, "Patna"),
        booking("c3", ist(2026, 2, 5), "completed", 100, "Patna"),
        booking("c3", ist(2026, 2, 20), "completed", 100, "Patna"),
        booking("c3", ist(2026, 3, 1), "completed", 100, "Patna"),
        booking("c4", ist(2026, 1, 25), "cancelled", 100, "Patna"),
        booking("c4", ist(2026, 2, 12), "completed", 100, "Patna"),
        # 31 Jan 20:00 UTC is 1 Feb 01:30 IST → February cohort.
        {**booking("c5", "2026-01-31T20:00:00+00:00", "completed", 100, "Patna")},
    ])

    U = {k: v["id"] for k, v in users.items()}
    test_db.tasks.insert_many([
        {"title": "t1", "assignee_id": U["employee"], "status": "completed", "created_at": ist(2026, 3, 2), "updated_at": ist(2026, 3, 4)},
        {"title": "t2", "assignee_id": U["employee2"], "status": "completed", "created_at": ist(2026, 3, 3), "updated_at": ist(2026, 3, 9)},
        {"title": "t3", "assignee_id": U["employee"], "status": "todo", "due_date": "2026-01-01", "created_at": ist(2026, 2, 1)},
        {"title": "t4", "assignee_id": U["employee2"], "status": "in_progress", "due_date": "2026-02-01T10:00:00+00:00", "created_at": ist(2026, 2, 1)},
        {"title": "t5", "assignee_id": U["manager"], "status": "todo", "due_date": "2099-01-01", "created_at": ist(2026, 2, 1)},
        {"title": "t6", "assignee_id": None, "status": "todo", "due_date": "2026-01-05", "created_at": ist(2026, 2, 1)},
    ])
    test_db.opportunities.insert_many([
        {"title": "o1", "assignee_id": U["employee"], "status": "open", "value_lakhs": 10, "updated_at": ist(2026, 3, 1)},
        {"title": "o2", "assignee_id": U["employee2"], "status": "in_progress", "value_lakhs": 20, "updated_at": ist(2026, 3, 1)},
        {"title": "o3", "assignee_id": U["employee"], "status": "won", "value_lakhs": 5, "updated_at": ist(2026, 3, 10)},
        {"title": "o4", "assignee_id": U["employee2"], "status": "lost", "value_lakhs": 7, "updated_at": ist(2026, 3, 11)},
        {"title": "o5", "assignee_id": U["employee"], "status": "lost", "value_lakhs": 1, "updated_at": ist(2026, 1, 1)},
    ])
    test_db.attendance.insert_many([
        {"employee_id": U["employee"], "date": "2026-03-02", "status": "present"},
        {"employee_id": U["employee"], "date": "2026-03-03", "status": "absent"},
        {"employee_id": U["employee"], "date": "2026-03-04", "status": "half_day"},
        {"employee_id": U["employee"], "date": "2026-03-05", "status": "leave"},
        {"employee_id": U["employee2"], "date": "2026-03-02", "status": "wfh"},
        {"employee_id": U["employee2"], "date": "2026-03-03", "status": "present"},
        {"employee_id": U["employee"], "date": "2026-04-01", "status": "absent"},
    ])
    test_db.leave_requests.insert_many([
        {"employee_id": U["employee"], "from_date": "2026-03-30", "to_date": "2026-04-02", "kind": "casual", "status": "approved"},
        {"employee_id": U["employee2"], "from_date": "2026-03-10", "to_date": "2026-03-11", "kind": "sick", "status": "approved"},
        {"employee_id": U["employee2"], "from_date": "2026-03-15", "to_date": "2026-03-20", "kind": "sick", "status": "pending"},
    ])
    test_db.calendar_events.insert_many([
        {"title": "e1", "organizer_id": U["manager"], "participant_ids": [], "visibility": "public", "status": "confirmed",
         "category": "Meeting", "start_time": datetime(2026, 3, 3, 5, tzinfo=timezone.utc), "end_time": datetime(2026, 3, 3, 6, tzinfo=timezone.utc)},
        {"title": "e2", "organizer_id": U["employee2"], "participant_ids": [], "visibility": "public", "status": "confirmed",
         "category": "Workshop", "start_time": datetime(2026, 3, 4, 5, tzinfo=timezone.utc), "end_time": datetime(2026, 3, 4, 6, tzinfo=timezone.utc)},
        {"title": "e3", "organizer_id": U["manager"], "participant_ids": [], "visibility": "public", "status": "cancelled",
         "category": "Meeting", "start_time": datetime(2026, 3, 5, 5, tzinfo=timezone.utc), "end_time": datetime(2026, 3, 5, 6, tzinfo=timezone.utc)},
    ])
    return {"V1": V1, "V2": V2}


def get(api, user, path, **params):
    return call(api, user, "GET", f"/analytics{path}", params=params)


def ok(api, user, path, **params):
    r = get(api, user, path, **params)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------- RBAC -------------------------

def test_module_access(api, users, data):
    for key in ("employee", "intern"):
        assert get(api, users[key], "/meta").status_code == 403
        assert get(api, users[key], "/operations", **MARCH).status_code == 403
        assert get(api, users[key], "/export/tasks", **MARCH).status_code == 403
    assert get(api, None, "/meta").status_code == 401
    m = ok(api, users["founder"], "/meta")
    assert m["marketplace"] is True and m["can_export"] is True
    assert {"Gaya", "Patna", "Purnia"} <= set(m["cities"])


@pytest.mark.parametrize("who", ["admin", "manager"])
def test_marketplace_is_founder_only(api, users, data, who):
    m = ok(api, users[who], "/meta")
    assert m["marketplace"] is False and m["cities"] == []
    for path in ("/marketplace/summary", "/marketplace/trend", "/marketplace/cohorts", "/marketplace/cities",
                 "/marketplace/cities/Gaya", "/marketplace/fleet", "/marketplace/funnel", "/marketplace/heatmap",
                 "/export/cities", "/export/summary"):
        assert get(api, users[who], path, **MARCH).status_code == 403, path


def test_invalid_range(api, users, data):
    assert get(api, users["founder"], "/marketplace/summary", **{"from": "2026-04-01", "to": "2026-03-01"}).status_code == 400
    assert get(api, users["founder"], "/marketplace/summary", **{"from": "yesterday"}).status_code == 400
    assert get(api, users["admin"], "/operations", **{"from": "2020-01-01", "to": "2026-03-01"}).status_code == 400


# ------------------------- marketplace -------------------------

def test_summary_period_over_period(api, users, data):
    d = ok(api, users["founder"], "/marketplace/summary", city="Gaya", **MARCH)
    assert d["range"]["previous"] == {"from": "2026-01-29", "to": "2026-02-28"}
    k = {x["key"]: x for x in d["kpis"]}
    assert (k["revenue"]["value"], k["revenue"]["previous"], k["revenue"]["delta"]) == (1500, 1000, 50.0)
    assert (k["bookings"]["value"], k["bookings"]["previous"], k["bookings"]["delta"]) == (4, 1, 300.0)
    assert (k["avg_booking_value"]["value"], k["avg_booking_value"]["delta"]) == (750, -25.0)
    assert (k["customers"]["value"], k["customers"]["previous"]) == (1, 1)
    assert k["new_customers"]["value"] == 1
    assert (k["repeat_rate"]["value"], k["repeat_rate"]["previous"], k["repeat_rate"]["delta"]) == (100.0, 0.0, 100.0)
    assert k["repeat_rate"]["delta_unit"] == "pp"
    assert (k["cancellation_rate"]["value"], k["cancellation_rate"]["inverse"]) == (25.0, True)
    # Utilisation: v1 31 avail days (3 booked: 5–7 Mar + 1 Mar spill-over), v2 16 days (2 booked); retired v3 excluded.
    assert d["utilisation"]["available_days"] == 47 and d["utilisation"]["booked_days"] == 5
    assert k["utilisation"]["value"] == 10.6 and k["utilisation"]["previous"] == 6.5
    assert k["utilisation"]["delta"] == 4.1


def test_empty_range_yields_zeros(api, users, data):
    d = ok(api, users["founder"], "/marketplace/summary", **{"from": "2025-06-01", "to": "2025-06-30"})
    k = {x["key"]: x for x in d["kpis"]}
    assert k["revenue"]["value"] == 0 and k["revenue"]["delta"] is None
    assert k["repeat_rate"]["value"] is None and k["cancellation_rate"]["value"] is None
    h = ok(api, users["founder"], "/marketplace/heatmap", **{"from": "2025-06-01", "to": "2025-06-30"})
    assert h["total"] == 0


def test_trend_granularity_and_buckets(api, users, data):
    d = ok(api, users["founder"], "/marketplace/trend", city="Gaya", **MARCH)
    assert d["granularity"] == "day" and len(d["series"]) == 31
    day5 = next(s for s in d["series"] if s["key"] == "2026-03-05")
    assert day5["revenue"] == 1000 and day5["bookings"] == 1
    assert sum(s["bookings"] for s in d["series"]) == 4
    w = ok(api, users["founder"], "/marketplace/trend", city="Gaya", granularity="week", **MARCH)
    assert w["series"][0]["key"] == "2026-02-23"  # Monday of the week holding 1 Mar
    assert sum(s["revenue"] for s in w["series"]) == 1500
    m = ok(api, users["founder"], "/marketplace/trend", **{"from": "2025-10-01", "to": "2026-09-30"})
    assert m["granularity"] == "month" and len(m["series"]) == 12


def test_cohort_retention_matrix(api, users, data):
    d = ok(api, users["founder"], "/marketplace/cohorts", city="Patna", **{"from": "2026-01-01", "to": "2026-04-30"})
    rows = {c["cohort"]: c for c in d["cohorts"]}
    assert list(rows) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    jan, feb = rows["2026-01"], rows["2026-02"]
    assert jan["size"] == 2                     # c1, c2
    assert jan["retention"][:4] == [50.0, 50.0, 50.0, None]   # Feb c1, Mar c2, Apr c1, May is after `to`
    assert feb["size"] == 3                     # c3, c4 (cancelled Jan booking ignored), c5 (IST boundary)
    assert feb["retention"][:3] == [33.3, 0.0, None]
    assert feb["retained"][:2] == [1, 0]
    assert rows["2026-03"]["size"] == 0 and rows["2026-03"]["retention"][0] is None
    assert d["average"][:3] == [40.0, 20.0, 50.0]
    assert d["customers"] == 5


def test_cities_and_drilldown(api, users, data):
    d = ok(api, users["founder"], "/marketplace/cities", **MARCH)
    cities = {c["city"]: c for c in d["cities"]}
    g = cities["Gaya"]
    assert (g["bookings"], g["revenue"], g["cancellation_rate"], g["utilisation"], g["vehicles"]) == (4, 1500, 25.0, 10.6, 2)
    assert cities["Patna"]["bookings"] == 2 and cities["Patna"]["utilisation"] is None

    c = ok(api, users["founder"], "/marketplace/cities/Gaya", **MARCH)
    s = c["summary"]
    assert (s["bookings"], s["revenue"], s["cancellation_rate"], s["utilisation"]) == (4, 1500, 25.0, 10.6)
    assert c["top_vehicles"][0]["id"] == data["V1"] and c["top_vehicles"][0]["utilisation"] == 9.7
    vendors = {v["vendor"]: v for v in c["vendors"]}
    assert (vendors["Vendor A"]["bookings"], vendors["Vendor A"]["revenue"], vendors["Vendor A"]["cancellation_rate"]) == (3, 1000, 33.3)
    assert (vendors["Vendor B"]["utilisation"], vendors["Vendor B"]["vehicles"]) == (12.5, 1)
    assert c["trend"]["granularity"] == "day"
    assert get(api, users["founder"], "/marketplace/cities/Atlantis", **MARCH).status_code == 404


def test_fleet_funnel_heatmap(api, users, data):
    f = ok(api, users["founder"], "/marketplace/fleet", city="Gaya", **MARCH)
    kinds = {k["kind"]: k for k in f["kinds"]}
    assert kinds["scooter"]["utilisation"] == 9.7 and kinds["bike"]["utilisation"] == 12.5
    assert kinds["bike"]["vehicles"] == 1  # retired vehicle excluded

    fn = ok(api, users["founder"], "/marketplace/funnel", city="Gaya", **MARCH)
    assert [s["count"] for s in fn["steps"]] == [4, 2, 1, 1]
    assert fn["cancelled"] == 1

    h = ok(api, users["founder"], "/marketplace/heatmap", city="Gaya", **MARCH)
    assert h["total"] == 3  # cancelled start excluded; the Feb-27 start is out of range
    assert h["matrix"][date(2026, 3, 10).weekday()][9] == 1
    assert h["matrix"][date(2026, 3, 5).weekday()][0] == 1


# ------------------------- operations -------------------------

def test_operations_company_wide(api, users, data):
    for who in ("founder", "admin"):
        d = ok(api, users[who], "/operations", **MARCH)
        t = d["tasks"]
        assert (t["created"], t["completed"], t["avg_cycle_days"]) == (2, 2, 4.0)
        assert t["granularity"] == "day"
        assert t["overdue_total"] == 3
        depts = {x["department"]: x["overdue"] for x in t["overdue_by_department"]}
        assert depts == {"Tech": 1, "Sales": 1, "Unassigned": 1}
        o = d["opportunities"]
        assert (o["open_value_lakhs"], o["won"], o["lost"], o["win_rate"]) == (30, 1, 1, 50.0)
        a = {x["department"]: x for x in d["attendance"]["departments"]}
        assert a["Tech"]["rate"] == 50.0 and a["Sales"]["rate"] == 100.0 and d["attendance"]["rate"] == 70.0
        assert d["leave"]["days"] == 4
        assert {x["department"]: x["days"] for x in d["leave"]["by_department"]} == {"Tech": 2, "Sales": 2}
        assert d["calendar"]["total"] == 2
    sales = ok(api, users["admin"], "/operations", department="Sales", **MARCH)
    assert sales["tasks"]["overdue_total"] == 1 and sales["tasks"]["completed"] == 1


def test_manager_scoped_to_department(api, users, data):
    d = ok(api, users["manager"], "/operations", **MARCH)
    assert d["scope"] == {"department": "Tech", "locked": True}
    t = d["tasks"]
    assert (t["created"], t["completed"], t["avg_cycle_days"], t["overdue_total"]) == (1, 1, 2.0, 1)
    assert [x["department"] for x in t["overdue_by_department"]] == ["Tech"]
    o = d["opportunities"]
    assert (o["open_value_lakhs"], o["win_rate"]) == (10, 100.0)
    assert [x["department"] for x in d["attendance"]["departments"]] == ["Tech"]
    assert d["leave"]["days"] == 2
    assert d["calendar"]["total"] == 1
    assert get(api, users["manager"], "/operations", department="Sales", **MARCH).status_code == 403
    assert ok(api, users["manager"], "/meta")["departments"] == ["Tech"]


# ------------------------- export -------------------------

def _csv(r):
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


def test_csv_export(api, users, data, test_db):
    rows = _csv(get(api, users["founder"], "/export/cities", **MARCH))
    assert rows[0][:4] == ["city", "bookings", "paid_bookings", "revenue"]
    gaya = next(r for r in rows if r[0] == "Gaya")
    assert gaya[1] == "4" and float(gaya[3]) == 1500

    rows = _csv(get(api, users["founder"], "/export/cohorts", city="Patna", **{"from": "2026-01-01", "to": "2026-04-30"}))
    assert rows[0][:3] == ["cohort", "customers", "m1_pct"] and rows[1][:3] == ["2026-01", "2", "50.0"]

    rows = _csv(get(api, users["founder"], "/export/city_vendors", city="Gaya", **MARCH))
    assert {r[0] for r in rows[1:]} == {"Vendor A", "Vendor B"}
    assert get(api, users["founder"], "/export/city_vendors", **MARCH).status_code == 400

    rows = _csv(get(api, users["manager"], "/export/overdue", **MARCH))
    assert len(rows) == 2 and rows[1][1] == "Tech"
    rows = _csv(get(api, users["admin"], "/export/tasks", **MARCH))
    assert rows[0] == ["period_start", "created", "completed"]

    assert get(api, users["founder"], "/export/nope", **MARCH).status_code == 404
    assert test_db.activity_logs.count_documents({"module": "Analytics", "action": "Exported analytics"}) >= 5


def test_csv_neutralises_formulas(api, users, data, test_db):
    test_db.vendors.update_one({"name": "Vendor B"}, {"$set": {"name": "=HYPERLINK(1)"}})
    rows = _csv(get(api, users["founder"], "/export/city_vendors", city="Gaya", **MARCH))
    assert "'=HYPERLINK(1)" in {r[0] for r in rows[1:]}
