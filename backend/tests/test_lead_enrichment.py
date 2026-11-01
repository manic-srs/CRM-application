"""LinkedIn autofill on New Lead (Apollo People Enrichment). Apollo is never called: every lookup goes to a mocked
transport, and any other Apollo call fails the test. All people and companies here are made up."""
import asyncio
import logging

import httpx
import pytest
from sqlalchemy import select

from app import apollo, mailer
from app.database import get_db
from app.main import app
from app.models import Account, Contact, Lead
from app.schemas import linkedin_profile_url
from conftest import login_as

TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}  # every stage change needs one

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin (see conftest.py)
KEY = "test-apollo-key-not-real"
ENDPOINT = "/api/leads/enrichment"
JANE = "https://linkedin.com/in/jane-doe-synthetic"
SITE = "http://www.synthetic-co.example"  # Jane's employer, as Apollo returns it (person.organization)
PAGE = "http://www.linkedin.com/company/synthetic-co"
REAL_ASYNC_CLIENT = httpx.AsyncClient


def person(**changes) -> dict:
    data = {
        "id": "synthetic-1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "linkedin_url": "http://www.linkedin.com/in/jane-doe-synthetic", "title": "Head of Operations",
        "email_status": "verified", "email": "jane.doe@synthetic-co.example", "match_confidence": "high",
        "photo_url": "https://media.example.test/photo.jpg", "city": "Springfield", "headline": "Operations at Synthetic Co",
        "organization_id": "synthetic-org-1",
        "organization": {"id": "synthetic-org-1", "name": "Synthetic Co", "industry": "information technology & services",
                         "website_url": SITE, "linkedin_url": PAGE, "primary_domain": "synthetic-co.example",
                         "phone": "+1 555 0100", "primary_phone": {"number": "+1 555 0100"}},
        "employment_history": [{"current": True, "organization_id": "synthetic-org-1", "organization_name": "Synthetic Co",
                                "title": "Head of Operations"}],
    }
    data.update(changes)
    return data


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No key, no cached answers, and no way to reach Apollo unless a test installs the mocked transport."""
    apollo.reset()
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    monkeypatch.setattr(apollo.httpx, "AsyncClient", lambda **kw: pytest.fail("Apollo must not be called here"))
    yield
    apollo.reset()


@pytest.fixture
def apollo_api(monkeypatch):
    """Apollo with a (fake) key and a mocked transport. Returns (requests seen, replies to give in order);
    without a queued reply it answers with Jane's profile."""
    monkeypatch.setenv("APOLLO_API_KEY", KEY)
    seen, replies = [], []

    async def handler(request):
        seen.append(request)
        reply = replies.pop(0) if replies else httpx.Response(200, json={"person": person()})
        result = reply(request) if callable(reply) else reply
        return await result if asyncio.iscoroutine(result) else result
    monkeypatch.setattr(apollo.httpx, "AsyncClient",
                        lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return seen, replies


def look_up(client, url=JANE):
    return client.post(ENDPOINT, json={"linkedin_url": url})


def lead_count() -> int:
    with next(app.dependency_overrides[get_db]()) as db:
        return len(db.scalars(select(Lead.id)).all())


# ---------- profile addresses ----------

@pytest.mark.parametrize("value", [
    "https://www.linkedin.com/in/Jane-Doe-Synthetic/",
    "http://linkedin.com/in/jane-doe-synthetic",
    "  linkedin.com/in/jane-doe-synthetic?trk=public_profile#about ",
    "https://uk.linkedin.com/in/jane-doe-synthetic",
    "www.linkedin.com/in/JANE-DOE-SYNTHETIC",
])
def test_profile_addresses_are_saved_in_one_form(value):
    assert linkedin_profile_url(value) == JANE


@pytest.mark.parametrize("value", [
    "", "   ", "jane-doe", "https://www.linkedin.com/company/synthetic-co", "https://www.linkedin.com/school/synthetic",
    "https://www.linkedin.com/in/", "https://www.linkedin.com/in/jane/details/experience",
    "https://www.linkedin.com/sales/lead/abc123", "https://www.linkedin.com/pub/jane-doe/1/2/3",
    "https://linkedin.com.example.test/in/jane-doe", "https://evil-linkedin.com/in/jane-doe",
    "https://www.linkedin.com@example.test/in/jane-doe", "https://user:pw@www.linkedin.com/in/jane-doe",
    "https://www.linkedin.com:443/in/jane-doe", "javascript:alert(1)", "ftp://linkedin.com/in/jane-doe",
    "file:///etc/passwd", "//www.linkedin.com/in/jane-doe", "https://lnkd.in/abc123",
    "https://www.linkedin.com/in/jane doe", "https://www.linkedin.com/in/ab", "https://www.linkedin.com/in/jane%2Fdoe",
    "https://www.linkedin.com/in/" + "a" * 300,
])
def test_other_addresses_are_refused(value):
    with pytest.raises(ValueError):
        linkedin_profile_url(value)


def test_refused_addresses_never_reach_apollo(client, apollo_api):
    seen, _ = apollo_api
    res = look_up(client, "https://www.linkedin.com/company/synthetic-co")
    assert res.status_code == 422 and "not a company" in res.json()["detail"]
    assert look_up(client, "https://linkedin.com.example.test/in/jane-doe").status_code == 422
    assert client.post(ENDPOINT, json={"linkedin_url": JANE, "reveal_personal_emails": True}).status_code == 422
    assert seen == []


# ---------- one lookup ----------

def test_a_match_fills_only_the_lead_fields_and_saves_nothing(client, apollo_api, monkeypatch):
    seen, _ = apollo_api
    sent = []
    monkeypatch.setattr(mailer, "send", lambda *a, **k: sent.append(a))
    leads_before = lead_count()
    res = look_up(client, "https://www.linkedin.com/in/Jane-Doe-Synthetic/?trk=x")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "matched" and body["linkedin_url"] == JANE and body["cached"] is False
    assert body["url_verified"] is True
    assert body["fields"] == {"first_name": "Jane", "last_name": "Doe", "company": "Synthetic Co",
                              "title": "Head of Operations", "industry": "information technology & services",
                              "company_website": SITE, "company_linkedin_url": PAGE,
                              "email": "jane.doe@synthetic-co.example"}
    assert set(body["unavailable"]) == {"phone"} and "mobile numbers are not requested" in body["unavailable"]["phone"]
    for private in ("photo", "Springfield", "headline", "555 0100", "synthetic-1", "synthetic-org-1"):
        assert private not in res.text  # nothing else from Apollo reaches the browser (not the company switchboard)
    # nothing saved, nothing sent
    assert lead_count() == leads_before and sent == []

    # the request: Apollo's fixed address, the key in the x-api-key header, the profile in the body, reveals off
    [request] = seen
    assert str(request.url).split("?")[0] == "https://api.apollo.io/api/v1/people/match"
    assert dict(request.url.params) == {"reveal_personal_emails": "false", "reveal_phone_number": "false",
                                        "run_waterfall_email": "false", "run_waterfall_phone": "false"}
    assert request.headers["x-api-key"] == KEY and "authorization" not in request.headers
    assert request.read() == b'{"linkedin_url":"https://www.linkedin.com/in/jane-doe-synthetic"}'  # LinkedIn's host
    assert "webhook" not in str(request.url) and KEY not in str(request.url)


@pytest.mark.parametrize("email, status, filled, reason", [
    ("jane.doe@synthetic-co.example", "verified", True, None),
    ("email_not_unlocked@domain.com", "verified", False, "no work email was revealed"),
    ("jane.guess@synthetic-co.example", "extrapolated", False, "only an unverified email"),
    (None, "unavailable", False, "no work email was revealed"),
    ("not-an-email", "verified", False, "isn't a valid address"),
    ("a" * 250 + "@synthetic-co.example", "verified", False, "too long for this form"),
])
def test_only_verified_work_emails_are_used(client, apollo_api, email, status, filled, reason):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(email=email, email_status=status)}))
    body = look_up(client).json()
    assert ("email" in body["fields"]) is filled
    if filled:
        assert body["fields"]["email"] == email
    else:
        assert reason in body["unavailable"]["email"]  # never cut down, never a guess


