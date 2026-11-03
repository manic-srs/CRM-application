"""Email campaigns: who gets the email, Outlook-safe sending, invalid emails, unsubscribe, and the exclusion rules
for every later campaign. Emails are not really sent (send_one is replaced). All data is made up."""
import itertools
from datetime import timedelta

import pytest

from app import campaigns
from app.database import get_db
from app.main import app
from app.models import CampaignRecipient, Lead
from app.services import now
from tests.conftest import login_as

NUMBERS = itertools.count(1)


@pytest.fixture
def sent(monkeypatch):
    """Every email "sent", and what the mail server answers for some addresses."""
    monkeypatch.setenv("CAMPAIGN_CHECK_DOMAINS", "false")
    monkeypatch.setenv("CAMPAIGN_PER_DAY", "1800")
    outbox, answers = [], {}

    def fake(to, subject, body, **kw):
        outbox.append({"to": to, "subject": subject, "body": body, **kw})
        return answers.get(to, campaigns.Result("sent"))
    monkeypatch.setattr(campaigns, "send_one", fake)
    return _Outbox(outbox, answers)


class _Outbox:
    def __init__(self, items, answers):
        self.items, self.answers = items, answers

    def to(self):
        return [m["to"] for m in self.items]


def db_session():
    return next(app.dependency_overrides[get_db]())


def run_round(**kw):
    db = db_session()
    try:
        return campaigns.run(db, pause_seconds=0, **kw)
    finally:
        db.close()


