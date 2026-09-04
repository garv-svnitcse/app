from __future__ import annotations
"""Pydantic models for WavyGo OS core collections."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

from db import BaseDocument, utc_now


Role = Literal["Founder", "Admin", "Manager", "Employee", "Intern"]


class User(BaseDocument):

    email: EmailStr

    name: str

    role: Role

    password_hash: str

    photo: Optional[str] = None

    online: bool = False

    phone: Optional[str] = None

    designation: Optional[str] = None

    department: Optional[str] = None

    status: str = "active"

    is_active: bool = True

    created_at: datetime = Field(default_factory=utc_now)

    updated_at: datetime = Field(default_factory=utc_now)


class UserPublic(BaseModel):

    id: str

    email: EmailStr

    name: str

    role: Role

    photo: Optional[str] = None

    online: bool = False

    phone: Optional[str] = None

    designation: Optional[str] = None

    department: Optional[str] = None

    status: Optional[str] = "active"

    is_active: Optional[bool] = True


class LoginRequest(BaseModel):

    email: EmailStr

    password: str

    remember: bool = False


class RegisterRequest(BaseModel):

    email: EmailStr

    password: str

    name: str

    role: Role = "Employee"


class TokenResponse(BaseModel):

    access_token: str

    refresh_token: str

    token_type: str = "bearer"

    user: UserPublic


class RefreshRequest(BaseModel):

    refresh_token: str


class UpdateProfileRequest(BaseModel):

    name: Optional[str] = None

    photo: Optional[str] = None

    phone: Optional[str] = None

    designation: Optional[str] = None

    department: Optional[str] = None


# Used when a Founder/Admin edits another employee's profile
class EmployeeAdminUpdateRequest(BaseModel):

    name: Optional[str] = None

    email: Optional[EmailStr] = None

    role: Optional[Role] = None

    phone: Optional[str] = None

    designation: Optional[str] = None

    department: Optional[str] = None

    photo: Optional[str] = None


class ChangePasswordRequest(BaseModel):

    current_password: str

    new_password: str


class Notification(BaseDocument):

    user_id: Optional[str] = None  # None = broadcast

    title: str

    body: str

    kind: Literal["info", "success", "warning", "error"] = "info"

    read: bool = False

    link: Optional[str] = None

    created_at: datetime = Field(default_factory=utc_now)


class ActivityLog(BaseDocument):

    user_id: str

    user_name: str

    user_role: Role

    action: str

    module: str

    target: Optional[str] = None

    meta: Optional[dict] = None

    created_at: datetime = Field(default_factory=utc_now)


class Session(BaseDocument):

    user_id: str

    refresh_token_id: str

    user_agent: Optional[str] = None

    ip: Optional[str] = None

    created_at: datetime = Field(default_factory=utc_now)

    last_used_at: datetime = Field(default_factory=utc_now)

    revoked: bool = False