from __future__ import annotations
import base64
import binascii
import hashlib
import re
from typing import List, Optional
from urllib.parse import quote, unquote_to_bytes

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from bson import Binary, ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import TaskIn, TaskStatusPatch, TaskCommentIn, SubtaskIn, TaskStatus, TaskPriority
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify
from email_utils import notify_assignment_by_email
from permissions import can

router = APIRouter(prefix="/tasks", tags=["tasks"])

# File content lives in `task_files` (one document per file); tasks and comments only carry
# metadata {id, name, size, content_type, uploaded_at, uploaded_by}. 15 MB keeps a single file
# document under MongoDB's 16 MB limit.
MAX_FILE_BYTES = 15 * 1024 * 1024


class TaskPatchIn(BaseModel):
    """Partial task update. Attachments are managed through /tasks/{id}/files, comments via /comments."""
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=20000)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[str] = None
    reporter_id: Optional[str] = None
    module: Optional[str] = Field(None, max_length=100)
    due_date: Optional[str] = Field(None, max_length=40)
    tags: Optional[List[str]] = None
    subtasks: Optional[List[SubtaskIn]] = None
    link: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _check_required(self):
        nulled = [f for f in ("title", "status", "priority", "module", "tags", "subtasks", "reporter_id")
                  if f in self.model_fields_set and getattr(self, f) is None]
        if nulled:
            raise ValueError(f"Fields cannot be null: {', '.join(nulled)}")
        if "title" in self.model_fields_set and not self.title.strip():
            raise ValueError("Title is required")
        return self


class TaskFileIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field("application/pdf", max_length=100)
    data: str  # base64, optionally as a data URL ("data:application/pdf;base64,...")
    comment_id: Optional[str] = None


def _clean_due(value):
    """An empty due date is stored as null (older tasks may still hold "", read as empty)."""
    if isinstance(value, str):
        value = value.strip()
    return value or None


async def _dept_ids(db, department):
    if not department:
        return []
    return [str(u["_id"]) async for u in db.users.find({"department": department}, {"_id": 1})]


async def _manager_ids(db, current: UserPublic):
    """A Manager's department members, always including the Manager (who may have no department)."""
    ids = await _dept_ids(db, current.department)
    if current.id not in ids:
        ids.append(current.id)
    return ids


def _role_task_filter(current: UserPublic, dept_ids: list[str] | None = None):
    """Build the same role-based task visibility filter used across endpoints."""
    if current.role == "Manager":
        ids = dept_ids or [current.id]
        return {"$or": [{"assignee_id": {"$in": ids}}, {"reporter_id": {"$in": ids}}]}
    elif current.role == "Employee":
        return {"$or": [{"assignee_id": current.id}, {"reporter_id": current.id}]}
    elif current.role == "Intern":
        return {"assignee_id": current.id}
    return None


async def _task_filter_for(db, current: UserPublic):
    if current.role == "Manager":
        return _role_task_filter(current, await _manager_ids(db, current))
    return _role_task_filter(current)


async def _can_access_task(db, current: UserPublic, doc) -> bool:
    """Single-task twin of _role_task_filter: whoever can list a task can open and work on it."""
    if current.role in ("Founder", "Admin"):
        return True
    if current.role == "Manager":
        ids = await _manager_ids(db, current)
        return doc.get("assignee_id") in ids or doc.get("reporter_id") in ids
    if current.role == "Employee":
        return current.id in (doc.get("assignee_id"), doc.get("reporter_id"))
    if current.role == "Intern":
        return doc.get("assignee_id") == current.id
    return False


async def _load_task(db, task_id: str, current: UserPublic):
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    if not await _can_access_task(db, current, doc):
        raise HTTPException(403, "You do not have access to this task")
    return doc


