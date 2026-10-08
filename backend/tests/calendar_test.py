from __future__ import annotations
"""Calendar API tests — single event, date range, month / week / day / agenda
views, participant filters, start_time sorting, pagination and visibility.

Runs against an isolated server and throwaway database (see local_harness.py).
"""
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests
from bson import ObjectId

from local_harness import api, mongo, test_db, users  # noqa: F401

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture(scope="module")
def harness_env():
    return {"CALENDAR_REMINDER_INTERVAL_SECONDS": "0.5"}


def _iso(*args) -> str:
    """IST datetime string, e.g. _iso(2031, 3, 10, 9) -> 2031-03-10T09:00:00+05:30."""
    return datetime(*args, tzinfo=IST).isoformat()


# ------------------------- fixtures -------------------------

def _create(api, user, **fields):
    body = {"title": "Event", "category": "Meeting", **fields}
    r = requests.post(f"{api}/calendar/events", json=body, headers=user["headers"], timeout=10)
    assert r.status_code == 201, r.text
    return r.json()


def _get(api, user, path, **params):
    return requests.get(f"{api}/calendar{path}", params=params, headers=user["headers"], timeout=10)


def _ids(events):
    return [e["id"] for e in events]


# ------------------------- create / validation -------------------------

def test_create_rejects_naive_datetime(api, users):
    r = requests.post(f"{api}/calendar/events", headers=users["founder"]["headers"], json={
        "title": "Naive", "start_time": "2031-01-05T10:00:00", "end_time": "2031-01-05T11:00:00"})
    assert r.status_code == 422


def test_create_rejects_end_before_start(api, users):
    r = requests.post(f"{api}/calendar/events", headers=users["founder"]["headers"], json={
        "title": "Backwards", "start_time": _iso(2031, 1, 5, 11), "end_time": _iso(2031, 1, 5, 10)})
    assert r.status_code == 422


def test_create_rejects_unknown_participant(api, users):
    r = requests.post(f"{api}/calendar/events", headers=users["founder"]["headers"], json={
        "title": "Ghost", "start_time": _iso(2031, 1, 5, 10), "end_time": _iso(2031, 1, 5, 11),
        "participant_ids": [str(ObjectId())]})
    assert r.status_code == 422


def test_intern_cannot_create(api, users):
    r = requests.post(f"{api}/calendar/events", headers=users["intern"]["headers"], json={
        "title": "Nope", "start_time": _iso(2031, 1, 5, 10), "end_time": _iso(2031, 1, 5, 11)})
    assert r.status_code == 403


def test_create_stores_utc_and_notifies(api, users, test_db):
    ev = _create(api, users["founder"], title="Kickoff",
                 start_time=_iso(2031, 1, 6, 10), end_time=_iso(2031, 1, 6, 11),
                 participant_ids=[users["employee"]["id"]])
    assert ev["start_time"] == "2031-01-06T04:30:00+00:00"
    assert ev["organizer_id"] == users["founder"]["id"]
    assert ev["organizer_name"] == "Test Founder"
    assert [p["id"] for p in ev["participants"]] == [users["employee"]["id"]]
    note = test_db.notifications.find_one({"user_id": users["employee"]["id"], "title": "Event invitation"})
    assert note and "Kickoff" in note["body"]
    assert note["link"] == f"/calendar?event={ev['id']}"


# ------------------------- single event -------------------------

def test_get_single_event(api, users):
    ev = _create(api, users["manager"], title="Single",
                 start_time=_iso(2031, 1, 7, 10), end_time=_iso(2031, 1, 7, 11))
    r = _get(api, users["employee"], f"/events/{ev['id']}")
    assert r.status_code == 200
    assert r.json()["title"] == "Single"
    assert r.json()["start_time"] == ev["start_time"]


def test_get_single_event_not_found(api, users):
    assert _get(api, users["founder"], f"/events/{ObjectId()}").status_code == 404
    assert _get(api, users["founder"], "/events/not-an-id").status_code == 404


def test_private_event_hidden_from_non_participants(api, users):
    ev = _create(api, users["manager"], title="1:1", visibility="private",
                 start_time=_iso(2031, 1, 8, 10), end_time=_iso(2031, 1, 8, 11),
                 participant_ids=[users["employee"]["id"]])
    assert _get(api, users["employee"], f"/events/{ev['id']}").status_code == 200
    assert _get(api, users["employee2"], f"/events/{ev['id']}").status_code == 404
    assert _get(api, users["admin"], f"/events/{ev['id']}").status_code == 200


