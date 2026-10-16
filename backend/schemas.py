"""What each API accepts (request body) and returns (response).

FastAPI checks every request against these, and returns a clear error if a required field is missing.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------- Leads ----------

class LeadBase(BaseModel):
    first_name: str | None = Field(None, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    company: str = Field(..., min_length=1, max_length=150)
    title: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=150)
    phone: str | None = Field(None, max_length=30)
    lead_source: str | None = Field(None, max_length=50)  # e.g. Web, Phone, Referral, LinkedIn
    description: str | None = None
    owner_id: int | None = None


class LeadCreate(LeadBase):
    """Body for POST /leads. Stage is not sent: every new lead starts at New."""


class LeadUpdate(BaseModel):
    """Body for PUT /leads/{id}. Send only the fields you want to change.
    Stage is changed with PUT /leads/{id}/stage or POST /leads/{id}/lost, not here."""

    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    company: str | None = Field(None, min_length=1, max_length=150)
    title: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=150)
    phone: str | None = Field(None, max_length=30)
    lead_source: str | None = Field(None, max_length=50)
    description: str | None = None
    owner_id: int | None = None


class LeadOut(LeadBase):
    """What the APIs return for a lead."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    lost_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class LeadList(BaseModel):
    total: int
    items: list[LeadOut]


# ---------- Stage change and Lost ----------

class StageChange(BaseModel):
    """Body for PUT /leads/{id}/stage. Only open stages can be set here."""

    stage: Literal["New", "Nurturing", "Demo"]
    changed_by: int | None = None  # user id of the salesperson


class MarkLost(BaseModel):
    """Body for POST /leads/{id}/lost. A Lost Reason is required."""

    lost_reason: str = Field(..., min_length=1, max_length=255)
    changed_by: int | None = None


# ---------- Stage history ----------

class StageHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    record_type: str
    record_id: int
    from_stage: str | None
    to_stage: str
    changed_by: int | None
    changed_at: datetime
