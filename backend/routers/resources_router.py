from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from auth_utils import require_roles
from db import get_db
from hub_utils import log_activity, serialize
from models import UserPublic
from models_part2 import ResourceIn

router = APIRouter(prefix="/resources", tags=["resources"])


async def _validate_assignee(db, assigned_to: str | None) -> str | None:
    assigned_to = (assigned_to or "").strip()
    if not assigned_to:
        return None
    if not ObjectId.is_valid(assigned_to):
        raise HTTPException(400, "Please select a valid employee")
    employee = await db.users.find_one({"_id": ObjectId(assigned_to)})
    if (
        not employee
        or not employee.get("password_hash")
        or employee.get("status") == "deactivated"
        or employee.get("is_active") is False
    ):
        raise HTTPException(400, "Assigned employee is not active")
    return assigned_to


async def _resource_out(db, resources: list[dict]) -> list[dict]:
    assigned_ids = {
        item["assigned_to"]
        for item in resources
        if ObjectId.is_valid(str(item.get("assigned_to") or ""))
    }
    users = {}
    if assigned_ids:
        user_docs = await db.users.find(
            {"_id": {"$in": [ObjectId(user_id) for user_id in assigned_ids]}},
            {"name": 1},
        ).to_list(len(assigned_ids))
        users = {str(item["_id"]): item["name"] for item in user_docs}
    return [
        {
            **serialize(item),
            "assigned_to_name": users.get(item.get("assigned_to")),
        }
        for item in resources
    ]


@router.get("")
async def list_resources(
    assigned_to: str | None = None,
    current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager")),
):
    db = get_db()
    query = {}

    if current.role == "Manager":
        team_ids = [
            str(user["_id"])
            async for user in db.users.find(
                {"department": current.department, "password_hash": {"$nin": ["", None]}},
                {"_id": 1},
            )
        ] if current.department else []
        if assigned_to:
            if assigned_to not in team_ids:
                return []
            query["assigned_to"] = assigned_to
        else:
            query["assigned_to"] = {"$in": team_ids}
    elif assigned_to:
        if not ObjectId.is_valid(assigned_to):
            raise HTTPException(400, "Please select a valid employee")
        query["assigned_to"] = assigned_to

    resources = await db.company_resources.find(query).sort("created_at", -1).to_list(500)
    return await _resource_out(db, resources)


@router.post("", status_code=201)
async def create_resource(
    payload: ResourceIn,
    current: UserPublic = Depends(require_roles("Founder")),
):
    db = get_db()
    name = payload.name.strip()
    category = payload.category.strip()
    if not name or not category:
        raise HTTPException(400, "Resource name and category are required")
    doc = payload.model_dump()
    doc.update({
        "name": name,
        "category": category,
        "assigned_to": await _validate_assignee(db, payload.assigned_to),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    result = await db.company_resources.insert_one(doc)
    saved = await db.company_resources.find_one({"_id": result.inserted_id})
    await log_activity(db, current, "Created company resource", "Resources", name)
    return (await _resource_out(db, [saved]))[0]


@router.patch("/{resource_id}")
async def update_resource(
    resource_id: str,
    payload: ResourceIn,
    current: UserPublic = Depends(require_roles("Founder")),
):
    if not ObjectId.is_valid(resource_id):
        raise HTTPException(400, "Invalid resource id")
    db = get_db()
    resource = await db.company_resources.find_one({"_id": ObjectId(resource_id)})
    if not resource:
        raise HTTPException(404, "Resource not found")
    name = payload.name.strip()
    category = payload.category.strip()
    if not name or not category:
        raise HTTPException(400, "Resource name and category are required")
    changes = payload.model_dump()
    changes.update({
        "name": name,
        "category": category,
        "assigned_to": await _validate_assignee(db, payload.assigned_to),
    })
    await db.company_resources.update_one({"_id": resource["_id"]}, {"$set": changes})
    saved = await db.company_resources.find_one({"_id": resource["_id"]})
    await log_activity(db, current, "Updated company resource", "Resources", name)
    return (await _resource_out(db, [saved]))[0]


@router.delete("/{resource_id}")
async def delete_resource(
    resource_id: str,
    current: UserPublic = Depends(require_roles("Founder")),
):
    if not ObjectId.is_valid(resource_id):
        raise HTTPException(400, "Invalid resource id")
    db = get_db()
    resource = await db.company_resources.find_one_and_delete({"_id": ObjectId(resource_id)})
    if not resource:
        raise HTTPException(404, "Resource not found")
    await log_activity(db, current, "Deleted company resource", "Resources", resource["name"])
    return {"ok": True}