@pytest.mark.parametrize("numbers, contact, phone, reason", [
    ([{"type_cd": "mobile", "raw_number": "+1 555 0199"}, {"type_cd": "work_direct", "raw_number": "+1 555 0101"}],
     None, "+1 555 0101", None),
    ([{"type_cd": "mobile", "raw_number": "+1 555 0199"}], None, None, "no direct business number"),  # never a mobile
    (None, {"phone_numbers": [{"type_cd": "work_direct", "sanitized_number": "+15550102"}]}, "+15550102", None),
    ([{"type_cd": "work_direct", "raw_number": "1" * 31}], None, None, "too long"),  # never cut down
])
def test_only_a_direct_business_number_is_used(client, apollo_api, numbers, contact, phone, reason):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=numbers, contact=contact)}))
    body = look_up(client).json()
    assert body["fields"].get("phone") == phone
    if reason:
        assert reason in body["unavailable"]["phone"]


def test_values_that_dont_fit_the_form_are_reported_not_cut(client, apollo_api):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(first_name="J" * 51, title="T" * 101,
                                                              organization={"name": "C" * 201})}))
    body = look_up(client).json()
    assert body["status"] == "matched" and set(body["fields"]) == {"last_name", "email"}
    for name in ("first_name", "title", "company"):
        assert "too long" in body["unavailable"][name]
    assert body["unavailable"]["industry"] == "Apollo didn't return it"


