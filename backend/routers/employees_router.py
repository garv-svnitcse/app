from __future__ import annotations
import os
import re
import secrets
import string
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles, hash_password
from models import UserPublic
from models_part2 import DepartmentIn, EmployeeInviteIn, AttendanceIn, LeaveIn, PerformanceIn
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify
from email_utils import send_invitation_email

router = APIRouter(prefix="/employees", tags=["employees"])


async def _dept_ids(db, department):
    """Return list of user ids (str) in the given department."""
    if not department:
        return []
    return [str(u["_id"]) async for u in db.users.find({"department": department}, {"_id": 1})]


def _gen_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "Wg" + "".join(secrets.choice(alphabet) for _ in range(length))


@router.get("")
async def list_employees(q: str | None = None, department: str | None = None, role: str | None = None,
                         current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    query = {}
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"designation": {"$regex": q, "$options": "i"}},
        ]
    if department: query["department"] = department
    if role: query["role"] = role
    # Managers only see their own department (team scoping = same department).
    if current.role == "Manager":
        query["department"] = current.department
    docs = await db.users.find(query, {"password_hash": 0}).sort("created_at", -1).to_list(500)
    return serialize_many(docs, drop=("password_hash",))


@router.post("/invite", status_code=201)
async def invite_employee(payload: EmployeeInviteIn,
                          background_tasks: BackgroundTasks,
                          current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    name = (payload.name or "").strip()
    email = (payload.email or "").lower().strip()
    if not name:
        raise HTTPException(400, "Full name is required")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Please provide a valid email address")
    if payload.role not in ("Admin", "Manager", "Employee", "Intern"):
        raise HTTPException(400, "Invalid role specified")
    if payload.role == "Founder":
        raise HTTPException(403, "Cannot create another Founder")
    if payload.role == "Admin" and current.role != "Founder":
        raise HTTPException(403, "Only the Founder can create an Admin")
    existing_user = await db.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if existing_user and existing_user.get("status") == "active" and (existing_user.get("is_active") is True or existing_user.get("active") is True):
        raise HTTPException(409, "Email is already registered as an active employee")

    frontend_url = os.environ.get("FRONTEND_URL", "https://app-eta-flax-97.vercel.app")
    token = secrets.token_urlsafe(32)
    invite_url = f"{frontend_url}/accept-invite?token={token}"

    if existing_user:
        await db.users.update_one(
            {"_id": existing_user["_id"]},
            {"$set": {
                "name": name,
                "role": payload.role,
                "designation": payload.designation,
                "department": payload.department,
                "phone": payload.phone,
                "status": "deactivated",
                "is_active": False,
                "active": False,
                "invited_by": current.name,
                "updated_at": utc_iso()
            }}
        )
        user_id = str(existing_user["_id"])
    else:
        user_doc = {
            "email": email,
            "name": name,
            "role": payload.role,
            "designation": payload.designation,
            "department": payload.department,
            "phone": payload.phone,
            "password_hash": "",
            "status": "deactivated",
            "is_active": False,
            "active": False,
            "online": False,
            "invited_by": current.name,
            "created_at": utc_iso(),
            "updated_at": utc_iso(),
        }
        res_u = await db.users.insert_one(user_doc)
        user_id = str(res_u.inserted_id)

    inv_doc = {
        "token": token,
        "email": email,
        "name": name,
        "role": payload.role,
        "designation": payload.designation,
        "department": payload.department,
        "phone": payload.phone,
        "status": "pending",
        "invited_by": current.name,
        "user_id": user_id,
        "created_at": utc_iso(),
    }
    await db.invitations.delete_many({"email": email})
    res = await db.invitations.insert_one(inv_doc)
    inv_doc["_id"] = res.inserted_id

    background_tasks.add_task(
        send_invitation_email,
        recipient_email=email,
        recipient_name=name,
        role=payload.role,
        token=token,
        invited_by=current.name,
        designation=payload.designation,
        department=payload.department
    )

    await log_activity(db, current, "Sent employee invitation", "Employees", target=name)
    return {
        **serialize(inv_doc),
        "token": token,
        "invite_url": invite_url,
        "user_id": user_id,
        "message": f"Invitation email sent to {email}. Employee added to database as deactivated pending invitation accept."
    }


@router.get("/invitations")
async def list_invitations(current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    docs = await db.invitations.find().sort("created_at", -1).to_list(500)
    return serialize_many(docs)


@router.get("/invite/{token}")
async def get_invite_details(token: str):
    db = get_db()
    inv = await db.invitations.find_one({"token": token})
    if not inv:
        raise HTTPException(404, "Invalid or expired invitation link")
    return {
        "email": inv["email"],
        "name": inv["name"],
        "role": inv["role"],
        "designation": inv.get("designation"),
        "department": inv.get("department"),
        "phone": inv.get("phone"),
        "invited_by": inv.get("invited_by"),
        "status": inv.get("status", "pending"),
        "already_accepted": inv.get("status") == "accepted",
    }


@router.post("/accept-invite")
async def accept_invite(payload: dict):
    token = payload.get("token")
    password = payload.get("password")
    if not token:
        raise HTTPException(400, "Invitation token is required")
    
    db = get_db()
    inv = await db.invitations.find_one({"token": token})
    if not inv:
        raise HTTPException(404, "Invalid or expired invitation link")
    
    email = inv["email"].lower().strip()
    if inv.get("status") == "accepted":
        return {
            "ok": True,
            "email": email,
            "already_accepted": True,
            "message": "Invitation already accepted! Redirecting to login page..."
        }

    if not password or len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters long")
    
    existing_user = await db.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if existing_user:
        await db.users.update_one(
            {"_id": existing_user["_id"]},
            {"$set": {
                "password_hash": hash_password(password),
                "name": inv["name"],
                "role": inv["role"],
                "designation": inv.get("designation"),
                "department": inv.get("department"),
                "phone": inv.get("phone"),
                "status": "active",
                "is_active": True,
                "active": True,
                "updated_at": utc_iso()
            }}
        )
    else:
        user_doc = {
            "email": email,
            "name": inv["name"],
            "role": inv["role"],
            "designation": inv.get("designation"),
            "department": inv.get("department"),
            "phone": inv.get("phone"),
            "password_hash": hash_password(password),
            "status": "active",
            "is_active": True,
            "active": True,
            "online": False,
            "created_at": utc_iso(),
            "updated_at": utc_iso(),
        }
        await db.users.insert_one(user_doc)

    await db.invitations.update_one(
        {"_id": inv["_id"]},
        {"$set": {"status": "accepted", "accepted_at": utc_iso()}}
    )

    await notify(db, None, "New teammate joined", f"{inv['name']} accepted the invitation and joined as {inv['role']}.",
                 kind="success", link="/employees")
    
    return {"ok": True, "email": email, "message": "Invitation accepted successfully! Redirecting to login page..."}


@router.post("/invitations/{invite_id}/resend")
async def resend_invitation(invite_id: str, background_tasks: BackgroundTasks, current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    invite_id_str = str(invite_id).strip()
    inv = None

    if ObjectId.is_valid(invite_id_str):
        inv = await db.invitations.find_one({"_id": ObjectId(invite_id_str)})
    if not inv:
        inv = await db.invitations.find_one({"_id": invite_id_str})
    if not inv:
        inv = await db.invitations.find_one({"token": invite_id_str})
    if not inv:
        inv = await db.invitations.find_one({"email": invite_id_str})
    if not inv:
        inv = await db.invitations.find_one({"email": {"$regex": f"^{re.escape(invite_id_str)}$", "$options": "i"}})
    if not inv:
        async for doc in db.invitations.find():
            if str(doc.get("_id")) == invite_id_str or str(doc.get("id")) == invite_id_str or doc.get("token") == invite_id_str or doc.get("email") == invite_id_str:
                inv = doc
                break

    if not inv:
        raise HTTPException(404, "Pending invitation not found")
    
    background_tasks.add_task(
        send_invitation_email,
        recipient_email=inv["email"],
        recipient_name=inv["name"],
        role=inv["role"],
        token=inv["token"],
        invited_by=current.name,
        designation=inv.get("designation"),
        department=inv.get("department")
    )
    return {"ok": True, "message": f"Invitation email is being resent to {inv['email']}"}


@router.delete("/invitations/{invite_id}", status_code=200)
async def delete_invitation(invite_id: str, current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    invite_id_str = str(invite_id).strip()
    inv = None

    if ObjectId.is_valid(invite_id_str):
        inv = await db.invitations.find_one({"_id": ObjectId(invite_id_str)})
    if not inv:
        inv = await db.invitations.find_one({"_id": invite_id_str})
    if not inv:
        inv = await db.invitations.find_one({"token": invite_id_str})
    if not inv:
        inv = await db.invitations.find_one({"email": invite_id_str})
    if not inv:
        inv = await db.invitations.find_one({"email": {"$regex": f"^{re.escape(invite_id_str)}$", "$options": "i"}})
    if not inv:
        async for doc in db.invitations.find():
            if str(doc.get("_id")) == invite_id_str or str(doc.get("id")) == invite_id_str or doc.get("token") == invite_id_str or doc.get("email") == invite_id_str:
                inv = doc
                break

    if not inv:
        raise HTTPException(404, "Pending invitation not found")
    
    email = inv.get("email", "").lower().strip()
    await db.invitations.delete_one({"_id": inv["_id"]})
    await log_activity(db, current, "Deleted pending invitation", "Employees", target=email)
    return {"ok": True, "message": f"Pending invitation for {email} deleted successfully"}


async def _find_user(db, employee_id: str):
    employee_id_str = str(employee_id).strip()
    if ObjectId.is_valid(employee_id_str):
        user = await db.users.find_one({"_id": ObjectId(employee_id_str)})
        if user:
            return user
    user = await db.users.find_one({"_id": employee_id_str})
    if user:
        return user
    user = await db.users.find_one({"email": {"$regex": f"^{re.escape(employee_id_str)}$", "$options": "i"}})
    return user


@router.post("/{employee_id}/reset-password")
async def reset_employee_password(employee_id: str, payload: dict | None = None,
                                  current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    target = await _find_user(db, employee_id)
    if not target:
        raise HTTPException(404, "Employee not found")
    if target.get("role") == "Founder":
        raise HTTPException(403, "Cannot reset the Founder password from here")
    new_password = (payload or {}).get("new_password") or _gen_temp_password()
    await db.users.update_one(
        {"_id": target["_id"]},
        {"$set": {"password_hash": hash_password(new_password), "updated_at": utc_iso()}},
    )
    await log_activity(db, current, "Reset password", "Employees", target=target["name"])
    await notify(db, str(target["_id"]), "Your password was reset",
                 f"{current.name} reset your password. Please sign in with the new temporary password and update it if allowed.",
                 kind="warning", link="/settings")
    return {"ok": True, "temp_password": new_password}


@router.patch("/{employee_id}/status")
async def toggle_employee_status(employee_id: str, payload: dict | None = None,
                                 current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    target = await _find_user(db, employee_id)
    if not target:
        raise HTTPException(404, "Employee not found")
    if target.get("role") == "Founder":
        raise HTTPException(403, "Cannot deactivate the Founder account")
    if target.get("role") == "Admin" and current.role != "Founder":
        raise HTTPException(403, "Only the Founder can deactivate an Admin")
    
    current_status = target.get("status", "active")
    req_status = (payload or {}).get("status")
    if req_status in ("active", "deactivated"):
        new_status = req_status
    else:
        new_status = "deactivated" if current_status == "active" else "active"
    
    is_act = (new_status == "active")
    await db.users.update_one(
        {"_id": target["_id"]},
        {"$set": {
            "status": new_status,
            "is_active": is_act,
            "active": is_act,
            "updated_at": utc_iso()
        }}
    )
    
    if not is_act:
        await db.sessions.delete_many({"user_id": str(target["_id"])})
    
    action_verb = "Reactivated" if is_act else "Deactivated"
    await log_activity(db, current, f"{action_verb} employee account", "Employees", target=target["name"])
    return {
        "ok": True,
        "status": new_status,
        "is_active": is_act,
        "message": f"Employee {target['name']} is now {new_status}."
    }


@router.patch("/{employee_id}")
async def update_employee(employee_id: str, payload: dict,
                          current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    new_role = payload.get("role")
    if new_role == "Founder":
        raise HTTPException(403, "Cannot assign the Founder role")
    if new_role == "Admin" and current.role != "Founder":
        raise HTTPException(403, "Only the Founder can assign the Admin role")
    target = await _find_user(db, employee_id)
    if not target:
        raise HTTPException(404, "Employee not found")
    if current.role == "Manager" and target.get("department") != current.department:
        raise HTTPException(403, "Managers can only edit teammates in their department")
    payload.pop("id", None); payload.pop("_id", None); payload.pop("password_hash", None); payload.pop("email", None)
    payload["updated_at"] = utc_iso()
    res = await db.users.update_one({"_id": target["_id"]}, {"$set": payload})
    if res.matched_count == 0:
        raise HTTPException(404, "Employee not found")
    doc = await db.users.find_one({"_id": target["_id"]}, {"password_hash": 0})
    await log_activity(db, current, "Updated employee", "Employees", target=doc["name"])
    return serialize(doc)


@router.delete("/{employee_id}")
async def delete_employee(employee_id: str,
                          current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    target = await _find_user(db, employee_id)
    if not target:
        raise HTTPException(404, "Employee not found")
    if target.get("role") == "Founder":
        raise HTTPException(403, "Cannot remove the Founder account")
    if target.get("role") == "Admin" and current.role != "Founder":
        raise HTTPException(403, "Only the Founder can remove an Admin")
    
    email = target.get("email")
    # Remove ONLY the user account credentials from db.users.
    # Preserve all assigned tasks, submitted data, attendance, leave requests, activity logs!
    await db.users.delete_one({"_id": target["_id"]})
    await db.sessions.delete_many({"user_id": str(target["_id"])})
    if email:
        await db.invitations.delete_many({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    
    await log_activity(db, current, "Removed employee account", "Employees", target=target["name"])
    return {
        "ok": True,
        "message": f"Employee account for {target['name']} removed. Assigned tasks and submitted data remain intact."
    }


# -------- Departments --------

@router.get("/departments/list")
async def list_departments(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    docs = await db.departments.find().sort("name", 1).to_list(200)
    out = []
    for d in docs:
        head_name = None
        if d.get("head_id"):
            try:
                u = await db.users.find_one({"_id": ObjectId(d["head_id"])}, {"name": 1})
                head_name = u["name"] if u else None
            except Exception: pass
        headcount = await db.users.count_documents({"department": d["name"]})
        out.append({**serialize(d), "head_name": head_name, "headcount": headcount})
    return out


@router.post("/departments/list", status_code=201)
async def create_department(payload: DepartmentIn,
                            current: UserPublic = Depends(require_roles("Founder", "Admin"))):
    db = get_db()
    doc = payload.model_dump()
    doc["created_at"] = utc_iso()
    res = await db.departments.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(db, current, "Created department", "Employees", target=doc["name"])
    return serialize(doc)


# -------- Attendance --------

@router.get("/attendance/records")
async def list_attendance(employee_id: str | None = None, date: str | None = None,
                          current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if date: q["date"] = date
    if current.role in ("Employee", "Intern"):
        q["employee_id"] = current.id
    elif current.role == "Manager":
        q["employee_id"] = {"$in": await _dept_ids(db, current.department)}
    elif employee_id:
        q["employee_id"] = employee_id
    docs = await db.attendance.find(q).sort("date", -1).to_list(500)
    return serialize_many(docs)


@router.post("/attendance/records", status_code=201)
async def add_attendance(payload: AttendanceIn, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    doc = payload.model_dump()
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_local = datetime.now().strftime("%Y-%m-%d")
    if doc["date"] not in (today_utc, today_local):
        raise HTTPException(400, "Attendance can only be marked for today (neither past nor future dates allowed)")
    if current.role in ("Employee", "Intern") and doc["employee_id"] != current.id:
        raise HTTPException(403, "You can only mark your own attendance")
    if current.role == "Manager":
        tgt = await db.users.find_one({"_id": oid(doc["employee_id"])})
        if not tgt or tgt.get("department") != current.department:
            raise HTTPException(403, "Managers can only mark attendance for their department")
    doc["created_at"] = utc_iso()
    await db.attendance.update_one(
        {"employee_id": doc["employee_id"], "date": doc["date"]},
        {"$set": doc}, upsert=True,
    )
    emp = await db.users.find_one({"_id": oid(doc["employee_id"])}, {"name": 1})
    await log_activity(db, current, f"Attendance · {doc['status']}", "Employees",
                       target=f"{emp['name'] if emp else '—'} · {doc['date']}")
    return {"ok": True}


# -------- Leave --------

@router.get("/leave/requests")
async def list_leave(status: str | None = None, employee_id: str | None = None,
                     current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if status: q["status"] = status
    if current.role in ("Employee", "Intern"):
        q["employee_id"] = current.id
    elif current.role == "Manager":
        q["employee_id"] = {"$in": await _dept_ids(db, current.department)}
    elif employee_id:
        q["employee_id"] = employee_id
    docs = await db.leave_requests.find(q).sort("created_at", -1).to_list(500)
    out = []
    for d in docs:
        emp = await db.users.find_one({"_id": ObjectId(d["employee_id"])}, {"name": 1, "photo": 1}) if d.get("employee_id") else None
        out.append({**serialize(d), "employee_name": emp["name"] if emp else None, "employee_photo": emp.get("photo") if emp else None})
    return out


@router.post("/leave/requests", status_code=201)
async def create_leave(payload: LeaveIn, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    doc = payload.model_dump()
    if current.role in ("Employee", "Intern") and doc["employee_id"] != current.id:
        raise HTTPException(403, "You can only request leave for yourself")
    if current.role == "Manager":
        tgt = await db.users.find_one({"_id": oid(doc["employee_id"])})
        if not tgt or tgt.get("department") != current.department:
            raise HTTPException(403, "Managers can only request leave for their department")
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    res = await db.leave_requests.insert_one(doc)
    doc["_id"] = res.inserted_id
        emp = await db.users.find_one({"_id": oid(doc["employee_id"])}, {"name": 1})
    await log_activity(db, current, "Leave requested", "Employees", target=f"{emp['name'] if emp else '—'} · {doc['from_date']} → {doc['to_date']}")

    approvers = await db.users.find(
        {"role": {"$in": ["Founder", "Admin", "Manager"]}},
        {"_id": 1},
    ).to_list(50)

    for a in approvers:
        await notify(
            db, str(a["_id"]), "Leave request",
            f"{emp['name'] if emp else 'Employee'} requested {doc['kind']} leave from {doc['from_date']} to {doc['to_date']}.",
            kind="warning", link="/employees",
        )
    return serialize(doc)


@router.patch("/leave/requests/{leave_id}")
async def update_leave(leave_id: str, payload: dict,
                       current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    status = payload.get("status")
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(400, "Invalid status")
    doc = await db.leave_requests.find_one({"_id": oid(leave_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    if current.role == "Manager":
        emp = await db.users.find_one({"_id": ObjectId(doc["employee_id"])}) if doc.get("employee_id") else None
        if not emp or emp.get("department") != current.department:
            raise HTTPException(403, "Managers can only action leave for their department")
    await db.leave_requests.update_one({"_id": oid(leave_id)}, {"$set": {"status": status, "updated_at": utc_iso()}})
    doc = await db.leave_requests.find_one({"_id": oid(leave_id)})
    emp = await db.users.find_one({"_id": ObjectId(doc["employee_id"])}, {"name": 1}) if doc.get("employee_id") else None
    await log_activity(db, current, f"Leave {status}", "Employees", target=emp["name"] if emp else None)
    if emp and doc.get("employee_id"):
        await notify(db, doc["employee_id"], f"Your leave was {status}",
                     f"{current.name} {status} your leave request {doc['from_date']} → {doc['to_date']}",
                     kind="success" if status == "approved" else "warning", link="/employees")
    return serialize(doc)


# -------- Performance --------

@router.get("/performance/reviews")
async def list_performance(employee_id: str | None = None,
                           current: UserPublic = Depends(get_current_user)):
    db = get_db()
    q = {}
    if current.role in ("Employee", "Intern"):
        q["employee_id"] = current.id
    elif current.role == "Manager":
        q["employee_id"] = {"$in": await _dept_ids(db, current.department)}
    elif employee_id:
        q["employee_id"] = employee_id
    docs = await db.performance_reviews.find(q).sort("created_at", -1).to_list(300)
    out = []
    for d in docs:
        emp = await db.users.find_one({"_id": ObjectId(d["employee_id"])}, {"name": 1, "designation": 1, "photo": 1}) if d.get("employee_id") else None
        out.append({**serialize(d), "employee_name": emp["name"] if emp else None,
                    "employee_designation": emp.get("designation") if emp else None,
                    "employee_photo": emp.get("photo") if emp else None})
    return out


@router.post("/performance/reviews", status_code=201)
async def create_performance(payload: PerformanceIn,
                             current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    doc = payload.model_dump()
    if current.role == "Manager":
        tgt = await db.users.find_one({"_id": oid(doc["employee_id"])})
        if not tgt or tgt.get("department") != current.department:
            raise HTTPException(403, "Managers can only review their department")
    doc["created_at"] = utc_iso()
    doc["reviewer_id"] = current.id
    doc["reviewer_name"] = current.name
    res = await db.performance_reviews.insert_one(doc)
    doc["_id"] = res.inserted_id
    emp = await db.users.find_one({"_id": oid(doc["employee_id"])}, {"name": 1})
    await log_activity(db, current, "Performance review recorded", "Employees",
                       target=f"{emp['name'] if emp else '—'} · {doc['period']}")
    if emp and doc.get("employee_id"):
        await notify(db, doc["employee_id"], "Performance review saved",
                     f"{current.name} saved your {doc['period']} review.", kind="info", link="/employees")
    return serialize(doc)


# -------- Overview stats --------

@router.get("/stats/overview")
async def employees_overview(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if current.role in ("Employee", "Intern"):
        my_leave = await db.leave_requests.count_documents({"employee_id": current.id, "status": "pending"})
        return {
            "total": 1,
            "online": 1 if current.online else 0,
            "by_role": [{"role": current.role, "count": 1}],
            "pending_leave": my_leave,
            "departments": 0,
        }
    total = await db.users.count_documents({})
    online = await db.users.count_documents({"online": True})
    by_role = {}
    async for u in db.users.find({}, {"role": 1}):
        by_role[u.get("role", "Employee")] = by_role.get(u.get("role", "Employee"), 0) + 1
    pending_leave = await db.leave_requests.count_documents({"status": "pending"})
    return {
        "total": total,
        "online": online,
        "by_role": [{"role": k, "count": v} for k, v in by_role.items()],
        "pending_leave": pending_leave,
        "departments": await db.departments.count_documents({}),
    }
