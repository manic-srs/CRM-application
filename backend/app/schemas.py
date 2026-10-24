"""What each API accepts (request body) and returns (response).

Field names match the PostgreSQL tables in database/schema.sql.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

LeadSource = Literal["Website", "Referral", "Phone", "Email", "Event", "Social Media", "Other"]
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

class LeadCreate(BaseModel):
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


class LeadUpdate(BaseModel):
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


class LeadDetail(LeadOut):
    """Everything the lead record page needs in one call."""

    tasks: list[TaskOut] = []
    notes: list[NoteOut] = []
    history: list[StageHistoryOut] = []


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
    owner_id: int
    owner_name: str | None = None
    created_at: datetime | None


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
    account_id: int
    account_name: str | None = None
    owner_id: int
    created_at: datetime | None


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


class SearchResult(BaseModel):
    type: str
    id: int
    name: str
    detail: str | None
