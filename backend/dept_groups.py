from __future__ import annotations
"""Department-wise group channels for WavyGo Connect.

One 'group' kind channel per department, auto-created and kept in sync
with each employee's current `department` field on the users collection.

Usage:
  - get_or_create_department_channel(db, dept_name) -> channel doc
  - add_member_to_department_channel(db, user_id, dept_name)
  - remove_member_from_department_channel(db, user_id, dept_name)
  - sync_employee_department_group(db, user_id, old_department, new_department)
      ^ call this any time an employee's department is set or changed
"""
from hub_utils import utc_iso


async def get_or_create_department_channel(db, department_name: str | None):
    """Return the group channel for a department, creating it if it doesn't exist yet.
    Safe to call repeatedly (idempotent)."""
    if not department_name:
        return None
    name = department_name.strip()
    if not name:
        return None

    channel = await db.channels.find_one({"kind": "group", "department": name})
    if channel:
        return channel

    doc = {
        "name": f"{name} Group",
        "kind": "group",
        "department": name,  # tags this channel as THE group for this department
        "description": f"Department group for {name}",
        "members": [],
        "created_by": "system",
        "created_at": utc_iso(),
        "last_message_at": utc_iso(),
    }
    res = await db.channels.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


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


async def rename_department_channel(db, old_department: str | None, new_department: str | None, member_ids=()):
    """Carry a department's group over to its new name: the existing channel is renamed (keeping its
    members and history) rather than a new, empty one being created. If a group already exists under
    the new name, the old group's members join it. `member_ids` (everyone now in the department) are
    added either way, so the group ends up matching the department."""
    old = (old_department or "").strip()
    new = (new_department or "").strip()
    if not new:
        return None
    channel = await db.channels.find_one({"kind": "group", "department": new})
    old_channel = await db.channels.find_one({"kind": "group", "department": old}) if old and old != new else None
    if old_channel and not channel:
        await db.channels.update_one({"_id": old_channel["_id"]}, {"$set": {
            "department": new,
            "name": f"{new} Group",
            "description": f"Department group for {new}",
        }})
        channel = await db.channels.find_one({"_id": old_channel["_id"]})
    elif old_channel:
        await db.channels.update_one({"_id": channel["_id"]},
                                     {"$addToSet": {"members": {"$each": old_channel.get("members", [])}}})
    if not channel:
        channel = await get_or_create_department_channel(db, new)
    ids = [str(i) for i in member_ids if i]
    if ids:
        await db.channels.update_one({"_id": channel["_id"]}, {"$addToSet": {"members": {"$each": ids}}})
    return await db.channels.find_one({"_id": channel["_id"]})
