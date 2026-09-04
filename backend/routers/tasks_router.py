from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import TaskIn, TaskStatusPatch, TaskCommentIn, SubtaskIn
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _dept_ids(db, department):
    if not department:
        return []
    return [str(u["_id"]) async for u in db.users.find({"department": department}, {"_id": 1})]


def _role_task_filter(current: UserPublic, dept_ids: list[str] | None = None):
    """Build the same role-based task visibility filter used across endpoints."""
    if current.role == "Manager":
        ids = dept_ids or []
        return {"$or": [{"assignee_id": {"$in": ids}}, {"reporter_id": {"$in": ids}}]}
    elif current.role == "Employee":
        return {"$or": [{"assignee_id": current.id}, {"reporter_id": current.id}]}
    elif current.role == "Intern":
        return {"assignee_id": current.id}
    return None


@router.get("")
async def list_tasks(status: str | None = None, assignee_id: str | None = None,
                     module: str | None = None, limit: int = Query(200, ge=1, le=500),
                     current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if status: q["status"] = status
    if assignee_id: q["assignee_id"] = assignee_id
    if module: q["module"] = module

    role_filter = None
    if current.role == "Manager":
        ids = await _dept_ids(db, current.department)
        role_filter = _role_task_filter(current, ids)
    elif current.role in ("Employee", "Intern"):
        role_filter = _role_task_filter(current)

    if role_filter:
        q = {"$and": [q, role_filter]} if q else role_filter

    docs = await db.tasks.find(q).sort("created_at", -1).to_list(limit)
    return serialize_many(docs)


async def _enrich_names(db, doc):
    for src, dst in (("assignee_id", "assignee_name"), ("reporter_id", "reporter_name")):
        uid = doc.get(src)
        if uid:
            try:
                u = await db.users.find_one({"_id": ObjectId(uid)}, {"name": 1, "role": 1, "photo": 1})
                if u:
                    doc[dst] = u["name"]
                    if src == "assignee_id":
                        doc["assignee_role"] = u.get("role")
                        doc["assignee_photo"] = u.get("photo")
            except Exception:
                pass
    return doc


@router.post("", status_code=201)
async def create_task(payload: TaskIn, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if current.role == "Intern":
        raise HTTPException(403, "Interns cannot create tasks")
    doc = payload.model_dump()
    if not doc.get("reporter_id"):
        doc["reporter_id"] = current.id
    doc["subtasks"] = [s if isinstance(s, dict) else s.model_dump() for s in doc.get("subtasks", [])]
    doc["comments"] = []
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    res = await db.tasks.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _enrich_names(db, doc)
    await log_activity(db, current, "Created task", "Task Board", target=doc["title"])
    if doc.get("assignee_id") and doc["assignee_id"] != current.id:
        await notify(db, doc["assignee_id"], "New task assigned",
                     f"{current.name} assigned you: {doc['title']}", kind="info", link="/task-board")
    return serialize(doc)


@router.get("/{task_id}")
async def get_task(task_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    await _enrich_names(db, doc)
    return serialize(doc)


def _can_touch_task(role, doc, uid):
    if role in ("Founder", "Admin", "Manager"):
        return True
    if role == "Employee":
        return doc.get("assignee_id") == uid or doc.get("reporter_id") == uid
    if role == "Intern":
        return doc.get("assignee_id") == uid
    return False


@router.patch("/{task_id}")
async def update_task(task_id: str, payload: dict, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    existing = await db.tasks.find_one({"_id": oid(task_id)})
    if not existing:
        raise HTTPException(404, "Not found")
    if not _can_touch_task(current.role, existing, current.id):
        raise HTTPException(403, "You cannot edit this task")
    if current.role == "Intern":
        # Interns may only change the status of their own assigned tasks.
        payload = {"status": payload["status"]} if "status" in payload else {}
        if not payload:
            raise HTTPException(403, "Interns can only update task status")
    payload.pop("id", None); payload.pop("_id", None); payload.pop("created_at", None); payload.pop("comments", None)
    payload["updated_at"] = utc_iso()
    if "subtasks" in payload:
        payload["subtasks"] = [s if isinstance(s, dict) else s for s in payload["subtasks"]]
    res = await db.tasks.update_one({"_id": oid(task_id)}, {"$set": payload})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    await _enrich_names(db, doc)
    if "assignee_id" in payload and payload["assignee_id"] and payload["assignee_id"] != current.id:
        await notify(db, payload["assignee_id"], "Task reassigned to you",
                     f"{current.name} moved '{doc['title']}' to you", kind="info", link="/task-board")
    await log_activity(db, current, "Updated task", "Task Board", target=doc["title"])
    return serialize(doc)


@router.patch("/{task_id}/status")
async def update_status(task_id: str, payload: TaskStatusPatch, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    existing = await db.tasks.find_one({"_id": oid(task_id)})
    if not existing:
        raise HTTPException(404, "Not found")
    if not _can_touch_task(current.role, existing, current.id):
        raise HTTPException(403, "You cannot update this task")
    await db.tasks.update_one({"_id": oid(task_id)}, {"$set": {"status": payload.status, "updated_at": utc_iso()}})
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    await log_activity(db, current, f"Task → {payload.status.replace('_', ' ')}", "Task Board", target=doc["title"])
    if doc.get("assignee_id") and payload.status == "completed":
        await notify(db, doc.get("reporter_id"), "Task completed",
                     f"'{doc['title']}' was marked completed by {current.name}", kind="success", link="/task-board")
    await _enrich_names(db, doc)
    return serialize(doc)


@router.delete("/{task_id}")
async def delete_task(task_id: str, current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    await db.tasks.delete_one({"_id": oid(task_id)})
    await log_activity(db, current, "Deleted task", "Task Board", target=doc["title"])
    return {"ok": True}


@router.post("/{task_id}/comments", status_code=201)
async def add_comment(task_id: str, payload: TaskCommentIn, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    if current.role not in ("Founder", "Admin", "Manager"):
        if not (doc.get("assignee_id") == current.id or doc.get("reporter_id") == current.id):
            raise HTTPException(403, "You can only comment on your own tasks")
    comment = {
        "id": str(ObjectId()),
        "body": payload.body,
        "author_id": current.id,
        "author_name": current.name,
        "created_at": utc_iso(),
        "attachments": payload.attachments or [],
        "attachment_name": payload.attachment_name,
    }
    await db.tasks.update_one({"_id": oid(task_id)}, {"$push": {"comments": comment}, "$set": {"updated_at": utc_iso()}})
    if doc.get("assignee_id") and doc["assignee_id"] != current.id:
        await notify(db, doc["assignee_id"], "New task comment",
                     f"{current.name} commented on '{doc['title']}'", kind="info", link="/task-board")
    await log_activity(db, current, "Commented on task", "Task Board", target=doc["title"])
    return comment


@router.get("/stats/overview")
async def task_stats(current: UserPublic = Depends(get_current_user)):
    db = get_db()

    role_filter = None
    if current.role == "Manager":
        ids = await _dept_ids(db, current.department)
        role_filter = _role_task_filter(current, ids)
    elif current.role in ("Employee", "Intern"):
        role_filter = _role_task_filter(current)

    async def c(extra: dict):
        q = {"$and": [extra, role_filter]} if role_filter else extra
        return await db.tasks.count_documents(q)

    return {
        "todo":        await c({"status": "todo"}),
        "in_progress": await c({"status": "in_progress"}),
        "review":      await c({"status": "review"}),
        "completed":   await c({"status": "completed"}),
        "cancelled":   await c({"status": "cancelled"}),
        "mine":        await c({"assignee_id": current.id, "status": {"$in": ["todo", "in_progress", "review"]}}),
    }