def test_department_event_visibility(api, users):
    ev = _create(api, users["manager"], title="Tech sync", visibility="department",
                 start_time=_iso(2031, 1, 9, 10), end_time=_iso(2031, 1, 9, 11))
    assert ev["department"] == "Tech"
    assert _get(api, users["intern"], f"/events/{ev['id']}").status_code == 200
    assert _get(api, users["employee2"], f"/events/{ev['id']}").status_code == 404


# ------------------------- date range -------------------------

@pytest.fixture(scope="module")
def range_events(api, users):
    """Events around the window [2031-02-10, 2031-02-12) IST, created out of order."""
    f = users["founder"]
    return {
        "inside_late":  _create(api, f, title="inside late",  start_time=_iso(2031, 2, 11, 15), end_time=_iso(2031, 2, 11, 16)),
        "inside_early": _create(api, f, title="inside early", start_time=_iso(2031, 2, 10, 9),  end_time=_iso(2031, 2, 10, 10)),
        "spans_start":  _create(api, f, title="spans start",  start_time=_iso(2031, 2, 9, 22),  end_time=_iso(2031, 2, 10, 2)),
        "ends_at_start": _create(api, f, title="ends at start", start_time=_iso(2031, 2, 9, 20), end_time=_iso(2031, 2, 10, 0)),
        "starts_at_end": _create(api, f, title="starts at end", start_time=_iso(2031, 2, 12, 0), end_time=_iso(2031, 2, 12, 1)),
        "zero_length":  _create(api, f, title="zero length",  start_time=_iso(2031, 2, 10, 0),  end_time=_iso(2031, 2, 10, 0)),
    }


def test_range_is_half_open_and_sorted(api, users, range_events):
    r = _get(api, users["founder"], "/events", start="2031-02-10", end="2031-02-12")
    assert r.status_code == 200, r.text
    ids = _ids(r.json()["items"])
    e = range_events
    assert ids == [e["spans_start"]["id"], e["zero_length"]["id"], e["inside_early"]["id"], e["inside_late"]["id"]]


def test_range_accepts_datetimes(api, users, range_events):
    r = _get(api, users["founder"], "/events", start=_iso(2031, 2, 11, 0), end=_iso(2031, 2, 11, 23, 59))
    assert _ids(r.json()["items"]) == [range_events["inside_late"]["id"]]


def test_range_respects_timezone(api, users, range_events):
    # 2031-02-10 in UTC starts 05:30 IST, so the 22:00 IST event on the 9th (16:30 UTC) is outside.
    r = _get(api, users["founder"], "/events", start="2031-02-10", end="2031-02-11", tz="UTC")
    ids = _ids(r.json()["items"])
    assert range_events["inside_early"]["id"] in ids
    assert range_events["spans_start"]["id"] not in ids


@pytest.mark.parametrize("params", [
    {"start": "2031-02-12", "end": "2031-02-10"},
    {"start": "2031-01-01", "end": "2032-06-01"},
    {"start": "10/02/2031", "end": "2031-02-12"},
    {"start": "2031-02-10", "end": "2031-02-12", "tz": "Mars/Olympus"},
])
def test_range_rejects_bad_input(api, users, params):
    assert _get(api, users["founder"], "/events", **params).status_code == 422


# ------------------------- pagination -------------------------

def test_pagination_walks_full_sorted_list(api, users, range_events):
    full = _get(api, users["founder"], "/events", start="2031-02-09", end="2031-02-13", page_size=200).json()
    assert full["total"] == 6
    seen = []
    for page in (1, 2, 3):
        body = _get(api, users["founder"], "/events", start="2031-02-09", end="2031-02-13",
                    page=page, page_size=2).json()
        assert body["total_pages"] == 3
        assert body["has_more"] is (page < 3)
        seen += _ids(body["items"])
    assert seen == _ids(full["items"])
    starts = [e["start_time"] for e in full["items"]]
    assert starts == sorted(starts)


def test_pagination_limits(api, users):
    assert _get(api, users["founder"], "/events", start="2031-02-09", end="2031-02-13", page_size=201).status_code == 422
    assert _get(api, users["founder"], "/events", start="2031-02-09", end="2031-02-13", page=0).status_code == 422
    body = _get(api, users["founder"], "/events", start="2031-02-09", end="2031-02-13", page=99).json()
    assert body["items"] == [] and body["has_more"] is False


# ------------------------- month / week / day -------------------------