async def _check_member(db, current: UserPublic, user_id: str | None, what: str = "assign tasks"):
    """Employees may only put themselves on a task; Managers stay inside their department."""
    if not user_id:
        return
    if not ObjectId.is_valid(user_id):
        raise HTTPException(422, "Invalid user id")
    # Deactivated accounts (including never-accepted invitation placeholders) cannot take tasks.
    member = await db.users.find_one({"_id": ObjectId(user_id)}, {"status": 1})
    if not member or member.get("status") == "deactivated":
        raise HTTPException(400, "Assignee not found")
    if not can(current.role, "task.assign"):
        if user_id != current.id:
            raise HTTPException(403, f"You can only {what} to yourself")
        return
    if current.role == "Manager" and user_id not in await _manager_ids(db, current):
        raise HTTPException(403, f"Managers can only {what} within their department")


# ------------------------- files -------------------------

def _decode_data_url(value: str) -> tuple[str, bytes]:
    head, _, body = value.partition(",")
    content_type = head[5:].split(";")[0] or "application/octet-stream"
    try:
        data = base64.b64decode(body) if ";base64" in head else unquote_to_bytes(body)
    except (binascii.Error, ValueError):
        data = b""
    return content_type, data


async def _store_file(db, task_id: str, data: bytes, name: str, content_type: str,
                      uploaded_by: str | None, comment_id: str | None = None, legacy_key: str | None = None):
    """Insert one file into task_files and return the metadata stored on the task/comment."""
    now = utc_iso()
    file_doc = {
        "task_id": task_id, "comment_id": comment_id, "name": name, "content_type": content_type,
        "size": len(data), "data": Binary(data), "uploaded_by": uploaded_by, "created_at": now,
    }
    if legacy_key:
        # Idempotent: concurrent readers migrating the same legacy attachment share one file.
        file_doc["legacy_key"] = legacy_key
        await db.task_files.update_one({"legacy_key": legacy_key}, {"$setOnInsert": file_doc}, upsert=True)
        saved = await db.task_files.find_one({"legacy_key": legacy_key}, {"_id": 1, "created_at": 1})
        file_id, now = saved["_id"], saved["created_at"]
    else:
        file_id = (await db.task_files.insert_one(file_doc)).inserted_id
    return {"id": str(file_id), "name": name, "size": len(data), "content_type": content_type,
            "uploaded_at": now, "uploaded_by": uploaded_by}


async def _legacy_meta(db, task_id, value, name, uploaded_by, comment_id, key):
    """Legacy attachments were inline strings: data URLs move to task_files, plain URLs stay links."""
    if value.startswith("data:"):
        content_type, data = _decode_data_url(value)
        return await _store_file(db, task_id, data, name, content_type, uploaded_by, comment_id, legacy_key=key)
    return {"id": f"legacy-{hashlib.sha1(key.encode()).hexdigest()[:16]}", "name": name, "url": value,
            "size": None, "content_type": None, "uploaded_at": None, "uploaded_by": uploaded_by}


async def _migrate_legacy_files(db, doc):
    """Lazily move inline attachments (task + comments) out of the task document, once per task."""
    tid = str(doc["_id"])
    atts = doc.get("attachments") or []
    if any(isinstance(a, str) for a in atts):
        migrated = [
            await _legacy_meta(db, tid, a, f"Task_Document_{i + 1}.pdf", doc.get("reporter_id"), None, f"{tid}:task:{i}")
            if isinstance(a, str) else a
            for i, a in enumerate(atts)
        ]
        # Only replace the array we read, so a file uploaded meanwhile is never dropped.
        await db.tasks.update_one({"_id": doc["_id"], "attachments": atts}, {"$set": {"attachments": migrated}})
        doc["attachments"] = migrated
    for c in doc.get("comments") or []:
        catts = c.get("attachments") or []
        if not any(isinstance(a, str) for a in catts):
            continue
        cid = c.get("id") or ""
        migrated = [
            await _legacy_meta(db, tid, a, c.get("attachment_name") or f"Comment_Attachment_{i + 1}.pdf",
                               c.get("author_id"), cid, f"{tid}:comment:{cid}:{i}")
            if isinstance(a, str) else a
            for i, a in enumerate(catts)
        ]
        if cid:
            await db.tasks.update_one({"_id": doc["_id"], "comments.id": cid},
                                      {"$set": {"comments.$.attachments": migrated}})
        c["attachments"] = migrated
    return doc


