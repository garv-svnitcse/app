from __future__ import annotations
"""WavyGo AI tests — status, conversation CRUD + ownership, guardrails, role scoping of
every tool, and the streaming tool-use loop against a local mock of the Messages API.

No test calls the real Anthropic API:
  * the harness server runs with ANTHROPIC_API_KEY="" (not configured) and
    WAVYGO_AI_TEST_TOOLS=1, which exposes the test-only tool runner;
  * a second server on the same throwaway DB gets a dummy key and ANTHROPIC_BASE_URL
    pointing at an in-process mock that speaks the Messages SSE protocol.
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from bson import ObjectId

from local_harness import BACKEND_DIR, _free_port, api, call, mongo, test_db, users  # noqa: F401


@pytest.fixture(scope="module")
def harness_env():
    return {"ANTHROPIC_API_KEY": "", "WAVYGO_AI_TEST_TOOLS": "1"}


# ------------------------- seed data -------------------------

@pytest.fixture(scope="module")
def seeded(test_db, users):
    u = users
    now = datetime.now(timezone.utc)
    today = (now + timedelta(hours=5, minutes=30)).date()
    tasks = [
        ("T-emp-own", u["employee"]["id"], u["manager"]["id"], "todo", (today - timedelta(days=2)).isoformat()),
        ("T-emp-reported", u["intern"]["id"], u["employee"]["id"], "in_progress", None),
        ("T-emp2-sales", u["employee2"]["id"], u["admin"]["id"], "todo", None),
        ("T-intern-own", u["intern"]["id"], u["manager"]["id"], "review", None),
        ("T-admin-own", u["admin"]["id"], u["founder"]["id"], "todo", None),
    ]
    test_db.tasks.insert_many([{
        "title": t, "assignee_id": a, "reporter_id": r, "status": s, "priority": "medium",
        "due_date": d, "module": "general", "created_at": now.isoformat(),
    } for t, a, r, s, d in tasks])
    test_db.opportunities.insert_many([
        {"title": "O-emp", "type": "grant", "status": "open", "assignee_id": u["employee"]["id"], "value_lakhs": 5},
        {"title": "O-emp2", "type": "grant", "status": "open", "assignee_id": u["employee2"]["id"], "value_lakhs": 7},
        {"title": "O-pool", "type": "grant", "status": "open", "assignee_id": None, "value_lakhs": 1},
    ])
    start = now + timedelta(days=1)
    ev = lambda title, **kw: {  # noqa: E731
        "title": title, "start_time": start, "end_time": start + timedelta(hours=1), "all_day": False,
        "category": "Meeting", "status": "confirmed", "organizer_id": u["admin"]["id"], "participant_ids": [], **kw}
    test_db.calendar_events.insert_many([
        ev("E-public", visibility="public"),
        ev("E-tech", visibility="department", department="Tech"),
        ev("E-private-emp2", visibility="private", participant_ids=[u["employee2"]["id"]]),
    ])
    iso_today = today.isoformat()
    test_db.attendance.insert_many([
        {"employee_id": u["employee"]["id"], "date": iso_today, "status": "present"},
        {"employee_id": u["employee2"]["id"], "date": iso_today, "status": "wfh"},
    ])
    test_db.leave_requests.insert_many([
        {"employee_id": u["employee"]["id"], "from_date": iso_today, "to_date": iso_today, "kind": "casual",
         "status": "pending", "reason": "R-emp", "created_at": now.isoformat()},
        {"employee_id": u["employee2"]["id"], "from_date": iso_today, "to_date": iso_today, "kind": "sick",
         "status": "pending", "reason": "R-emp2", "created_at": now.isoformat()},
    ])
    test_db.notifications.insert_many([
        {"user_id": u["employee"]["id"], "title": "N-emp", "body": "x", "read": False, "created_at": now.isoformat()},
        {"user_id": u["employee2"]["id"], "title": "N-emp2", "body": "x", "read": False, "created_at": now.isoformat()},
    ])
    return True


def tool(api, user, name, **args):
    return call(api, user, "POST", f"/ai/_test/tools/{name}", json=args)


def titles(items, key="title"):
    return {i[key] for i in items}


# ------------------------- status / CRUD / ownership -------------------------

def test_status_not_configured(api, users):
    r = call(api, users["employee"], "GET", "/ai/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is False
    assert body["model"] == "claude-opus-5"
    assert "marketplace_kpis" not in body["tools"]
    assert "marketplace_kpis" in call(api, users["founder"], "GET", "/ai/status").json()["tools"]
    intern_tools = call(api, users["intern"], "GET", "/ai/status").json()["tools"]
    assert "opportunities_summary" not in intern_tools and "my_tasks" in intern_tools
    assert call(api, None, "GET", "/ai/status").status_code == 401


def test_conversation_crud_and_activity(api, users, test_db):
    emp = users["employee"]
    r = call(api, emp, "POST", "/ai/conversations", json={})
    assert r.status_code == 201, r.text
    conv = r.json()
    assert conv["title"] == "New chat" and conv["messages"] == []
    assert test_db.activity_logs.find_one({"user_id": emp["id"], "action": "Started AI conversation",
                                           "module": "WavyGo AI"})
    assert any(c["id"] == conv["id"] for c in call(api, emp, "GET", "/ai/conversations").json())
    r = call(api, emp, "PATCH", f"/ai/conversations/{conv['id']}", json={"title": "Renamed"})
    assert r.status_code == 200 and r.json()["title"] == "Renamed"
    assert call(api, emp, "PATCH", f"/ai/conversations/{conv['id']}", json={"title": ""}).status_code == 422
    assert call(api, emp, "GET", f"/ai/conversations/{conv['id']}").json()["title"] == "Renamed"
    assert call(api, emp, "DELETE", f"/ai/conversations/{conv['id']}").status_code == 200
    assert call(api, emp, "GET", f"/ai/conversations/{conv['id']}").status_code == 404
    assert call(api, emp, "GET", "/ai/conversations/not-an-id").status_code == 404


def test_conversations_are_private(api, users):
    mine = call(api, users["founder"], "POST", "/ai/conversations", json={"title": "Founder only"}).json()
    other = users["employee"]
    path = f"/ai/conversations/{mine['id']}"
    assert call(api, other, "GET", path).status_code == 404
    assert call(api, other, "PATCH", path, json={"title": "x"}).status_code == 404
    assert call(api, other, "DELETE", path).status_code == 404
    assert call(api, other, "POST", f"{path}/messages", json={"content": "hi"}).status_code == 404
    assert all(c["id"] != mine["id"] for c in call(api, other, "GET", "/ai/conversations").json())
    assert call(api, users["founder"], "GET", path).status_code == 200


def test_message_when_not_configured_and_validation(api, users):
    emp = users["employee"]
    conv = call(api, emp, "POST", "/ai/conversations", json={}).json()
    path = f"/ai/conversations/{conv['id']}/messages"
    r = call(api, emp, "POST", path, json={"content": "hello"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert call(api, emp, "POST", path, json={"content": "x" * 4001}).status_code == 422


# ------------------------- tool scoping -------------------------

def test_task_tools_scoping(api, users, seeded):
    r = tool(api, users["employee"], "my_tasks", status="all")
    assert r.status_code == 200, r.text
    assert titles(r.json()["tasks"]) == {"T-emp-own"}
    assert r.json()["tasks"][0]["overdue"] is True

    emp = titles(tool(api, users["employee"], "search_tasks", status="all").json()["tasks"])
    assert emp == {"T-emp-own", "T-emp-reported"}
    intern = titles(tool(api, users["intern"], "search_tasks", status="all").json()["tasks"])
    assert intern == {"T-emp-reported", "T-intern-own"}
    mgr = titles(tool(api, users["manager"], "search_tasks", status="all").json()["tasks"])
    assert {"T-emp-own", "T-emp-reported", "T-intern-own"} <= mgr and "T-emp2-sales" not in mgr
    founder = titles(tool(api, users["founder"], "search_tasks", status="all", limit=25).json()["tasks"])
    assert {"T-emp2-sales", "T-admin-own"} <= founder
    # Naming someone outside your scope never widens it.
    assert tool(api, users["employee"], "search_tasks", status="all", assignee_name="Employee2").json()["tasks"] == []
    assert tool(api, users["employee"], "search_tasks", bogus=1).status_code == 400
    assert tool(api, users["employee"], "search_tasks", limit="lots").status_code == 400


def test_opportunities_scoping(api, users, seeded):
    assert tool(api, users["intern"], "opportunities_summary").status_code == 403
    assert titles(tool(api, users["employee"], "opportunities_summary").json()["opportunities"]) == {"O-emp"}
    mgr = tool(api, users["manager"], "opportunities_summary").json()
    assert titles(mgr["opportunities"]) == {"O-emp", "O-pool"}
    founder = tool(api, users["founder"], "opportunities_summary").json()
    assert titles(founder["opportunities"]) == {"O-emp", "O-emp2", "O-pool"}
    assert founder["pipeline_value_lakhs"] == 13


def test_events_scoping(api, users, seeded):
    emp = titles(tool(api, users["employee"], "upcoming_events").json()["events"])
    assert {"E-public", "E-tech"} <= emp and "E-private-emp2" not in emp
    emp2 = titles(tool(api, users["employee2"], "upcoming_events").json()["events"])
    assert {"E-public", "E-private-emp2"} <= emp2 and "E-tech" not in emp2
    assert {"E-public", "E-tech", "E-private-emp2"} <= titles(tool(api, users["admin"], "upcoming_events").json()["events"])


def test_attendance_and_leave_scoping(api, users, seeded):
    me = tool(api, users["employee"], "attendance_and_leave").json()
    assert [lv["reason"] for lv in me["leave_requests"]] == ["R-emp"]
    assert me["attendance_summary"] == {"present": 1}
    assert tool(api, users["employee"], "attendance_and_leave", scope="team").status_code == 403
    assert tool(api, users["intern"], "attendance_and_leave", scope="team").status_code == 403
    mgr = tool(api, users["manager"], "attendance_and_leave", scope="team").json()
    assert {lv["reason"] for lv in mgr["pending_leave_requests"]} == {"R-emp"}
    assert titles(mgr["attendance_by_employee"], "employee") == {"Test Employee"}
    founder = tool(api, users["founder"], "attendance_and_leave", scope="team").json()
    assert {"R-emp", "R-emp2"} <= {lv["reason"] for lv in founder["pending_leave_requests"]}


def test_marketplace_founder_only(api, users, seeded):
    r = tool(api, users["founder"], "marketplace_kpis")
    assert r.status_code == 200, r.text
    assert any(k["label"] == "Revenue (MTD)" for k in r.json()["kpis"])
    for key in ("admin", "manager", "employee", "intern"):
        assert tool(api, users[key], "marketplace_kpis").status_code == 403


def test_directory_and_notifications(api, users, seeded):
    people = tool(api, users["intern"], "team_directory", limit=40).json()["people"]
    assert people and all(set(p) == {"name", "role", "department", "designation"} for p in people)
    notes = titles(tool(api, users["employee"], "notifications_recent").json()["notifications"])
    assert "N-emp" in notes and "N-emp2" not in notes
    assert tool(api, users["employee"], "no_such_tool").status_code == 400


# ------------------------- streaming against a mock Messages API -------------------------

class MockAnthropic(BaseHTTPRequestHandler):
    requests_seen: list = []

    def log_message(self, *a):  # silence
        pass

    def _sse(self, events):
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("request-id", "req_mock")
        self.end_headers()
        for ev in events:
            self.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
            self.wfile.flush()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        MockAnthropic.requests_seen.append({"body": body, "headers": dict(self.headers)})
        last = body["messages"][-1]
        content = last["content"]
        first_text = content if isinstance(content, str) else ""
        if "trigger-400" in first_text:
            payload = json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}).encode()
            self.send_response(400)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        start = {"type": "message_start", "message": {
            "id": "msg_mock", "type": "message", "role": "assistant", "model": body["model"], "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}
        if "slow" in first_text:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            try:
                for ev in [start,
                           {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                           *({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Partial "}}
                             for _ in range(20))]:
                    self.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.25)
            except OSError:
                pass  # the backend hung up after the browser pressed Stop
            return
        results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] \
            if isinstance(content, list) else []
        if results:
            data = json.loads(results[0]["content"])
            text = f"You have {data['returned']} open tasks: " + ", ".join(t["title"] for t in data["tasks"])
            events = [start,
                      {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                      {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[:10]}},
                      {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[10:]}},
                      {"type": "content_block_stop", "index": 0},
                      {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                       "usage": {"output_tokens": 20}},
                      {"type": "message_stop"}]
        else:
            events = [start,
                      {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                      {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Checking."}},
                      {"type": "content_block_stop", "index": 0},
                      {"type": "content_block_start", "index": 1, "content_block": {
                          "type": "tool_use", "id": "toolu_mock", "name": "my_tasks", "input": {}}},
                      {"type": "content_block_delta", "index": 1, "delta": {
                          "type": "input_json_delta", "partial_json": '{"status": "open"}'}},
                      {"type": "content_block_stop", "index": 1},
                      {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                       "usage": {"output_tokens": 12}},
                      {"type": "message_stop"}]
        self._sse(events)


@pytest.fixture(scope="module")
def mock_api(mongo, users, tmp_path_factory):
    MockAnthropic.requests_seen = []
    mock = ThreadingHTTPServer(("127.0.0.1", 0), MockAnthropic)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    port = _free_port()
    log = open(tmp_path_factory.mktemp("ai-api") / "uvicorn.log", "w")
    env = {**os.environ, "DB_NAME": mongo.harness_db_name, "ANTHROPIC_API_KEY": "test-key",
           "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{mock.server_address[1]}", "WAVYGO_AI_TEST_TOOLS": "",
           "WAVYGO_AI_RATE_LIMIT": "5"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)],
                            cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}/api"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if requests.get(f"{base}/health", timeout=1).status_code == 200:
                break
        except requests.ConnectionError:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail(f"mock-backed server did not start, see {log.name}")
    yield base
    proc.terminate()
    proc.wait(10)
    log.close()
    mock.shutdown()


def read_sse(resp) -> list[tuple[str, dict]]:
    events = []
    for block in resp.text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.strip().splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_streaming_tool_loop(mock_api, users, seeded, test_db):
    emp = users["employee"]
    assert call(mock_api, emp, "GET", "/ai/status").json()["configured"] is True
    conv = call(mock_api, emp, "POST", "/ai/conversations", json={}).json()
    r = call(mock_api, emp, "POST", f"/ai/conversations/{conv['id']}/messages", json={"content": "What are my tasks?"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    events = read_sse(r)
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and kinds[-1] == "done" and "error" not in kinds
    assert [d["status"] for k, d in events if k == "tool"] == ["running", "done"]
    text = "".join(d["text"] for k, d in events if k == "delta")
    assert "T-emp-own" in text and "T-emp2-sales" not in text

    first, second = MockAnthropic.requests_seen[-2:]
    assert first["body"]["model"] == "claude-opus-5"
    assert "server-side-fallback-2026-07-01" in first["headers"].get("anthropic-beta", "")
    assert first["body"]["fallbacks"] == "default"
    assert first["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Test Employee" in first["body"]["system"][1]["text"]
    assert {t["name"] for t in first["body"]["tools"]} >= {"my_tasks", "team_directory"}
    assert "marketplace_kpis" not in {t["name"] for t in first["body"]["tools"]}
    tool_result = second["body"]["messages"][-1]["content"][0]["content"]
    assert "T-emp-own" in tool_result and "T-emp2-sales" not in tool_result

    time.sleep(0.3)  # the reply is saved by a background task
    saved = call(mock_api, emp, "GET", f"/ai/conversations/{conv['id']}").json()
    assert saved["title"] == "What are my tasks?"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][1]["tool_calls"][0]["name"] == "my_tasks"
    assert "T-emp-own" in saved["messages"][1]["content"]

    # Regenerate replaces the assistant reply instead of adding a new user turn.
    r = call(mock_api, emp, "POST", f"/ai/conversations/{conv['id']}/messages", json={"regenerate": True})
    assert r.status_code == 200 and read_sse(r)[-1][0] == "done"
    time.sleep(0.3)
    saved = call(mock_api, emp, "GET", f"/ai/conversations/{conv['id']}").json()
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]


def test_api_error_is_friendly(mock_api, users):
    mgr = users["manager"]
    conv = call(mock_api, mgr, "POST", "/ai/conversations", json={}).json()
    r = call(mock_api, mgr, "POST", f"/ai/conversations/{conv['id']}/messages", json={"content": "trigger-400"})
    assert r.status_code == 200
    errors = [d for k, d in read_sse(r) if k == "error"]
    assert errors and errors[0]["code"] == "bad_request" and "bad" != errors[0]["detail"]
    saved = call(mock_api, mgr, "GET", f"/ai/conversations/{conv['id']}").json()
    assert [m["role"] for m in saved["messages"]] == ["user"]


def test_rate_limit_and_test_endpoint_hidden(mock_api, users, test_db):
    intern = users["intern"]
    conv = call(mock_api, intern, "POST", "/ai/conversations", json={}).json()
    now = datetime.now(timezone.utc)
    test_db.ai_usage.insert_many([{"_id": ObjectId(), "user_id": intern["id"], "created_at": now} for _ in range(5)])
    r = call(mock_api, intern, "POST", f"/ai/conversations/{conv['id']}/messages", json={"content": "hi"})
    assert r.status_code == 429
    assert call(mock_api, intern, "GET", "/ai/status").json()["limits"]["remaining_this_hour"] == 0
    assert call(mock_api, intern, "POST", "/ai/_test/tools/my_tasks", json={}).status_code == 404


def test_stop_saves_partial_reply(mock_api, users):
    admin = users["admin"]
    conv = call(mock_api, admin, "POST", "/ai/conversations", json={}).json()
    with requests.post(f"{mock_api}/ai/conversations/{conv['id']}/messages", json={"content": "slow please"},
                       headers=admin["headers"], stream=True, timeout=15) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith(b"event: delta"):
                break  # like the Stop button: abort mid-stream
    deadline = time.time() + 8
    msgs = []
    while time.time() < deadline:
        msgs = call(mock_api, admin, "GET", f"/ai/conversations/{conv['id']}").json()["messages"]
        if len(msgs) == 2:
            break
        time.sleep(0.25)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["stopped"] is True and msgs[1]["content"].startswith("Partial")
    # The conversation is free again for the next message.
    r = call(mock_api, admin, "POST", f"/ai/conversations/{conv['id']}/messages", json={"content": "trigger-400"})
    assert r.status_code == 200
