"""What each API accepts (request body) and returns (response).

Field names match the PostgreSQL tables in database/schema.sql.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import re
from urllib.parse import quote, unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

LeadSource = Literal["Website", "Referral", "Phone", "Email", "Event", "Social Media", "Other", "Upload"]
LostReason = Literal["Price", "Competitor", "No response", "No budget", "Not interested", "Other"]
Priority = Literal["Low", "Normal", "High"]
Salutation = Literal["Mr.", "Ms.", "Mrs.", "Dr.", "Prof."]
UserRole = Literal["Salesperson", "Manager", "Admin"]


class Out(BaseModel):
    """Base for responses: reads ORM objects and sends money as numbers (not strings)."""

    model_config = ConfigDict(from_attributes=True)


def money(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


# ---------- Users and login ----------

class UserOut(Out):
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    email_stage_updates: bool = False
    email_assignments: bool = True
    email_reminders: bool = True
    team_access: bool = False
    created_at: datetime | None = None
    role_changed_at: datetime | None = None
    access_changed_at: datetime | None = None
    permissions: list[str] = []  # filled for the logged-in user (login, /auth/me)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    """Admin adds a user (there is no public sign up)."""
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = "Salesperson"


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=100)
    email: str | None = Field(None, max_length=255)  # the login username
    role: UserRole | None = None
    is_active: bool | None = None


class ProfileUpdate(BaseModel):
    """What a user can change on their own profile (email and role are changed by the Admin).
    Send only what changes."""
    full_name: str | None = Field(None, min_length=2, max_length=100)
    email_stage_updates: bool | None = None  # email me when my leads / deals move to the next stage
    email_assignments: bool | None = None    # email me when something is assigned to me
    email_reminders: bool | None = None      # email me reminders (tasks, demos, close dates, overdue)


class TeamAccess(BaseModel):
    team_access: bool


class PermissionChange(BaseModel):
    role: UserRole
    permission: str
    allowed: bool


class PasswordReset(BaseModel):
    """Admin sets a new password for a user."""
    password: str = Field(..., min_length=8, max_length=128)


class PasswordChange(BaseModel):
    """A user changes their own password."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class TransferRecords(BaseModel):
    """Move everything a user owns to another user (e.g. when someone leaves)."""
    to_user_id: int
    deactivate: bool = False