def test_company_falls_back_to_the_current_job(client, apollo_api):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(organization=None)}))
    body = look_up(client).json()
    assert body["fields"]["company"] == "Synthetic Co" and "industry" in body["unavailable"]
    assert body["unavailable"]["company_website"] == body["unavailable"]["company_linkedin_url"] == "Apollo didn't return it"


# ---------- company details: the verified person's current employer, from the same answer ----------

DROP = object()  # leaves the field out of Apollo's organization


def employer(**changes) -> dict:
    """Jane's answer with changes to her employer (DROP leaves a field out)."""
    organization = {**person()["organization"], **changes}
    return person(organization={k: v for k, v in organization.items() if v is not DROP})


@pytest.mark.parametrize("changes, filled, missing", [
    ({}, {"company": "Synthetic Co", "industry": "information technology & services", "company_website": SITE,
          "company_linkedin_url": PAGE}, set()),
    ({"linkedin_url": DROP}, {"company_website": SITE}, {"company_linkedin_url"}),
    ({"website_url": None, "industry": ""}, {"company": "Synthetic Co", "company_linkedin_url": PAGE},
     {"company_website", "industry"}),
    ({"website_url": "   ", "linkedin_url": None, "industry": DROP}, {"company": "Synthetic Co"},
     {"company_website", "company_linkedin_url", "industry"}),
])
def test_full_partial_and_missing_company_details(client, apollo_api, changes, filled, missing):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": employer(**changes)}))
    body = look_up(client).json()
    assert body["status"] == "matched" and body["url_verified"] is True
    assert {k: body["fields"][k] for k in filled} == filled
    for name in missing:
        assert name not in body["fields"] and body["unavailable"][name] == "Apollo didn't return it"


def test_a_website_is_never_guessed_from_the_email_or_domain(client, apollo_api):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": employer(website_url=DROP, linkedin_url=DROP)}))
    body = look_up(client).json()
    assert body["fields"]["email"] == "jane.doe@synthetic-co.example"  # its domain and primary_domain are known...
    assert "company_website" not in body["fields"] and "company_linkedin_url" not in body["fields"]  # ...but not used
    assert "synthetic-co.example" not in str(body["unavailable"])


