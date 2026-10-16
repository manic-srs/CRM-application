"""Python classes that map to the MySQL tables in database/01_schema.sql.
The tables are created by the SQL script; these classes only read/write them."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, String, Text
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
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(30))
    website: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]

    owner: Mapped[User] = relationship()
    contacts: Mapped[list["Contact"]] = relationship(back_populates="account")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    job_title: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]

    account: Mapped[Account] = relationship(back_populates="contacts")
    owner: Mapped[User] = relationship()


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    company: Mapped[str | None] = mapped_column(String(200))
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
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]

    owner: Mapped[User] = relationship()
    opportunity: Mapped["Opportunity | None"] = relationship(back_populates="lead")
    tasks: Mapped[list["Task"]] = relationship(back_populates="lead")
    history: Mapped[list["StageHistory"]] = relationship(back_populates="lead")
    notes: Mapped[list["Note"]] = relationship(back_populates="lead")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(20), default="Opportunity")   # Opportunity/Proposal/Won/Lost
    expected_value: Mapped[Decimal | None]
    final_value: Mapped[Decimal | None]
    expected_close_date: Mapped[date | None]
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    lost_notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None]
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    primary_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]

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
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]

    owner: Mapped[User] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="tasks")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="tasks")


class StageHistory(Base):
    __tablename__ = "stage_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_stage: Mapped[str | None] = mapped_column(String(30))
    to_stage: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime | None]
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
    created_at: Mapped[datetime | None]

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
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime | None]

    user: Mapped[User] = relationship()
    task: Mapped[Task | None] = relationship()