class TestEmail(BaseModel):
    to: str = Field(..., min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginResponse(BaseModel):
    message: str
    user: UserOut
    token: str  # send as "Authorization: Bearer <token>" on every request


# ---------- History, tasks, notes (shown on record pages) ----------

class StageHistoryOut(Out):
    id: int
    from_stage: str | None
    to_stage: str
    note: str | None
    changed_at: datetime | None
    changed_by_id: int
    changed_by_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None


class TaskOut(Out):
    id: int
    title: str
    description: str | None
    due_date: datetime
    reminder_at: datetime | None
    status: str
    priority: str
    is_auto: bool
    completed_at: datetime | None
    owner_id: int
    owner_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None
    related_type: str | None = None
    related_to: str | None = None
    is_overdue: bool = False
    created_at: datetime | None


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime
    reminder_at: datetime | None = None
    priority: Priority = "Normal"
    owner_id: int | None = None  # default: owner of the lead/opportunity, else the first user
    lead_id: int | None = None
    opportunity_id: int | None = None
    created_by_id: int | None = None  # logged-in user; the owner is notified when someone else assigns it


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime | None = None
    reminder_at: datetime | None = None
    priority: Priority | None = None
    owner_id: int | None = None
    changed_by_id: int | None = None  # logged-in user (not saved; used for the assignment notification)


class NoteOut(Out):
    id: int
    body: str
    created_by_id: int
    created_by_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None
    created_at: datetime | None


class NoteCreate(BaseModel):
    body: str = Field(..., min_length=1)
    created_by_id: int | None = None
    lead_id: int | None = None
    opportunity_id: int | None = None


# ---------- Leads ----------

def clean_url(value: str | None, *, linkedin: bool = False) -> str | None:
    """'linkedin.com/in/x' -> 'https://linkedin.com/in/x'. Empty -> None. LinkedIn fields must point to linkedin.com."""
    value = (value or "").strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = re.sub(r"^https?://", "", value, flags=re.I).split("/")[0].lower()
    if "." not in host or " " in value:
        raise ValueError("Enter a valid web address")
    if linkedin and not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        raise ValueError("Enter a LinkedIn address (linkedin.com/...)")
    return value


PROFILE_HOST = re.compile(r"(?:www\.|[a-z]{2}\.)?linkedin\.com")  # also country sites such as uk.linkedin.com
PROFILE_NAME = re.compile(r"[\w-]{3,100}")  # letters (any language), digits, - and _


def linkedin_profile_url(value: str | None) -> str:
    """A person's LinkedIn profile (linkedin.com/in/<name>) in one form: https://linkedin.com/in/<name>.
    Raises ValueError for anything else: company or school pages, sites that only look like LinkedIn, other schemes,
    a login or port in the address, short links (lnkd.in) and extra path parts. Query and #fragment are dropped."""
    raw = (value or "").strip()
    if not raw or len(raw) > 300 or any(ch.isspace() for ch in raw):
        raise ValueError("Enter a LinkedIn profile address like https://www.linkedin.com/in/name")
    if "://" not in raw:
        if raw.startswith("/") or ":" in raw.split("/")[0]:
            raise ValueError("Enter a LinkedIn profile address like https://www.linkedin.com/in/name")
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Only https:// LinkedIn profile addresses can be used")
    try:
        port = parts.port
    except ValueError:
        port = -1
    host = (parts.hostname or "").lower()
    if "@" in parts.netloc or port is not None or not PROFILE_HOST.fullmatch(host):
        raise ValueError("This isn't a linkedin.com profile address")
    match = re.fullmatch(r"/in/([^/]+)/?", parts.path)
    if not match:
        raise ValueError("Use a person's profile address (linkedin.com/in/...), not a company, school or other page")
    name = unquote(match.group(1))
    if not PROFILE_NAME.fullmatch(name):
        raise ValueError("This LinkedIn profile address isn't valid")
    return f"https://linkedin.com/in/{quote(name.lower(), safe='-_')}"


class LeadLinks(BaseModel):
    """Research links and company size on a lead (New Lead / Edit Lead / import)."""

    linkedin_url: str | None = Field(None, max_length=300)
    company_website: str | None = Field(None, max_length=255)
    company_linkedin_url: str | None = Field(None, max_length=300)
    annual_revenue: Decimal | None = Field(None, ge=0, le=Decimal("99999999999999"))  # turnover, USD
    employees: int | None = Field(None, ge=0, le=10_000_000)  # headcount
    location: str | None = Field(None, max_length=200)

    @field_validator("linkedin_url", "company_linkedin_url")
    @classmethod
    def _linkedin(cls, v):
        return clean_url(v, linkedin=True)

    @field_validator("company_website")
    @classmethod
    def _website(cls, v):
        return clean_url(v)

    @field_validator("location")
    @classmethod
    def _location(cls, v):
        return " ".join(v.split()) or None if v else None


class LeadCreate(LeadLinks):
    """Like the Salesforce "New Lead" form: Last Name and Company are required."""

    salutation: Salutation | None = None
    first_name: str | None = Field(None, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    company: str = Field(..., min_length=1, max_length=200)
    title: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=30)
    source: LeadSource = "Other"
    owner_id: int | None = None  # default: the logged-in user
    created_by_id: int | None = None  # ignored: the logged-in user creates it
    welcome_email: bool = True  # email the lead (no-reply) that their details were received; needs an email
    confirm_duplicate: bool = False  # the email already exists on a closed lead / contact: create a new lead anyway

    @field_validator("linkedin_url")
    @classmethod
    def _profile(cls, v):
        """A person's profile address is saved in one form (other LinkedIn links stay as typed)."""
        try:
            return linkedin_profile_url(v) if v else v
        except ValueError:
            return v


class LeadUpdate(LeadLinks):
    """Send only the fields to change. Stage changes use /stage, /lost and /convert."""

    salutation: Salutation | None = None
    first_name: str | None = Field(None, max_length=50)
    last_name: str | None = Field(None, min_length=1, max_length=50)
    company: str | None = Field(None, min_length=1, max_length=200)
    title: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=30)
    source: LeadSource | None = None
    demo_date: datetime | None = None
    owner_id: int | None = None
    changed_by_id: int | None = None  # logged-in user (not saved; used for the assignment notification)


