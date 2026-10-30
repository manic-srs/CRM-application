"""LinkedIn profile autofill for the New Lead form (Apollo People Enrichment, see app/apollo.py).

Looks a profile up and returns the lead details found. Saves nothing and sends nothing: the user reviews the form
and saves the lead as usual. Same access as creating a lead: any signed-in user.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import apollo
from app.schemas import linkedin_profile_url
from app.security import acting_user

router = APIRouter(prefix="/api/leads", tags=["Leads: LinkedIn autofill"])


class EnrichmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin_url: str = Field(..., min_length=1, max_length=300)


class EnrichmentOut(BaseModel):
    status: Literal["matched", "unverified", "no_match"]  # unverified: Apollo's LinkedIn URL missing/invalid/different
    linkedin_url: str  # the profile address in its saved form
    url_verified: bool = False  # true only when Apollo's returned LinkedIn URL is this same profile
    fields: dict[str, str] = {}  # first_name, last_name, company, title, industry, email, phone: only those found
    unavailable: dict[str, str] = {}  # the other fields, with the reason they are empty
    message: str | None = None
    cached: bool = False  # answered from this user's recent lookups (no new Apollo request)


@router.get("/enrichment")
def enrichment_status():
    """Whether LinkedIn autofill is available (an Apollo API key is set on the server). The key is never returned."""
    acting_user()
    return {"enabled": apollo.enabled()}


@router.post("/enrichment", response_model=EnrichmentOut)
async def enrich_lead(data: EnrichmentRequest):
    """Looks up a LinkedIn profile (linkedin.com/in/...) in Apollo for the New Lead form."""
    me = acting_user()
    try:
        url = linkedin_profile_url(data.linkedin_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return await apollo.enrich(me.id, url)