@pytest.mark.parametrize("website, saved", [
    ("https://www.synthetic-co.example/about", "https://www.synthetic-co.example/about"),
    ("synthetic-co.example", "https://synthetic-co.example"),  # the form's rule adds https:// (as when typed)
])
def test_a_returned_website_follows_the_form_rule(client, apollo_api, website, saved):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": employer(website_url=website)}))
    assert look_up(client).json()["fields"]["company_website"] == saved


@pytest.mark.parametrize("website", [
    "not a website", "javascript:alert(1)", "ftp://files.synthetic-co.example", "http://user@synthetic-co.example",
    "https://synthetic co.example", "http://localhost", "https://.synthetic-co.example", "http://[::1",
    "https://synthetic-co.example/\npath", 12345, ["http://synthetic-co.example"], {"url": SITE}, True,
])
def test_a_malformed_website_is_reported_not_used(client, apollo_api, website):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": employer(website_url=website)}))
    body = look_up(client).json()
    assert body["status"] == "matched" and "company_website" not in body["fields"]
    assert body["unavailable"]["company_website"] == "Apollo's address isn't a valid web address, so it was not used"
    assert body["fields"]["company_linkedin_url"] == PAGE  # the other company details still fill


@pytest.mark.parametrize("page, saved", [
    ("linkedin.com/company/synthetic-co", "https://linkedin.com/company/synthetic-co"),
    ("https://uk.linkedin.com/company/synthetic-co/", "https://uk.linkedin.com/company/synthetic-co/"),
    ("https://www.linkedin.com/school/synthetic-university", "https://www.linkedin.com/school/synthetic-university"),
    ("https://www.linkedin.com/showcase/synthetic-labs", "https://www.linkedin.com/showcase/synthetic-labs"),
])
def test_a_returned_company_page_follows_the_form_rule(client, apollo_api, page, saved):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": employer(linkedin_url=page)}))
    assert look_up(client).json()["fields"]["company_linkedin_url"] == saved


@pytest.mark.parametrize("page", [
    "http://www.linkedin.com/in/jane-doe-synthetic",  # a person's profile is not a company page
    "https://www.synthetic-co.example/company/synthetic-co", "https://linkedin.com.example.test/company/synthetic-co",
    "https://www.linkedin.com@example.test/company/synthetic-co", "https://user@www.linkedin.com/company/synthetic-co",
    "https://www.linkedin.com/company/", "https://www.linkedin.com/company/synthetic-co/jobs",
    "https://www.linkedin.com/feed/", "javascript:alert(1)", "not a page", 404, ["x"],
])
def test_a_malformed_company_page_is_reported_not_used(client, apollo_api, page):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": employer(linkedin_url=page)}))
    body = look_up(client).json()
    assert body["status"] == "matched" and "company_linkedin_url" not in body["fields"]
    assert body["unavailable"]["company_linkedin_url"] == "Apollo's address isn't a LinkedIn company page, so it was not used"
    assert body["fields"]["company_website"] == SITE


def test_company_links_that_dont_fit_the_form_are_reported_not_cut(client, apollo_api):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": employer(
        website_url="https://" + "w" * 250 + ".example", linkedin_url="https://www.linkedin.com/company/" + "c" * 280)}))
    body = look_up(client).json()
    for name in ("company_website", "company_linkedin_url"):
        assert name not in body["fields"] and "too long" in body["unavailable"][name]


