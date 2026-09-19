from __future__ import annotations
"""Department-wise group channels for WavyGo Connect.

One ``group`` channel is created for every record in ``departments``.  The
department on a user record is the source of truth for group access; the
``members`` field is retained and reconciled for compatibility with the
existing Connect channel schema.

Usage:
  - get_or_create_department_channel(db, dept_name) -> channel doc
  - add_member_to_department_channel(db, user_id, dept_name)
  - remove_member_from_department_channel(db, user_id, dept_name)
  - sync_employee_department_group(db, user_id, old_department, new_department)
      ^ call this any time an employee's department is set or changed
"""
from hub_utils import utc_iso
from pymongo import ReturnDocument


def _normalise(name: str | None) -> str:
    return (name or "").strip().casefold()


async def canonical_department_name(db, department_name: str | None) -> str | None:
    """Return the configured spelling for a department, if it exists."""
    target = _normalise(department_name)
    if not target:
        return None
    departments = await db.departments.find({}, {"name": 1}).to_list(200)
    return next(
        ((department.get("name") or "").strip()
         for department in departments
         if _normalise(department.get("name")) == target),
        None,
    )


async def ensure_department_group_index(db):
    """Enforce one department-backed group per department where Mongo allows it."""
    await db.channels.create_index(
        [("kind", 1), ("department", 1)],
        unique=True,
        partialFilterExpression={"kind": "group", "department": {"$type": "string"}},
        name="one_department_group",
    )


async def ensure_department_groups(db):
    """Create the known department groups and reconcile their cached members.

    This is safe to call from request paths.  It replaces the need for a
    one-off seed run when a deployment already has departments and employees.
    """
    await ensure_department_group_index(db)
    departments = await db.departments.find({}, {"name": 1}).to_list(200)
    for department in departments:
        name = (department.get("name") or "").strip()
        if not name:
            continue
        channel = await get_or_create_department_channel(db, name)
        members = [
            str(user["_id"])
            async for user in db.users.find({"department": name}, {"_id": 1})
        ]
        await db.channels.update_one(
            {"_id": channel["_id"]}, {"$set": {"members": members}}
        )


async def get_or_create_department_channel(db, department_name: str | None):
    """Return the group channel for a department, creating it if it doesn't exist yet.
    Safe to call repeatedly (idempotent)."""
    if not department_name:
        return None
    name = await canonical_department_name(db, department_name)
    if not name:
        return None

    doc = {
        "name": f"{name} Group",
        "kind": "group",
        "department": name,  # tags this channel as THE group for this department
        "department_group": True,
        "description": f"Department group for {name}",
        "members": [],
        "created_by": "system",
        "created_at": utc_iso(),
        "last_message_at": utc_iso(),
    }
    # Upsert + the unique index installed by ensure_department_groups protects
    # against two concurrent requests making duplicate department channels.
    channel = await db.channels.find_one_and_update(
        {"kind": "group", "department": name},
        {"$setOnInsert": doc, "$set": {"department_group": True}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return channel


async def add_member_to_department_channel(db, user_id: str, department_name: str | None):
    channel = await get_or_create_department_channel(db, department_name)
    if not channel:
        return
    if user_id not in channel.get("members", []):
        await db.channels.update_one({"_id": channel["_id"]}, {"$addToSet": {"members": user_id}})


async def remove_member_from_department_channel(db, user_id: str, department_name: str | None):
    if not department_name:
        return
    name = department_name.strip()
    if not name:
        return
    channel = await db.channels.find_one({"kind": "group", "department": name})
    if not channel:
        return
    await db.channels.update_one({"_id": channel["_id"]}, {"$pull": {"members": user_id}})


async def sync_employee_department_group(
    db, user_id: str, old_department: str | None, new_department: str | None
):
    """THE MAIN ENTRY POINT.

    Call this whenever an employee's department is set for the first time
    or changed. Removes them from the old department's group and adds them
    to the new one. If old == new, just makes sure they're a member
    (covers first-time invite acceptance where old_department is None).
    """
    old_department = (old_department or "").strip()
    new_department = (new_department or "").strip()

    if old_department == new_department:
        if new_department:
            await add_member_to_department_channel(db, user_id, new_department)
        return

    if old_department:
        await remove_member_from_department_channel(db, user_id, old_department)
    if new_department:
        await add_member_to_department_channel(db, user_id, new_department)


def is_department_group_member(channel: dict, department_name: str | None) -> bool:
    """Return whether a live employee department grants access to ``channel``."""
    return bool(channel.get("department_group")) and _normalise(channel.get("department")) == _normalise(department_name)
