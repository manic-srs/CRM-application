"""Python classes that map to the PostgreSQL tables in database/schema.sql.
The tables are created by the SQL script; these classes only read/write them.
(server_default=func.now() mirrors DEFAULT CURRENT_TIMESTAMP in the SQL, so tests on SQLite behave the same.)"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Computed, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="Salesperson")
    is_active: Mapped[bool] = mapped_column(default=True)
    # Which notifications also come by email (the bell always shows everything). Changed in My Profile.
    email_stage_updates: Mapped[bool] = mapped_column(default=False)   # lead / deal moved to the next stage
    email_assignments: Mapped[bool] = mapped_column(default=True)      # a record was assigned to me
    email_reminders: Mapped[bool] = mapped_column(default=True)        # task, demo, close-date, overdue reminders
    team_access: Mapped[bool] = mapped_column(default=False)           # a Manager let this user see the team's records
    role_changed_at: Mapped[datetime | None]    # last time the Admin changed the role
    access_changed_at: Mapped[datetime | None]  # last activate / deactivate / team access change
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())


class ActivityLog(Base):
    """Admin activity log: who changed users, permissions and record owners, and when."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    actor: Mapped[User | None] = relationship()


class RolePermission(Base):
    """What the Admin changed on the Roles & Permissions page (the defaults live in app/security.py)."""

    __tablename__ = "role_permissions"

    role: Mapped[str] = mapped_column(String(20), primary_key=True)
    permission: Mapped[str] = mapped_column(String(40), primary_key=True)
    allowed: Mapped[bool]
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    updated_by: Mapped[User | None] = relationship()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(30))
    website: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship()
    contacts: Mapped[list["Contact"]] = relationship(back_populates="account")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    salutation: Mapped[str | None] = mapped_column(String(10))
    first_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    # filled automatically by the database from first + last name
    full_name: Mapped[str] = mapped_column(String(101), Computed("TRIM(COALESCE(first_name || ' ', '') || last_name)", persisted=True))
    job_title: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    account: Mapped[Account] = relationship(back_populates="contacts")
    owner: Mapped[User] = relationship()


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    salutation: Mapped[str | None] = mapped_column(String(10))
    first_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    # filled automatically by the database from first + last name
    name: Mapped[str] = mapped_column(String(101), Computed("TRIM(COALESCE(first_name || ' ', '') || last_name)", persisted=True))
    company: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(20), default="Other")
    stage: Mapped[str] = mapped_column(String(20), default="New")   # New/Nurturing/Demo/Converted/Lost
    demo_date: Mapped[datetime | None]
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    lost_notes: Mapped[str | None] = mapped_column(Text)
    converted_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship()
    opportunity: Mapped["Opportunity | None"] = relationship(back_populates="lead")
    tasks: Mapped[list["Task"]] = relationship(back_populates="lead")
    history: Mapped[list["StageHistory"]] = relationship(back_populates="lead")
    notes: Mapped[list["Note"]] = relationship(back_populates="lead")
    transfers: Mapped[list["LeadTransfer"]] = relationship(back_populates="lead", order_by="LeadTransfer.id")


class LeadTransfer(Base):
    """Every time a lead gets a new owner: from whom, to whom, who did it and when."""

    __tablename__ = "lead_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    from_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    transferred_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(300))
    transferred_at: Mapped[datetime] = mapped_column(server_default=func.now())

    lead: Mapped[Lead] = relationship(back_populates="transfers")
    from_user: Mapped[User | None] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped[User] = relationship(foreign_keys=[to_user_id])
    transferred_by: Mapped[User] = relationship(foreign_keys=[transferred_by_id])


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(20), default="Opportunity")   # Opportunity/Proposal/Won/Lost
    expected_value: Mapped[Decimal | None]
    final_value: Mapped[Decimal | None]
    expected_close_date: Mapped[date | None]
    probability: Mapped[int] = mapped_column(default=20)  # % chance to win, set by stage
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    lost_notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None]
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    primary_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    account: Mapped[Account] = relationship(back_populates="opportunities")
    primary_contact: Mapped[Contact | None] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="opportunity")
    owner: Mapped[User] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="opportunity")
    history: Mapped[list["StageHistory"]] = relationship(back_populates="opportunity")
    notes: Mapped[list["Note"]] = relationship(back_populates="opportunity")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[datetime]
    reminder_at: Mapped[datetime | None]
    reminder_sent: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="Open")      # Open/Done/Auto-closed
    priority: Mapped[str] = mapped_column(String(10), default="Normal")  # Low/Normal/High
    is_auto: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[datetime | None]
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="tasks")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="tasks")


class StageHistory(Base):
    __tablename__ = "stage_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_stage: Mapped[str | None] = mapped_column(String(30))
    to_stage: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    changed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))

    changed_by: Mapped[User] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="history")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="history")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    created_by: Mapped[User] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="notes")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="notes")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(200))  # page in the app, e.g. /leads/5
    kind: Mapped[str] = mapped_column(String(10), default="update")  # update | reminder
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship()
    task: Mapped[Task | None] = relationship()

class Email(Base):
    """An email sent from the CRM to a lead / contact, saved on the record's activity."""

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    to_address: Mapped[str] = mapped_column(String(500))
    cc_address: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="Sent")  # Sent / Failed
    error: Mapped[str | None] = mapped_column(Text)
    sent_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    sent_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    sent_by: Mapped[User] = relationship()
    attachments: Mapped[list["EmailAttachment"]] = relationship(back_populates="email", cascade="all, delete-orphan")


class EmailAttachment(Base):
    __tablename__ = "email_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    data: Mapped[bytes] = mapped_column(LargeBinary)

    email: Mapped[Email] = relationship(back_populates="attachments")


class OpportunityAttachment(Base):
    """A file kept on an opportunity (proposal, quote, signed order...), uploaded at the Opportunity or Proposal stage.
    The bytes are deferred: lists and other queries never load them, only the download does.
    Deleting only hides the file (deleted_at / deleted_by_id are set); the row and the bytes stay."""

    __tablename__ = "opportunity_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"))
    stage: Mapped[str] = mapped_column(String(20))           # stage of the deal when the file was uploaded
    filename: Mapped[str] = mapped_column(String(255))       # cleaned name shown in the app
    content_type: Mapped[str] = mapped_column(String(100))   # detected from the file content by the server
    size_bytes: Mapped[int]
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    opportunity: Mapped[Opportunity] = relationship()
    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id])
    deleted_by: Mapped[User | None] = relationship(foreign_keys=[deleted_by_id])
