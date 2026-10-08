from __future__ import annotations

import re
import secrets
import string
from datetime import date as date_cls, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    BackgroundTasks,
    UploadFile,
    File,
    Form,
)
from services.image_service import upload_file
from bson import ObjectId

from db import get_db
from auth_utils import get_current_user, require_roles, hash_password
from models import UserPublic
from models_part2 import (
    DepartmentIn, EmployeeInviteIn, EmployeeUpdateIn, AttendanceIn, LeaveIn, LeaveDecisionIn, PerformanceIn,
    SubmittedDetailsIn, CompanyDetailsIn,
)
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify
from permissions import can
from email_utils import send_invitation_email, send_password_reset_email, email_configured
from dept_groups import sync_employee_department_group, add_member_to_department_channel, get_or_create_department_channel, rename_department_channel

router = APIRouter(prefix="/employees", tags=["employees"])

# Attendance days are company-local dates; check-in/out times are stored as UTC ISO strings.
COMPANY_TZ = ZoneInfo("Asia/Kolkata")
INVITE_TTL = timedelta(days=7)
INVITE_EXPIRED_MSG = "Invalid or expired invitation link"
MIN_PASSWORD = 8
ROLES = ("Founder", "Admin", "Manager", "Employee", "Intern")

# Invited-but-never-activated accounts are placeholders: no password yet. They are listed
# only as invitations, never as employees.
NO_PASSWORD = {"$in": ["", None]}
REAL_USERS = {"password_hash": {"$nin": ["", None]}}

# Profile fields anyone may edit on their own account vs. fields managed by the org.
SELF_FIELDS = {"name", "phone", "photo"}
ORG_FIELDS = SELF_FIELDS | {"designation", "department", "role"}

# Roles that may see and edit everything in an employee's details profile.
ADMIN_ROLES = ("Founder", "Admin")


# ============================================================
# HELPERS
# ============================================================

def _today_ist() -> str:
    return datetime.now(COMPANY_TZ).date().isoformat()


def _email_regex(email: str) -> dict:
    return {"$regex": f"^{re.escape(email)}$", "$options": "i"}


def _norm_dept(name: str | None) -> str:
    return " ".join((name or "").split())


def _dept_match(name: str | None) -> dict:
    """Matches a department name ignoring case and stray spaces, so older records written as
    ' Marketing ' still count as Marketing. An empty name matches nothing."""
    words = _norm_dept(name).split()
    if not words:
        return {"$in": []}
    return {"$regex": r"^\s*" + r"\s+".join(re.escape(w) for w in words) + r"\s*$", "$options": "i"}


def _is_placeholder(user: dict) -> bool:
    return not user.get("password_hash")


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _invite_expired(inv: dict) -> bool:
    expires = _parse_ts(inv.get("expires_at"))
    if expires is None:
        # Invitations created before expiry was stored expire 7 days after creation.
        created = _parse_ts(inv.get("created_at"))
        expires = created + INVITE_TTL if created else None
    return expires is not None and datetime.now(timezone.utc) > expires


