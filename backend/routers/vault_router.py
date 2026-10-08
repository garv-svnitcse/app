"""Company Vault (mounted at /api/vault): Founder-only document storage.

Metadata lives in `vault_documents`, folders in `vault_folders`; file bytes live in
GridFS (bucket "vault"). Storage is isolated behind `_put_bytes` / `_get_stream` /
`_delete` so an object store (e.g. S3) can replace GridFS without touching routes.

Every version of a document keeps its own stored file. Restoring an old version
appends a new version that points at the same stored file (no byte copy), so
deletes de-duplicate file ids before removing them.

Expiry: `expires_on` is a calendar date (YYYY-MM-DD) compared against "today" in
VAULT_TZ (default Asia/Kolkata). `send_expiry_reminders(db)` notifies every active
Founder and Admin plus the document's owner (each person once) at 30 days, at 7 days and
when expired; the stages already sent are tracked in `reminders_sent` and reset whenever the
expiry date changes.

Access control: every folder and document carries `access` ({mode: everyone|restricted,
roles, departments, user_ids}) plus a derived `access_keys` list ("*", "role:<Role>",
"dept:<casefolded name>", "user:<id>") used for filtering. A user sees an item when they are a
Founder/Admin, its owner, or share a key with it. A restricted folder also hides every document
in it (cascade); a document whose folder no longer exists counts as hidden (owner + Founders/Admins
only), in both the list filter and single-document checks. Restricted with no roles/departments/people
means owner + Founders/Admins only.
Items stored before access control existed have no `access_keys` and stay visible to everyone
who can open the vault. Only the owner, Founders and Admins may edit, re-version, delete or
change access of an item. Module-level entry is still gated by permissions.py (vault.view /
vault.manage).

Server wiring (outside this module): call `await ensure_indexes(db)` on startup and
`await send_expiry_reminders(db)` periodically from the background loop.
"""
# No `from __future__ import annotations`: FastAPI resolves Form/File/Query
# parameters and the Pydantic bodies below from runtime annotations.
import hashlib
import json
import logging
import math
import os
import re
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import AsyncIterator, Literal, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
# pyrefly: ignore [missing-import]
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from gridfs.errors import NoFile

from db import get_db
from auth_utils import get_current_user
from models import UserPublic
from hub_utils import log_activity, notify, oid, utc_iso
from permissions import can

router = APIRouter(prefix="/vault", tags=["company-vault"])
logger = logging.getLogger("wavygo.vault")

MODULE = "Company Vault"
LINK = "/company-vault"
BUCKET = "vault"
MAX_BYTES = 25 * 1024 * 1024
DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 100
EXPIRY_WINDOW_DAYS = 30
MAX_TAGS = 20
MAX_TAG_LEN = 40
VAULT_TZ = os.environ.get("VAULT_TZ", "Asia/Kolkata")

# Extension -> canonical content type. The client-supplied type is never trusted.
ALLOWED_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "csv": "text/csv",
    "txt": "text/plain",
}
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
SORTS = {
    "updated": [("updated_at", -1), ("_id", -1)],
    "title": [("title_lower", 1), ("_id", 1)],
    "size": [("size", -1), ("_id", -1)],
    "expiry": [("expires_on", 1), ("_id", 1)],
}
REMINDER_STAGES = ("30d", "7d", "expired")
HIDDEN_FIELDS = ("title_lower", "reminders_sent", "file_id", "access_keys")

# Access control
ROLES = ("Founder", "Admin", "Manager", "Employee", "Intern")
VAULT_ADMIN_ROLES = {"Founder", "Admin"}  # see and manage every item regardless of its access
EVERYONE = "*"
MAX_ACCESS_DEPTS = 50
MAX_ACCESS_USERS = 200
MAX_DEPT_LEN = 80


# ------------------------- storage (swap for S3 here) -------------------------

def _bucket(db) -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(db, bucket_name=BUCKET)


async def _put_bytes(db, data: bytes, filename: str, content_type: str) -> str:
    """Store bytes, return an opaque storage id."""
    file_id = await _bucket(db).upload_from_stream(
        filename, data, metadata={"content_type": content_type})
    return str(file_id)


async def _get_stream(db, storage_id: str) -> tuple[AsyncIterator[bytes], int]:
    """Open a stored file: (async chunk iterator, length). Raises 404 if missing."""
    try:
        stream = await _bucket(db).open_download_stream(ObjectId(storage_id))
    except (NoFile, Exception) as e:  # bad id or missing file
        logger.warning("Vault file %s unavailable: %s", storage_id, e)
        raise HTTPException(404, "Stored file not found")

    async def chunks():
        try:
            while True:
                chunk = await stream.readchunk()
                if not chunk:
                    break
                yield chunk
        finally:
            stream.close()

    return chunks(), stream.length


async def _delete(db, storage_id: str) -> None:
    try:
        await _bucket(db).delete(ObjectId(storage_id))
    except NoFile:
        pass


# ------------------------- helpers -------------------------

def _require(current: UserPublic, action: str) -> None:
    if not can(current.role, action):
        if action == "vault.view":
            raise HTTPException(403, "You don't have access to the Company Vault")
        raise HTTPException(403, "You don't have permission to change the Company Vault")