@pytest.mark.parametrize("answer", [
    person(organization_id="another-org", organization={**person()["organization"]}),
    person(employment_history=[{"current": True, "organization_id": "another-org", "organization_name": "Current Co",
                                "title": "Head of Operations"}]),
])
def test_company_details_of_another_employer_are_not_used(client, apollo_api, answer):
    """person.organization must be the person's current employer (same id as organization_id / the current job)."""
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": answer}))
    res = look_up(client)
    body = res.json()
    assert body["status"] == "matched" and body["fields"]["last_name"] == "Doe"
    for name in ("industry", "company_website", "company_linkedin_url"):
        assert name not in body["fields"] and "aren't for the person's current job" in body["unavailable"][name]
    assert SITE not in res.text and PAGE not in res.text
    current = answer["employment_history"][0]["organization_name"]
    assert body["fields"]["company"] == current  # the current job's own name is still used


def test_an_unverified_profile_fills_no_company_details_either(client, apollo_api):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(linkedin_url="https://www.linkedin.com/in/someone-else")}))
    res = look_up(client)
    assert res.json()["status"] == "unverified" and res.json()["fields"] == {}
    for value in ("Synthetic Co", SITE, PAGE, "information technology"):
        assert value not in res.text


@pytest.mark.parametrize("data, message", [
    ({"person": None}, "no match"),
    ({"person": None, "match_confidence": "none"}, "no match"),
    ({"person": person(match_confidence="none")}, "no match"),
    ({"person": person(match_confidence="low")}, "low-confidence"),
    ({"person": {"id": "x", "linkedin_url": JANE, "photo_url": "https://media.example.test/p.jpg"}}, "no details"),
])
def test_no_match_fills_nothing(client, apollo_api, data, message):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json=data))
    body = look_up(client).json()
    assert body["status"] == "no_match" and body["fields"] == {} and message in body["message"]
    assert body["url_verified"] is False


MISSING = object()  # the person has no linkedin_url key at all


@pytest.mark.parametrize("returned, reason", [
    (MISSING, "has no LinkedIn profile URL"),
    (None, "has no LinkedIn profile URL"),
    ("", "has no LinkedIn profile URL"),
    ("   ", "has no LinkedIn profile URL"),
    (12345, "invalid LinkedIn profile URL"),
    (["https://www.linkedin.com/in/jane-doe-synthetic"], "invalid LinkedIn profile URL"),
    ("not a url", "invalid LinkedIn profile URL"),
    ("https://www.linkedin.com/company/synthetic-co", "invalid LinkedIn profile URL"),
    ("https://linkedin.com.example.test/in/jane-doe-synthetic", "invalid LinkedIn profile URL"),
    ("https://www.linkedin.com/in/jane-doe-synthetic/details", "invalid LinkedIn profile URL"),
    ("https://www.linkedin.com/in/someone-else", "different LinkedIn profile"),
    ("https://www.linkedin.com/in/jane-doe-synthetic-2", "different LinkedIn profile"),
])
def test_an_unverified_profile_fills_nothing(client, apollo_api, returned, reason):
    """Fails closed: Apollo's person must carry this same LinkedIn profile URL, or nothing is filled."""
    _, replies = apollo_api
    data = person()
    if returned is MISSING:
        del data["linkedin_url"]
    else:
        data["linkedin_url"] = returned
    replies.append(httpx.Response(200, json={"person": data}))
    body = look_up(client).json()
    assert body["status"] == "unverified" and body["url_verified"] is False
    assert body["fields"] == {} and body["unavailable"] == {}
    assert body["message"].startswith("The profile could not be verified:") and reason in body["message"]
    for private in ("Jane", "Synthetic Co", "jane.doe@"):
        assert private not in body["message"]  # the message never repeats Apollo's data


@pytest.mark.parametrize("returned", [
    "http://www.linkedin.com/in/jane-doe-synthetic",
    "https://www.linkedin.com/in/Jane-Doe-Synthetic/",
    "linkedin.com/in/jane-doe-synthetic?trk=public_profile",
    "https://uk.linkedin.com/in/jane-doe-synthetic",
    JANE,
])
def test_a_matching_profile_url_is_verified(client, apollo_api, returned):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(linkedin_url=returned)}))
    body = look_up(client).json()
    assert body["status"] == "matched" and body["url_verified"] is True and body["fields"]["last_name"] == "Doe"