def _content_disposition(kind: str, name: str) -> str:
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", name) or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


# ------------------------- tasks -------------------------

async def _enrich_many(db, docs):
    """Batched assignee/reporter names for list views (one users query per page)."""
    ids = {d.get(k) for d in docs for k in ("assignee_id", "reporter_id")}
    oids = [ObjectId(i) for i in ids if isinstance(i, str) and ObjectId.is_valid(i)]
    people = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": oids}}, {"name": 1, "role": 1, "photo": 1})}
    for d in docs:
        a, r = people.get(d.get("assignee_id")), people.get(d.get("reporter_id"))
        if a:
            d["assignee_name"], d["assignee_role"], d["assignee_photo"] = a["name"], a.get("role"), a.get("photo")
        if r:
            d["reporter_name"] = r["name"]
    return docs


@router.get("")
async def list_tasks(
    status: str | None = None,
    assignee_id: str | None = None,
    module: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()
    q = {}

    if status:
        q["status"] = status
    if assignee_id:
        q["assignee_id"] = assignee_id
    if module:
        q["module"] = module

    role_filter = await _task_filter_for(db, current)

    if role_filter:
        q = {"$and": [q, role_filter]} if q else role_filter

    docs = await db.tasks.find(q).sort("created_at", -1).to_list(limit)
    for d in docs:
        await _migrate_legacy_files(db, d)
    await _enrich_many(db, docs)
    return serialize_many(docs)


async def _enrich_names(db, doc):
    for src, dst in (
        ("assignee_id", "assignee_name"),
        ("reporter_id", "reporter_name")
    ):
        uid = doc.get(src)

        if uid:
            try:
                u = await db.users.find_one(
                    {"_id": ObjectId(uid)},
                    {"name": 1, "role": 1, "photo": 1}
                )

                if u:
                    doc[dst] = u["name"]

                    if src == "assignee_id":
                        doc["assignee_role"] = u.get("role")
                        doc["assignee_photo"] = u.get("photo")

            except Exception:
                pass

    return doc


@router.post("", status_code=201)
async def create_task(payload: TaskIn, background_tasks: BackgroundTasks, current: UserPublic = Depends(get_current_user)):
    db = get_db()

    if current.role == "Intern":
        raise HTTPException(403, "Interns cannot create tasks")

    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(422, "Title is required")

    # Files are uploaded separately (POST /tasks/{id}/files); the reporter is always the caller.
    doc = payload.model_dump(exclude={"attachments", "reporter_id"})
    doc["title"] = title
    doc["reporter_id"] = current.id
    doc["assignee_id"] = doc.get("assignee_id") or None
    doc["due_date"] = _clean_due(doc.get("due_date"))
    doc["attachments"] = []

    await _check_member(db, current, doc["assignee_id"])

    doc["subtasks"] = [
        s if isinstance(s, dict) else s.model_dump()
        for s in doc.get("subtasks", [])
    ]

    doc["comments"] = []
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()

    res = await db.tasks.insert_one(doc)
    doc["_id"] = res.inserted_id

    await _enrich_names(db, doc)

    await log_activity(
        db,
        current,
        "Created task",
        "Task Board",
        target=doc["title"]
    )

    # Notify assigned employee with the exact task ID
    if doc.get("assignee_id") and doc["assignee_id"] != current.id:
        await notify(db, doc["assignee_id"], "New task assigned",
                     f"{current.name} assigned you: {doc['title']}", kind="info",
                     link=f"/task-board?task_id={doc['_id']}")
        # Self-assignment gets no email, same as the in-app notification.
        await notify_assignment_by_email(
            db=db,
            assignee_id=doc["assignee_id"],
            item_type="task",
            item_title=doc.get("title", "Untitled Task"),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("priority"),
            deadline=doc.get("due_date"),
            item_id=str(doc["_id"]),
            background_tasks=background_tasks,
        )
    return serialize(doc)


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()

    doc = await _load_task(db, task_id, current)

    await _migrate_legacy_files(db, doc)
    await _enrich_names(db, doc)

    return serialize(doc)


def _completion_fields(status) -> dict:
    """completed_at marks when a task was finished (analytics cycle time); reopening clears it."""
    if status is None:
        return {}
    return {"completed_at": utc_iso() if status == "completed" else None}


async def _notify_completed(db, current: UserPublic, before, doc):
    """Tell the reporter a task was completed, unless they completed it themselves."""
    if before.get("status") == "completed" or doc.get("status") != "completed":
        return
    reporter = doc.get("reporter_id")
    if reporter and reporter != current.id:
        await notify(
            db,
            reporter,
            "Task completed",
            f"'{doc['title']}' was marked completed by {current.name}",
            kind="success",
            link=f"/task-board?task_id={str(doc['_id'])}"
        )


@router.patch("/{task_id}")
async def update_task(task_id: str, payload: TaskPatchIn, background_tasks: BackgroundTasks, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if isinstance(payload, dict):  # direct (non-HTTP) callers may pass a plain dict
        payload = TaskPatchIn.model_validate(payload)

    existing = await _load_task(db, task_id, current)

    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
    if "assignee_id" in changes:
        changes["assignee_id"] = changes["assignee_id"] or None
    if "due_date" in changes:
        changes["due_date"] = _clean_due(changes["due_date"])
    # Values echoed back unchanged are not edits (and must not count as reassignments).
    # Legacy tasks may store "" for "no due date"; that equals a cleared (null) due date.
    before = {**existing, "due_date": _clean_due(existing.get("due_date"))}
    changes = {k: v for k, v in changes.items() if before.get(k) != v}

    if current.role == "Intern" and set(changes) - {"status"}:
        # Interns may only change the status of their own assigned tasks.
        raise HTTPException(403, "Interns can only update task status")

    if {"assignee_id", "reporter_id"} & set(changes) and not can(current.role, "task.assign"):
        raise HTTPException(403, "You cannot change the assignee or reporter of a task")
    if "assignee_id" in changes:
        await _check_member(db, current, changes["assignee_id"])
    if "reporter_id" in changes:
        await _check_member(db, current, changes["reporter_id"], "set reporters")

    if changes:
        changes["updated_at"] = utc_iso()
        changes.update(_completion_fields(changes.get("status")))
        res = await db.tasks.update_one(
            {"_id": oid(task_id)},
            {"$set": changes}
        )

        if res.matched_count == 0:
            raise HTTPException(404, "Not found")

    doc = await db.tasks.find_one({"_id": oid(task_id)})

    await _migrate_legacy_files(db, doc)
    await _enrich_names(db, doc)
    new_assignee = changes.get("assignee_id")
    if new_assignee and new_assignee != current.id:
        await notify(db, new_assignee, "Task reassigned to you",
                     f"{current.name} moved '{doc['title']}' to you", kind="info",
                     link=f"/task-board?task_id={task_id}")
    if new_assignee and new_assignee != current.id:
        await notify_assignment_by_email(
            db=db,
            assignee_id=new_assignee,
            item_type="task",
            item_title=doc.get("title", existing.get("title", "Untitled Task")),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("priority", existing.get("priority")),
            deadline=doc.get("due_date", existing.get("due_date")),
            item_id=str(doc["_id"]),
            background_tasks=background_tasks,
        )
    if "status" in changes:
        await _notify_completed(db, current, existing, doc)
    if changes:
        await log_activity(db, current, "Updated task", "Task Board", target=doc["title"],
                           meta={"fields": sorted(k for k in changes if k != "updated_at")})
    return serialize(doc)


@router.patch("/{task_id}/status")
async def update_status(
    task_id: str,
    payload: TaskStatusPatch,
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()

    existing = await _load_task(db, task_id, current)

    if existing.get("status") == payload.status:
        # Same status (e.g. a card dropped back into its column): nothing to record.
        await _migrate_legacy_files(db, existing)
        await _enrich_names(db, existing)
        return serialize(existing)

    await db.tasks.update_one(
        {"_id": oid(task_id)},
        {
            "$set": {
                "status": payload.status,
                "updated_at": utc_iso(),
                **_completion_fields(payload.status),
            }
        }
    )

    doc = await db.tasks.find_one({"_id": oid(task_id)})

    await log_activity(
        db,
        current,
        f"Task → {payload.status.replace('_', ' ')}",
        "Task Board",
        target=doc["title"]
    )

    # Notify reporter with the exact task ID
    await _notify_completed(db, current, existing, doc)

    await _migrate_legacy_files(db, doc)
    await _enrich_names(db, doc)

    return serialize(doc)


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current: UserPublic = Depends(require_roles("Founder", "Admin"))
):
    db = get_db()

    doc = await db.tasks.find_one({"_id": oid(task_id)})

    if not doc:
        raise HTTPException(404, "Not found")

    await db.tasks.delete_one({"_id": oid(task_id)})
    await db.task_files.delete_many({"task_id": task_id})

    await log_activity(
        db,
        current,
        "Deleted task",
        "Task Board",
        target=doc["title"]
    )

    return {"ok": True}


@router.post("/{task_id}/comments", status_code=201)
async def add_comment(
    task_id: str,
    payload: TaskCommentIn,
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()

    doc = await _load_task(db, task_id, current)

    body = (payload.body or "").strip()
    if not body and not payload.attachments:
        raise HTTPException(422, "Comment cannot be empty")

    comment_id = str(ObjectId())
    # Older clients still send inline data URLs; those go to task_files like any upload.
    attachments = []
    for i, a in enumerate(payload.attachments or []):
        name = payload.attachment_name or f"Comment_Attachment_{i + 1}.pdf"
        attachments.append(await _legacy_meta(db, task_id, a, name, current.id, comment_id,
                                              f"{task_id}:comment:{comment_id}:{i}"))

    comment = {
        "id": comment_id,
        "body": body,
        "author_id": current.id,
        "author_name": current.name,
        "created_at": utc_iso(),
        "attachments": attachments,
        "attachment_name": payload.attachment_name,
    }

    await db.tasks.update_one(
        {"_id": oid(task_id)},
        {
            "$push": {"comments": comment},
            "$set": {"updated_at": utc_iso()}
        }
    )

    # Notify assignee with the exact task ID
    if doc.get("assignee_id") and doc["assignee_id"] != current.id:
        await notify(
            db,
            doc["assignee_id"],
            "New task comment",
            f"{current.name} commented on '{doc['title']}'",
            kind="info",
            link=f"/task-board?task_id={str(doc['_id'])}"
        )

    await log_activity(
        db,
        current,
        "Commented on task",
        "Task Board",
        target=doc["title"]
    )

    return comment


@router.post("/{task_id}/files", status_code=201)
async def upload_task_file(
    task_id: str,
    payload: TaskFileIn,
    current: UserPublic = Depends(get_current_user)
):
    """Attach a PDF to the task, or to one of its comments when comment_id is given."""
    db = get_db()

    doc = await _load_task(db, task_id, current)

    body = payload.data.partition(",")[2] if payload.data.startswith("data:") else payload.data
    if len(body) > MAX_FILE_BYTES * 4 // 3 + 16:
        raise HTTPException(413, "Files must be under 15MB")
    try:
        data = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "File data must be base64 encoded")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Files must be under 15MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, "Only PDF documents can be attached")

    if payload.comment_id:
        comment = next((c for c in doc.get("comments") or [] if c.get("id") == payload.comment_id), None)
        if not comment:
            raise HTTPException(404, "Comment not found")
        if comment.get("author_id") != current.id and not can(current.role, "task.edit_any"):
            raise HTTPException(403, "You can only attach files to your own comments")
    elif current.role == "Intern":
        raise HTTPException(403, "Interns can attach documents to their comments only")

    name = payload.name.replace("\\", "/").rsplit("/", 1)[-1].strip() or "Document.pdf"
    meta = await _store_file(db, task_id, data, name, "application/pdf", current.id, payload.comment_id)

    if payload.comment_id:
        await db.tasks.update_one(
            {"_id": oid(task_id), "comments.id": payload.comment_id},
            {"$push": {"comments.$.attachments": meta}, "$set": {"updated_at": utc_iso()}}
        )
    else:
        await db.tasks.update_one(
            {"_id": oid(task_id)},
            {"$push": {"attachments": meta}, "$set": {"updated_at": utc_iso()}}
        )

    await log_activity(db, current, "Attached file to task", "Task Board",
                       target=f"{doc['title']} · {name}")

    return meta


@router.get("/{task_id}/files/{file_id}")
async def download_task_file(
    task_id: str,
    file_id: str,
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()

    await _load_task(db, task_id, current)

    f = await db.task_files.find_one({"_id": oid(file_id), "task_id": task_id})
    if not f:
        raise HTTPException(404, "File not found")

    # Only PDFs are rendered inline; anything else (legacy data URLs) is forced to download.
    is_pdf = f.get("content_type") == "application/pdf"
    return Response(
        content=bytes(f["data"]),
        media_type="application/pdf" if is_pdf else "application/octet-stream",
        headers={
            "Content-Disposition": _content_disposition("inline" if is_pdf else "attachment", f.get("name") or "file"),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/{task_id}/files/{file_id}")
async def delete_task_file(
    task_id: str,
    file_id: str,
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()

    doc = await _load_task(db, task_id, current)
    await _migrate_legacy_files(db, doc)

    metas = list(doc.get("attachments") or []) + [
        a for c in doc.get("comments") or [] for a in c.get("attachments") or []
    ]
    meta = next((a for a in metas if isinstance(a, dict) and a.get("id") == file_id), None)
    if not meta:
        raise HTTPException(404, "File not found")

    if meta.get("uploaded_by") != current.id and not can(current.role, "task.edit_any"):
        raise HTTPException(403, "Only the uploader can remove this file")

    await db.tasks.update_one(
        {"_id": oid(task_id)},
        {
            "$pull": {"attachments": {"id": file_id}, "comments.$[].attachments": {"id": file_id}},
            "$set": {"updated_at": utc_iso()}
        }
    )
    if ObjectId.is_valid(file_id):
        await db.task_files.delete_one({"_id": ObjectId(file_id), "task_id": task_id})

    await log_activity(db, current, "Removed file from task", "Task Board",
                       target=f"{doc['title']} · {meta.get('name')}")

    return {"ok": True}


@router.get("/stats/overview")
async def task_stats(
    current: UserPublic = Depends(get_current_user)
):
    db = get_db()

    role_filter = await _task_filter_for(db, current)

    async def c(extra: dict):
        q = (
            {"$and": [extra, role_filter]}
            if role_filter
            else extra
        )

        return await db.tasks.count_documents(q)

    return {
        "todo": await c({"status": "todo"}),
        "in_progress": await c({"status": "in_progress"}),
        "review": await c({"status": "review"}),
        "completed": await c({"status": "completed"}),
        "cancelled": await c({"status": "cancelled"}),
        "mine": await c({
            "assignee_id": current.id,
            "status": {
                "$in": ["todo", "in_progress", "review"]
            }
        }),
    }