# ------------------------- access control -------------------------

RoleName = Literal["Founder", "Admin", "Manager", "Employee", "Intern"]


class AccessIn(BaseModel):
    mode: Literal["everyone", "restricted"] = "everyone"
    roles: list[RoleName] = Field(default_factory=list, max_length=len(ROLES))
    departments: list[str] = Field(default_factory=list, max_length=MAX_ACCESS_DEPTS)
    user_ids: list[str] = Field(default_factory=list, max_length=MAX_ACCESS_USERS)


def _default_access() -> dict:
    return {"mode": "everyone", "roles": [], "departments": [], "user_ids": []}


def _norm_dept(name: Optional[str]) -> str:
    return " ".join((name or "").split())


def _is_vault_admin(current: UserPublic) -> bool:
    return current.role in VAULT_ADMIN_ROLES


def _viewer_keys(current: UserPublic) -> list[str]:
    keys = [EVERYONE, f"role:{current.role}", f"user:{current.id}"]
    dept = _norm_dept(current.department).casefold()
    if dept:
        keys.append(f"dept:{dept}")
    return keys


def _access_match(current: UserPublic) -> dict:
    """Mongo filter: items whose access list admits this user (legacy items have no keys)."""
    return {"$or": [{"access_keys": {"$exists": False}}, {"access_keys": {"$in": _viewer_keys(current)}}]}


def _keys_admit(item: dict, current: UserPublic) -> bool:
    keys = item.get("access_keys")
    if keys is None:  # legacy item, created before access control
        return True
    return bool(set(keys) & set(_viewer_keys(current)))


def _can_see_folder(folder: dict, current: UserPublic) -> bool:
    return _is_vault_admin(current) or folder.get("created_by") == current.id or _keys_admit(folder, current)


def _can_edit(item: dict, owner_field: str, current: UserPublic) -> bool:
    # Owner rights never bypass vault.manage (an owner whose role lost it becomes view-only).
    if not can(current.role, "vault.manage"):
        return False
    return _is_vault_admin(current) or item.get(owner_field) == current.id


def _require_edit(item: dict, owner_field: str, current: UserPublic, what: str = "document") -> None:
    if not _can_edit(item, owner_field, current):
        raise HTTPException(403, f"Only the {what}'s owner, Founders or Admins can change it")


async def _clean_access(db, raw: Optional[AccessIn]) -> dict:
    """Validate an access setting; returns {"access": ..., "access_keys": [...]}."""
    if raw is None or raw.mode == "everyone":
        return {"access": _default_access(), "access_keys": [EVERYONE]}
    roles = [r for r in ROLES if r in set(raw.roles)]
    departments: list[str] = []
    seen: set[str] = set()
    for d in raw.departments:
        d = _norm_dept(d)
        if not d:
            continue
        if len(d) > MAX_DEPT_LEN:
            raise HTTPException(422, f"Department names can be at most {MAX_DEPT_LEN} characters")
        if d.casefold() not in seen:
            seen.add(d.casefold())
            departments.append(d)
    user_ids: list[str] = []
    for u in raw.user_ids:
        u = (u or "").strip()
        if not ObjectId.is_valid(u):
            raise HTTPException(422, "Invalid employee id in access list")
        if u not in user_ids:
            user_ids.append(u)
    if user_ids:
        found = {str(d["_id"]) async for d in db.users.find(
            {"_id": {"$in": [ObjectId(u) for u in user_ids]}}, {"_id": 1})}
        if any(u not in found for u in user_ids):
            raise HTTPException(422, "Some selected employees no longer exist")
    keys = [f"role:{r}" for r in roles] + [f"dept:{d.casefold()}" for d in departments] \
        + [f"user:{u}" for u in user_ids]
    return {"access": {"mode": "restricted", "roles": roles, "departments": departments, "user_ids": user_ids},
            "access_keys": keys}


def _parse_access_form(value: Optional[str]) -> Optional[AccessIn]:
    """Multipart uploads send access as a JSON string."""
    if not value or not value.strip():
        return None
    try:
        return AccessIn.model_validate(json.loads(value))
    except (ValueError, ValidationError):
        raise HTTPException(422, "access must be JSON: {mode, roles, departments, user_ids}")


def _access_out(item: dict) -> dict:
    return item.get("access") or _default_access()


async def _visible_folder_ids(db, current: UserPublic) -> Optional[list[str]]:
    """Ids of folders this user may see; None means all (Founder/Admin)."""
    if _is_vault_admin(current):
        return None
    flt = {"$or": [{"created_by": current.id}, _access_match(current)]}
    return [str(f["_id"]) async for f in db.vault_folders.find(flt, {"_id": 1})]


async def _doc_filter(db, current: UserPublic) -> dict:
    """Mongo filter for documents this user may see. Owners always see their own documents;
    everyone else needs the document's access AND its folder's access (cascade)."""
    if _is_vault_admin(current):
        return {}
    folder_ids = await _visible_folder_ids(db, current)
    return {"$or": [
        {"uploaded_by": current.id},
        {"$and": [_access_match(current), {"folder_id": {"$in": [None, *folder_ids]}}]},
    ]}