@pytest.fixture(scope="module")
def march_events(api, users):
    f = users["founder"]
    return {
        # Multi-day: Mon 3 Mar 18:00 -> Wed 5 Mar 10:00 IST.
        "multi_day": _create(api, f, title="Offsite", start_time=_iso(2031, 3, 3, 18), end_time=_iso(2031, 3, 5, 10)),
        # Ends exactly at midnight: must not spill into 11 Mar.
        "to_midnight": _create(api, f, title="Late review", start_time=_iso(2031, 3, 10, 22), end_time=_iso(2031, 3, 11, 0)),
        "mid_month": _create(api, f, title="Launch", category="Product Launch",
                             start_time=_iso(2031, 3, 15, 11), end_time=_iso(2031, 3, 15, 12)),
        "next_month": _create(api, f, title="April", start_time=_iso(2031, 4, 1, 9), end_time=_iso(2031, 4, 1, 10)),
    }


def _day(view, iso_date):
    return next(d["event_ids"] for d in view["days"] if d["date"] == iso_date)


def test_month_view(api, users, march_events):
    r = _get(api, users["founder"], "/month", year=2031, month=3)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["range"]["first_day"] == "2031-03-01"
    assert view["range"]["last_day"] == "2031-03-31"
    assert len(view["days"]) == 31
    ids = _ids(view["events"])
    assert march_events["next_month"]["id"] not in ids
    multi = march_events["multi_day"]["id"]
    assert [multi in _day(view, d) for d in ("2031-03-02", "2031-03-03", "2031-03-04", "2031-03-05", "2031-03-06")] \
        == [False, True, True, True, False]
    midnight = march_events["to_midnight"]["id"]
    assert midnight in _day(view, "2031-03-10") and midnight not in _day(view, "2031-03-11")


def test_month_view_full_weeks(api, users):
    view = _get(api, users["founder"], "/month", year=2031, month=3, full_weeks=True).json()
    # 1 Mar 2031 is a Saturday, 31 Mar a Monday.
    assert view["range"]["first_day"] == "2031-02-24"
    assert view["range"]["last_day"] == "2031-04-06"
    view = _get(api, users["founder"], "/month", year=2031, month=3, full_weeks=True, week_start="sunday").json()
    assert view["range"]["first_day"] == "2031-02-23"
    assert view["range"]["last_day"] == "2031-04-05"


def test_month_view_category_filter(api, users, march_events):
    view = _get(api, users["founder"], "/month", year=2031, month=3, category="Product Launch").json()
    assert _ids(view["events"]) == [march_events["mid_month"]["id"]]


def test_week_view(api, users, march_events):
    view = _get(api, users["founder"], "/week", date="2031-03-05").json()
    assert (view["range"]["first_day"], view["range"]["last_day"]) == ("2031-03-03", "2031-03-09")
    assert len(view["days"]) == 7
    assert _ids(view["events"]) == [march_events["multi_day"]["id"]]
    view = _get(api, users["founder"], "/week", date="2031-03-05", week_start="sunday").json()
    assert (view["range"]["first_day"], view["range"]["last_day"]) == ("2031-03-02", "2031-03-08")


def test_day_view(api, users, march_events):
    view = _get(api, users["founder"], "/day", date="2031-03-15").json()
    assert view["view"] == "day" and len(view["days"]) == 1
    assert _ids(view["events"]) == [march_events["mid_month"]["id"]]


def test_day_view_timezone_boundary(api, users, march_events):
    # 22:00-24:00 IST on 10 Mar is 16:30-18:30 UTC, still 10 Mar in UTC; in New York it is 10 Mar morning.
    ist = _ids(_get(api, users["founder"], "/day", date="2031-03-11").json()["events"])
    assert march_events["to_midnight"]["id"] not in ist
    utc = _get(api, users["founder"], "/day", date="2031-03-10", tz="UTC").json()
    assert utc["timezone"] == "UTC"
    assert march_events["to_midnight"]["id"] in _ids(utc["events"])


def test_views_reject_bad_input(api, users):
    assert _get(api, users["founder"], "/month", year=2031, month=13).status_code == 422
    assert _get(api, users["founder"], "/week", date="2031-13-01").status_code == 422
    assert _get(api, users["founder"], "/day", date="yesterday").status_code == 422


# ------------------------- agenda -------------------------