class LeadOut(Out):
    id: int
    salutation: str | None
    first_name: str | None
    last_name: str
    name: str  # first + last name, filled automatically
    company: str | None
    title: str | None
    industry: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None = None
    company_website: str | None = None
    company_linkedin_url: str | None = None
    annual_revenue: Decimal | None = None
    employees: int | None = None
    location: str | None = None
    untouched: bool = False  # uploaded and not worked on yet
    uploaded_from: str | None = None  # file name when the lead came from a bulk upload
    source: str
    stage: str
    demo_date: datetime | None
    lost_reason: str | None
    lost_notes: str | None
    converted_at: datetime | None
    closed_at: datetime | None
    owner_id: int
    owner_name: str | None = None
    opportunity_id: int | None = None
    created_at: datetime | None
    updated_at: datetime | None
    last_transferred_at: datetime | None = None  # when the lead last got a new owner (shown in the list)

    @field_serializer("annual_revenue")
    def _revenue(self, value):
        return money(value)


class LeadTransferOut(Out):
    id: int
    from_user_id: int | None
    from_user_name: str | None = None
    to_user_id: int
    to_user_name: str | None = None
    transferred_by_id: int
    transferred_by_name: str | None = None
    note: str | None
    transferred_at: datetime | None


class LeadDetail(LeadOut):
    """Everything the lead record page needs in one call."""

    tasks: list[TaskOut] = []
    notes: list[NoteOut] = []
    history: list[StageHistoryOut] = []
    transfers: list[LeadTransferOut] = []


class LeadTransfer(BaseModel):
    """Give the lead to another user. Only the owner changes: details and stage stay as they are."""
    to_user_id: int
    note: str | None = Field(None, max_length=300)


class CancelDemo(BaseModel):
    """reschedule_to set: the demo moves to that date and the lead stays at Demo.
    Not set: the demo is cancelled and the lead goes back to Nurturing."""
    reason: str | None = Field(None, max_length=300)
    reschedule_to: datetime | None = None


class LeadStageChange(BaseModel):
    stage: Literal["New", "Nurturing", "Demo"]
    demo_date: datetime | None = None  # used when moving to Demo: the demo task is due then
    note: str | None = None
    changed_by_id: int | None = None  # default: the lead owner
    completed_stages: list[str] = []  # stages skipped on the way, confirmed as already done by the salesperson
    completed_note: str | None = Field(None, max_length=500)  # e.g. "Demo was done on a call"


class MarkLost(BaseModel):
    lost_reason: LostReason
    lost_notes: str | None = None  # internal: never sent to the customer
    changed_by_id: int | None = None
    notify_customer: bool = True  # polite no-reply email to the customer (no reason or notes)


class ConvertLead(BaseModel):
    """All optional. account_id = attach to an existing account instead of creating one."""

    opportunity_name: str | None = Field(None, max_length=200)
    expected_value: float | None = Field(None, ge=0)
    expected_close_date: date | None = None
    account_id: int | None = None
    changed_by_id: int | None = None
    completed_stages: list[str] = []  # stages skipped on the way, confirmed as already done by the salesperson
    completed_note: str | None = Field(None, max_length=500)  # e.g. "Demo was done on a call"


# ---------- Accounts and contacts ----------

class AccountOut(Out):
    id: int
    name: str
    industry: str | None
    phone: str | None
    website: str | None
    address: str | None
    linkedin_url: str | None = None
    annual_revenue: Decimal | None = None
    employees: int | None = None
    owner_id: int
    owner_name: str | None = None
    created_at: datetime | None

    @field_serializer("annual_revenue")
    def _revenue(self, value):
        return money(value)


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    industry: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=30)
    website: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)
    owner_id: int | None = None


