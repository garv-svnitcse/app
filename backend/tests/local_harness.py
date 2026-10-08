from __future__ import annotations
"""Isolated API test harness.

Import the fixtures into a test module:

    from local_harness import api, mongo, test_db, users, harness_env, call  # noqa: F401

For each test module it starts a real uvicorn (`server:app`) on a free port against
a throwaway database on the local MongoDB (MONGO_URL from backend/.env), inserts
one active user per role, mints access tokens directly and drops the database
afterwards. Development and production data are never touched.

Fixtures (all module-scoped):
  api         base URL, e.g. http://127.0.0.1:53211/api
  test_db     pymongo Database of the throwaway DB, for arranging/asserting state
  users       {"founder"|"admin"|"manager"|"employee"|"employee2"|"intern":
               {"id", "email", "name", "role", "department", "headers"}}
  harness_env extra environment for the server; override it in a test module.
"""
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth_utils import create_access_token, hash_password  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
TEST_PASSWORD = "Harness@12345"

USERS = {
    "founder":   {"name": "Test Founder",   "role": "Founder",  "department": None},
    "admin":     {"name": "Test Admin",     "role": "Admin",    "department": None},
    "manager":   {"name": "Test Manager",   "role": "Manager",  "department": "Tech"},
    "employee":  {"name": "Test Employee",  "role": "Employee", "department": "Tech"},
    "employee2": {"name": "Test Employee2", "role": "Employee", "department": "Sales"},
    "intern":    {"name": "Test Intern",    "role": "Intern",   "department": "Tech"},
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(api, user, method, path, **kwargs):
    """requests wrapper: call(api, users["admin"], "GET", "/tasks", params={...})."""
    headers = {**(user["headers"] if user else {}), **kwargs.pop("headers", {})}
    return requests.request(method, f"{api}{path}", headers=headers, timeout=15, **kwargs)


@pytest.fixture(scope="module")
def harness_env():
    return {}


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable at {MONGO_URL}: {e}")
    name = f"wavygo_test_{uuid.uuid4().hex[:10]}"
    client.harness_db_name = name
    yield client
    client.drop_database(name)
    client.close()


@pytest.fixture(scope="module")
def test_db(mongo):
    return mongo[mongo.harness_db_name]


@pytest.fixture(scope="module")
def api(mongo, harness_env, tmp_path_factory):
    port = _free_port()
    log = open(tmp_path_factory.mktemp("api") / "uvicorn.log", "w")
    # Never send real email from tests: an empty key makes every email sender a logged no-op.
    env = {**os.environ, "DB_NAME": mongo.harness_db_name, "BREVO_API_KEY": "", **harness_env}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)],
        cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
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
        log.close()
        pytest.fail(f"Test backend did not start, see {log.name}")
    yield base
    proc.terminate()
    proc.wait(10)
    log.close()
    print(f"test backend log: {log.name}")


@pytest.fixture(scope="module")
def users(test_db, api):
    """One active user per role. Only one Founder may exist, so reuse the one startup seeded."""
    out = {}
    for key, u in USERS.items():
        if u["role"] == "Founder":
            doc = test_db.users.find_one({"role": "Founder"})
            test_db.users.update_one({"_id": doc["_id"]}, {"$set": {
                "name": u["name"], "password_hash": hash_password(TEST_PASSWORD), "status": "active"}})
            _id, email = doc["_id"], doc["email"]
        else:
            _id = ObjectId()
            email = f"{key}.{_id}@harness.wavygo.in"
            test_db.users.insert_one({
                "_id": _id, "email": email, "status": "active", "is_active": True,
                "password_hash": hash_password(TEST_PASSWORD), **u,
            })
        token = create_access_token(str(_id), email, u["role"])
        out[key] = {"id": str(_id), "email": email, "headers": {"Authorization": f"Bearer {token}"}, **u}
    return out