async def _can_see_doc(db, doc: dict, current: UserPublic) -> bool:
    if _is_vault_admin(current) or doc.get("uploaded_by") == current.id:
        return True
    if not _keys_admit(doc, current):
        return False
    if doc.get("folder_id"):
        folder = await db.vault_folders.find_one({"_id": oid(doc["folder_id"])}, {"created_by": 1, "access_keys": 1})
        # Same rule as _doc_filter: a missing folder is not in the visible-folder list, so the doc is hidden.
        if not folder or not _can_see_folder(folder, current):
            return False
    return True


def _today() -> date:
    return datetime.now(ZoneInfo(VAULT_TZ)).date()


def _parse_expiry(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(422, "expires_on must be a date (YYYY-MM-DD)")


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    out: list[str] = []
    for t in tags or []:
        t = re.sub(r"\s+", " ", str(t)).strip().lower()
        if not t:
            continue
        if len(t) > MAX_TAG_LEN:
            raise HTTPException(422, f"Tags can be at most {MAX_TAG_LEN} characters")
        if t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise HTTPException(422, f"At most {MAX_TAGS} tags per document")
    return out


def _clean_text(value: Optional[str], field: str, max_len: int, required: bool = False) -> Optional[str]:
    value = (value or "").strip()
    if required and not value:
        raise HTTPException(422, f"{field} is required")
    if len(value) > max_len:
        raise HTTPException(422, f"{field} can be at most {max_len} characters")
    return value or None


def _content_disposition(kind: str, name: str) -> str:
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", name) or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def _safe_filename(name: Optional[str]) -> str:
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name[:200] or "file"


def _detect_type(filename: str, data: bytes) -> str:
    """Return the canonical content type, or raise when the type is not allowed
    or the bytes don't look like the claimed type."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ctype = ALLOWED_TYPES.get(ext)
    if not ctype:
        raise HTTPException(415, "Unsupported file type. Allowed: PDF, PNG, JPG, WEBP, DOCX, XLSX, PPTX, CSV, TXT")
    head = data[:16]
    ok = True
    if ext == "pdf":
        ok = data[:1024].lstrip(b"\xef\xbb\xbf\r\n\t ").startswith(b"%PDF-")
    elif ext == "png":
        ok = head.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in ("jpg", "jpeg"):
        ok = head.startswith(b"\xff\xd8\xff")
    elif ext == "webp":
        ok = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    elif ext in ("docx", "xlsx", "pptx"):
        ok = head.startswith(b"PK\x03\x04")
    elif ext in ("csv", "txt"):
        ok = b"\x00" not in data[:8192]
    if not ok:
        raise HTTPException(400, f"File content does not match the .{ext} extension")
    return ctype


async def _read_upload(file: UploadFile) -> tuple[bytes, str, str]:
    """Read and validate an upload: (bytes, safe filename, content type)."""
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 25 MB")
    if not data:
        raise HTTPException(400, "File is empty")
    name = _safe_filename(file.filename)
    return data, name, _detect_type(name, data)


def _expiry_state(expires_on: Optional[str], today: date) -> tuple[Optional[str], Optional[int]]:
    if not expires_on:
        return None, None
    days = (date.fromisoformat(expires_on) - today).days
    if days < 0:
        return "expired", days
    if days <= EXPIRY_WINDOW_DAYS:
        return "expiring", days
    return "valid", days


def _out(doc: dict, today: Optional[date] = None, current: Optional[UserPublic] = None) -> dict:
    today = today or _today()
    out = {k: v for k, v in doc.items() if k not in HIDDEN_FIELDS and k != "_id"}
    out["id"] = str(doc["_id"])
    out["versions"] = [
        {k: v for k, v in ver.items() if k != "file_id"}
        for ver in sorted(doc.get("versions", []), key=lambda v: v["version"], reverse=True)
    ]
    out["expiry_status"], out["days_to_expiry"] = _expiry_state(doc.get("expires_on"), today)
    out["access"] = _access_out(doc)
    out["access_legacy"] = "access_keys" not in doc
    out["can_edit"] = bool(current and _can_edit(doc, "uploaded_by", current))
    return out


async def _load(db, doc_id: str, current: UserPublic) -> dict:
    """Load a document the user may see; hidden documents are reported as not found."""
    doc = await db.vault_documents.find_one({"_id": oid(doc_id)})
    if not doc or not await _can_see_doc(db, doc, current):
        raise HTTPException(404, "Document not found")
    return doc


async def _folder_name(db, folder_id: Optional[str], current: UserPublic) -> Optional[str]:
    """Validate a folder id the user may see; returns the folder name (None for unfiled)."""
    if not folder_id:
        return None
    folder = await db.vault_folders.find_one({"_id": oid(folder_id)})
    if not folder or not _can_see_folder(folder, current):
        raise HTTPException(422, "Folder not found")
    return folder["name"]


async def _notify_founders(db, title: str, body: str, link: str, kind: str = "info",
                           exclude: Optional[str] = None) -> int:
    sent = 0
    async for u in db.users.find({"role": "Founder", "status": {"$ne": "deactivated"}}, {"_id": 1}):
        uid = str(u["_id"])
        if uid == exclude:
            continue
        await notify(db, uid, title, body, kind=kind, link=link)
        sent += 1
    return sent


async def _notify_expiry(db, doc: dict, title: str, body: str, kind: str) -> int:
    """Expiry reminder for one document: every active Founder/Admin plus its owner, each notified once."""
    active = {"status": {"$ne": "deactivated"}, "is_active": {"$ne": False}}
    ids: list[str] = [str(u["_id"]) async for u in db.users.find(
        {"role": {"$in": sorted(VAULT_ADMIN_ROLES)}, **active}, {"_id": 1})]
    owner = doc.get("uploaded_by")
    if owner and owner not in ids and ObjectId.is_valid(owner) and \
            await db.users.count_documents({"_id": ObjectId(owner), **active}, limit=1):
        ids.append(owner)
    for uid in dict.fromkeys(ids):
        await notify(db, uid, title, body, kind=kind, link=_doc_link(doc["_id"]))
    return len(set(ids))


def _doc_link(doc_id) -> str:
    return f"{LINK}?doc={doc_id}"


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def _stream_response(chunks, length: int, content_type: str, filename: str, inline: bool) -> StreamingResponse:
    inline = inline and content_type in INLINE_TYPES
    return StreamingResponse(
        chunks,
        media_type=content_type if content_type in INLINE_TYPES else "application/octet-stream",
        headers={
            "Content-Length": str(length),
            "Content-Disposition": _content_disposition("inline" if inline else "attachment", filename),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, no-store",
        },
    )


# ------------------------- setup / background -------------------------

async def ensure_indexes(db) -> None:
    await db.vault_folders.create_index("name_lower", unique=True)
    await db.vault_documents.create_index([("updated_at", -1), ("_id", -1)])
    await db.vault_documents.create_index("folder_id")
    await db.vault_documents.create_index("tags")
    await db.vault_documents.create_index("expires_on", sparse=True)
    await db.vault_documents.create_index("title_lower")
    await db.vault_documents.create_index("access_keys")
    await db.vault_documents.create_index("uploaded_by")
    await db.vault_folders.create_index("access_keys")


def _stage_for(days: int) -> Optional[str]:
    if days < 0:
        return "expired"
    if days <= 7:
        return "7d"
    if days <= 30:
        return "30d"
    return None


async def send_expiry_reminders(db) -> int:
    """Notify Founders, Admins and each document's owner about documents 30 days / 7 days from expiry
    and expired ones.
    Each stage is sent at most once per expiry date. Returns notifications sent."""
    today = _today()
    horizon = (today + timedelta(days=EXPIRY_WINDOW_DAYS)).isoformat()
    sent = 0
    cursor = db.vault_documents.find(
        {"expires_on": {"$ne": None, "$lte": horizon}, "reminders_sent": {"$ne": "expired"}},
        {"title": 1, "expires_on": 1, "reminders_sent": 1, "uploaded_by": 1},
    )
    async for doc in cursor:
        days = (date.fromisoformat(doc["expires_on"]) - today).days
        stage = _stage_for(days)
        if not stage or stage in (doc.get("reminders_sent") or []):
            continue
        # Mark this stage and every earlier one, atomically, so a late upload that is
        # already inside the 7-day window never gets a stale 30-day reminder afterwards.
        stages = list(REMINDER_STAGES[: REMINDER_STAGES.index(stage) + 1])
        res = await db.vault_documents.update_one(
            {"_id": doc["_id"], "expires_on": doc["expires_on"], "reminders_sent": {"$ne": stage}},
            {"$addToSet": {"reminders_sent": {"$each": stages}}},
        )
        if res.modified_count != 1:
            continue
        exp = date.fromisoformat(doc["expires_on"]).strftime("%d %b %Y")
        if stage == "expired":
            title, body, kind = "Document expired", f"“{doc['title']}” expired on {exp}.", "warning"
        else:
            title = "Document expiring soon"
            body = f"“{doc['title']}” expires on {exp} ({days} day{'s' if days != 1 else ''} left)."
            kind = "warning"
        sent += await _notify_expiry(db, doc, title, body, kind)
    return sent


# ------------------------- folders -------------------------

class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    access: Optional[AccessIn] = None


class FolderPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    access: Optional[AccessIn] = None


def _folder_out(f: dict, current: UserPublic, counts: Optional[dict] = None) -> dict:
    c = (counts or {}).get(str(f["_id"]), {})
    return {"id": str(f["_id"]), "name": f["name"], "count": c.get("count", 0), "size": c.get("size", 0),
            "created_at": f.get("created_at"), "created_by": f.get("created_by"),
            "access": _access_out(f), "access_legacy": "access_keys" not in f,
            "can_edit": _can_edit(f, "created_by", current)}


FOLDER_TAKEN = "A folder with this name already exists"
NAME_UNAVAILABLE = "This folder name is not available. Please choose another"


def _folder_taken(current: UserPublic, conflict: Optional[dict] = None) -> HTTPException:
    """409 for a duplicate folder name. Names are unique vault-wide, including folders the caller can't
    see, so only people who can see the clashing folder (Founder/Admin see all) get the explicit message.
    Today only Founder/Admin hold vault.manage, so they always get it; the neutral text is a safeguard."""
    visible = _is_vault_admin(current) or (conflict is not None and _can_see_folder(conflict, current))
    return HTTPException(409, FOLDER_TAKEN if visible else NAME_UNAVAILABLE)


def _folder_name_clean(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        raise HTTPException(422, "Folder name is required")
    return name


@router.get("/folders")
async def list_folders(current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.view")
    db = get_db()
    vis = await _doc_filter(db, current)
    counts = {r["_id"]: r for r in await db.vault_documents.aggregate([
        {"$match": vis},
        {"$group": {"_id": "$folder_id", "count": {"$sum": 1}, "size": {"$sum": "$size"}}},
    ]).to_list(None)}
    folder_ids = await _visible_folder_ids(db, current)
    flt = {} if folder_ids is None else {"_id": {"$in": [ObjectId(i) for i in folder_ids]}}
    folders = [_folder_out(f, current, counts) async for f in db.vault_folders.find(flt).sort("name_lower", 1)]
    unfiled = counts.get(None, {})
    return {"folders": folders, "unfiled_count": unfiled.get("count", 0),
            "total_count": sum(c["count"] for c in counts.values())}


@router.post("/folders", status_code=201)
async def create_folder(body: FolderIn, current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.manage")
    db = get_db()
    name = _folder_name_clean(body.name)
    access = await _clean_access(db, body.access)
    # Explicit check; the unique index from ensure_indexes() is the race-proof backstop.
    conflict = await db.vault_folders.find_one({"name_lower": name.lower()}, {"created_by": 1, "access_keys": 1})
    if conflict:
        raise _folder_taken(current, conflict)
    doc = {"name": name, "name_lower": name.lower(), "created_by": current.id, "created_at": utc_iso(), **access}
    try:
        res = await db.vault_folders.insert_one(doc)
    except DuplicateKeyError:
        raise _folder_taken(current)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Created vault folder", MODULE, target=name,
                       meta={"access": access["access"]["mode"]})
    return _folder_out(doc, current)


async def _load_folder(db, folder_id: str, current: UserPublic) -> dict:
    folder = await db.vault_folders.find_one({"_id": oid(folder_id)})
    if not folder or not _can_see_folder(folder, current):
        raise HTTPException(404, "Folder not found")
    return folder


@router.patch("/folders/{folder_id}")
async def update_folder(folder_id: str, body: FolderPatch, current: UserPublic = Depends(get_current_user)):
    """Rename a folder and/or change its access (owner, Founder or Admin)."""
    _require(current, "vault.manage")
    db = get_db()
    folder = await _load_folder(db, folder_id, current)
    _require_edit(folder, "created_by", current, "folder")
    fields = body.model_dump(exclude_unset=True)
    updates: dict = {}
    old_name = folder["name"]
    if fields.get("name") is not None:
        name = _folder_name_clean(body.name)
        conflict = await db.vault_folders.find_one({"name_lower": name.lower(), "_id": {"$ne": folder["_id"]}},
                                                   {"created_by": 1, "access_keys": 1})
        if conflict:
            raise _folder_taken(current, conflict)
        if name != old_name:
            updates.update(name=name, name_lower=name.lower())
    if "access" in fields:
        updates.update(await _clean_access(db, body.access))
    if updates:
        try:
            folder = await db.vault_folders.find_one_and_update(
                {"_id": folder["_id"]}, {"$set": updates}, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            raise _folder_taken(current)
        if not folder:
            raise HTTPException(404, "Folder not found")
        if "name" in updates:
            await log_activity(db, current, "Renamed vault folder", MODULE, target=f"{old_name} → {folder['name']}")
        if "access" in updates:
            await log_activity(db, current, "Changed vault folder access", MODULE, target=folder["name"],
                               meta={"folder_id": folder_id, "access": updates["access"]})
    vis = await _doc_filter(db, current)
    counts = {r["_id"]: r for r in await db.vault_documents.aggregate([
        {"$match": {"$and": [vis, {"folder_id": folder_id}]}},
        {"$group": {"_id": "$folder_id", "count": {"$sum": 1}, "size": {"$sum": "$size"}}},
    ]).to_list(None)}
    return _folder_out(folder, current, counts)


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.manage")
    db = get_db()
    folder = await _load_folder(db, folder_id, current)
    _require_edit(folder, "created_by", current, "folder")
    if await db.vault_documents.count_documents({"folder_id": folder_id}, limit=1):
        raise HTTPException(409, "Folder is not empty. Move or delete its documents first.")
    await db.vault_folders.delete_one({"_id": folder["_id"]})
    await log_activity(db, current, "Deleted vault folder", MODULE, target=folder["name"])
    return {"ok": True}


# ------------------------- documents -------------------------

@router.get("/tags")
async def list_tags(current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.view")
    db = get_db()
    rows = await db.vault_documents.aggregate([
        {"$match": await _doc_filter(db, current)},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 200},
    ]).to_list(None)
    return [{"tag": r["_id"], "count": r["count"]} for r in rows]


@router.get("/documents")
async def list_documents(
    folder_id: Optional[str] = Query(None, description="Folder id, or 'unfiled'"),
    tag: Optional[str] = None,
    q: Optional[str] = Query(None, max_length=200),
    expiry: Optional[str] = Query(None, pattern="^(expiring|expired|any)$"),
    sort: str = Query("updated", pattern="^(updated|title|size|expiry)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current: UserPublic = Depends(get_current_user),
):
    _require(current, "vault.view")
    db = get_db()
    today = _today()
    flt: dict = {}
    if folder_id == "unfiled":
        flt["folder_id"] = None
    elif folder_id:
        oid(folder_id)
        flt["folder_id"] = folder_id
    if tag and tag.strip():
        flt["tags"] = tag.strip().lower()
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        flt["$or"] = [{"title": rx}, {"file_name": rx}, {"description": rx}, {"tags": rx}]
    if expiry == "expired":
        flt["expires_on"] = {"$ne": None, "$lt": today.isoformat()}
    elif expiry == "expiring":
        flt["expires_on"] = {"$gte": today.isoformat(),
                             "$lte": (today + timedelta(days=EXPIRY_WINDOW_DAYS)).isoformat()}
    elif expiry == "any":
        flt["expires_on"] = {"$ne": None}
    vis = await _doc_filter(db, current)
    if vis:
        flt["$and"] = [vis]
    total = await db.vault_documents.count_documents(flt)
    skip = (page - 1) * page_size
    if sort == "expiry" and "expires_on" not in flt:
        # Soonest expiry first, then documents without an expiry date (Mongo would sort nulls first).
        dated = {**flt, "expires_on": {"$ne": None}}
        n_dated = await db.vault_documents.count_documents(dated)
        docs = await db.vault_documents.find(dated).sort(SORTS["expiry"]) \
            .skip(skip).limit(page_size).to_list(page_size)
        if len(docs) < page_size:
            docs += await db.vault_documents.find({**flt, "expires_on": None}).sort(SORTS["updated"]) \
                .skip(max(0, skip - n_dated)).limit(page_size - len(docs)).to_list(page_size)
    else:
        docs = await db.vault_documents.find(flt).sort(SORTS[sort]) \
            .skip(skip).limit(page_size).to_list(page_size)
    return {
        "items": [_out(d, today, current) for d in docs],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }


@router.post("/documents", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    folder_id: Optional[str] = Form(None),
    tags: Optional[str] = Form(None, description="Comma-separated"),
    description: Optional[str] = Form(None),
    expires_on: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    access: Optional[str] = Form(None, description='JSON: {"mode": "everyone"|"restricted", "roles": [], '
                                                    '"departments": [], "user_ids": []}'),
    current: UserPublic = Depends(get_current_user),
):
    _require(current, "vault.manage")
    db = get_db()
    folder_id = (folder_id or "").strip() or None
    folder_name = await _folder_name(db, folder_id, current)
    access_fields = await _clean_access(db, _parse_access_form(access))
    tag_list = _clean_tags(tags)
    expiry = _parse_expiry(expires_on)
    description = _clean_text(description, "Description", 2000)
    note = _clean_text(note, "Note", 300)
    data, name, ctype = await _read_upload(file)
    title = _clean_text(title, "Title", 200) or (name.rsplit(".", 1)[0] if "." in name else name)

    now = utc_iso()
    checksum = hashlib.sha256(data).hexdigest()
    storage_id = await _put_bytes(db, data, name, ctype)
    version = {
        "version": 1, "file_id": storage_id, "file_name": name, "content_type": ctype,
        "size": len(data), "checksum": checksum, "uploaded_by": current.id,
        "uploaded_by_name": current.name, "uploaded_at": now, "note": note,
    }
    doc = {
        "title": title, "title_lower": title.lower(), "folder_id": folder_id, "tags": tag_list,
        "description": description, "file_name": name, "content_type": ctype, "size": len(data),
        "checksum": checksum, "file_id": storage_id, "version": 1,
        "uploaded_by": current.id, "uploaded_by_name": current.name,
        "created_at": now, "updated_at": now, "expires_on": expiry, "reminders_sent": [],
        "versions": [version], **access_fields,
    }
    try:
        res = await db.vault_documents.insert_one(doc)
    except Exception:
        await _delete(db, storage_id)
        raise
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Uploaded document", MODULE, target=title,
                       meta={"document_id": str(res.inserted_id), "folder": folder_name, "size": len(data),
                             "access": access_fields["access"]["mode"]})
    await _notify_founders(db, "Document added to Vault",
                           f"{current.name} uploaded “{title}” ({_human_size(len(data))}).",
                           _doc_link(res.inserted_id), exclude=current.id)
    await _notify_shared(db, doc, current, None)
    return _out(doc, current=current)


async def _notify_shared(db, doc: dict, current: UserPublic, before: Optional[list[str]]) -> None:
    """Tell people who were individually given access (only newly added ones when `before` is given).
    People who still can't open it (e.g. the folder is restricted, or they lack vault.view) are skipped."""
    ids = set((doc.get("access") or {}).get("user_ids") or []) - set(before or []) - {current.id}
    if not ids:
        return
    async for u in db.users.find({"_id": {"$in": [ObjectId(i) for i in ids]}, "status": {"$ne": "deactivated"},
                                  "is_active": {"$ne": False}}, {"role": 1, "department": 1}):
        uid = str(u["_id"])
        viewer = SimpleNamespace(id=uid, role=u.get("role"), department=u.get("department"))
        if not can(viewer.role, "vault.view") or not await _can_see_doc(db, doc, viewer):
            continue
        await notify(db, uid, "Document shared with you",
                     f"{current.name} shared “{doc['title']}” in the Company Vault.", link=_doc_link(doc["_id"]))


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.view")
    return _out(await _load(get_db(), doc_id, current), current=current)


class DocumentPatch(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    folder_id: Optional[str] = None
    tags: Optional[list[str]] = None
    description: Optional[str] = Field(None, max_length=2000)
    expires_on: Optional[str] = None
    access: Optional[AccessIn] = None


@router.patch("/documents/{doc_id}")
async def update_document(doc_id: str, body: DocumentPatch, current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.manage")
    db = get_db()
    doc = await _load(db, doc_id, current)
    _require_edit(doc, "uploaded_by", current)
    fields = body.model_dump(exclude_unset=True)
    updates: dict = {}
    if "title" in fields:
        title = _clean_text(fields["title"], "Title", 200, required=True)
        updates.update(title=title, title_lower=title.lower())
    if "folder_id" in fields:
        folder_id = (fields["folder_id"] or "").strip() or None
        if folder_id != doc.get("folder_id"):
            await _folder_name(db, folder_id, current)
        updates["folder_id"] = folder_id
    if "tags" in fields:
        updates["tags"] = _clean_tags(fields["tags"] or [])
    if "description" in fields:
        updates["description"] = _clean_text(fields["description"], "Description", 2000)
    if "expires_on" in fields:
        updates["expires_on"] = _parse_expiry(fields["expires_on"])
        if updates["expires_on"] != doc.get("expires_on"):
            updates["reminders_sent"] = []
    before_users = (doc.get("access") or {}).get("user_ids") or []
    if "access" in fields:
        new_access = await _clean_access(db, body.access)
        # Only a real change counts (the edit dialog always re-sends the current access).
        if new_access["access"] != _access_out(doc):
            updates.update(new_access)
    if not updates:
        return _out(doc, current=current)
    updates["updated_at"] = utc_iso()
    doc = await db.vault_documents.find_one_and_update(
        {"_id": doc["_id"]}, {"$set": updates}, return_document=ReturnDocument.AFTER)
    if not doc:
        raise HTTPException(404, "Document not found")
    changed = [k for k in fields if k in updates]
    await log_activity(db, current, "Edited document details", MODULE, target=doc["title"],
                       meta={"document_id": doc_id, "fields": changed})
    if "access" in updates:
        await log_activity(db, current, "Changed document access", MODULE, target=doc["title"],
                           meta={"document_id": doc_id, "access": updates["access"]})
        await _notify_shared(db, doc, current, before_users)
    return _out(doc, current=current)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.manage")
    db = get_db()
    existing = await _load(db, doc_id, current)
    _require_edit(existing, "uploaded_by", current)
    doc = await db.vault_documents.find_one_and_delete({"_id": existing["_id"]})
    if not doc:
        raise HTTPException(404, "Document not found")
    for storage_id in {v["file_id"] for v in doc.get("versions", [])} | {doc.get("file_id")}:
        if storage_id:
            await _delete(db, storage_id)
    await log_activity(db, current, "Deleted document", MODULE, target=doc["title"],
                       meta={"document_id": doc_id, "versions": len(doc.get("versions", []))})
    await _notify_founders(db, "Document removed from Vault",
                           f"{current.name} deleted “{doc['title']}”.", LINK, exclude=current.id)
    return {"ok": True}


@router.get("/documents/{doc_id}/download")
async def download_document(doc_id: str, inline: bool = False, current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.view")
    db = get_db()
    doc = await _load(db, doc_id, current)
    chunks, length = await _get_stream(db, doc["file_id"])
    if not inline:
        await log_activity(db, current, "Downloaded document", MODULE, target=doc["title"],
                           meta={"document_id": doc_id, "version": doc["version"]})
    return _stream_response(chunks, length, doc["content_type"], doc["file_name"], inline)


def _find_version(doc: dict, number: int) -> dict:
    for v in doc.get("versions", []):
        if v["version"] == number:
            return v
    raise HTTPException(404, "Version not found")


async def _append_version(db, doc: dict, current: UserPublic, version: dict) -> dict:
    """Append a version with an optimistic check on the current version number."""
    number = doc["version"] + 1
    version = {**version, "version": number, "uploaded_by": current.id,
               "uploaded_by_name": current.name, "uploaded_at": utc_iso()}
    updated = await db.vault_documents.find_one_and_update(
        {"_id": doc["_id"], "version": doc["version"]},
        {"$push": {"versions": version}, "$set": {
            "version": number, "file_id": version["file_id"], "file_name": version["file_name"],
            "content_type": version["content_type"], "size": version["size"],
            "checksum": version["checksum"], "updated_at": version["uploaded_at"],
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(409, "The document changed while you were uploading. Please try again.")
    return updated


@router.post("/documents/{doc_id}/versions", status_code=201)
async def upload_version(
    doc_id: str,
    file: UploadFile = File(...),
    note: Optional[str] = Form(None),
    current: UserPublic = Depends(get_current_user),
):
    _require(current, "vault.manage")
    db = get_db()
    doc = await _load(db, doc_id, current)
    _require_edit(doc, "uploaded_by", current)
    note = _clean_text(note, "Note", 300)
    data, name, ctype = await _read_upload(file)
    storage_id = await _put_bytes(db, data, name, ctype)
    try:
        updated = await _append_version(db, doc, current, {
            "file_id": storage_id, "file_name": name, "content_type": ctype, "size": len(data),
            "checksum": hashlib.sha256(data).hexdigest(), "note": note,
        })
    except Exception:
        await _delete(db, storage_id)
        raise
    await log_activity(db, current, "Uploaded new document version", MODULE, target=doc["title"],
                       meta={"document_id": doc_id, "version": updated["version"]})
    await _notify_founders(db, "New document version",
                           f"{current.name} uploaded version {updated['version']} of “{doc['title']}”.",
                           _doc_link(doc_id), exclude=current.id)
    return _out(updated, current=current)


@router.get("/documents/{doc_id}/versions/{number}/download")
async def download_version(doc_id: str, number: int, inline: bool = False,
                           current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.view")
    db = get_db()
    doc = await _load(db, doc_id, current)
    v = _find_version(doc, number)
    chunks, length = await _get_stream(db, v["file_id"])
    if not inline:
        await log_activity(db, current, "Downloaded document version", MODULE, target=doc["title"],
                           meta={"document_id": doc_id, "version": number})
    return _stream_response(chunks, length, v["content_type"], v["file_name"], inline)


@router.post("/documents/{doc_id}/versions/{number}/restore")
async def restore_version(doc_id: str, number: int, current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.manage")
    db = get_db()
    doc = await _load(db, doc_id, current)
    _require_edit(doc, "uploaded_by", current)
    v = _find_version(doc, number)
    if number == doc["version"]:
        raise HTTPException(409, "This is already the current version")
    updated = await _append_version(db, doc, current, {
        "file_id": v["file_id"], "file_name": v["file_name"], "content_type": v["content_type"],
        "size": v["size"], "checksum": v["checksum"], "note": f"Restored from version {number}",
        "restored_from": number,
    })
    await log_activity(db, current, "Restored document version", MODULE, target=doc["title"],
                       meta={"document_id": doc_id, "from_version": number, "version": updated["version"]})
    return _out(updated, current=current)


# ------------------------- stats / ops -------------------------

@router.get("/stats")
async def vault_stats(current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.view")
    db = get_db()
    today = _today()
    horizon = (today + timedelta(days=EXPIRY_WINDOW_DAYS)).isoformat()
    vis = await _doc_filter(db, current)
    rows = await db.vault_documents.aggregate([{"$match": vis}, {"$facet": {
        "totals": [{"$group": {"_id": None, "count": {"$sum": 1}, "size": {"$sum": "$size"}}}],
        "by_folder": [{"$group": {"_id": "$folder_id", "count": {"$sum": 1}, "size": {"$sum": "$size"}}}],
        "expired": [{"$match": {"expires_on": {"$ne": None, "$lt": today.isoformat()}}}, {"$count": "n"}],
        "expiring": [{"$match": {"expires_on": {"$gte": today.isoformat(), "$lte": horizon}}}, {"$count": "n"}],
        "files": [{"$unwind": "$versions"},
                  {"$group": {"_id": "$versions.file_id", "size": {"$first": "$versions.size"}}},
                  {"$group": {"_id": None, "size": {"$sum": "$size"}, "count": {"$sum": 1}}}],
    }}]).to_list(1)
    r = rows[0]
    names = {str(f["_id"]): f["name"] async for f in db.vault_folders.find({}, {"name": 1})}
    # A user's own document can sit in a folder they can't see; don't reveal that folder's name.
    folder_ids = await _visible_folder_ids(db, current)
    if folder_ids is not None:
        names = {k: v for k, v in names.items() if k in set(folder_ids)}
    by_folder = sorted(
        ({"folder_id": g["_id"], "name": names.get(g["_id"], "Unfiled") if g["_id"] else "Unfiled",
          "count": g["count"], "size": g["size"]} for g in r["by_folder"]),
        key=lambda x: (-x["count"], x["name"].lower()),
    )
    totals = r["totals"][0] if r["totals"] else {"count": 0, "size": 0}
    files = r["files"][0] if r["files"] else {"count": 0, "size": 0}
    return {
        "count": totals["count"],
        "total_size": totals["size"],
        "storage_size": files["size"],
        "stored_files": files["count"],
        "by_folder": by_folder,
        "expiring_30d": r["expiring"][0]["n"] if r["expiring"] else 0,
        "expired": r["expired"][0]["n"] if r["expired"] else 0,
    }


@router.post("/reminders/run")
async def run_reminders(current: UserPublic = Depends(get_current_user)):
    _require(current, "vault.manage")
    if not _is_vault_admin(current):
        raise HTTPException(403, "Only Founders or Admins can run vault reminders")
    db = get_db()
    sent = await send_expiry_reminders(db)
    await log_activity(db, current, "Ran vault expiry reminders", MODULE, meta={"sent": sent})
    return {"sent": sent}
