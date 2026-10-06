from __future__ import annotations
"""Company resource assignment API tests using the isolated local API harness."""

from local_harness import api, mongo, test_db, users, harness_env, call  # noqa: F401


def _resource(name, assigned_to=None):
    return {
        "name": name,
        "category": "Equipment",
        "description": "Shared test resource",
        "status": "available",
        "assigned_to": assigned_to,
    }


def test_founder_can_manage_resources_and_assignments(api, users, test_db):
    created = call(api, users["founder"], "POST", "/resources", json=_resource("Test laptop", users["employee"]["id"]))
    assert created.status_code == 201, created.text
    resource = created.json()
    assert resource["assigned_to"] == users["employee"]["id"]
    assert resource["assigned_to_name"] == users["employee"]["name"]

    updated = call(
        api,
        users["founder"],
        "PATCH",
        f"/resources/{resource['id']}",
        json={**_resource("Test laptop"), "status": "maintenance"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["assigned_to"] is None
    assert updated.json()["status"] == "maintenance"

    deleted = call(api, users["founder"], "DELETE", f"/resources/{resource['id']}")
    assert deleted.status_code == 200, deleted.text
    assert test_db.company_resources.count_documents({"_id": {"$exists": True}}) == 0


def test_resource_visibility_respects_manager_department(api, users):
    for name, employee in (("Tech laptop", "employee"), ("Sales laptop", "employee2")):
        response = call(
            api,
            users["founder"],
            "POST",
            "/resources",
            json=_resource(name, users[employee]["id"]),
        )
        assert response.status_code == 201, response.text

    visible = call(api, users["manager"], "GET", "/resources")
    assert visible.status_code == 200, visible.text
    assert [item["name"] for item in visible.json()] == ["Tech laptop"]
    outside_team = call(
        api,
        users["manager"],
        "GET",
        "/resources",
        params={"assigned_to": users["employee2"]["id"]},
    )
    assert outside_team.status_code == 200
    assert outside_team.json() == []


def test_only_founder_can_manage_and_directory_roles_can_read(api, users):
    assert call(api, users["employee"], "GET", "/resources").status_code == 403
    assert call(api, users["admin"], "POST", "/resources", json=_resource("Not allowed")).status_code == 403
    assert call(api, users["manager"], "POST", "/resources", json=_resource("Not allowed")).status_code == 403