# ---------- problems ----------

def raise_(error):
    def reply(request):
        raise error("synthetic failure", request=request)
    return reply


@pytest.mark.parametrize("reply, status, message", [
    (httpx.Response(401, text="Invalid access credentials."), 502, "rejected the server's API key"),
    (httpx.Response(403, json={"error": "forbidden"}), 502, "doesn't allow People Enrichment"),
    (httpx.Response(402, json={}), 502, "no enrichment credits"),
    (httpx.Response(422, json={"error_details": {"code": "USAGE.CREDITS.INSUFFICIENT"}}), 502, "no enrichment credits"),
    (httpx.Response(429, headers={"retry-after": "30"}, json={"error_details": {
        "code": "USAGE.RATE_LIMIT.API_RATE_LIMIT_EXCEEDED"}}), 429, "Try again in 30 seconds"),
    (httpx.Response(500, text="oops"), 502, "couldn't look up this profile"),
    (httpx.Response(200, text="<html>not json</html>"), 502, "unexpected answer"),
    (httpx.Response(200, json=["not", "an", "object"]), 502, "unexpected answer"),
    (raise_(httpx.ReadTimeout), 504, "took too long"),
    (raise_(httpx.ConnectError), 502, "can't be reached"),
])
def test_apollo_problems_get_a_plain_message_and_can_be_retried(client, apollo_api, reply, status, message):
    seen, replies = apollo_api
    replies.append(reply)
    res = look_up(client)
    assert res.status_code == status and message in res.json()["detail"]
    assert KEY not in res.text
    if status == 429:
        assert res.headers["retry-after"] == "30"
    assert look_up(client).json()["status"] == "matched"  # a failure isn't remembered: Retry asks Apollo again
    assert len(seen) == 2


def test_without_a_key_the_form_is_told_autofill_is_off(client):
    assert client.get(ENDPOINT).json() == {"enabled": False}
    res = look_up(client)
    assert res.status_code == 503 and "isn't set up" in res.json()["detail"]  # and Apollo isn't called (autouse)


def test_status_never_returns_the_key(client, apollo_api):
    res = client.get(ENDPOINT)
    assert res.json() == {"enabled": True} and KEY not in res.text


def test_login_is_needed_and_every_user_who_can_create_leads_can_use_it(client, apollo_api):
    seen, _ = apollo_api
    client.headers.pop("Authorization")
    assert client.get(ENDPOINT).status_code == 401 and look_up(client).status_code == 401
    for user in (RAVI, PRIYA, ASHA):  # Salesperson, Manager, Admin can all create leads
        assert look_up(login_as(client, user)).status_code == 200
    assert len(seen) == 3  # answers are kept per user


def test_the_same_profile_is_looked_up_once(client, apollo_api):
    seen, _ = apollo_api
    first = look_up(client).json()
    again = look_up(client, "linkedin.com/in/JANE-DOE-SYNTHETIC/").json()  # same profile, written differently
    assert len(seen) == 1 and again["cached"] is True and again["fields"] == first["fields"]
    assert (again["fields"]["company_website"], again["fields"]["company_linkedin_url"]) == (SITE, PAGE)  # kept too
    look_up(client, JANE + "-other")
    assert len(seen) == 2


def test_lookups_are_rate_limited_per_user(client, apollo_api, monkeypatch):
    seen, _ = apollo_api
    monkeypatch.setattr(apollo, "LOOKUPS_PER_MINUTE", 2)
    assert look_up(client, JANE + "-1").status_code == 200
    assert look_up(client, JANE + "-2").status_code == 200
    limited = look_up(client, JANE + "-3")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert look_up(client, JANE + "-1").status_code == 200  # an answer already kept doesn't count
    assert look_up(login_as(client, PRIYA), JANE + "-3").status_code == 200  # another user has their own limit
    assert len(seen) == 3


