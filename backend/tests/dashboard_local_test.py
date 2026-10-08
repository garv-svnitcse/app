from __future__ import annotations
"""Dashboard API tests — no invented numbers on an empty database, real revenue /
booking aggregates and period-over-period deltas (IST boundaries), calendar
visibility in "Upcoming calendar", live system status, marketplace sections
hidden from non-Founder roles, and the public live KPIs.

Runs against an isolated server and throwaway database (see local_harness.py).
Tests share one database and run in file order.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from local_harness import api, mongo, test_db, users, call  # noqa: F401

IST = ZoneInfo("Asia/Kolkata")
MARKETPLACE_KEYS = ("revenue_series", "bookings_series", "cities", "vendor_perf")


@pytest.fixture(scope="module")
def harness_env():
    # Email is reported "not configured" when BREVO_API_KEY is absent.
    return {"BREVO_API_KEY": ""}


def _stats(api, user):
    r = call(api, user, "GET", "/dashboard/stats")
    assert r.status_code == 200, r.text
    return r.json()


def _kpis(data):
    return {k["key"]: k for k in data["kpis"]}


def _now_ist():
    return datetime.now(timezone.utc).astimezone(IST)


def _booking(test_db, created: datetime, amount: float, status: str, city: str = "Patna"):
    test_db.bookings.insert_one({
        "customer_name": "Test Customer", "vehicle_label": "Activa · BR01", "city": city,
        "amount": amount, "status": status,
        "created_at": created.astimezone(timezone.utc).isoformat(),
        "updated_at": created.astimezone(timezone.utc).isoformat(),
    })


def _event(test_db, title, start: datetime, organizer_id, visibility="public", status="confirmed", department=None):
    start = start.astimezone(timezone.utc)
    return test_db.calendar_events.insert_one({
        "title": title, "description": "", "start_time": start, "end_time": start + timedelta(hours=1),
        "all_day": False, "category": "Meeting", "visibility": visibility, "department": department,
        "organizer_id": organizer_id, "participant_ids": [], "status": status,
    }).inserted_id


# ------------------------- empty database -------------------------

def test_empty_db_has_no_invented_numbers(api, users):
    data = _stats(api, users["founder"])
    kpis = data["kpis"]
    assert len(kpis) == 9
    assert all(k["value"] == 0 for k in kpis)
    assert all(k["delta"] is None for k in kpis)
    assert len(data["revenue_series"]) == 6 and all(p["revenue"] == 0 for p in data["revenue_series"])
    assert "target" not in data["revenue_series"][0]
    assert len(data["bookings_series"]) == 7 and all(p["bookings"] == 0 for p in data["bookings_series"])
    assert data["bookings_series"][-1]["day"] == _now_ist().strftime("%a")
    for key in ("cities", "vendor_perf", "tasks_today", "upcoming_events", "opportunities"):
        assert data[key] == [], key
    assert data["company_health"]["score"] is None
    assert data["company_health"]["signals"] == []


# ------------------------- system status -------------------------

def test_system_status_is_live(api, users, test_db):
    stamp = datetime.now(timezone.utc).isoformat()
    test_db.activity_logs.insert_one({"user_name": "Test Founder", "action": "Did a thing",
                                      "module": "Test", "created_at": stamp})
    status = _stats(api, users["founder"])["system_status"]
    services = {s["name"]: s for s in status["services"]}
    assert services["API"]["status"] == "operational"
    assert services["Database"]["status"] == "operational"
    assert services["Database"]["detail"].startswith("Ping ") and services["Database"]["detail"].endswith(" ms")
    assert services["Email notifications"]["status"] == "not_configured"
    assert services["Activity log"]["at"] == stamp
    assert status["last_activity_at"] == stamp
    assert status["overall"] == "degraded"  # email is not configured
    assert "Payments" not in services and "uptime" not in services["API"]


# ------------------------- RBAC -------------------------

@pytest.mark.parametrize("role", ["admin", "manager"])
def test_non_founder_gets_no_marketplace_data(api, users, test_db, role):
    _booking(test_db, datetime.now(timezone.utc) - timedelta(minutes=5), 99_000, "completed")
    data = _stats(api, users[role])
    for key in MARKETPLACE_KEYS:
        assert key not in data, key
    keys = set(_kpis(data))
    assert not keys & {"revenue", "revenue_today", "revenue_week", "bookings", "vendors", "vehicles"}
    assert "open_tasks" in keys
    assert data["company_health"]["flags"]["kyc_pending"] is None
    assert data["company_health"]["flags"]["open_tickets"] is None
    test_db.bookings.delete_many({})


def test_employee_payload_unchanged_shape(api, users):
    data = _stats(api, users["employee"])
    assert data["revenue_series"] == [] and data["system_status"] is None


# ------------------------- revenue / bookings -------------------------

def test_revenue_series_and_deltas(api, users, test_db):
    now = datetime.now(timezone.utc)
    local = now.astimezone(IST)
    month_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
    just_now = now - timedelta(seconds=30)
    _booking(test_db, just_now, 250_000, "completed", "Patna")
    _booking(test_db, just_now, 500_000, "cancelled", "Gaya")
    _booking(test_db, just_now, 70_000, "pending", "Gaya")
    _booking(test_db, prev_month_start + timedelta(minutes=1), 100_000, "confirmed", "Patna")

    data = _stats(api, users["founder"])
    k = _kpis(data)
    assert k["revenue"]["value"] == 250_000
    assert k["revenue"]["delta"] == 150.0  # 2.5L vs 1L in the same days of last month
    assert k["revenue_today"]["value"] == 250_000 and k["revenue_today"]["delta"] is None
    assert k["revenue_week"]["value"] == 250_000
    assert k["bookings"]["value"] == 4
    assert k["bookings"]["delta"] == 300.0  # 1 booking existed a month ago
    assert k["bookings_today"]["value"] == 3 and k["bookings_today"]["delta"] is None
    assert k["active_bookings"]["value"] == 1 and k["active_bookings"]["compare"] is None

    series = data["revenue_series"]
    assert series[-1] == {"month": local.strftime("%b"), "revenue": 2.5}
    assert series[-2] == {"month": prev_month_start.strftime("%b"), "revenue": 1.0}
    assert data["bookings_series"][-1]["bookings"] == 3

    cities = {c["city"]: c for c in data["cities"]}
    assert cities["Patna"] == {"city": "Patna", "bookings": 2, "revenue": 3.5, "growth": 150.0}
    assert cities["Gaya"] == {"city": "Gaya", "bookings": 2, "revenue": 0, "growth": None}
    assert data["cities"][0]["city"] == "Patna"


# ------------------------- tasks -------------------------

def test_tasks_are_due_today_or_overdue(api, users, test_db):
    today = _now_ist().date()
    rows = [
        ("Overdue", (today - timedelta(days=2)).isoformat(), "low", "todo"),
        ("Due today", today.isoformat(), "urgent", "in_progress"),
        ("Due tomorrow", (today + timedelta(days=1)).isoformat(), "urgent", "todo"),
        ("Review overdue", (today - timedelta(days=1)).isoformat(), "medium", "review"),
        ("Done", today.isoformat(), "high", "completed"),
        ("Undated", None, "high", "todo"),
    ]
    for title, due, prio, status in rows:
        test_db.tasks.insert_one({"title": title, "due_date": due, "priority": prio, "status": status,
                                  "assignee_id": users["employee"]["id"]})
    data = _stats(api, users["founder"])
    assert [t["title"] for t in data["tasks_today"]] == ["Due today", "Review overdue", "Overdue"]
    assert [t["overdue"] for t in data["tasks_today"]] == [False, True, True]
    assert data["tasks_due_count"] == 3
    assert data["tasks_today"][0]["assignee_name"] == "Test Employee"
    ops = {s["label"]: s for s in data["company_health"]["signals"]}["Operations"]
    assert ops["value"] == 60  # 3 of 5 open tasks (review counts as open) are not overdue
    # Team KPIs (roles without Marketplace): the overdue review task counts as overdue.
    kpis = _kpis(_stats(api, users["manager"]))
    assert kpis["overdue_tasks"]["value"] == 2 and kpis["open_tasks"]["value"] == 5


def test_manager_sees_only_department_tasks_and_opportunities(api, users, test_db):
    today = _now_ist().date().isoformat()
    test_db.tasks.insert_one({"title": "Sales dept task", "due_date": today, "priority": "urgent",
                              "status": "todo", "assignee_id": users["employee2"]["id"]})
    test_db.opportunities.insert_one({"title": "Sales deal", "type": "Partnership", "status": "open",
                                      "value_lakhs": 5, "deadline": "2000-01-01", "assignee_id": users["employee2"]["id"]})
    manager = _stats(api, users["manager"])
    assert "Sales dept task" not in [t["title"] for t in manager["tasks_today"]]
    assert "Sales deal" not in [o["title"] for o in manager["opportunities"]]
    # Every task the Manager's dashboard lists can be opened.
    for t in manager["tasks_today"]:
        assert call(api, users["manager"], "GET", f"/tasks/{t['id']}").status_code == 200
    founder = _stats(api, users["founder"])
    assert "Sales dept task" in [t["title"] for t in founder["tasks_today"]]
    assert "Sales deal" in [o["title"] for o in founder["opportunities"]]
    test_db.tasks.delete_one({"title": "Sales dept task"})
    test_db.opportunities.delete_one({"title": "Sales deal"})


# ------------------------- upcoming calendar -------------------------

def test_upcoming_calendar_is_real_and_visibility_scoped(api, users, test_db):
    tomorrow = (_now_ist() + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    other = users["employee2"]["id"]
    public_id = _event(test_db, "Public sync", tomorrow, other)
    private_id = _event(test_db, "Private 1:1", tomorrow + timedelta(minutes=30), other, visibility="private")
    dept_id = _event(test_db, "Tech standup", tomorrow + timedelta(hours=1), other, visibility="department", department="Tech")
    _event(test_db, "Cancelled", tomorrow + timedelta(hours=2), other, status="cancelled")
    _event(test_db, "Past", _now_ist() - timedelta(hours=3), other)

    events = _stats(api, users["manager"])["upcoming_events"]
    assert [e["id"] for e in events] == [str(public_id), str(dept_id)]
    first = events[0]
    assert first["when"] == "Tomorrow, 11:00 AM"
    assert first["link"] == f"/calendar?event={public_id}"
    assert first["category"] == "Meeting"
    assert first["start_time"] == tomorrow.astimezone(timezone.utc).isoformat()

    # Founder sees all visibilities; only the next 5, sorted by start_time.
    for i in range(4):
        _event(test_db, f"Later {i}", tomorrow + timedelta(days=2, hours=i), other)
    founder_events = _stats(api, users["founder"])["upcoming_events"]
    assert len(founder_events) == 5
    assert [e["id"] for e in founder_events[:3]] == [str(public_id), str(private_id), str(dept_id)]
    starts = [e["start_time"] for e in founder_events]
    assert starts == sorted(starts)


def test_upcoming_calendar_includes_in_progress_events(api, users, test_db):
    test_db.calendar_events.delete_many({})
    started = _now_ist() - timedelta(minutes=30)
    running_id = _event(test_db, "Running now", started, users["founder"]["id"])  # ends in 30 minutes
    _event(test_db, "Finished", _now_ist() - timedelta(hours=2), users["founder"]["id"])
    events = _stats(api, users["founder"])["upcoming_events"]
    assert [e["id"] for e in events] == [str(running_id)]
    assert events[0]["when"].startswith("Now, until ")


def test_opportunities_are_real(api, users, test_db):
    test_db.opportunities.insert_one({"title": "Real deal", "type": "Partnership", "status": "open",
                                      "value_lakhs": 12, "deadline": "2099-01-01"})
    test_db.opportunities.insert_one({"title": "Lost deal", "type": "Partnership", "status": "lost"})
    opps = _stats(api, users["founder"])["opportunities"]
    assert [o["title"] for o in opps] == ["Real deal"]


def test_pipeline_total_covers_all_open_deals(api, users, test_db):
    test_db.opportunities.delete_many({})
    test_db.opportunities.insert_many([
        {"title": f"Deal {i}", "type": "Partnership", "status": "open", "value_lakhs": 10, "deadline": "2099-01-01"}
        for i in range(5)
    ] + [{"title": "Won", "type": "Partnership", "status": "won", "value_lakhs": 99}])
    data = _stats(api, users["founder"])
    assert len(data["opportunities"]) == 3
    assert data["pipeline"] == {"count": 5, "value_lakhs": 50}
    test_db.opportunities.delete_many({})


# ------------------------- public live KPIs -------------------------

def test_live_kpis_are_real_counts_and_cached(api, test_db):
    test_db.vendors.insert_many([{"name": "V1", "active": True}, {"name": "V2", "active": False}])
    test_db.vehicles.insert_many([{"status": s} for s in ("available", "available", "available", "maintenance")])
    test_db.cities.insert_many([{"name": "Patna", "status": "active"}, {"name": "Gaya", "status": "planned"}])
    expected_today = test_db.bookings.count_documents({})  # every booking left is from today or last month
    expected_today -= 1  # the last-month booking

    r = call(api, None, "GET", "/dashboard/live-kpis")
    assert r.status_code == 200
    kpis = {k["label"]: k["value"] for k in r.json()["kpis"]}
    assert kpis == {
        "Today's Bookings": str(expected_today),
        "Active Vendors": "1",
        "Vehicles Online": "3",
        "Cities Served": "1",
    }

    test_db.vendors.insert_one({"name": "V3", "active": True})
    again = call(api, None, "GET", "/dashboard/live-kpis").json()
    assert {k["label"]: k["value"] for k in again["kpis"]}["Active Vendors"] == "1"  # served from cache


# ------------------------- activity module filter -------------------------

def test_activity_module_filter(api, users, test_db):
    test_db.activity_logs.insert_many([
        {"user_id": users["founder"]["id"], "action": "Created booking", "module": "Marketplace", "created_at": "2030-01-01T00:00:00+00:00"},
        {"user_id": users["founder"]["id"], "action": "Moved task", "module": "Task Board", "created_at": "2030-01-01T00:00:01+00:00"},
    ])
    modules = call(api, users["founder"], "GET", "/activity/modules").json()
    assert {"Marketplace", "Task Board"} <= set(modules)
    rows = call(api, users["founder"], "GET", "/activity", params={"module": "Task Board"}).json()
    assert rows and {r["module"] for r in rows} == {"Task Board"}
    assert call(api, users["employee"], "GET", "/activity/modules").status_code == 403


def test_activity_cursor_pagination(api, users, test_db):
    founder = users["founder"]
    # Five rows sharing one timestamp plus two later ones: the cursor must not skip ties.
    rows = [{"user_id": founder["id"], "action": f"Paged {i}", "module": "Paging",
             "created_at": "2032-01-01T00:00:00+00:00" if i < 5 else f"2032-01-01T00:00:0{i}+00:00"} for i in range(7)]
    test_db.activity_logs.insert_many(rows)

    # The bare-list shape stays for existing callers (Dashboard).
    assert isinstance(call(api, founder, "GET", "/activity", params={"limit": 2}).json(), list)

    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 3, "paged": True, "module": "Paging", **({"before": cursor} if cursor else {})}
        body = call(api, founder, "GET", "/activity", params=params).json()
        seen += [r["action"] for r in body["items"]]
        pages += 1
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
    assert pages == 3
    assert len(seen) == 7 and len(set(seen)) == 7
    assert seen[:2] == ["Paged 6", "Paged 5"]

    # A bare created_at is accepted as a cursor too.
    body = call(api, founder, "GET", "/activity",
                params={"paged": True, "module": "Paging", "before": "2032-01-01T00:00:05+00:00"}).json()
    assert len(body["items"]) == 5 and body["has_more"] is False


# ------------------------- recent notifications -------------------------

def test_recent_notifications_use_per_user_read_state_and_links(api, users, test_db):
    founder, admin = users["founder"], users["admin"]
    test_db.notifications.insert_many([
        {"user_id": None, "title": "Announcement: read by founder", "body": "b", "kind": "info", "read": False,
         "read_by": [founder["id"]], "link": None, "created_at": "2031-01-01T00:00:00+00:00"},
        {"user_id": founder["id"], "title": "Personal with link", "body": "b", "kind": "info", "read": False,
         "link": "/calendar", "created_at": "2031-01-01T00:00:01+00:00"},
    ])
    items = {n["title"]: n for n in _stats(api, founder)["recent_notifications"]}
    assert items["Announcement: read by founder"]["read"] is True
    assert items["Personal with link"]["read"] is False
    assert items["Personal with link"]["link"] == "/calendar"
    # The broadcast is still unread for everyone else.
    admin_items = {n["title"]: n for n in _stats(api, admin)["recent_notifications"]}
    assert admin_items["Announcement: read by founder"]["read"] is False