def test_agenda_includes_in_progress_and_skips_cancelled(api, users):
    f = users["founder"]
    running = _create(api, f, title="Running", start_time=_iso(2031, 5, 1, 9), end_time=_iso(2031, 5, 1, 12))
    upcoming = _create(api, f, title="Upcoming", start_time=_iso(2031, 5, 2, 9), end_time=_iso(2031, 5, 2, 10))
    later = _create(api, f, title="Too far", start_time=_iso(2031, 5, 20, 9), end_time=_iso(2031, 5, 20, 10))
    cancelled = _create(api, f, title="Cancelled", status="cancelled",
                        start_time=_iso(2031, 5, 3, 9), end_time=_iso(2031, 5, 3, 10))

    body = _get(api, f, "/agenda", start=_iso(2031, 5, 1, 10), days=7).json()
    assert _ids(body["items"]) == [running["id"], upcoming["id"]]
    assert body["timezone"] == "Asia/Kolkata"

    body = _get(api, f, "/agenda", start=_iso(2031, 5, 1, 10), days=7, include_cancelled=True).json()
    assert _ids(body["items"]) == [running["id"], upcoming["id"], cancelled["id"]]
    assert later["id"] not in _ids(body["items"])


def test_agenda_defaults_to_local_midnight_today(api, users):
    body = _get(api, users["founder"], "/agenda").json()
    start = datetime.fromisoformat(body["range"]["start"])
    ist = ZoneInfo("Asia/Kolkata")
    midnight = datetime.combine(datetime.now(ist).date(), datetime.min.time(), ist)
    assert start == midnight


# ------------------------- participants -------------------------

def test_participant_and_organizer_filters(api, users):
    emp, emp2, mgr = users["employee"], users["employee2"], users["manager"]
    invited = _create(api, mgr, title="Invited", start_time=_iso(2031, 6, 2, 10), end_time=_iso(2031, 6, 2, 11),
                      participant_ids=[emp["id"]])
    own = _create(api, emp, title="Own", start_time=_iso(2031, 6, 3, 10), end_time=_iso(2031, 6, 3, 11))
    other = _create(api, mgr, title="Other", start_time=_iso(2031, 6, 4, 10), end_time=_iso(2031, 6, 4, 11),
                    participant_ids=[emp2["id"]])

    mine = _get(api, emp, "/events", start="2031-06-01", end="2031-06-30", participant_id="me").json()
    assert _ids(mine["items"]) == [invited["id"], own["id"]]

    by_id = _get(api, users["founder"], "/events", start="2031-06-01", end="2031-06-30",
                 participant_id=emp2["id"]).json()
    assert _ids(by_id["items"]) == [other["id"]]

    organised = _get(api, users["founder"], "/week", date="2031-06-02", organizer_id=mgr["id"]).json()
    assert _ids(organised["events"]) == [invited["id"], other["id"]]

    assert _get(api, emp, "/events", start="2031-06-01", end="2031-06-30",
                participant_id="bogus").status_code == 422


# ------------------------- edit / delete -------------------------

def test_only_organiser_or_admin_can_modify(api, users):
    ev = _create(api, users["employee"], title="Mine", start_time=_iso(2031, 7, 1, 10), end_time=_iso(2031, 7, 1, 11))
    url = f"{api}/calendar/events/{ev['id']}"
    assert requests.patch(url, json={"title": "Hijack"}, headers=users["employee2"]["headers"]).status_code == 403
    r = requests.patch(url, json={"title": "Renamed"}, headers=users["employee"]["headers"])
    assert r.status_code == 200 and r.json()["title"] == "Renamed"
    r = requests.patch(url, json={"end_time": _iso(2031, 7, 1, 9)}, headers=users["employee"]["headers"])
    assert r.status_code == 422
    assert requests.delete(url, headers=users["employee2"]["headers"]).status_code == 403
    assert requests.delete(url, headers=users["admin"]["headers"]).status_code == 200
    assert _get(api, users["employee"], f"/events/{ev['id']}").status_code == 404


# ------------------------- invitees -------------------------

def test_invitees_available_to_every_role(api, users, test_db):
    test_db.users.insert_one({"_id": ObjectId(), "email": f"gone.{uuid.uuid4().hex}@calendar-test.wavygo.in",
                                     "name": "Gone User", "role": "Employee", "status": "deactivated"})
    r = _get(api, users["intern"], "/invitees")
    assert r.status_code == 200
    people = r.json()
    names = [p["name"] for p in people]
    assert names == sorted(names)
    assert "Test Employee2" in names and "Gone User" not in names
    assert set(people[0]) == {"id", "name", "photo", "role", "department", "designation"}


# ------------------------- reminders -------------------------

