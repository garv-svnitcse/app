from __future__ import annotations
"""All Part 2 domain models. Kept lightweight — Pydantic BaseModel with optional fields
so routers can accept partial updates. Storage still uses raw dicts + hub_utils.serialize."""
from datetime import date, datetime, timezone
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from hub_utils import utc_iso


# ------------------------- Marketplace -------------------------

class CityIn(BaseModel):
    name: str
    state: str = "Bihar"
    status: Literal["active", "paused", "planned"] = "active"


class VendorIn(BaseModel):
    name: str
    contact_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    city: str
    kyc_status: Literal["pending", "approved", "rejected"] = "pending"
    active: bool = True
    rating: float = 4.5
    notes: Optional[str] = None


class VehicleIn(BaseModel):
    model: str
    kind: Literal["bike", "scooter", "ebike"] = "scooter"
    plate: str
    vendor_id: Optional[str] = None
    city: str
    hourly_rate: float = 40.0
    daily_rate: float = 399.0
    status: Literal["available", "booked", "maintenance", "retired"] = "available"


class CustomerIn(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    city: str
    kyc_status: Literal["pending", "approved", "rejected"] = "pending"


class BookingIn(BaseModel):
    customer_id: str
    vehicle_id: str
    city: str
    start_time: str
    end_time: str
    amount: float
    status: Literal["pending", "confirmed", "active", "completed", "cancelled"] = "pending"


class PricingIn(BaseModel):
    name: str
    city: str
    hourly: float = 40.0
    daily: float = 399.0
    weekly: float = 1999.0
    monthly: float = 6499.0
    active: bool = True


class CouponIn(BaseModel):
    code: str
    discount_pct: float = 10.0
    valid_from: Optional[str] = None
    valid_till: Optional[str] = None
    usage_limit: int = 100
    used_count: int = 0
    active: bool = True


class KycIn(BaseModel):
    subject_type: Literal["vendor", "customer"]
    subject_id: str
    subject_name: str
    doc_type: Literal["aadhaar", "pan", "dl", "gst", "cin", "other"] = "aadhaar"
    status: Literal["pending", "approved", "rejected"] = "pending"
    notes: Optional[str] = None


class SupportIn(BaseModel):
    subject: str
    description: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    status: Literal["open", "in_progress", "resolved", "closed"] = "open"


class ReviewIn(BaseModel):
    booking_id: Optional[str] = None
    customer_name: str
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    rating: float = 5.0
    comment: Optional[str] = None


# ------------------------- Tasks -------------------------

TaskStatus = Literal["todo", "in_progress", "review", "completed", "cancelled"]
TaskPriority = Literal["low", "medium", "high", "urgent"]


class SubtaskIn(BaseModel):
    title: str
    done: bool = False


class TaskCommentIn(BaseModel):
    body: str
    attachments: List[str] = Field(default_factory=list)
    attachment_name: Optional[str] = None


class TaskIn(BaseModel):
    title: str
    description: Optional[str] = ""
    status: TaskStatus = "todo"
    priority: TaskPriority = "medium"
    assignee_id: Optional[str] = None
    reporter_id: Optional[str] = None
    module: str = "General"
    due_date: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    subtasks: List[SubtaskIn] = Field(default_factory=list)
    attachments: List[str] = Field(default_factory=list)
    link: Optional[str] = None


class TaskStatusPatch(BaseModel):
    status: TaskStatus


# ------------------------- Employees -------------------------

EmployeeRole = Literal["Founder", "Admin", "Manager", "Employee", "Intern"]


def _iso_date(value: str) -> str:
    """Normalise a YYYY-MM-DD string; anything else is a validation error."""
    return date.fromisoformat((value or "").strip()).isoformat()


def _utc_iso_time(value: Optional[str]) -> Optional[str]:
    """Attendance times are stored as UTC ISO strings; the input must carry an offset."""
    if value is None or not str(value).strip():
        return None
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("must include a timezone offset")
    return dt.astimezone(timezone.utc).isoformat()


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    head_id: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Department name is required")
        return v


class EmployeeInviteIn(BaseModel):
    email: str
    name: str
    role: str = "Employee"
    designation: Optional[str] = None
    department: Optional[str] = None
    phone: Optional[str] = None


class EmployeeUpdateIn(BaseModel):
    """Editable profile fields. The router decides which of them the caller may change."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    photo: Optional[str] = None
    designation: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = Field(default=None, max_length=80)
    role: Optional[EmployeeRole] = None


class AttendanceIn(BaseModel):
    employee_id: str
    date: str  # YYYY-MM-DD, company-local (Asia/Kolkata)
    status: Literal["present", "absent", "leave", "half_day", "wfh"] = "present"
    check_in: Optional[str] = None
    check_out: Optional[str] = None

    check_date = field_validator("date")(_iso_date)
    check_times = field_validator("check_in", "check_out")(_utc_iso_time)


class LeaveIn(BaseModel):
    """New leave requests are always created as pending; approval goes through the PATCH route."""
    employee_id: Optional[str] = None  # defaults to the caller
    from_date: str
    to_date: str
    kind: Literal["casual", "sick", "earned", "unpaid"] = "casual"
    reason: str = Field(max_length=2000)

    check_dates = field_validator("from_date", "to_date")(_iso_date)

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A reason is required")
        return v

    @model_validator(mode="after")
    def _check_order(self):
        if self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        return self


class LeaveDecisionIn(BaseModel):
    status: Literal["approved", "rejected"]
    note: Optional[str] = Field(default=None, max_length=1000)


class PerformanceIn(BaseModel):
    employee_id: str
    period: str = Field(min_length=1, max_length=40)  # e.g. Q1-2026
    score: float = Field(default=4.0, ge=1, le=5)
    highlights: Optional[str] = None
    growth_areas: Optional[str] = None


# ------------------------- Opportunities -------------------------

OpportunityType = Literal[
    "Grant", "Investor", "Accelerator", "Incubator", "Competition",
    "Government Scheme", "Tender", "CSR", "Partnership", "Workshop", "Conference",
]

OpportunityStatus = Literal["open", "assigned", "in_progress", "won", "lost", "closed"]


class OpportunityIn(BaseModel):
    title: str
    type: OpportunityType
    description: Optional[str] = ""
    organisation: Optional[str] = None
    deadline: Optional[str] = None
    value_lakhs: Optional[float] = Field(default=None, ge=0)
    status: OpportunityStatus = "open"
    assignee_id: Optional[str] = None
    documents: List[str] = Field(default_factory=list)
    link: Optional[str] = None


class OpportunityAssign(BaseModel):
    assignee_id: str


class OpportunityStatusPatch(BaseModel):
    status: OpportunityStatus


# ------------------------- WavyGo Connect -------------------------

ChannelKind = Literal["channel", "dm", "group", "announcement"]


class ChannelIn(BaseModel):
    name: str
    kind: ChannelKind = "channel"
    description: Optional[str] = None
    members: List[str] = Field(default_factory=list)  # list of user_ids


class MessageIn(BaseModel):
    body: str
    attachments: List[str] = Field(default_factory=list)


# ------------------------- Calendar -------------------------

EventCategory = Literal["Meeting", "Product Launch", "Team Sync", "Workshop", "Milestone", "Reminder", "Other"]
EventVisibility = Literal["public", "department", "private"]
EventStatus = Literal["confirmed", "tentative", "cancelled"]
RsvpResponse = Literal["accepted", "tentative", "declined"]

MAX_EVENT_PARTICIPANTS = 200
MAX_REMINDER_MINUTES = 7 * 24 * 60


def _require_tz(value: Optional[datetime]) -> Optional[datetime]:
    """Calendar times must carry an explicit UTC offset — a naive time is ambiguous."""
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("must include a timezone offset, e.g. 2026-09-28T10:00:00+05:30")
    return value


def _dedupe_ids(values: Optional[List[str]]) -> Optional[List[str]]:
    if values is None:
        return None
    ids = list(dict.fromkeys(v.strip() for v in values if v and v.strip()))
    if len(ids) > MAX_EVENT_PARTICIPANTS:
        raise ValueError(f"at most {MAX_EVENT_PARTICIPANTS} participants allowed")
    return ids


class CalendarEventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default="", max_length=5000)
    start_time: datetime
    end_time: datetime
    all_day: bool = False
    category: EventCategory = "Meeting"
    location: Optional[str] = Field(default=None, max_length=300)
    meeting_link: Optional[str] = Field(default=None, max_length=500)
    participant_ids: List[str] = Field(default_factory=list)
    visibility: EventVisibility = "public"
    department: Optional[str] = None
    status: EventStatus = "confirmed"
    # Minutes before start_time to notify organiser and participants; None = no reminder.
    reminder_minutes: Optional[int] = Field(default=15, ge=0, le=MAX_REMINDER_MINUTES)

    check_tz = field_validator("start_time", "end_time")(_require_tz)
    check_participant_ids = field_validator("participant_ids")(_dedupe_ids)

    @model_validator(mode="after")
    def _check_order(self):
        if self.end_time < self.start_time:
            raise ValueError("end_time must not be before start_time")
        return self


class CalendarEventPatch(BaseModel):
    """Partial update. Cross-field checks (time order) run in the router after merging."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    all_day: Optional[bool] = None
    category: Optional[EventCategory] = None
    location: Optional[str] = Field(default=None, max_length=300)
    meeting_link: Optional[str] = Field(default=None, max_length=500)
    participant_ids: Optional[List[str]] = None
    visibility: Optional[EventVisibility] = None
    department: Optional[str] = None
    status: Optional[EventStatus] = None
    reminder_minutes: Optional[int] = Field(default=None, ge=0, le=MAX_REMINDER_MINUTES)

    check_tz = field_validator("start_time", "end_time")(_require_tz)
    check_participant_ids = field_validator("participant_ids")(_dedupe_ids)


class CalendarRsvpIn(BaseModel):
    response: RsvpResponse


class SubmittedDetailsIn(BaseModel):
    phone: Optional[str] = None
    personal_email: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    college: Optional[str] = None
    degree: Optional[str] = None

    resume_url: Optional[str] = None
    id_proof_url: Optional[str] = None
    other_documents: List[dict] = Field(default_factory=list)

    bank_account_last4: Optional[str] = None


class CompanyDetailsIn(BaseModel):
    employee_code: Optional[str] = None
    reporting_manager: Optional[str] = None
    joining_date: Optional[str] = None
    employment_type: Optional[str] = None
    stipend_or_salary: Optional[float] = None

    offer_letter_url: Optional[str] = None
    employment_agreement_url: Optional[str] = None
    other_documents: List[dict] = Field(default_factory=list)

    nda_signed: Optional[bool] = False
    assigned_assets: Optional[str] = None