def _attendance_out(doc: dict) -> dict:
    out = serialize(doc)
    check_in, check_out = _parse_ts(doc.get("check_in")), _parse_ts(doc.get("check_out"))
    out["duration_minutes"] = (
        int((check_out - check_in).total_seconds() // 60)
        if check_in and check_out and check_out >= check_in else None
    )
    return out


async def _dept_ids(db, department):
    """Return list of user ids (str) in the given department."""
    if not department:
        return []

    return [
        str(u["_id"])
        async for u in db.users.find(
            {"department": _dept_match(department)},
            {"_id": 1},
        )
    ]


async def _user_map(db, ids, fields=("name",)) -> dict:
    """{id: user} for the valid ObjectId strings in ids; malformed ids are skipped."""
    oids = list({ObjectId(i) for i in ids if i and ObjectId.is_valid(str(i))})
    if not oids:
        return {}
    projection = {f: 1 for f in fields}
    return {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": oids}}, projection)}


async def _get_employee(db, employee_id) -> dict:
    """A real (activated at least once) user by id, or 400/404."""
    if not employee_id or not ObjectId.is_valid(str(employee_id)):
        raise HTTPException(400, "Please select a valid employee")
    user = await db.users.find_one({"_id": ObjectId(str(employee_id))})
    if not user or _is_placeholder(user):
        raise HTTPException(404, "Employee not found")
    return user


def _same_department(current: UserPublic, target: dict) -> bool:
    return bool(_norm_dept(current.department)) and _norm_dept(target.get("department")).casefold() == _norm_dept(current.department).casefold()


async def _resolve_department(db, name: str | None) -> str | None:
    """Canonical name of an existing department (case-insensitive), None for blank, else 400."""
    name = " ".join((name or "").split())
    if not name:
        return None
    dept = await db.departments.find_one({"name": _email_regex(name)}, {"name": 1})
    if not dept:
        raise HTTPException(400, f"Unknown department: {name}")
    return dept["name"]


def _gen_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "Wg" + "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


async def _find_user(db, employee_id: str):
    employee_id_str = str(employee_id).strip()

    if ObjectId.is_valid(employee_id_str):
        user = await db.users.find_one(
            {"_id": ObjectId(employee_id_str)}
        )
        if user:
            return user

    user = await db.users.find_one(
        {"_id": employee_id_str}
    )
    if user:
        return user

    return await db.users.find_one({"email": _email_regex(employee_id_str)})


async def _find_invitation(db, invite_id: str):
    invite_id = str(invite_id).strip()
    if ObjectId.is_valid(invite_id):
        inv = await db.invitations.find_one({"_id": ObjectId(invite_id)})
        if inv:
            return inv
    return await db.invitations.find_one({"token": invite_id})


# ============================================================
# EMPLOYEES
# ============================================================

@router.get("")
async def list_employees(
    q: str | None = None,
    department: str | None = None,
    role: str | None = None,
    current: UserPublic = Depends(
        require_roles("Founder", "Admin", "Manager")
    ),
):
    db = get_db()

    query = dict(REAL_USERS)

    if q:
        pattern = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [
            {"name": pattern},
            {"email": pattern},
            {"designation": pattern},
        ]

    if department:
        query["department"] = _dept_match(department)

    if role:
        query["role"] = role

    # Managers only see their own department.
    if current.role == "Manager":
        if department and _norm_dept(department).casefold() != _norm_dept(current.department).casefold():
            raise HTTPException(403, "Managers can only view their own department")
        query["department"] = _dept_match(current.department)

    docs = await db.users.find(
        query,
        {"password_hash": 0},
    ).sort(
        "created_at",
        -1,
    ).to_list(500)

    return serialize_many(docs)

@router.post("/{employee_id}/profile/document")
async def upload_employee_document(
    employee_id: str,
    file: UploadFile = File(...),
    section: str = Form(...),
    document_type: str = Form(...),
    current: UserPublic = Depends(get_current_user),
):
    """
    Upload an employee profile document to Cloudinary
    and save its URL in employee_profiles.
    """

    db = get_db()
    target = await _get_employee(db, employee_id)

    is_self = str(target["_id"]) == current.id
    is_admin = current.role in ADMIN_ROLES

    # Employee can upload their own submitted documents.
    # Founder/Admin can upload both submitted and company documents.
    if section == "submitted":
        if not (is_self or is_admin):
            raise HTTPException(
                403,
                "Only the employee or an admin can upload submitted documents",
            )
    elif section == "company":
        if not is_admin:
            raise HTTPException(
                403,
                "Only Founder/Admin can upload company documents",
            )
    else:
        raise HTTPException(
            400,
            "Invalid section. Use 'submitted' or 'company'",
        )

    allowed_documents = {
        "submitted": {
            "resume",
            "id_proof",
            "other",
        },
        "company": {
            "offer_letter",
            "employment_agreement",
            "other",
        },
    }

    if document_type not in allowed_documents[section]:
        raise HTTPException(
            400,
            f"Invalid document type for {section}",
        )

    uploaded = await upload_file(file)

    now = utc_iso()

    # Single documents replace the previous document.
    if document_type == "resume":
        update_field = "submitted.resume_url"
        update_value = uploaded["url"]

        update = {
            "$set": {
                update_field: update_value,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        }

    elif document_type == "id_proof":
        update_field = "submitted.id_proof_url"
        update_value = uploaded["url"]

        update = {
            "$set": {
                update_field: update_value,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        }

    elif document_type == "offer_letter":
        update_field = "company.offer_letter_url"
        update_value = uploaded["url"]

        update = {
            "$set": {
                update_field: update_value,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        }

    elif document_type == "employment_agreement":
        update_field = "company.employment_agreement_url"
        update_value = uploaded["url"]

        update = {
            "$set": {
                update_field: update_value,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        }

    else:
        # Other documents can have multiple files.
        other_field = f"{section}.other_documents"

        update = {
            "$push": {
                other_field: {
                    "url": uploaded["url"],
                    "name": uploaded["name"],
                    "size": uploaded["size"],
                    "content_type": uploaded["content_type"],
                    "public_id": uploaded["public_id"],
                    "resource_type": uploaded["resource_type"],
                }
            },
            "$set": {
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        }

    await db.employee_profiles.update_one(
        {"employee_id": str(target["_id"])},
        update,
        upsert=True,
    )

    await log_activity(
        db,
        current,
        "Uploaded employee document",
        "Employees",
        target=target["name"],
        meta={
            "section": section,
            "document_type": document_type,
            "filename": uploaded["name"],
        },
    )

    doc = await db.employee_profiles.find_one(
        {"employee_id": str(target["_id"])}
    )

    return {
        "ok": True,
        "message": "Document uploaded successfully",
        "document": uploaded,
        "profile": _profile_out(doc, current, target),
    }
# ============================================================
# INVITE EMPLOYEE
# ============================================================

@router.post("/invite", status_code=201)
async def invite_employee(
    payload: EmployeeInviteIn,
    background_tasks: BackgroundTasks,
    current: UserPublic = Depends(
        require_roles("Founder", "Admin")
    ),
):
    db = get_db()

    name = (payload.name or "").strip()
    email = (payload.email or "").lower().strip()

    if not name:
        raise HTTPException(400, "Full name is required")

    if (
        not email
        or "@" not in email
        or "." not in email.split("@")[-1]
    ):
        raise HTTPException(400, "Please provide a valid email address")

    if payload.role not in ROLES:
        raise HTTPException(400, "Invalid role specified")

    if not can(current.role, f"user.invite.{payload.role.lower()}"):
        raise HTTPException(403, f"Your role cannot invite a {payload.role}")

    department = await _resolve_department(db, payload.department)

    existing_user = await db.users.find_one({"email": _email_regex(email)})
    if existing_user and not _is_placeholder(existing_user):
        if existing_user.get("status") == "deactivated" or existing_user.get("is_active") is False:
            raise HTTPException(409, "This email belongs to a deactivated employee — reactivate their account instead")
        raise HTTPException(409, "Email is already registered as an active employee")

    now = datetime.now(timezone.utc)
    fields = {
        "name": name,
        "role": payload.role,
        "designation": payload.designation,
        "department": department,
        "phone": payload.phone,
    }

    if existing_user:
        # Placeholder from an earlier, never-accepted invitation: refresh its details.
        await db.users.update_one(
            {"_id": existing_user["_id"]},
            {"$set": {**fields, "invited_by": current.name, "updated_at": now.isoformat()}},
        )
        user_id = str(existing_user["_id"])
    else:
        user_doc = {
            "email": email,
            **fields,
            "password_hash": "",
            "status": "deactivated",
            "is_active": False,
            "active": False,
            "online": False,
            "invite_pending": True,
            "invited_by": current.name,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        res_u = await db.users.insert_one(user_doc)
        user_id = str(res_u.inserted_id)

    token = secrets.token_urlsafe(32)
    inv_doc = {
        "token": token,
        "email": email,
        **fields,
        "status": "pending",
        "invited_by": current.name,
        "invited_by_id": current.id,
        "user_id": user_id,
        "created_at": now.isoformat(),
        "expires_at": (now + INVITE_TTL).isoformat(),
    }
    await db.invitations.delete_many({"email": email})
    res = await db.invitations.insert_one(inv_doc)
    inv_doc["_id"] = res.inserted_id

    email_queued = email_configured()
    if email_queued:
        background_tasks.add_task(
            send_invitation_email,
            recipient_email=email,
            recipient_name=name,
            role=payload.role,
            token=token,
            invited_by=current.name,
            designation=payload.designation,
            department=department,
        )

    await log_activity(db, current, "Sent employee invitation", "Employees", target=name)
    return {
        **serialize(inv_doc),
        "email_queued": email_queued,
        "message": (
            f"Invitation created — email queued to {email}."
            if email_queued
            else f"Invitation created — share the link with {name}."
        ),
    }


# ============================================================
# INVITATIONS
# ============================================================

@router.get("/invitations")
async def list_invitations(
    current: UserPublic = Depends(
        require_roles(
            "Founder",
            "Admin",
            "Manager",
        )
    ),
):
    db = get_db()

    q = {}
    if current.role == "Manager":
        # Managers see their department's invitations, without the secret tokens.
        q["department"] = _dept_match(current.department)

    docs = await db.invitations.find(q).sort(
        "created_at",
        -1,
    ).to_list(500)

    drop = ("password_hash",) if can(current.role, "employee.invite") else ("password_hash", "token")
    return [
        {**serialize(d, drop=drop), "expired": d.get("status") == "pending" and _invite_expired(d)}
        for d in docs
    ]


@router.get("/invite/{token}")
async def get_invite_details(token: str):
    db = get_db()

    inv = await db.invitations.find_one(
        {"token": token}
    )

    if not inv or (inv.get("status") != "accepted" and _invite_expired(inv)):
        raise HTTPException(404, INVITE_EXPIRED_MSG)

    return {
        "email": inv["email"],
        "name": inv["name"],
        "role": inv["role"],
        "designation": inv.get("designation"),
        "department": inv.get("department"),
        "phone": inv.get("phone"),
        "invited_by": inv.get("invited_by"),
        "status": inv.get(
            "status",
            "pending",
        ),
        "already_accepted": (
            inv.get("status") == "accepted"
        ),
    }


@router.post("/accept-invite")
async def accept_invite(payload: dict):
    token = payload.get("token")
    password = payload.get("password")

    if not token or not isinstance(token, str):
        raise HTTPException(400, "Invitation token is required")

    db = get_db()

    inv = await db.invitations.find_one(
        {"token": token}
    )

    if not inv:
        raise HTTPException(404, INVITE_EXPIRED_MSG)

    email = inv["email"].lower().strip()

    if inv.get("status") == "accepted":
        return {
            "ok": True,
            "email": email,
            "already_accepted": True,
            "message": (
                "Invitation already accepted! "
                "Redirecting to login page..."
            ),
        }

    if inv.get("status") != "pending" or _invite_expired(inv):
        raise HTTPException(404, INVITE_EXPIRED_MSG)

    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD} characters long")

    taken_msg = "This email already has a WavyGo OS account. Please sign in instead."
    now = utc_iso()
    fields = {
        "name": inv["name"],
        "role": inv["role"],
        "designation": inv.get("designation"),
        "department": inv.get("department"),
        "phone": inv.get("phone"),
    }

    # Only the placeholder created by this invitation may be activated — never an
    # existing account that happens to share the email.
    if inv.get("user_id"):
        user = await db.users.find_one({"_id": oid(inv["user_id"])})
        if not user:
            raise HTTPException(404, INVITE_EXPIRED_MSG)
    else:
        user = await db.users.find_one({"email": _email_regex(email)})

    if user:
        if (user.get("email") or "").lower().strip() != email or not _is_placeholder(user) \
                or user.get("status") != "deactivated":
            raise HTTPException(409, taken_msg)
        if await db.users.find_one({"email": _email_regex(email), "_id": {"$ne": user["_id"]}}, {"_id": 1}):
            raise HTTPException(409, taken_msg)
        res = await db.users.update_one(
            {"_id": user["_id"], "password_hash": NO_PASSWORD, "status": "deactivated"},
            {
                "$set": {
                    **fields,
                    "password_hash": hash_password(password),
                    "status": "active",
                    "is_active": True,
                    "active": True,
                    "updated_at": now,
                },
                "$unset": {"invite_pending": ""},
            },
        )
        if res.modified_count == 0:
            raise HTTPException(409, taken_msg)
        user_id = str(user["_id"])
    else:
        # Legacy invitation that never created a placeholder.
        res = await db.users.insert_one({
            "email": email,
            **fields,
            "password_hash": hash_password(password),
            "status": "active",
            "is_active": True,
            "active": True,
            "online": False,
            "created_at": now,
            "updated_at": now,
        })
        user_id = str(res.inserted_id)

    await db.invitations.update_one(
        {"_id": inv["_id"]},
        {"$set": {"status": "accepted", "accepted_at": now, "user_id": user_id}},
    )

    if inv.get("department"):
        await add_member_to_department_channel(db, user_id, inv["department"])

    await log_activity(db, {"id": user_id, "name": inv["name"], "role": inv["role"]},
                       "Accepted invitation", "Employees", target=email)
    await notify(db, None, "New teammate joined", f"{inv['name']} accepted the invitation and joined as {inv['role']}.",
                 kind="success", link="/employees")

    return {"ok": True, "email": email, "message": "Invitation accepted successfully! Redirecting to login page..."}


@router.post(
    "/invitations/{invite_id}/resend"
)
async def resend_invitation(
    invite_id: str,
    background_tasks: BackgroundTasks,
    current: UserPublic = Depends(
        require_roles("Founder", "Admin")
    ),
):
    db = get_db()

    inv = await _find_invitation(db, invite_id)

    if not inv or inv.get("status") != "pending":
        raise HTTPException(404, "Pending invitation not found")

    # Resending renews the 7-day validity of the same link.
    expires_at = (datetime.now(timezone.utc) + INVITE_TTL).isoformat()
    await db.invitations.update_one({"_id": inv["_id"]}, {"$set": {"expires_at": expires_at}})

    email_queued = email_configured()
    if email_queued:
        background_tasks.add_task(
            send_invitation_email,
            recipient_email=inv["email"],
            recipient_name=inv["name"],
            role=inv["role"],
            token=inv["token"],
            invited_by=current.name,
            designation=inv.get("designation"),
            department=inv.get("department"),
        )

    await log_activity(db, current, "Resent employee invitation", "Employees", target=inv["email"])

    return {
        "ok": True,
        "email_queued": email_queued,
        "expires_at": expires_at,
        "message": (
            f"Invitation email is being resent to {inv['email']}"
            if email_queued
            else "Invitation renewed for 7 days — email is not configured, share the link instead."
        ),
    }


@router.delete(
    "/invitations/{invite_id}",
    status_code=200,
)
async def delete_invitation(
    invite_id: str,
    current: UserPublic = Depends(
        require_roles("Founder", "Admin")
    ),
):
    db = get_db()

    inv = await _find_invitation(db, invite_id)

    if not inv:
        raise HTTPException(404, "Pending invitation not found")

    email = inv.get("email", "").lower().strip()

    await db.invitations.delete_one({"_id": inv["_id"]})

    # Also remove the never-activated placeholder account the invitation created.
    if inv.get("status") != "accepted":
        placeholder = {"password_hash": NO_PASSWORD, "status": "deactivated"}
        if inv.get("user_id") and ObjectId.is_valid(str(inv["user_id"])):
            placeholder["_id"] = ObjectId(str(inv["user_id"]))
        else:
            placeholder["email"] = _email_regex(email)
        await db.users.delete_one(placeholder)

    await log_activity(
        db,
        current,
        "Deleted pending invitation",
        "Employees",
        target=email,
    )

    return {
        "ok": True,
        "message": (
            f"Pending invitation for {email} "
            "deleted successfully"
        ),
    }


# ============================================================
# EMPLOYEE PASSWORD
# ============================================================


@router.post("/{employee_id}/reset-password")
async def reset_employee_password(employee_id: str,
                                  background_tasks: BackgroundTasks,
                                  payload: dict | None = None,
                                  current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()

    target = await _find_user(
        db,
        employee_id,
    )

    if not target:
        raise HTTPException(404, "Employee not found")

    if target.get("role") == "Founder":
        raise HTTPException(403, "Cannot reset the Founder password from here")

    if target.get("role") == "Admin" and current.role != "Founder" and str(target["_id"]) != current.id:
        raise HTTPException(403, "Only the Founder can reset an Admin's password")

    if _is_placeholder(target):
        raise HTTPException(400, "This teammate has not accepted their invitation yet")

    raw_pwd = (payload or {}).get("new_password")
    if raw_pwd is not None and str(raw_pwd).strip():
        raw_pwd = str(raw_pwd).strip()
        if len(raw_pwd) < MIN_PASSWORD:
            raise HTTPException(400, f"Password must be at least {MIN_PASSWORD} characters long")
        new_password = raw_pwd
    else:
        new_password = _gen_temp_password()

    await db.users.update_one(
        {"_id": target["_id"]},
        {
            "$set": {
                "password_hash": hash_password(
                    new_password
                ),
                "updated_at": utc_iso(),
            }
        },
    )
    # Sign the teammate out everywhere, like the self-service reset: old sessions must not outlive the password
    if str(target["_id"]) != current.id:
        await db.sessions.update_many(
            {"user_id": str(target["_id"]), "revoked": {"$ne": True}},
            {"$set": {"revoked": True, "revoked_at": utc_iso()}},
        )
    await log_activity(db, current, "Reset password", "Employees", target=target["name"])
    await notify(db, str(target["_id"]), "Your password was reset",
                 f"{current.name} reset your password. Please sign in with the new password and update it if allowed.",
                 kind="warning", link="/settings")

    target_email = target.get("email")
    target_name = target.get("name") or "Employee"
    email_queued = bool(target_email) and email_configured()
    if email_queued:
        background_tasks.add_task(
            send_password_reset_email,
            recipient_email=target_email,
            recipient_name=target_name,
            new_password=new_password,
            reset_by=current.name,
        )

    return {
        "ok": True,
        "temp_password": new_password,
        "email": target_email,
        "email_queued": email_queued,
        "message": (
            f"Password reset — email queued to {target_email}"
            if email_queued
            else "Password reset — email is not configured, share the new password securely"
        ),
    }


# ============================================================
# EMPLOYEE STATUS
# ============================================================

@router.patch(
    "/{employee_id}/status"
)
async def toggle_employee_status(
    employee_id: str,
    payload: dict | None = None,
    current: UserPublic = Depends(
        require_roles("Founder", "Admin")
    ),
):
    db = get_db()

    target = await _find_user(
        db,
        employee_id,
    )

    if not target:
        raise HTTPException(404, "Employee not found")

    if str(target["_id"]) == current.id:
        raise HTTPException(400, "You cannot change the status of your own account")

    if target.get("role") == "Founder":
        raise HTTPException(403, "Cannot deactivate the Founder account")

    if (
        target.get("role") == "Admin"
        and current.role != "Founder"
    ):
        raise HTTPException(403, "Only the Founder can deactivate an Admin")

    current_status = target.get(
        "status",
        "active",
    )

    req_status = (
        (payload or {}).get("status")
    )

    if req_status in (
        "active",
        "deactivated",
    ):
        new_status = req_status
    else:
        new_status = (
            "deactivated"
            if current_status == "active"
            else "active"
        )

    is_active = (
        new_status == "active"
    )

    if is_active and _is_placeholder(target):
        raise HTTPException(400, "This teammate has not accepted their invitation yet, so there is no account to activate")

    await db.users.update_one(
        {"_id": target["_id"]},
        {
            "$set": {
                "status": new_status,
                "is_active": is_active,
                "active": is_active,
                "updated_at": utc_iso(),
            }
        },
    )

    if not is_active:
        # Revoke (not delete) so access tokens naming these sessions stay dead after a later reactivation
        await db.sessions.update_many(
            {"user_id": str(target["_id"]), "revoked": {"$ne": True}},
            {"$set": {"revoked": True, "revoked_at": utc_iso()}},
        )

    action_verb = (
        "Reactivated"
        if is_active
        else "Deactivated"
    )

    await log_activity(
        db,
        current,
        f"{action_verb} employee account",
        "Employees",
        target=target["name"],
    )

    return {
        "ok": True,
        "status": new_status,
        "is_active": is_active,
        "message": (
            f"Employee {target['name']} "
            f"is now {new_status}."
        ),
    }


# ============================================================
# UPDATE EMPLOYEE
# ============================================================

@router.patch("/{employee_id}")
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdateIn,
    current: UserPublic = Depends(
        require_roles(
            "Founder",
            "Admin",
            "Manager",
        )
    ),
):
    db = get_db()

    target = await _find_user(
        db,
        employee_id,
    )

    if not target:
        raise HTTPException(404, "Employee not found")

    if _is_placeholder(target):
        raise HTTPException(400, "This teammate has not accepted their invitation yet — re-invite them to change details")

    # Decide which fields the caller may change on this target.
    target_role = target.get("role")
    if str(target["_id"]) == current.id:
        allowed = SELF_FIELDS | ({"designation", "department"} if current.role == "Founder" else set())
    elif target_role == "Founder":
        raise HTTPException(403, "Only the Founder can edit the Founder profile")
    elif current.role == "Admin" and target_role == "Admin":
        raise HTTPException(403, "Admins cannot edit other Admins")
    elif current.role == "Manager":
        if target_role not in ("Employee", "Intern") or not _same_department(current, target):
            raise HTTPException(403, "Managers can only edit Employees and Interns in their department")
        allowed = SELF_FIELDS | {"designation"}
    else:
        allowed = ORG_FIELDS

    changes = {}
    for key, value in payload.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value.strip()
        if key in ("phone", "photo", "designation", "department") and value == "":
            value = None
        if key == "department" and value:
            value = await _resolve_department(db, value)
        if value == target.get(key) or (value is None and not target.get(key)):
            continue  # unchanged fields are ignored, so forms may send the whole profile
        if key not in allowed:
            raise HTTPException(403, f"You are not allowed to change {key} for this teammate")
        changes[key] = value

    if "name" in changes and not changes["name"]:
        raise HTTPException(400, "Name cannot be empty")

    if "role" in changes:
        new_role = changes["role"]
        if not new_role:
            raise HTTPException(400, "Role is required")
        # A role may only be granted (or taken away) by someone allowed to invite that role.
        if not can(current.role, f"user.invite.{new_role.lower()}") \
                or not can(current.role, f"user.invite.{target_role.lower()}"):
            raise HTTPException(403, f"Your role cannot assign the {new_role} role")

    if not changes:
        return serialize(target)

    old_department = target.get("department")
    await db.users.update_one(
        {"_id": target["_id"]},
        {"$set": {**changes, "updated_at": utc_iso()}},
    )

    doc = await db.users.find_one({"_id": target["_id"]}, {"password_hash": 0})
    if "department" in changes:
        await sync_employee_department_group(db, str(target["_id"]), old_department, changes["department"])
    await log_activity(db, current, "Updated employee", "Employees", target=doc["name"],
                       meta={"fields": sorted(changes)})
    if "role" in changes and str(target["_id"]) != current.id:
        await notify(db, str(target["_id"]), "Your role was updated",
                     f"{current.name} changed your role to {changes['role']}.", kind="info", link="/settings")
    return serialize(doc)


# ============================================================
# EMPLOYEE PROFILE (details submitted by employee + details given by company)
# ============================================================

def _can_view_profile(current: UserPublic, target: dict) -> bool:
    if str(target["_id"]) == current.id or current.role in ADMIN_ROLES:
        return True
    return current.role == "Manager" and _same_department(current, target)


def _profile_out(doc: dict | None, current: UserPublic, target: dict) -> dict:
    is_self = str(target["_id"]) == current.id
    is_admin = current.role in ADMIN_ROLES
    stored = doc or {}

    submitted = {**SubmittedDetailsIn().model_dump(mode="json"), **(stored.get("submitted") or {})}
    company = {**CompanyDetailsIn().model_dump(mode="json"), **(stored.get("company") or {})}

    # Managers see the profile, but not the sensitive parts.
    if not (is_self or is_admin):
        company["stipend_or_salary"] = None
        submitted["bank_account_last4"] = None
        submitted["id_proof_url"] = None

    return {
        "employee_id": str(target["_id"]),
        "name": target.get("name"),
        "email": target.get("email"),
        "role": target.get("role"),
        "designation": target.get("designation"),
        "department": target.get("department"),
        "submitted": submitted,
        "company": company,
        "can_edit_submitted": is_self or is_admin,
        "can_edit_company": is_admin,
        "updated_at": stored.get("updated_at"),
    }


@router.get("/{employee_id}/profile")
async def get_employee_profile(
    employee_id: str,
    current: UserPublic = Depends(get_current_user),
):
    db = get_db()
    target = await _get_employee(db, employee_id)

    if not _can_view_profile(current, target):
        raise HTTPException(403, "You are not allowed to view this profile")

    doc = await db.employee_profiles.find_one({"employee_id": str(target["_id"])})
    return _profile_out(doc, current, target)


@router.put("/{employee_id}/profile/submitted")
async def update_submitted_details(
    employee_id: str,
    payload: SubmittedDetailsIn,
    current: UserPublic = Depends(get_current_user),
):
    """Details the employee fills in about themselves. Editable by the employee or Founder/Admin."""
    db = get_db()
    target = await _get_employee(db, employee_id)
    is_self = str(target["_id"]) == current.id

    if not (is_self or current.role in ADMIN_ROLES):
        raise HTTPException(403, "Only the employee or an admin can edit these details")

    data = payload.model_dump(mode="json", exclude_unset=True)
    for key, value in list(data.items()):
        if isinstance(value, str):
            value = value.strip() or None
            data[key] = value

    last4 = data.get("bank_account_last4")
    if last4 and (not last4.isdigit() or len(last4) != 4):
        raise HTTPException(400, "Enter only the last 4 digits of the bank account")

    if not data:
        raise HTTPException(400, "Nothing to update")

    now = utc_iso()
    await db.employee_profiles.update_one(
        {"employee_id": str(target["_id"])},
        {
            "$set": {**{f"submitted.{k}": v for k, v in data.items()}, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    await log_activity(db, current, "Updated employee details", "Employees", target=target["name"],
                       meta={"section": "submitted", "fields": sorted(data)})

    doc = await db.employee_profiles.find_one({"employee_id": str(target["_id"])})
    return _profile_out(doc, current, target)


@router.patch("/{employee_id}/profile/company")
async def update_company_details(
    employee_id: str,
    payload: CompanyDetailsIn,
    current: UserPublic = Depends(require_roles("Founder", "Admin")),
):
    """Details the company records for an employee. Founder/Admin only."""
    db = get_db()
    target = await _get_employee(db, employee_id)

    data = payload.model_dump(mode="json", exclude_unset=True)
    for key, value in list(data.items()):
        if isinstance(value, str):
            data[key] = value.strip() or None

    if data.get("stipend_or_salary") is not None and data["stipend_or_salary"] < 0:
        raise HTTPException(400, "Stipend / salary cannot be negative")

    if not data:
        raise HTTPException(400, "Nothing to update")

    now = utc_iso()
    await db.employee_profiles.update_one(
        {"employee_id": str(target["_id"])},
        {
            "$set": {**{f"company.{k}": v for k, v in data.items()}, "updated_at": now,
                     "company_updated_by": current.id},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    await log_activity(db, current, "Updated company details", "Employees", target=target["name"],
                       meta={"section": "company", "fields": sorted(data)})

    if str(target["_id"]) != current.id:
        await notify(db, str(target["_id"]), "Your employment details were updated",
                     f"{current.name} updated your company details.", kind="info", link="/employees")

    doc = await db.employee_profiles.find_one({"employee_id": str(target["_id"])})
    return _profile_out(doc, current, target)


# ============================================================
# DELETE EMPLOYEE
# ============================================================

@router.delete("/{employee_id}")
async def delete_employee(
    employee_id: str,
    current: UserPublic = Depends(
        require_roles("Founder", "Admin")
    ),
):
    db = get_db()

    target = await _find_user(
        db,
        employee_id,
    )

    if not target:
        raise HTTPException(404, "Employee not found")

    if str(target["_id"]) == current.id:
        raise HTTPException(400, "You cannot remove your own account")

    if target.get("role") == "Founder":
        raise HTTPException(403, "Cannot remove the Founder account")

    if (
        target.get("role") == "Admin"
        and current.role != "Founder"
    ):
        raise HTTPException(403, "Only the Founder can remove an Admin")

    email = target.get("email")

    # Remove ONLY the user account.
    # Assigned tasks and submitted data remain.
    await db.users.delete_one(
        {"_id": target["_id"]}
    )

    await db.sessions.delete_many(
        {
            "user_id": str(
                target["_id"]
            )
        }
    )

    if email:
        await db.invitations.delete_many({"email": _email_regex(email)})

    await log_activity(
        db,
        current,
        "Removed employee account",
        "Employees",
        target=target["name"],
    )

    return {
        "ok": True,
        "message": (
            f"Employee account for "
            f"{target['name']} removed. "
            "Assigned tasks and submitted data "
            "remain intact."
        ),
    }


# ============================================================
# DEPARTMENTS
# ============================================================

@router.get("/departments/list")
async def list_departments(
    current: UserPublic = Depends(
        get_current_user
    ),
):
    """Registered departments, plus department names that employees carry but that were never
    set up (registered: false), so no teammate is left out of the cards."""
    db = get_db()

    docs = await db.departments.find().sort("name", 1).to_list(200)
    heads = await _user_map(db, [d.get("head_id") for d in docs])

    counts: dict[str, int] = {}
    spellings: dict[str, dict[str, int]] = {}
    async for u in db.users.find({**REAL_USERS, "department": {"$nin": ["", None]}}, {"department": 1}):
        name = _norm_dept(u.get("department"))
        if not name:
            continue
        key = name.casefold()
        counts[key] = counts.get(key, 0) + 1
        spellings.setdefault(key, {})
        spellings[key][name] = spellings[key].get(name, 0) + 1

    out = []
    registered = set()
    for d in docs:
        key = _norm_dept(d.get("name")).casefold()
        registered.add(key)
        head = heads.get(str(d.get("head_id")))
        out.append({
            **serialize(d),
            "head_name": head["name"] if head else None,
            "headcount": counts.get(key, 0),
            "registered": True,
        })

    for key, total in counts.items():
        if key in registered:
            continue
        name = max(spellings[key].items(), key=lambda kv: kv[1])[0]
        out.append({"id": None, "name": name, "head_id": None, "head_name": None, "description": None,
                    "headcount": total, "registered": False})

    out.sort(key=lambda d: (not d["registered"], d["name"].casefold()))
    return out


@router.post(
    "/departments/list",
    status_code=201,
)
async def create_department(
    payload: DepartmentIn,
    current: UserPublic = Depends(
        require_roles(
            "Founder",
            "Admin",
        )
    ),
):
    db = get_db()

    doc = payload.model_dump()

    if await db.departments.find_one({"name": _email_regex(doc["name"])}, {"_id": 1}):
        raise HTTPException(409, f"A department named {doc['name']} already exists")

    if doc.get("head_id"):
        doc["head_id"] = str((await _get_employee(db, doc["head_id"]))["_id"])

    doc["created_at"] = utc_iso()

    res = await db.departments.insert_one(
        doc
    )

    doc["_id"] = res.inserted_id
    await get_or_create_department_channel(db, doc["name"])
    await log_activity(db, current, "Created department", "Employees", target=doc["name"])
    return serialize(doc)


@router.patch("/departments/{department_id}")
async def update_department(
    department_id: str,
    payload: dict,
    current: UserPublic = Depends(require_roles("Founder", "Admin")),
):
    """Rename a department, set its head, or change its description. Renaming also moves the
    employees who carry the old name (in any spelling) to the new one."""
    db = get_db()
    dept = await db.departments.find_one({"_id": oid(department_id)})
    if not dept:
        raise HTTPException(404, "Department not found")

    allowed = {"name", "head_id", "description"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(422, f"Unknown fields: {', '.join(sorted(unknown))}")

    changes = {}
    if "name" in payload:
        name = _norm_dept(payload.get("name"))
        if not name or len(name) > 80:
            raise HTTPException(422, "Department name must be 1–80 characters")
        clash = await db.departments.find_one({"name": _email_regex(name), "_id": {"$ne": dept["_id"]}}, {"_id": 1})
        if clash:
            raise HTTPException(409, f"A department named {name} already exists")
        changes["name"] = name
    if "description" in payload:
        description = (payload.get("description") or "").strip()
        if len(description) > 1000:
            raise HTTPException(422, "Description is too long")
        changes["description"] = description or None
    if "head_id" in payload:
        head_id = payload.get("head_id")
        if head_id:
            head = await _get_employee(db, head_id)
            if _is_placeholder(head) or head.get("status") == "deactivated":
                raise HTTPException(400, "The department head must be an active employee")
            changes["head_id"] = str(head["_id"])
        else:
            changes["head_id"] = None

    if not changes:
        return serialize(dept)
    changes["updated_at"] = utc_iso()
    await db.departments.update_one({"_id": dept["_id"]}, {"$set": changes})
    if "name" in changes and changes["name"] != dept["name"]:
        await db.users.update_many({"department": _dept_match(dept["name"])}, {"$set": {"department": changes["name"]}})
        # Rename the department's Connect group (members and history stay) instead of starting an empty one
        await rename_department_channel(db, dept["name"], changes["name"],
                                        member_ids=await _dept_ids(db, changes["name"]))
    await log_activity(db, current, "Updated department", "Employees", target=changes.get("name", dept["name"]),
                       meta={"fields": sorted(k for k in changes if k != "updated_at")})
    return serialize(await db.departments.find_one({"_id": dept["_id"]}))


# ============================================================
# ATTENDANCE
# ============================================================

@router.get("/attendance/records")
async def list_attendance(
    employee_id: str | None = None,
    date: str | None = None,
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    q = {}

    if date:
        q["date"] = date

    if current.role in (
        "Employee",
        "Intern",
    ):
        q["employee_id"] = current.id

    elif current.role == "Manager":
        dept = await _dept_ids(db, current.department)
        q["employee_id"] = (employee_id if employee_id in dept else {"$in": []}) if employee_id else {"$in": dept}

    elif employee_id:
        q["employee_id"] = employee_id

    docs = await db.attendance.find(
        q
    ).sort(
        "date",
        -1,
    ).to_list(500)

    names = await _user_map(db, [d.get("employee_id") for d in docs])
    return [
        {
            **_attendance_out(d),
            "employee_name": (names.get(str(d.get("employee_id"))) or {}).get("name") or d.get("employee_name"),
        }
        for d in docs
    ]


@router.post(
    "/attendance/records",
    status_code=201,
)
async def add_attendance(
    payload: AttendanceIn,
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    if payload.date != _today_ist():
        raise HTTPException(
            400,
            "Attendance can only be marked for today "
            "(neither past nor future dates allowed)",
        )

    target = await _get_employee(db, payload.employee_id)
    employee_id = str(target["_id"])

    if employee_id == current.id:
        if not can(current.role, "attendance.mark_self"):
            raise HTTPException(403, "You cannot mark attendance")
        if payload.status == "leave":
            raise HTTPException(403, "Leave is recorded through an approved leave request")
    else:
        if not can(current.role, "attendance.mark_others"):
            raise HTTPException(403, "You can only mark your own attendance")
        if current.role == "Manager" and not _same_department(current, target):
            raise HTTPException(403, "Managers can only mark attendance for their department")

    if payload.check_in and payload.check_out and payload.check_out < payload.check_in:
        raise HTTPException(400, "Check-out must not be before check-in")

    # Only the provided fields are written, so an existing check-in/out survives a status change.
    now = utc_iso()
    fields = {"status": payload.status, "updated_at": now}
    on_insert = {"employee_name": target.get("name"), "created_at": now, "marked_by": current.id}
    for key in ("check_in", "check_out"):
        if getattr(payload, key):
            fields[key] = getattr(payload, key)
        else:
            on_insert[key] = None

    await db.attendance.update_one(
        {"employee_id": employee_id, "date": payload.date},
        {"$set": fields, "$setOnInsert": on_insert},
        upsert=True,
    )
    doc = await db.attendance.find_one({"employee_id": employee_id, "date": payload.date})

    await log_activity(
        db,
        current,
        f"Attendance · {payload.status}",
        "Employees",
        target=f"{target.get('name') or '—'} · {payload.date}",
    )

    return {"ok": True, "record": _attendance_out(doc)}


@router.post("/attendance/check-in")
async def attendance_check_in(
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    if not can(current.role, "attendance.mark_self"):
        raise HTTPException(403, "You cannot mark attendance")

    today, now = _today_ist(), utc_iso()
    key = {"employee_id": current.id, "date": today}

    # Idempotent: the first check-in of the day wins, later calls return the same record.
    res = await db.attendance.update_one(
        key,
        {"$setOnInsert": {
            "employee_name": current.name, "status": "present", "check_in": now, "check_out": None,
            "created_at": now, "updated_at": now,
        }},
        upsert=True,
    )
    checked_in = res.upserted_id is not None
    if not checked_in:
        # A record may exist without a check-in (e.g. marked manually); fill it in once.
        res = await db.attendance.update_one(
            {**key, "check_in": {"$in": [None, ""]}},
            {"$set": {"check_in": now, "updated_at": now}},
        )
        checked_in = res.modified_count > 0
        if checked_in:
            await db.attendance.update_one({**key, "status": "absent"}, {"$set": {"status": "present"}})

    doc = await db.attendance.find_one(key)
    if checked_in:
        await log_activity(db, current, "Checked in", "Employees", target=f"{current.name} · {today}")

    return {**_attendance_out(doc), "already_checked_in": not checked_in}


@router.post("/attendance/check-out")
async def attendance_check_out(
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    if not can(current.role, "attendance.mark_self"):
        raise HTTPException(403, "You cannot mark attendance")

    key = {"employee_id": current.id, "date": _today_ist()}
    doc = await db.attendance.find_one(key)
    if not doc or not doc.get("check_in"):
        raise HTTPException(400, "Check in first — there is no check-in for today")

    # Latest check-out wins, matching sign-out behaviour.
    now = utc_iso()
    await db.attendance.update_one({"_id": doc["_id"]}, {"$set": {"check_out": now, "updated_at": now}})
    doc = await db.attendance.find_one({"_id": doc["_id"]})

    await log_activity(db, current, "Checked out", "Employees", target=f"{current.name} · {key['date']}")
    return _attendance_out(doc)


# ============================================================
# LEAVE
# ============================================================

async def _leave_approvers(db, employee: dict) -> list[str]:
    """Founder/Admin plus Managers of the employee's own department (never the employee)."""
    scopes = [{"role": {"$in": ["Founder", "Admin"]}}]
    if employee.get("department"):
        scopes.append({"role": "Manager", "department": _dept_match(employee["department"])})
    docs = await db.users.find(
        {**REAL_USERS, "$or": scopes, "status": {"$ne": "deactivated"}, "_id": {"$ne": employee["_id"]}},
        {"_id": 1},
    ).to_list(100)
    return [str(d["_id"]) for d in docs]


async def _mark_leave_days(db, leave: dict, employee: dict):
    """Approved leave shows up in attendance, except on days the employee actually checked in."""
    try:
        day, last = date_cls.fromisoformat(leave["from_date"]), date_cls.fromisoformat(leave["to_date"])
    except (KeyError, TypeError, ValueError):
        return
    now = utc_iso()
    for _ in range(366):
        if day > last:
            break
        key = {"employee_id": leave["employee_id"], "date": day.isoformat()}
        existing = await db.attendance.find_one(key)
        if not existing:
            await db.attendance.insert_one({
                **key, "employee_name": employee.get("name"), "status": "leave", "check_in": None,
                "check_out": None, "leave_id": str(leave["_id"]), "created_at": now, "updated_at": now,
            })
        elif not existing.get("check_in"):
            await db.attendance.update_one({"_id": existing["_id"]}, {"$set": {"status": "leave", "updated_at": now}})
        day += timedelta(days=1)


@router.get("/leave/requests")
async def list_leave(
    status: str | None = None,
    employee_id: str | None = None,
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    q = {}

    if status:
        q["status"] = status

    if current.role in (
        "Employee",
        "Intern",
    ):
        q["employee_id"] = current.id

    elif current.role == "Manager":
        q["employee_id"] = {
            "$in": await _dept_ids(
                db,
                current.department,
            )
        }

    elif employee_id:
        q["employee_id"] = employee_id

    docs = await db.leave_requests.find(
        q
    ).sort(
        "created_at",
        -1,
    ).to_list(500)

    emps = await _user_map(db, [d.get("employee_id") for d in docs], fields=("name", "photo"))

    out = []

    for d in docs:
        emp = emps.get(str(d.get("employee_id")))
        out.append(
            {
                **serialize(d),
                "employee_name": emp["name"] if emp else None,
                "employee_photo": emp.get("photo") if emp else None,
            }
        )

    return out


@router.post(
    "/leave/requests",
    status_code=201,
)
async def create_leave(
    payload: LeaveIn,
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    target = await _get_employee(db, payload.employee_id or current.id)
    employee_id = str(target["_id"])

    if employee_id != current.id:
        if current.role in ("Employee", "Intern"):
            raise HTTPException(403, "You can only request leave for yourself")
        if current.role == "Manager" and not _same_department(current, target):
            raise HTTPException(403, "Managers can only request leave for their department")

    now = utc_iso()
    # New requests are always pending; the status is decided via PATCH by an approver.
    doc = {
        **payload.model_dump(),
        "employee_id": employee_id,
        "status": "pending",
        "requested_by": current.id,
        "created_at": now,
        "updated_at": now,
    }

    res = await db.leave_requests.insert_one(
        doc
    )

    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Leave requested", "Employees",
                       target=f"{target['name']} · {doc['from_date']} → {doc['to_date']}")

    for approver_id in await _leave_approvers(db, target):
        if approver_id == current.id:
            continue
        await notify(
            db, approver_id, "Leave request",
            f"{target['name']} requested {doc['kind']} leave from {doc['from_date']} to {doc['to_date']}.",
            kind="warning", link="/employees",
        )
    return {**serialize(doc), "employee_name": target["name"]}


@router.patch("/leave/requests/{leave_id}")
async def decide_leave(
    leave_id: str,
    payload: LeaveDecisionIn,
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    if not can(current.role, "leave.approve"):
        raise HTTPException(403, "You are not allowed to approve leave")

    leave = await db.leave_requests.find_one({"_id": oid(leave_id)})
    if not leave:
        raise HTTPException(404, "Leave request not found")

    if leave.get("employee_id") == current.id:
        raise HTTPException(403, "You cannot approve or reject your own leave")

    emp = (await _user_map(db, [leave.get("employee_id")], fields=("name", "department"))).get(
        str(leave.get("employee_id")))
    if current.role == "Manager" and (not emp or not _same_department(current, emp)):
        raise HTTPException(403, "Managers can only decide leave for their department")

    if leave.get("status") != "pending":
        raise HTTPException(409, f"Leave request is already {leave.get('status')}")

    status = payload.status
    now = utc_iso()
    res = await db.leave_requests.update_one(
        {"_id": leave["_id"], "status": "pending"},
        {"$set": {
            "status": status,
            "decided_by": current.id,
            "decided_by_name": current.name,
            "decided_at": now,
            "decision_note": payload.note,
            "updated_at": now,
        }},
    )
    if res.modified_count == 0:
        raise HTTPException(409, "Leave request was already decided")

    doc = await db.leave_requests.find_one({"_id": leave["_id"]})
    if status == "approved" and emp:
        await _mark_leave_days(db, doc, emp)

    await log_activity(db, current, f"Leave {status}", "Employees",
                       target=f"{emp['name'] if emp else '—'} · {doc['from_date']} → {doc['to_date']}")

    if emp:
        await notify(
            db,
            doc["employee_id"],
            f"Your leave was {status}",
            f"{current.name} {status} your leave request {doc['from_date']} → {doc['to_date']}",
            kind="success" if status == "approved" else "warning",
            link="/employees",
        )

    return {**serialize(doc), "employee_name": emp["name"] if emp else None}


# ============================================================
# PERFORMANCE
# ============================================================

@router.get("/performance/reviews")
async def list_performance(
    employee_id: str | None = None,
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    q = {}

    if current.role in (
        "Employee",
        "Intern",
    ):
        q["employee_id"] = current.id

    elif current.role == "Manager":
        q["employee_id"] = {
            "$in": await _dept_ids(
                db,
                current.department,
            )
        }

    elif employee_id:
        q["employee_id"] = employee_id

    docs = await db.performance_reviews.find(
        q
    ).sort(
        "created_at",
        -1,
    ).to_list(300)

    emps = await _user_map(db, [d.get("employee_id") for d in docs], fields=("name", "designation", "photo"))

    out = []

    for d in docs:
        emp = emps.get(str(d.get("employee_id")))
        out.append(
            {
                **serialize(d),
                "employee_name": emp["name"] if emp else None,
                "employee_designation": emp.get("designation") if emp else None,
                "employee_photo": emp.get("photo") if emp else None,
            }
        )

    return out


@router.post(
    "/performance/reviews",
    status_code=201,
)
async def create_performance(
    payload: PerformanceIn,
    current: UserPublic = Depends(
        require_roles(
            "Founder",
            "Admin",
            "Manager",
        )
    ),
):
    db = get_db()

    target = await _get_employee(db, payload.employee_id)

    if str(target["_id"]) == current.id:
        raise HTTPException(403, "You cannot review yourself")

    if current.role == "Manager" and not _same_department(current, target):
        raise HTTPException(403, "Managers can only review their department")

    doc = payload.model_dump()
    doc["employee_id"] = str(target["_id"])
    doc["created_at"] = utc_iso()
    doc["reviewer_id"] = current.id
    doc["reviewer_name"] = current.name

    res = await db.performance_reviews.insert_one(
        doc
    )

    doc["_id"] = res.inserted_id

    await log_activity(
        db,
        current,
        "Performance review recorded",
        "Employees",
        target=f"{target['name']} · {doc['period']}",
    )

    await notify(
        db,
        doc["employee_id"],
        "Performance review saved",
        f"{current.name} saved your {doc['period']} review.",
        kind="info",
        link="/employees",
    )

    return serialize(doc)


# ============================================================
# OVERVIEW STATS
# ============================================================

@router.get("/stats/overview")
async def employees_overview(
    current: UserPublic = Depends(
        get_current_user
    ),
):
    db = get_db()

    if current.role in (
        "Employee",
        "Intern",
    ):
        # Personal numbers only — no synthetic team counts.
        today = _today_ist()
        mine = {"employee_id": current.id}
        today_rec = await db.attendance.find_one({**mine, "date": today})
        return {
            "scope": "self",
            "present_this_month": await db.attendance.count_documents({
                **mine, "date": {"$regex": f"^{today[:7]}"}, "status": {"$in": ["present", "wfh", "half_day"]},
            }),
            "checked_in_today": bool(today_rec and today_rec.get("check_in")),
            "pending_leave": await db.leave_requests.count_documents({**mine, "status": "pending"}),
            "approved_leave": await db.leave_requests.count_documents({**mine, "status": "approved"}),
        }

    users_q = dict(REAL_USERS)
    leave_q = {"status": "pending"}
    if current.role == "Manager":
        users_q["department"] = _dept_match(current.department)
        leave_q["employee_id"] = {"$in": await _dept_ids(db, current.department)}

    by_role = {}
    async for u in db.users.find(users_q, {"role": 1}):
        role = u.get("role", "Employee")
        by_role[role] = by_role.get(role, 0) + 1

    out = {
        "scope": "department" if current.role == "Manager" else "company",
        "department": current.department if current.role == "Manager" else None,
        "total": sum(by_role.values()),
        "online": await db.users.count_documents({**users_q, "online": True}),
        "by_role": [{"role": k, "count": v} for k, v in by_role.items()],
        "pending_leave": await db.leave_requests.count_documents(leave_q),
        "departments": (
            (1 if current.department else 0)
            if current.role == "Manager"
            else await db.departments.count_documents({})
        ),
    }
    if can(current.role, "employee.invite"):
        out["pending_invites"] = await db.invitations.count_documents({"status": "pending"})
    return out