def _wait_for(predicate, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.25)
    return None


def test_reminder_sent_once_to_organiser_and_participants(api, users, test_db):
    soon = datetime.now(timezone.utc) + timedelta(minutes=10)
    ev = _create(api, users["manager"], title="Standup soon", reminder_minutes=15,
                 start_time=soon.isoformat(), end_time=(soon + timedelta(minutes=15)).isoformat(),
                 participant_ids=[users["employee"]["id"]])
    assert ev["reminder_minutes"] == 15 and "reminder_at" not in ev
    notes = test_db.notifications
    q = {"title": "Event reminder", "link": f"/calendar?event={ev['id']}"}
    assert _wait_for(lambda: notes.count_documents(q) >= 2), "reminder not delivered"
    time.sleep(1.2)  # a few more loop passes must not resend
    got = list(notes.find(q))
    assert sorted(n["user_id"] for n in got) == sorted([users["manager"]["id"], users["employee"]["id"]])
    assert "starts in 10 min" in got[0]["body"] or "starts in 9 min" in got[0]["body"]


def test_no_reminder_when_disabled_cancelled_or_far_off(api, users, test_db):
    soon = datetime.now(timezone.utc) + timedelta(minutes=5)
    later = datetime.now(timezone.utc) + timedelta(days=3)
    silent = _create(api, users["manager"], title="No reminder", reminder_minutes=None,
                     start_time=soon.isoformat(), end_time=(soon + timedelta(minutes=30)).isoformat())
    cancelled = _create(api, users["manager"], title="Called off", status="cancelled",
                        start_time=soon.isoformat(), end_time=(soon + timedelta(minutes=30)).isoformat())
    far = _create(api, users["manager"], title="Next week",
                  start_time=later.isoformat(), end_time=(later + timedelta(hours=1)).isoformat())
    time.sleep(1.5)
    links = [f"/calendar?event={e['id']}" for e in (silent, cancelled, far)]
    assert test_db.notifications.count_documents({"title": "Event reminder", "link": {"$in": links}}) == 0


def test_rescheduling_rearms_reminder(api, users, test_db):
    later = datetime.now(timezone.utc) + timedelta(days=2)
    ev = _create(api, users["manager"], title="Moved up",
                 start_time=later.isoformat(), end_time=(later + timedelta(hours=1)).isoformat())
    soon = datetime.now(timezone.utc) + timedelta(minutes=5)
    r = requests.patch(f"{api}/calendar/events/{ev['id']}", headers=users["manager"]["headers"],
                       json={"start_time": soon.isoformat(), "end_time": (soon + timedelta(hours=1)).isoformat()})
    assert r.status_code == 200, r.text
    q = {"title": "Event reminder", "link": f"/calendar?event={ev['id']}"}
    assert _wait_for(lambda: test_db.notifications.count_documents(q) == 1)


def test_reminder_minutes_validation(api, users):
    r = requests.post(f"{api}/calendar/events", headers=users["manager"]["headers"], json={
        "title": "Bad", "start_time": _iso(2031, 1, 5, 10), "end_time": _iso(2031, 1, 5, 11), "reminder_minutes": -5})
    assert r.status_code == 422


# ------------------------- search -------------------------

def test_search_matches_title_location_and_description(api, users):
    a = _create(api, users["founder"], title="Quarterly board review",
                start_time=_iso(2032, 2, 3, 10), end_time=_iso(2032, 2, 3, 11))
    b = _create(api, users["founder"], title="Standup", location="Board room",
                start_time=_iso(2032, 2, 3, 12), end_time=_iso(2032, 2, 3, 13))
    c = _create(api, users["founder"], title="Lunch", description="Nothing to see",
                start_time=_iso(2032, 2, 3, 14), end_time=_iso(2032, 2, 3, 15))
    r = _get(api, users["founder"], "/day", date="2032-02-03", tz="Asia/Kolkata", q="BOARD")
    assert r.status_code == 200
    assert _ids(r.json()["events"]) == [a["id"], b["id"]]
    assert c["id"] not in _ids(r.json()["events"])
    # Regex metacharacters are matched literally.
    r = _get(api, users["founder"], "/day", date="2032-02-03", tz="Asia/Kolkata", q=".*")
    assert r.json()["events"] == []


# ------------------------- RSVP -------------------------

def _rsvp(api, user, event_id, response):
    return requests.post(f"{api}/calendar/events/{event_id}/rsvp", json={"response": response},
                         headers=user["headers"], timeout=10)


