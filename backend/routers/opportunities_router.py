from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from bson import ObjectId
from db import get_db
from auth_utils import get_current_user, require_roles
from models import UserPublic
from models_part2 import OpportunityIn, OpportunityAssign, OpportunityStatusPatch
from hub_utils import serialize, serialize_many, oid, utc_iso, log_activity, notify
from email_utils import notify_assignment_by_email

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


async def _dept_ids(db, department):
    if not department:
        return []
    return [str(u["_id"]) async for u in db.users.find({"department": department}, {"_id": 1})]


async def _enrich(db, doc):
    if doc.get("assignee_id"):
        try:
            u = await db.users.find_one({"_id": ObjectId(doc["assignee_id"])}, {"name": 1, "photo": 1, "role": 1})
            if u:
                doc["assignee_name"] = u["name"]
                doc["assignee_photo"] = u.get("photo")
        except Exception:
            pass
    return doc


@router.get("")
async def list_opps(status: str | None = None, type: str | None = None,
                    assignee_id: str | None = None,
                    limit: int = Query(200, ge=1, le=500),
                    current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if current.role == "Intern":
        raise HTTPException(403, "Interns do not have access to opportunities")
    q = {}
    if status: q["status"] = status
    if type: q["type"] = type
    if assignee_id: q["assignee_id"] = assignee_id

    role_filter = None
    if current.role == "Manager":
        ids = await _dept_ids(db, current.department)
        role_filter = {"$or": [{"assignee_id": {"$in": ids}}, {"assignee_id": None},
                               {"assignee_id": {"$exists": False}}]}
    elif current.role == "Employee":
        role_filter = {"assignee_id": current.id}

    if role_filter:
        q = {"$and": [q, role_filter]} if q else role_filter

    docs = await db.opportunities.find(q).sort("deadline", 1).to_list(limit)
    for d in docs:
        await _enrich(db, d)
    return serialize_many(docs)


@router.post("", status_code=201)
async def create_opp(payload: OpportunityIn,
                     background_tasks: BackgroundTasks,
                     current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    doc = payload.model_dump()
    doc["created_at"] = utc_iso()
    doc["updated_at"] = utc_iso()
    doc["created_by"] = current.id
    res = await db.opportunities.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _enrich(db, doc)
    await log_activity(db, current, "Logged opportunity", "Opportunity Hub", target=doc["title"])
    if doc.get("assignee_id") and doc["assignee_id"] != current.id:
        await notify(db, doc["assignee_id"], "Opportunity assigned",
                     f"{current.name} assigned you: {doc['title']}", kind="info", link="/opportunity-hub")
    if doc.get("assignee_id"):
        await notify_assignment_by_email(
            db=db,
            assignee_id=doc["assignee_id"],
            item_type="opportunity",
            item_title=doc.get("title", "Untitled Opportunity"),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("type"),
            deadline=doc.get("deadline"),
            item_id=str(doc["_id"]),
            background_tasks=background_tasks,
        )
    return serialize(doc)


@router.get("/stats/overview")
async def opp_stats(current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if current.role == "Intern":
        raise HTTPException(403, "Interns do not have access to opportunities")
    q = {}
    if current.role == "Manager":
        ids = await _dept_ids(db, current.department)
        q = {"$or": [{"assignee_id": {"$in": ids}}, {"assignee_id": None}, {"assignee_id": {"$exists": False}}]}
    elif current.role == "Employee":
        q = {"assignee_id": current.id}

    async def c(status_val):
        query = {"$and": [q, {"status": status_val}]} if q else {"status": status_val}
        return await db.opportunities.count_documents(query)

    mine_query = {"assignee_id": current.id, "status": {"$nin": ["won", "lost", "closed"]}}

    active_q = {"$and": [q, {"status": {"$in": ["open", "assigned", "in_progress"]}}]} if q else {"status": {"$in": ["open", "assigned", "in_progress"]}}
    pipeline_cursor = db.opportunities.find(active_q, {"value_lakhs": 1})
    pipeline_lakhs = sum([doc.get("value_lakhs", 0) or 0 async for doc in pipeline_cursor])

    won_q = {"$and": [q, {"status": "won"}]} if q else {"status": "won"}
    won_cursor = db.opportunities.find(won_q, {"value_lakhs": 1})
    won_lakhs = sum([doc.get("value_lakhs", 0) or 0 async for doc in won_cursor])

    return {
        "open":        await c("open"),
        "assigned":    await c("assigned"),
        "in_progress": await c("in_progress"),
        "won":         await c("won"),
        "lost":        await c("lost"),
        "mine":        await db.opportunities.count_documents(mine_query),
        "pipeline_lakhs": round(pipeline_lakhs, 2),
        "won_lakhs": round(won_lakhs, 2),
    }


@router.get("/{opp_id}")
async def get_opp(opp_id: str, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if current.role == "Intern":
        raise HTTPException(403, "Interns do not have access to opportunities")
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    await _enrich(db, doc)
    return serialize(doc)


@router.patch("/{opp_id}")
async def update_opp(opp_id: str, payload: dict,
                     background_tasks: BackgroundTasks,
                     current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if current.role == "Intern":
        raise HTTPException(403, "Interns do not have access to opportunities")
    existing = await db.opportunities.find_one({"_id": oid(opp_id)})
    if not existing:
        raise HTTPException(404, "Not found")
    if current.role == "Employee":
        if existing.get("assignee_id") != current.id:
            raise HTTPException(403, "You can only edit opportunities assigned to you")
        payload = {k: v for k, v in payload.items() if k in ("status", "notes", "documents")}
        if not payload:
            raise HTTPException(403, "You can only edit status, notes or documents")
    elif current.role == "Manager":
        ids = await _dept_ids(db, current.department)
        if existing.get("assignee_id") and existing["assignee_id"] not in ids:
            raise HTTPException(403, "Managers can only edit opportunities in their department")
    payload.pop("id", None); payload.pop("_id", None); payload.pop("created_at", None)
    payload["updated_at"] = utc_iso()
    res = await db.opportunities.update_one({"_id": oid(opp_id)}, {"$set": payload})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    await _enrich(db, doc)
    if "assignee_id" in payload and payload["assignee_id"] and payload["assignee_id"] != existing.get("assignee_id"):
        await notify_assignment_by_email(
            db=db,
            assignee_id=payload["assignee_id"],
            item_type="opportunity",
            item_title=doc.get("title", existing.get("title", "Untitled Opportunity")),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("type", existing.get("type")),
            deadline=doc.get("deadline", existing.get("deadline")),
            item_id=opp_id,
            background_tasks=background_tasks,
        )
    await log_activity(db, current, "Updated opportunity", "Opportunity Hub", target=doc["title"])
    return serialize(doc)


@router.post("/{opp_id}/assign")
async def assign_opp(opp_id: str, payload: OpportunityAssign,
                     background_tasks: BackgroundTasks,
                     current: UserPublic = Depends(require_roles("Founder", "Admin", "Manager"))):
    db = get_db()
    await db.opportunities.update_one({"_id": oid(opp_id)}, {"$set": {"assignee_id": payload.assignee_id, "status": "assigned", "updated_at": utc_iso()}})
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    await _enrich(db, doc)
    await log_activity(db, current, "Assigned opportunity", "Opportunity Hub",
                       target=f"{doc['title']} → {doc.get('assignee_name')}")
    if payload.assignee_id != current.id:
        await notify(db, payload.assignee_id, "Opportunity assigned",
                     f"{current.name} assigned you: {doc['title']}", kind="info", link="/opportunity-hub")
    if payload.assignee_id:
        await notify_assignment_by_email(
            db=db,
            assignee_id=payload.assignee_id,
            item_type="opportunity",
            item_title=doc.get("title", "Untitled Opportunity"),
            assigned_by_name=current.name,
            assigned_by_role=current.role,
            priority=doc.get("type"),
            deadline=doc.get("deadline"),
            item_id=opp_id,
            background_tasks=background_tasks,
        )
    return serialize(doc)


@router.patch("/{opp_id}/status")
async def update_opp_status(opp_id: str, payload: OpportunityStatusPatch, current: UserPublic = Depends(get_current_user)):
    db = get_db()
    if current.role == "Intern":
        raise HTTPException(403, "Interns do not have access to opportunities")
    existing = await db.opportunities.find_one({"_id": oid(opp_id)})
    if not existing:
        raise HTTPException(404, "Not found")
    if current.role == "Employee" and existing.get("assignee_id") != current.id:
        raise HTTPException(403, "You can only update opportunities assigned to you")
    await db.opportunities.update_one({"_id": oid(opp_id)}, {"$set": {"status": payload.status, "updated_at": utc_iso()}})
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    await _enrich(db, doc)
    await log_activity(db, current, f"Opportunity → {payload.status}", "Opportunity Hub", target=doc["title"])
    return serialize(doc)


@router.delete("/{opp_id}")
async def delete_opp(opp_id: str, current: UserPublic = Depends(require_roles("Founder"))):
    db = get_db()
    doc = await db.opportunities.find_one({"_id": oid(opp_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    await db.opportunities.delete_one({"_id": oid(opp_id)})
    await log_activity(db, current, "Deleted opportunity", "Opportunity Hub", target=doc["title"])
    return {"ok": True}