def test_lookups_at_the_same_time_share_one_apollo_request(apollo_api, monkeypatch):
    seen, replies = apollo_api

    async def slow(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"person": person()})
    replies.append(slow)

    async def both():
        return await asyncio.gather(apollo.enrich(RAVI, JANE), apollo.enrich(RAVI, JANE))
    first, second = asyncio.run(both())
    assert len(seen) == 1 and first["fields"] == second["fields"]
    assert sorted([first["cached"], second["cached"]]) == [False, True]


def test_logs_hold_no_key_or_personal_details(client, apollo_api, caplog):
    _, replies = apollo_api
    replies.append(httpx.Response(401, text="Invalid access credentials for test-apollo-key-not-real"))
    with caplog.at_level(logging.DEBUG):
        look_up(client)
        look_up(client)
    for private in (KEY, "jane-doe-synthetic", "Jane", "jane.doe@", "Synthetic Co", "Head of Operations",
                    "synthetic-co.example", "company/synthetic-co"):
        assert private not in caplog.text
    assert "Apollo lookup failed: HTTP 401" in caplog.text and "Apollo lookup: matched" in caplog.text


# ---------- the saved lead ----------

def test_autofilled_company_details_are_saved_and_conversion_copies_them_to_the_account(client, apollo_api):
    fields = look_up(client).json()["fields"]
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.scalars(select(Lead.id)).all() == [] and db.scalars(select(Account.id)).all() == []  # lookup saves nothing
    # what the New Lead form sends when the user keeps the autofilled values
    res = client.post("/api/leads", json={**fields, "linkedin_url": JANE, "source": "Other", "welcome_email": False})
    assert res.status_code == 201, res.text
    lead = res.json()
    company = ("Synthetic Co", "information technology & services", SITE, PAGE)
    assert (lead["company"], lead["industry"], lead["company_website"], lead["company_linkedin_url"]) == company
    converted = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "completed_stages": ["Nurturing", "Demo"],
                                                                        "note": "Synthetic test: converting"})
    assert converted.status_code == 200, converted.text
    account = converted.json()["account"]
    assert (account["name"], account["industry"], account["website"], account["linkedin_url"]) == company

def test_a_new_lead_keeps_the_profile_in_one_form_and_conversion_copies_it(client):
    res = client.post("/api/leads", json={"first_name": "Jane", "last_name": "Doe", "company": "Synthetic Co",
                                          "email": "jane.doe@synthetic-co.example", "welcome_email": False,
                                          "linkedin_url": "https://WWW.linkedin.com/in/Jane-Doe-Synthetic/?trk=x"})
    assert res.status_code == 201, res.text
    lead = res.json()
    assert lead["linkedin_url"] == JANE
    converted = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "completed_stages": ["Nurturing", "Demo"], "note": "Synthetic test note"})
    assert converted.status_code == 200, converted.text
    with next(app.dependency_overrides[get_db]()) as db:
        contact = db.get(Contact, converted.json()["contact"]["id"])
        assert contact.linkedin_url == JANE

    # other LinkedIn links are kept as before (no new rule for them), and editing a lead works as before
    other = client.post("/api/leads", json={"last_name": "Roe", "company": "Synthetic Co", "welcome_email": False,
                                            "linkedin_url": "linkedin.com/company/synthetic-co"})
    assert other.status_code == 201 and other.json()["linkedin_url"] == "https://linkedin.com/company/synthetic-co"
    edited = client.put(f"/api/leads/{other.json()['id']}", json={"linkedin_url": "linkedin.com/in/Roe-Synthetic/"})
    assert edited.status_code == 200 and edited.json()["linkedin_url"] == "https://linkedin.com/in/Roe-Synthetic/"
    assert client.post("/api/leads", json={"last_name": "X", "company": "Y", "welcome_email": False,
                                           "linkedin_url": "https://example.test/in/x"}).status_code == 422