def test_rsvp_records_response_and_notifies_organiser(api, users, test_db):
    ev = _create(api, users["manager"], title="Design crit",
                 start_time=_iso(2032, 3, 1, 10), end_time=_iso(2032, 3, 1, 11),
                 participant_ids=[users["employee"]["id"], users["employee2"]["id"]])
    assert {p["response"] for p in ev["participants"]} == {"pending"}
    assert "responses" not in ev

    r = _rsvp(api, users["employee"], ev["id"], "accepted")
    assert r.status_code == 200, r.text
    by_id = {p["id"]: p["response"] for p in r.json()["participants"]}
    assert by_id == {users["employee"]["id"]: "accepted", users["employee2"]["id"]: "pending"}
    note = test_db.notifications.find_one({"user_id": users["manager"]["id"], "title": "Event response",
                                           "link": f"/calendar?event={ev['id']}"})
    assert note and "accepted" in note["body"]


def test_rsvp_rejects_uninvited_and_bad_values(api, users):
    ev = _create(api, users["manager"], title="Closed door",
                 start_time=_iso(2032, 3, 2, 10), end_time=_iso(2032, 3, 2, 11),
                 participant_ids=[users["employee"]["id"]])
    assert _rsvp(api, users["employee2"], ev["id"], "accepted").status_code == 404
    assert _rsvp(api, users["employee"], ev["id"], "maybe").status_code == 422
    assert _rsvp(api, users["employee"], str(ObjectId()), "accepted").status_code == 404


def test_reschedule_resets_responses_and_notifies(api, users, test_db):
    ev = _create(api, users["manager"], title="Movable",
                 start_time=_iso(2032, 3, 3, 10), end_time=_iso(2032, 3, 3, 11),
                 participant_ids=[users["employee"]["id"]])
    _rsvp(api, users["employee"], ev["id"], "accepted")
    # A title-only edit keeps answers.
    r = requests.patch(f"{api}/calendar/events/{ev['id']}", headers=users["manager"]["headers"],
                       json={"title": "Movable (renamed)"})
    assert r.json()["participants"][0]["response"] == "accepted"
    r = requests.patch(f"{api}/calendar/events/{ev['id']}", headers=users["manager"]["headers"],
                       json={"start_time": _iso(2032, 3, 4, 10), "end_time": _iso(2032, 3, 4, 11)})
    assert r.status_code == 200
    assert r.json()["participants"][0]["response"] == "pending"
    assert test_db.notifications.count_documents({"user_id": users["employee"]["id"], "title": "Event rescheduled",
                                                  "link": f"/calendar?event={ev['id']}"}) == 1


# ------------------------- availability -------------------------

def test_availability_reports_busy_blocks_and_hides_private_titles(api, users):
    emp = users["employee"]["id"]
    public = _create(api, users["manager"], title="Team planning",
                     start_time=_iso(2032, 4, 5, 10), end_time=_iso(2032, 4, 5, 11), participant_ids=[emp])
    _create(api, users["employee"], title="Private 1:1", visibility="private",
            start_time=_iso(2032, 4, 5, 14), end_time=_iso(2032, 4, 5, 15))
    declined = _create(api, users["manager"], title="Optional sync",
                       start_time=_iso(2032, 4, 5, 16), end_time=_iso(2032, 4, 5, 17), participant_ids=[emp])
    _rsvp(api, users["employee"], declined["id"], "declined")

    r = _get(api, users["employee2"], "/availability", user_ids=emp,
             start="2032-04-05", end="2032-04-06", tz="Asia/Kolkata")
    assert r.status_code == 200, r.text
    busy = r.json()["users"][0]["busy"]
    assert [b["title"] for b in busy] == ["Team planning", "Busy"]
    assert busy[0]["event_id"] == public["id"] and busy[1]["event_id"] is None

    r = _get(api, users["employee2"], "/availability", user_ids=emp, start="2032-04-05", end="2032-04-06",
             tz="Asia/Kolkata", exclude_event_id=public["id"])
    assert [b["title"] for b in r.json()["users"][0]["busy"]] == ["Busy"]


def test_availability_validation(api, users):
    h = users["founder"]
    assert _get(api, h, "/availability", user_ids="me", start="2032-04-06", end="2032-04-05").status_code == 422
    assert _get(api, h, "/availability", user_ids="me", start="2032-01-01", end="2032-03-01").status_code == 422
    assert _get(api, h, "/availability", user_ids="nope", start="2032-01-01", end="2032-01-02").status_code == 422
