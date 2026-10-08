from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth_utils import get_current_user
from db import get_db, utc_now
from hub_utils import log_activity
from models import UserPublic
from permissions import can

router = APIRouter(prefix="/settings", tags=["settings"])

# Defaults used until the Founder edits the profile; edits are stored in
# the `settings` collection as {_id: "company", ...fields}.
COMPANY_DEFAULTS = {
    "name": "WAVYGO MOBILITY SERVICES PRIVATE LIMITED",
    "brand": "WavyGo OS",
    "cin": "U77100BR2025PTC077095",
    "industry": "Travel-Tech · Mobility · Vehicle Rental",
    "country": "India",
    "founded": "2025",
    "hq": "Patna, Bihar, India",
}


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    brand: Optional[str] = Field(None, min_length=1, max_length=100)
    cin: Optional[str] = Field(None, min_length=1, max_length=50)
    industry: Optional[str] = Field(None, min_length=1, max_length=200)
    country: Optional[str] = Field(None, min_length=1, max_length=100)
    founded: Optional[str] = Field(None, min_length=4, max_length=20)
    hq: Optional[str] = Field(None, min_length=1, max_length=200)

    model_config = {"extra": "forbid", "str_strip_whitespace": True}


async def _company(db) -> dict:
    stored = await db.settings.find_one({"_id": "company"}) or {}
    return {k: stored.get(k) or v for k, v in COMPANY_DEFAULTS.items()}


@router.get("/company")
async def company_info(_: UserPublic = Depends(get_current_user)):
    return await _company(get_db())


@router.patch("/company")
async def update_company(payload: CompanyUpdate, current: UserPublic = Depends(get_current_user)):
    if not can(current.role, "settings.company_edit"):
        raise HTTPException(status_code=403, detail="Only the Founder can edit company details")
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No changes provided")
    db = get_db()
    await db.settings.update_one(
        {"_id": "company"},
        {"$set": {**updates, "updated_at": utc_now().isoformat(), "updated_by": current.id}},
        upsert=True,
    )
    await log_activity(db, current, "Updated company profile", "Settings", target="Company",
                       meta={"fields": sorted(updates)})
    return await _company(db)


@router.get("/roles")
async def roles(_: UserPublic = Depends(get_current_user)):
    # Keep in sync with backend/permissions.py
    return {
        "roles": [
            {"name": "Founder", "level": 100, "description": "Full access to every module, including Marketplace, Company Vault and Finance. Only role that can edit company details or create Admins."},
            {"name": "Admin", "level": 80, "description": "Invite and manage users, reset passwords, oversee tasks, opportunities, CRM, marketing, analytics and all activity logs."},
            {"name": "Manager", "level": 60, "description": "Assign tasks and opportunities, edit employee records, approve leave and run CRM, marketing and analytics; sees team activity."},
            {"name": "Employee", "level": 40, "description": "Create and work on own tasks, update assigned opportunities, schedule calendar events, mark attendance and request leave."},
            {"name": "Intern", "level": 20, "description": "Work on assigned tasks and comment, view the calendar, mark attendance and request leave."},
        ]
    }
