"""Database tables as Python classes.

Table and column names match the "Database tables" section of the project plan,
so they line up with the MySQL schema (database/schema.sql).
Day 1 tables: users, leads, stage_history. Accounts, contacts, opportunities and tasks come on Day 2.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

# Lead stages, in order. "Converted" and "Lost" are closed stages.
LEAD_STAGES = ["New", "Nurturing", "Demo", "Converted", "Lost"]
LEAD_OPEN_STAGES = ["New", "Nurturing", "Demo"]
LEAD_CLOSED_STAGES = ["Converted", "Lost"]


def now_utc():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="sales_rep")  # sales_rep or manager


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str] = mapped_column(String(100))
    company: Mapped[str] = mapped_column(String(150))
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lead_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str] = mapped_column(String(20), default="New", index=True)
    lost_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class StageHistory(Base):
    """One row for every stage change of a lead (later also opportunities)."""

    __tablename__ = "stage_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_type: Mapped[str] = mapped_column(String(20))  # "lead" or "opportunity"
    record_id: Mapped[int] = mapped_column(Integer, index=True)
    from_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)  # empty when the record is created
    to_stage: Mapped[str] = mapped_column(String(20))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
