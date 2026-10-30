"""Apollo People Enrichment for the New Lead form: a LinkedIn profile address -> the lead details Apollo returns.

- Server only. APOLLO_API_KEY stays on the backend; the browser calls POST /api/leads/enrichment.
- Only Apollo's fixed People Enrichment endpoint is called (never the LinkedIn address itself), with the profile
  address in the request body. Personal emails, phone reveal and waterfall enrichment stay off; no webhooks.
- Fields are filled only when the LinkedIn URL in Apollo's answer is the pasted profile. A missing, invalid or
  different URL fails closed: nothing is filled and the form says the profile could not be verified.
- Credits (Apollo's docs): 1 credit when Apollo returns person data or an email; none when nobody matches.
- Only the seven lead fields are kept, in memory, per user, for 10 minutes, so pasting the same profile again
  doesn't spend another credit. The full Apollo response is never stored or logged.
"""
import asyncio
import logging
import math
import os
import re
import time
from collections import deque

import httpx
from fastapi import HTTPException

from app.schemas import linkedin_profile_url
from app.services import CUSTOMER_EMAIL_RE

APOLLO_URL = "https://api.apollo.io/api/v1/people/match"
# Also Apollo's defaults, sent explicitly: no personal emails, no phone reveal (needs a webhook), no waterfall
APOLLO_FLAGS = {"reveal_personal_emails": "false", "reveal_phone_number": "false",
                "run_waterfall_email": "false", "run_waterfall_phone": "false"}
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
MAX_RESPONSE_BYTES = 1024 * 1024
PLACEHOLDER_EMAIL = "email_not_unlocked@domain.com"  # Apollo's stand-in when an email isn't revealed
LIMITS = {"first_name": 50, "last_name": 50, "company": 200, "title": 100, "industry": 100, "email": 255, "phone": 30}
NOT_RETURNED = "Apollo didn't return it"
LOOKUPS_PER_MINUTE = 10  # per user; cached answers don't count
CACHE_SECONDS = 600
CACHE_SIZE = 500

log = logging.getLogger("crm.apollo")
_cache: dict[tuple[int, str], tuple[float, dict]] = {}
_locks: dict[tuple[int, str], asyncio.Lock] = {}
_recent: dict[int, deque] = {}


def api_key() -> str:
    return os.getenv("APOLLO_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def reset() -> None:
    """Forgets cached answers and rate counters (used by the tests)."""
    _cache.clear()
    _locks.clear()
    _recent.clear()


# ---------- what Apollo returned -> lead fields ----------

def text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def work_email(person: dict) -> tuple[str, str]:
    """(email, why there is none). Only an address Apollo marks as verified; never its placeholder or a guess."""
    email = text(person.get("email"))
    if not email or email.lower() == PLACEHOLDER_EMAIL:
        return "", "no work email was revealed (personal emails are not requested)"
    if person.get("email_status") != "verified":
        return "", "only an unverified email was returned, so it was not used"
    if not CUSTOMER_EMAIL_RE.match(email):
        return "", "the returned email isn't a valid address"
    return email, ""


def business_phone(person: dict) -> str:
    """A direct business line returned for the person. Mobile and other numbers are never used, and phone reveal is
    off, so this is often empty. The company's switchboard is not the lead's phone."""
    contact = person.get("contact") if isinstance(person.get("contact"), dict) else {}
    for number in person.get("phone_numbers") or contact.get("phone_numbers") or []:
        if isinstance(number, dict) and (number.get("type_cd") or number.get("type")) == "work_direct":
            return text(number.get("raw_number")) or text(number.get("sanitized_number"))
    return ""


def lead_fields(person: dict) -> tuple[dict, dict]:
    """(fields to fill, why each other field is empty). Values that don't fit the form are reported, never cut."""
    organization = person.get("organization") if isinstance(person.get("organization"), dict) else {}
    jobs = person.get("employment_history") if isinstance(person.get("employment_history"), list) else []
    current_job = next((j for j in jobs if isinstance(j, dict) and j.get("current")), {})
    email, no_email = work_email(person)
    values = {
        "first_name": text(person.get("first_name")),
        "last_name": text(person.get("last_name")),
        "company": text(organization.get("name")) or text(current_job.get("organization_name")),
        "title": text(person.get("title")),
        "industry": text(organization.get("industry")),
        "email": email,
        "phone": business_phone(person),
    }
    reasons = {"email": no_email, "phone": "no direct business number was returned (mobile numbers are not requested)"}
    fields, unavailable = {}, {}
    for name, value in values.items():
        if not value:
            unavailable[name] = reasons.get(name) or NOT_RETURNED
        elif len(value) > LIMITS[name]:
            unavailable[name] = "too long for this form, so it was not filled"
        else:
            fields[name] = value
    return fields, unavailable


def unverified_reason(returned, url: str) -> str:
    """Why Apollo's person can't be shown to be the pasted profile; "" only when Apollo's own LinkedIn URL is the
    same profile. Fails closed: a missing, invalid or different profile URL means nothing is filled."""
    if returned is None or (isinstance(returned, str) and not returned.strip()):
        return "Apollo's answer has no LinkedIn profile URL"
    try:
        return "" if linkedin_profile_url(returned) == url else "Apollo returned a different LinkedIn profile"
    except (ValueError, AttributeError):  # not a person profile address, or not text at all
        return "Apollo returned an invalid LinkedIn profile URL"


def outcome(data: dict, url: str) -> dict:
    """The answer for the form: matched (with fields, profile URL verified), unverified or no_match (nothing to fill)."""
    person = data.get("person")
    confidence = (person or {}).get("match_confidence") if isinstance(person, dict) else None
    confidence = confidence or data.get("match_confidence")
    if not isinstance(person, dict) or confidence == "none":
        return no_match(url, "Apollo found no match for this profile.")
    if confidence == "low":
        return no_match(url, "Apollo found only a low-confidence match, so nothing was filled.")
    reason = unverified_reason(person.get("linkedin_url"), url)
    if reason:
        return no_match(url, f"The profile could not be verified: {reason}. Nothing was filled.", status="unverified")
    fields, unavailable = lead_fields(person)
    if not fields:
        return no_match(url, "Apollo matched the profile but returned no details for this form.")
    return {"status": "matched", "linkedin_url": url, "url_verified": True, "fields": fields,
            "unavailable": unavailable, "message": None}


def no_match(url: str, message: str, status: str = "no_match") -> dict:
    return {"status": status, "linkedin_url": url, "url_verified": False, "fields": {}, "unavailable": {},
            "message": message}


# ---------- calling Apollo ----------

def error_code(response: httpx.Response) -> str:
    """Apollo's machine-readable error code (safe to log); never the message or body."""
    try:
        details = response.json().get("error_details") or {}
        code = details.get("code") if isinstance(details, dict) else ""
    except (ValueError, AttributeError):
        code = ""
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_.]{1,80}", code) else ""