def lead(client, first="Mia", email=True, **extra):
    n = next(NUMBERS)
    body = {"first_name": first, "last_name": f"Camp{n}", "company": "Bluebird",
            **({"email": f"{first.lower()}{n}@bluebird.example"} if email else {}), **extra}
    res = client.post("/api/leads", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def make(client, lead_ids, **extra):
    body = {"name": "Spring offer", "subject": "Hello {first_name}",
            "body": "Hi {first_name},\n\nA short note from {sender_name} about {company}.", "lead_ids": lead_ids, **extra}
    return client.post("/api/campaigns", json=body)


def unsubscribe(client, lead_id):
    token = campaigns.unsubscribe_token(lead_id)
    return client.post("/api/public/unsubscribe", data={"t": token, "action": "unsubscribe"})


def test_preview_and_send_leave_out_invalid_unsubscribed_and_no_email(client, sent):
    good, invalid, gone, none = lead(client), lead(client), lead(client), lead(client, email=False)
    assert client.post(f"/api/leads/{invalid['id']}/email-status", json={"status": "invalid", "reason": "Bounced"}).status_code == 200
    assert unsubscribe(client, gone["id"]).status_code == 200
    ids = [good["id"], invalid["id"], gone["id"], none["id"]]
    preview = client.post("/api/campaigns/preview", json={"lead_ids": ids}).json()
    assert (preview["eligible"], preview["left_out"]) == (1, 3)
    assert preview["reasons"] == {"unsubscribed": 1, "invalid": 1, "no_email": 1, "other": 0}

    res = make(client, ids)
    assert res.status_code == 201, res.text
    assert res.json()["counts"]["Queued"] == 1 and res.json()["counts"]["Skipped"] == 3
    assert run_round()["sent"] == 1
    mail = sent.items[0]
    assert mail["to"] == good["email"] and mail["subject"] == "Hello Mia"
    assert "A short note from Ravi Kumar about Bluebird." in mail["body"]
    assert f"/api/public/unsubscribe?t={campaigns.unsubscribe_token(good['id'])}" in mail["body"]
    assert mail["reply_to"] == "ravi@crm.test" and mail["unsubscribe"].endswith(campaigns.unsubscribe_token(good["id"]))
    detail = client.get(f"/api/campaigns/{res.json()['id']}").json()
    assert detail["status"] == "Completed" and detail["counts"]["Sent"] == 1
    bell = client.get("/api/notifications").json()
    assert any(n["title"] == "Campaign sent" and "1 sent" in n["message"] for n in bell)


def test_server_rejection_marks_the_email_invalid_and_later_campaigns_skip_it(client, sent):
    ok, bad = lead(client), lead(client, first="Zed")
    sent.answers[bad["email"]] = campaigns.Result("invalid", "550 5.1.1 User unknown")
    first = make(client, [ok["id"], bad["id"]]).json()
    result = run_round()
    assert (result["sent"], result["invalid"]) == (1, 1)
    page = client.get("/api/leads/page", params={"view": "invalid_email"}).json()
    assert [l["id"] for l in page["items"]] == [bad["id"]]
    assert "550 5.1.1" in page["items"][0]["email_invalid_reason"]
    # the next campaign to everyone leaves the bad address out
    second = make(client, [], stages=["New"]).json()
    assert second["counts"]["Queued"] == 1 and second["counts"]["Skipped"] == 1
    run_round()
    assert sent.to().count(bad["email"]) == 1  # only the first try
    rows = client.get(f"/api/campaigns/{first['id']}", params={"status": "Invalid"}).json()["recipients"]["items"]
    assert rows[0]["email"] == bad["email"]


def test_unsubscribe_link_asks_first_then_unsubscribes_and_can_subscribe_again(client, sent):
    one = lead(client)
    token = campaigns.unsubscribe_token(one["id"])
    page = client.get("/api/public/unsubscribe", params={"t": token})
    assert page.status_code == 200 and "Are you sure you want to unsubscribe?" in page.text and ">Cancel<" in page.text
    assert client.get(f"/api/leads/{one['id']}").json()["unsubscribed_at"] is None  # opening the link changes nothing
    # Outlook / Gmail one-click (RFC 8058): POST with the token in the URL
    done = client.post(f"/api/public/unsubscribe?t={token}", data={"List-Unsubscribe": "One-Click"})
    assert "You're unsubscribed" in done.text
    assert client.get(f"/api/leads/{one['id']}").json()["unsubscribed_at"] is not None
    assert [l["id"] for l in client.get("/api/leads/page", params={"view": "unsubscribed"}).json()["items"]] == [one["id"]]
    assert any(n["title"] == "Lead unsubscribed" for n in client.get("/api/notifications").json())
    assert make(client, [one["id"]]).status_code == 400  # nobody left to email
    again = client.post("/api/public/unsubscribe", data={"t": token, "action": "subscribe"})
    assert "You're subscribed" in again.text and make(client, [one["id"]]).status_code == 201
    # a wrong token does nothing
    assert "isn't valid" in client.get("/api/public/unsubscribe", params={"t": f"{one['id']}.forged"}).text


def test_unsubscribing_while_queued_skips_the_lead(client, sent):
    one, two = lead(client), lead(client)
    campaign = make(client, [one["id"], two["id"]]).json()
    unsubscribe(client, two["id"])
    run_round()
    assert sent.to() == [one["email"]]
    counts = client.get(f"/api/campaigns/{campaign['id']}").json()["counts"]
    assert (counts["Sent"], counts["Skipped"]) == (1, 1)


def test_temporary_problems_are_retried_then_failed(client, sent):
    one = lead(client)
    sent.answers[one["email"]] = campaigns.Result("retry", "Outlook is busy (429)", wait=120)
    campaign = make(client, [one["id"]]).json()
    assert run_round()["retry"] == 1
    db = db_session()
    row = db.query(CampaignRecipient).filter_by(campaign_id=campaign["id"]).one()
    assert row.status == "Queued" and row.attempts == 1 and row.next_attempt_at >= now() + timedelta(minutes=4)
    for _ in range(3):  # pretend the wait is over, three more times
        row.next_attempt_at = now() - timedelta(seconds=1)
        db.commit()
        run_round()
        db.refresh(row)
    assert row.status == "Failed" and row.attempts == 4
    db.close()
    assert client.get(f"/api/campaigns/{campaign['id']}").json()["status"] == "Completed"


def test_wrong_mail_settings_pause_the_campaign(client, sent):
    one = lead(client)
    sent.answers[one["email"]] = campaigns.Result("setup", "The mail server refused the login")
    campaign = make(client, [one["id"]]).json()
    assert "paused" in run_round()
    detail = client.get(f"/api/campaigns/{campaign['id']}").json()
    assert detail["status"] == "Paused" and "refused the login" in detail["status_note"]
    assert detail["counts"]["Queued"] == 1
    del sent.answers[one["email"]]
    assert client.post(f"/api/campaigns/{campaign['id']}/resume").json()["status"] == "Sending"
    assert run_round()["sent"] == 1


def test_daily_limit_and_schedule(client, sent, monkeypatch):
    monkeypatch.setenv("CAMPAIGN_PER_DAY", "2")
    people = [lead(client) for _ in range(3)]
    later = make(client, [people[0]["id"]], send_at=(now() + timedelta(hours=2)).isoformat()).json()
    assert later["status"] == "Scheduled"
    make(client, [p["id"] for p in people])
    run_round()
    assert len(sent.items) == 2  # 2 in any 24 hours
    assert run_round().get("waiting") == "daily limit"
    assert client.get(f"/api/campaigns/{later['id']}").json()["status"] == "Scheduled"  # not due yet


def test_who_can_do_what(client, sent):
    mine = lead(client)
    priyas = lead(login_as(client, 1))
    login_as(client, 2)  # Ravi, Salesperson: only his own leads
    preview = client.post("/api/campaigns/preview", json={"lead_ids": [mine["id"], priyas["id"]]}).json()
    assert preview["eligible"] == 1
    campaign = make(client, [mine["id"], priyas["id"]]).json()
    assert campaign["counts"]["total"] == 1
    assert make(client, [mine["id"]], body="Hello {nickname}, how are you?").status_code == 400  # unknown merge field
    # the Manager can see and pause it; another salesperson can't even see it
    assert login_as(client, 1).post(f"/api/campaigns/{campaign['id']}/pause").json()["status"] == "Paused"
    assert login_as(client, 1).post(f"/api/campaigns/{campaign['id']}/cancel").json()["counts"]["Cancelled"] == 1
    assert run_round()["sent"] == 0
    # a lead's email can be marked valid again after fixing it
    login_as(client, 2)
    client.post(f"/api/leads/{mine['id']}/email-status", json={"status": "invalid"})
    assert client.post(f"/api/leads/{mine['id']}/email-status", json={"status": "valid"}).json()["email_status"] == "OK"
    # subscribing someone again needs a reason (only when the lead asked)
    unsubscribe(client, mine["id"])
    assert client.post(f"/api/leads/{mine['id']}/email-status", json={"status": "subscribed"}).status_code == 400


def test_same_email_twice_in_one_campaign_goes_once(client, sent):
    db = db_session()
    a, b = lead(client), lead(client)
    db.get(Lead, b["id"]).email = a["email"]
    db.commit()
    db.close()
    preview = client.post("/api/campaigns/preview", json={"lead_ids": [a["id"], b["id"]]}).json()
    assert (preview["eligible"], preview["reasons"]["other"]) == (1, 1)


def test_every_email_has_both_unsubscribe_and_subscribe_links(client, sent):
    one = lead(client)
    make(client, [one["id"]])
    run_round()
    body = sent.items[0]["body"]
    token = campaigns.unsubscribe_token(one["id"])
    assert f"Unsubscribe: " in body and f"unsubscribe?t={token}\n" in body
    assert f"Subscribe again: " in body and f"unsubscribe?t={token}&action=subscribe" in body
    # the Subscribe link asks first, and subscribes an unsubscribed lead again
    unsubscribe(client, one["id"])
    page = client.get("/api/public/unsubscribe", params={"t": token, "action": "subscribe"})
    assert "Subscribe again" in page.text and client.get(f"/api/leads/{one['id']}").json()["unsubscribed_at"]
    client.post("/api/public/unsubscribe", data={"t": token, "action": "subscribe"})
    assert client.get(f"/api/leads/{one['id']}").json()["unsubscribed_at"] is None


def test_cancel_on_the_unsubscribe_page_changes_nothing(client, sent):
    one = lead(client)
    token = campaigns.unsubscribe_token(one["id"])
    page = client.get("/api/public/unsubscribe", params={"t": token, "action": "cancel"})
    assert "Nothing changed" in page.text and "still subscribed" in page.text
    assert client.get(f"/api/leads/{one['id']}").json()["unsubscribed_at"] is None


def test_email_dashboard_totals(client, sent):
    good, bad, gone, blank = lead(client), lead(client, first="Zed"), lead(client), lead(client, email=False)
    sent.answers[bad["email"]] = campaigns.Result("invalid", "550 5.1.1 User unknown")
    unsubscribe(client, gone["id"])
    make(client, [good["id"], bad["id"], gone["id"], blank["id"]])
    run_round()
    body = client.get("/api/campaigns/summary").json()
    assert body["campaigns"] == 1
    assert body["emails"] == {"sent": 1, "failed": 0, "invalid": 1, "queued": 0, "left_out": 2}
    assert body["leads"] == {"working": 1, "invalid": 1, "unsubscribed": 1, "no_email": 1}
    # another salesperson sees only their own campaigns and leads
    from tests.conftest import login_as
    other = login_as(client, 1).get("/api/campaigns/summary").json()  # a Manager sees the team
    assert other["emails"]["sent"] == 1


def test_a_real_email_is_built_and_handed_to_the_mail_server(monkeypatch):
    """send_one itself (the other tests replace it): the message is built and sent through SMTP, with the
    one-click unsubscribe header on one line and both links in the body. The SMTP server is a stand-in."""
    monkeypatch.setenv("SMTP_HOST", "mail.test")
    monkeypatch.setenv("SMTP_PORT", "1025")
    handed = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            handed.append(msg.as_bytes())

    monkeypatch.setattr(campaigns.smtplib, "SMTP", FakeSMTP)
    link = campaigns.unsubscribe_link(42)
    body = "Hi Mia,\n\n" + "A long line of text for the email. " * 20 + campaigns.footer(42)
    result = campaigns.send_one("mia@bluebird.example", "Hello", body, sender_name="Asha Rao",
                                reply_to="asha@company.example", unsubscribe=link)
    assert result.outcome == "sent", result
    raw = handed[0].decode()
    assert f"List-Unsubscribe: <{link}>\r\n" in raw  # one line, not folded
    assert "List-Unsubscribe-Post: List-Unsubscribe=One-Click" in raw
    assert all(len(line) <= 78 for line in raw.split("\r\n\r\n", 1)[1].splitlines())  # quoted-printable body