class ContactOut(Out):
    id: int
    salutation: str | None
    first_name: str | None
    last_name: str
    full_name: str  # first + last name, filled automatically
    job_title: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None = None
    account_id: int
    account_name: str | None = None
    owner_id: int
    created_at: datetime | None
    updated_at: datetime | None = None


class ContactCreate(BaseModel):
    salutation: Salutation | None = None
    first_name: str | None = Field(None, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    job_title: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=30)
    account_id: int
    owner_id: int | None = None


# ---------- Opportunities ----------

class OpportunityOut(Out):
    id: int
    name: str
    stage: str
    expected_value: float | None
    final_value: float | None
    expected_close_date: date | None
    probability: int
    lost_reason: str | None
    lost_notes: str | None
    closed_at: datetime | None
    account_id: int
    account_name: str | None = None
    primary_contact_id: int | None
    primary_contact_name: str | None = None
    lead_id: int | None
    owner_id: int
    owner_name: str | None = None
    created_at: datetime | None
    updated_at: datetime | None

    @field_serializer("expected_value", "final_value")
    def _money(self, value):
        return money(value)


class AccountDetail(AccountOut):
    contacts: list[ContactOut] = []
    opportunities: list[OpportunityOut] = []


class OpportunityDetail(OpportunityOut):
    tasks: list[TaskOut] = []
    notes: list[NoteOut] = []
    history: list[StageHistoryOut] = []


class OpportunityUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    expected_value: float | None = Field(None, ge=0)
    expected_close_date: date | None = None
    probability: int | None = Field(None, ge=0, le=100)  # set automatically by stage; can be adjusted
    primary_contact_id: int | None = None
    owner_id: int | None = None
    changed_by_id: int | None = None  # logged-in user (not saved; used for the assignment notification)


class OpportunityStageChange(BaseModel):
    stage: Literal["Opportunity", "Proposal"]
    note: str | None = None
    changed_by_id: int | None = None


class MarkWon(BaseModel):
    final_value: float | None = Field(None, ge=0)  # default: the expected value
    note: str | None = None
    changed_by_id: int | None = None
    notify_customer: bool = True  # thank-you no-reply email to the deal's contact
    completed_stages: list[str] = []  # stages skipped on the way, confirmed as already done by the salesperson
    completed_note: str | None = Field(None, max_length=500)  # e.g. "Demo was done on a call"


class ConvertResult(BaseModel):
    lead: LeadOut
    account: AccountOut
    contact: ContactOut
    opportunity: OpportunityOut
    tasks_auto_closed: int
    new_task: TaskOut | None


# ---------- Notifications and search ----------

class NotificationOut(Out):
    id: int
    user_id: int
    task_id: int | None
    title: str
    message: str | None
    link: str | None = None
    kind: str = "update"  # "update" (vanishes once seen) or "reminder" (stays until the task is done)
    is_read: bool
    created_at: datetime | None


# ---------- Emails ----------

class AttachmentOut(Out):
    id: int
    filename: str
    content_type: str
    size_bytes: int


class EmailOut(Out):
    id: int
    subject: str
    body: str
    to_address: str
    cc_address: str | None
    status: str
    error: str | None
    sent_by_id: int
    sent_by_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None
    contact_id: int | None
    account_id: int | None
    sent_at: datetime | None
    attachments: list[AttachmentOut] = []


class OpportunityAttachmentOut(Out):
    """A file on an opportunity (never the bytes: those come from the download only)."""
    id: int
    opportunity_id: int
    filename: str
    content_type: str  # detected from the file content by the server
    size_bytes: int
    stage: str  # stage of the deal when the file was uploaded
    uploaded_by_id: int
    uploaded_by_name: str | None = None
    uploaded_at: datetime | None


class SearchResult(BaseModel):
    type: str
    id: int
    name: str
    detail: str | None