def retry_seconds(response: httpx.Response) -> int:
    value = response.headers.get("retry-after", "")
    return min(max(int(value), 1), 3600) if value.isdigit() else 60


async def call_apollo(url: str) -> dict:
    # Apollo gets LinkedIn's own host (www.); the CRM saves https://linkedin.com/in/...
    body = {"linkedin_url": url.replace("://linkedin.com/", "://www.linkedin.com/", 1)}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.post(
                APOLLO_URL, params=APOLLO_FLAGS, json=body,
                headers={"x-api-key": api_key(), "Cache-Control": "no-cache", "accept": "application/json"},
            )
    except httpx.TimeoutException:
        log.warning("Apollo lookup timed out")
        raise HTTPException(504, "Apollo took too long to answer. Try again.") from None
    except httpx.HTTPError:
        log.warning("Apollo could not be reached")
        raise HTTPException(502, "Apollo can't be reached right now. Try again later.") from None
    if response.status_code == 200:
        try:
            data = response.json() if len(response.content) <= MAX_RESPONSE_BYTES else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            log.warning("Apollo returned an unusable answer")
            raise HTTPException(502, "Apollo returned an unexpected answer. Try again later.")
        return data
    code = error_code(response)
    log.warning("Apollo lookup failed: HTTP %s %s", response.status_code, code)
    if response.status_code == 401:
        raise HTTPException(502, "Apollo rejected the server's API key. Ask your administrator to check APOLLO_API_KEY.")
    if response.status_code == 402 or "CREDIT" in code:
        raise HTTPException(502, "The Apollo account has no enrichment credits left. Ask your administrator.")
    if response.status_code == 403:
        raise HTTPException(502, "The Apollo API key or plan doesn't allow People Enrichment. Ask your administrator.")
    if response.status_code == 429:
        wait = retry_seconds(response)
        raise HTTPException(429, f"Apollo is limiting lookups right now. Try again in {wait} seconds.",
                            headers={"Retry-After": str(wait)})
    raise HTTPException(502, "Apollo couldn't look up this profile right now. Try again later.")


# ---------- one lookup per user and profile ----------

def check_rate(user_id: int) -> None:
    now, recent = time.monotonic(), _recent.setdefault(user_id, deque())
    while recent and now - recent[0] >= 60:
        recent.popleft()
    if len(recent) >= LOOKUPS_PER_MINUTE:
        wait = max(1, math.ceil(60 - (now - recent[0])))
        raise HTTPException(429, f"Too many profile lookups. Try again in {wait} seconds.", headers={"Retry-After": str(wait)})
    recent.append(now)


def remember(key: tuple[int, str], result: dict) -> None:
    now = time.monotonic()
    _cache[key] = (now, result)
    for old in [k for k, (at, _) in _cache.items() if now - at >= CACHE_SECONDS]:
        del _cache[old]
    while len(_cache) > CACHE_SIZE:
        del _cache[next(iter(_cache))]
    if len(_locks) > CACHE_SIZE:
        for old in [k for k, lock in _locks.items() if not lock.locked() and k not in _cache]:
            del _locks[old]


async def enrich(user_id: int, url: str) -> dict:
    """The form's answer for a normalized profile address. The same user asking again within 10 minutes (or at the
    same time) gets the saved answer without another Apollo request."""
    if not enabled():
        raise HTTPException(503, "LinkedIn autofill isn't set up on this server. Fill in the lead details manually.")
    key = (user_id, url)
    async with _locks.setdefault(key, asyncio.Lock()):
        saved = _cache.get(key)
        if saved and time.monotonic() - saved[0] < CACHE_SECONDS:
            return {**saved[1], "cached": True}
        check_rate(user_id)
        result = outcome(await call_apollo(url), url)
        log.info("Apollo lookup: %s", result["status"])
        remember(key, result)
    return {**result, "cached": False}
