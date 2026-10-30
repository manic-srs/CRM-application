"""Change Stage popup with files (POST /api/opportunities/{id}/stage-with-files): the stage change and its files are
saved together, or nothing is saved. Uses the made-up files and helpers of test_opportunity_attachments.py."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mailer
from app.models import Contact, Notification, Opportunity, OpportunityAttachment, StageHistory, Task, User
from app.routers import opportunities
from app.routers.attachments import MAX_FILE_BYTES
from app.routers.opportunities import STAGE_MAX_FILES, STAGE_MAX_REQUEST_BYTES
from conftest import login_as
from test_opportunity_attachments import (ASHA, DOCX, DOCX_SAMPLE, JPEG, PDF, PNG, PRIYA, RAVI, add_salesperson,
                                          db_session, jpeg_file, move, new_opportunity, pdf_file, png_file, saved,
                                          stored_rows, url, zip_file)


@pytest.fixture(autouse=True)
def sent(monkeypatch, client):
    """Notification emails are recorded here instead of being sent. Ravi wants stage emails, so every saved
    stage change of his deals sends one (and a refused save sends none)."""
    messages = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **k: messages.append((to, subject)))
    with db_session() as db:
        db.get(User, RAVI).email_stage_updates = True
        db.commit()
    return messages


def stage_url(opp_id):
    return f"/api/opportunities/{opp_id}/stage-with-files"


def change(client, opp_id, stage, files, note=None):
    form = {"stage": stage} | ({"note": note} if note is not None else {})
    return client.post(stage_url(opp_id), data=form, files=[("files", f) for f in files])


def state(opp_id):
    """Everything a stage change touches, to check that a refused save changed nothing."""
    with db_session() as db:
        opp = db.get(Opportunity, opp_id)
        return {
            "stage": opp.stage,
            "probability": opp.probability,
            "final_value": opp.final_value,
            "closed_at": opp.closed_at,
            "history": db.scalars(select(StageHistory.id).where(StageHistory.opportunity_id == opp_id)).all(),
            "tasks": sorted((t.id, t.title, t.status) for t in db.scalars(select(Task).where(Task.opportunity_id == opp_id))),
            "notifications": db.scalar(select(func.count(Notification.id)).where(Notification.link == f"/opportunities/{opp_id}")),
            "files": db.scalar(select(func.count(OpportunityAttachment.id))),
        }


def summary(client, opp_id):
    """Stage, probability, tasks and history as the record page shows them (ids left out, to compare two deals)."""
    detail = client.get(f"/api/opportunities/{opp_id}").json()
    return (detail["stage"], detail["probability"], sorted((t["title"].split(" - ")[0], t["status"]) for t in detail["tasks"]),
            [(h["from_stage"], h["to_stage"], h["note"]) for h in detail["history"]])


FOUR_FILES = [("proposal.pdf", pdf_file(), PDF), ("Plan.docx", DOCX_SAMPLE, DOCX), ("photo.jpeg", jpeg_file(), JPEG),
              ("chart.png", png_file(), PNG)]


# ---------- saving ----------

def test_files_are_saved_with_the_stage_change_and_get_the_new_stage(client, sent):
    opp = new_opportunity(client)
    sent.clear()
    res = change(client, opp["id"], "Proposal", FOUR_FILES, note="Sent the proposal")
    assert res.status_code == 200, res.text
    assert (res.json()["stage"], res.json()["probability"]) == ("Proposal", 75)

    files = client.get(url(opp["id"])).json()
    assert sorted((f["filename"], f["content_type"], f["stage"], f["uploaded_by_name"]) for f in files) == sorted(
        (name, kind, "Proposal", "Ravi Kumar") for name, _, kind in FOUR_FILES)
    for f in files:  # the stored bytes are the uploaded ones
        original = next(data for name, data, _ in FOUR_FILES if name == f["filename"])
        assert client.get(url(opp["id"], f["id"], "/file")).content == original
    assert [to for to, _ in sent] == [["ravi@crm.test"]]  # one "moved to Proposal" email to the owner

    # the stage change itself is the same as PUT /stage without files
    other = new_opportunity(client)
    assert client.put(f"/api/opportunities/{other['id']}/stage", json={"stage": "Proposal", "note": "Sent the proposal"}).status_code == 200
    assert summary(client, opp["id"]) == summary(client, other["id"])
    assert summary(client, opp["id"])[3][-1] == ("Opportunity", "Proposal", "Sent the proposal")


def test_moving_back_to_opportunity_labels_the_new_files_opportunity(client):
    opp = new_opportunity(client)
    move(client, opp["id"], "Proposal")
    earlier = saved(client, opp["id"], "quote-v1.pdf", pdf_file())  # from the Attachments card, at Proposal
    res = change(client, opp["id"], "Opportunity", [("revised-scope.docx", DOCX_SAMPLE, DOCX)], note="Scope changed")
    assert res.status_code == 200, res.text
    assert res.json()["stage"] == "Opportunity"
    stages = {f["filename"]: f["stage"] for f in client.get(url(opp["id"])).json()}
    assert stages == {"quote-v1.pdf": "Proposal", "revised-scope.docx": "Opportunity"}
    assert earlier["stage"] == "Proposal"


def test_size_limit_is_20_mib_per_file(client):
    opp = new_opportunity(client)
    before = state(opp["id"])
    over = change(client, opp["id"], "Proposal", [("small.png", png_file(), PNG),
                                                  ("one-byte-over.pdf", pdf_file(MAX_FILE_BYTES + 1), PDF)])
    assert over.status_code == 413 and "one-byte-over.pdf is larger than 20 MB" in over.json()["detail"]
    assert state(opp["id"]) == before
    exact = change(client, opp["id"], "Proposal", [("exactly-20mib.pdf", pdf_file(MAX_FILE_BYTES), PDF)])
    assert exact.status_code == 200, exact.text
    assert [(r.filename, r.size_bytes, r.stage) for r in stored_rows()] == [("exactly-20mib.pdf", MAX_FILE_BYTES, "Proposal")]


@pytest.mark.parametrize("name, data, status, message", [
    ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, 415, "old Word files (.doc)"),
    ("notes.txt", b"hello", 415, "only PDF, Word (.docx), JPG and PNG"),
    ("empty.pdf", b"", 422, "empty.pdf is empty"),
    ("report.pdf", png_file(), 415, "is really a PNG image"),
    ("fake.png", b"GIF89a" + b"\x00" * 40, 415, "isn't a real PNG image"),
    ("cut-off.pdf", pdf_file()[:-8], 422, "damaged or incomplete"),
    ("proposal.docx", zip_file({"readme.txt": "just a zip"}), 415, "isn't a Word document"),
    ("proposal.docx", b"PK\x03\x04" + b"\x00" * 200, 422, "looks damaged"),
])
def test_a_refused_file_means_nothing_is_saved(client, sent, name, data, status, message):
    opp = new_opportunity(client)
    before = state(opp["id"])
    sent.clear()
    # a good file first: it must not be saved on its own
    res = change(client, opp["id"], "Proposal", [("good.pdf", pdf_file(), PDF), (name, data, PDF)], note="Should not be saved")
    assert res.status_code == status, res.text
    assert message in res.json()["detail"] and name in res.json()["detail"]
    assert state(opp["id"]) == before  # same stage, history, tasks and notifications; no file
    assert sent == []  # no "moved to Proposal" email


def test_a_failed_save_can_be_retried_without_duplicates(client, sent):
    opp = new_opportunity(client)
    before = state(opp["id"])

    def broken_commit(self):
        raise RuntimeError("database went away")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Session, "commit", broken_commit)
        with pytest.raises(RuntimeError):
            change(client, opp["id"], "Proposal", [("quote.pdf", pdf_file(), PDF)])
    assert state(opp["id"]) == before

    sent.clear()
    assert change(client, opp["id"], "Proposal", [("quote.pdf", pdf_file(), PDF)], note="Retry").status_code == 200
    again = change(client, opp["id"], "Proposal", [("quote.pdf", pdf_file(), PDF)], note="Retry")  # e.g. a double click
    assert again.status_code == 400 and "already at Proposal" in again.json()["detail"]
    after = state(opp["id"])
    assert after["files"] == 1 and len(after["history"]) == len(before["history"]) + 1
    assert after["notifications"] == before["notifications"] + 1 and len(sent) == 1
    assert len([t for t in after["tasks"] if t[2] == "Open" and t[1].startswith("Follow up on proposal")]) == 1


# ---------- form ----------

def test_the_form_is_checked(client):
    opp = new_opportunity(client)
    pdf = ("quote.pdf", pdf_file(), PDF)
    assert change(client, opp["id"], "Proposal", []).status_code == 422  # no files: PUT /stage is for that
    too_many = change(client, opp["id"], "Proposal", [pdf] * (STAGE_MAX_FILES + 1))
    assert too_many.status_code == 400
    assert change(client, opp["id"], "Proposal", [pdf] * STAGE_MAX_FILES).status_code == 200  # 5 is fine
    assert len(stored_rows()) == STAGE_MAX_FILES
    opp = new_opportunity(client)
    before = state(opp["id"])
    assert change(client, opp["id"], "Won", [pdf]).status_code == 422  # Won / Lost have their own popups
    assert client.post(stage_url(opp["id"]), files=[("files", pdf)]).status_code == 422  # no stage
    assert change(client, opp["id"], "Opportunity", [pdf]).status_code == 400  # already there
    extra = client.post(stage_url(opp["id"]), data={"stage": "Proposal", "owner_id": "1"}, files=[("files", pdf)])
    assert extra.status_code == 400
    other_name = client.post(stage_url(opp["id"]), data={"stage": "Proposal"}, files=[("file", pdf)])
    assert other_name.status_code == 400 and "Unknown form field: file" in other_name.json()["detail"]

    def chunked():
        yield b"--x\r\nContent-Disposition: form-data; name=\"stage\"\r\n\r\nProposal\r\n"
        yield b"--x\r\nContent-Disposition: form-data; name=\"files\"; filename=\"a.pdf\"\r\n\r\n" + pdf_file() + b"\r\n--x--\r\n"
    no_length = client.post(stage_url(opp["id"]), content=chunked(), headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert no_length.status_code == 411
    too_big = client.post(stage_url(opp["id"]), content=b"x" * (STAGE_MAX_REQUEST_BYTES + 1),
                          headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert too_big.status_code == 413  # refused from the request size, before anything is read
    assert state(opp["id"]) == before
    # 5 files of 20 MB plus the form fit, and nginx allows 102 MB for this address (frontend/nginx.conf)
    assert STAGE_MAX_FILES * MAX_FILE_BYTES < STAGE_MAX_REQUEST_BYTES <= 102 * 1024 * 1024


# ---------- login, access and closed deals ----------

def test_only_people_who_can_edit_the_deal_can_save(client):
    opp = new_opportunity(client)  # owned by Ravi
    pdf = [("quote.pdf", pdf_file(), PDF)]
    before = state(opp["id"])
    token = client.headers.pop("Authorization").split(" ", 1)[1]
    assert change(client, opp["id"], "Proposal", pdf).status_code == 401
    assert client.post(stage_url(opp["id"]), params={"token": token}, data={"stage": "Proposal"},
                       files=[("files", pdf[0])]).status_code == 401  # never a token in the address

    sam = add_salesperson(client)
    assert change(login_as(client, sam), opp["id"], "Proposal", pdf).status_code == 404  # can't see Ravi's deal
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    assert change(login_as(client, sam), opp["id"], "Proposal", pdf).status_code == 403  # team access is read-only
    assert login_as(client, ASHA).put("/api/permissions", json={"role": "Manager", "permission": "edit_team_records",
                                                                "allowed": False}).status_code == 200
    assert change(login_as(client, PRIYA), opp["id"], "Proposal", pdf).status_code == 403
    assert state(opp["id"]) == before

    assert login_as(client, ASHA).put("/api/permissions", json={"role": "Manager", "permission": "edit_team_records",
                                                                "allowed": True}).status_code == 200
    res = change(login_as(client, PRIYA), opp["id"], "Proposal", pdf)
    assert res.status_code == 200, res.text
    assert [(f["uploaded_by_name"], f["stage"]) for f in client.get(url(opp["id"])).json()] == [("Priya Sharma", "Proposal")]
    res = change(login_as(client, ASHA), opp["id"], "Opportunity", [("admin.png", png_file(), PNG)])
    assert res.status_code == 200, res.text


@pytest.mark.parametrize("close", [
    lambda client, opp_id: client.post(f"/api/opportunities/{opp_id}/won", json={"completed_stages": ["Proposal"]}),
    lambda client, opp_id: client.post(f"/api/opportunities/{opp_id}/lost", json={"lost_reason": "Price"}),
])
def test_closed_deals_take_no_stage_change_or_files(client, close):
    opp = new_opportunity(client)
    assert close(client, opp["id"]).status_code == 200
    before = state(opp["id"])
    res = change(client, opp["id"], "Proposal", [("late.pdf", pdf_file(), PDF)])
    assert res.status_code == 400 and "closed" in res.json()["detail"]
    assert state(opp["id"]) == before


def test_stage_changes_without_files_are_unchanged(client):
    opp = new_opportunity(client)
    res = client.put(f"/api/opportunities/{opp['id']}/stage", json={"stage": "Proposal", "note": "No files"})
    assert res.status_code == 200 and res.json()["stage"] == "Proposal"
    assert stored_rows() == []
    assert client.put(f"/api/opportunities/{opp['id']}/stage", json={"stage": "Proposal"}).status_code == 400


# ---------- Mark as Won with files (POST /api/opportunities/{id}/won-with-files) ----------

def won_url(opp_id):
    return f"/api/opportunities/{opp_id}/won-with-files"


def win(client, opp_id, files, **fields):
    """Mark as Won with files; fields are form fields (completed_stages may be a list)."""
    return client.post(won_url(opp_id), data=fields, files=[("files", f) for f in files])


def customer_emails(sent):
    return [to for to, subject in sent if subject.startswith("Thank you for choosing")]


def contact_email(opp):
    with db_session() as db:
        return db.get(Contact, opp["primary_contact_id"]).email


def test_mark_as_won_saves_the_amount_note_files_and_email_together(client, sent):
    opp = new_opportunity(client)
    move(client, opp["id"], "Proposal")
    sent.clear()
    res = win(client, opp["id"], FOUR_FILES, final_value="1500.50", note="Contract signed", notify_customer="true")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["stage"], body["probability"], body["final_value"]) == ("Won", 100, 1500.5)
    assert body["closed_at"] and body["history"][-1]["note"] == "Contract signed"

    # the files are labelled Proposal (the stage being closed), can be opened, but no file can be added or deleted
    files = client.get(url(opp["id"])).json()
    assert sorted((f["filename"], f["stage"], f["content_type"]) for f in files) == sorted(
        (name, "Proposal", kind) for name, _, kind in FOUR_FILES)
    for f in files:
        assert client.get(url(opp["id"], f["id"], "/file")).content == next(d for n, d, _ in FOUR_FILES if n == f["filename"])
    assert saved_status(client, opp["id"]) == 409
    assert client.delete(url(opp["id"], files[0]["id"])).status_code == 409

    # one thank-you email to the deal's contact, sent after the save; the owner hears about Won as before
    assert customer_emails(sent) == [[contact_email(opp)]]
    assert [to for to, subject in sent if subject.startswith("[SalesTrack]")] == [["ravi@crm.test"]]

    # the Won change itself is the same as POST /won without files
    other = new_opportunity(client)
    move(client, other["id"], "Proposal")
    assert client.post(f"/api/opportunities/{other['id']}/won",
                       json={"final_value": 1500.5, "note": "Contract signed"}).status_code == 200
    assert summary(client, opp["id"]) == summary(client, other["id"])
    assert all(t["status"] != "Open" for t in client.get(f"/api/opportunities/{opp['id']}").json()["tasks"])


def saved_status(client, opp_id):
    return client.post(url(opp_id), files={"file": ("late.pdf", pdf_file(), PDF)}).status_code


def test_won_from_opportunity_needs_proposal_confirmed_and_files_stay_proposal(client, sent):
    opp = new_opportunity(client)  # at Opportunity: Proposal is skipped, so it must be confirmed as done
    before = state(opp["id"])
    sent.clear()
    refused = win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], notify_customer="true")
    assert refused.status_code == 409 and "Complete Proposal" in refused.json()["detail"]
    assert state(opp["id"]) == before and sent == []

    res = win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], completed_stages=["Proposal"],
              completed_note="Sent by email", notify_customer="false")
    assert res.status_code == 200, res.text
    assert [(h["from_stage"], h["to_stage"]) for h in res.json()["history"]][-2:] == [("Opportunity", "Proposal"),
                                                                                     ("Proposal", "Won")]
    assert res.json()["final_value"] == 1000  # no amount given: the expected value
    assert [(f["filename"], f["stage"]) for f in client.get(url(opp["id"])).json()] == [("quote.pdf", "Proposal")]
    assert customer_emails(sent) == []  # not chosen


@pytest.mark.parametrize("final_value, status, message", [
    ("-5", 422, "final_value"),
    ("abc", 422, "final_value"),
])
def test_an_invalid_amount_saves_nothing(client, sent, final_value, status, message):
    opp = new_opportunity(client)
    move(client, opp["id"], "Proposal")
    before = state(opp["id"])
    sent.clear()
    res = win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], final_value=final_value, notify_customer="true")
    assert res.status_code == status and message in res.json()["detail"]
    assert state(opp["id"]) == before and sent == []


def test_a_deal_without_an_amount_needs_one(client, sent):
    login_as(client, RAVI)
    lead = client.post("/api/leads", json={"last_name": "NoAmount", "company": "Synthetic Co",
                                           "email": "no.amount@example.test", "welcome_email": False}).json()
    opp = client.post(f"/api/leads/{lead['id']}/convert", json={"completed_stages": ["Nurturing", "Demo"]}).json()["opportunity"]
    move(client, opp["id"], "Proposal")
    before = state(opp["id"])
    sent.clear()
    res = win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], notify_customer="true")
    assert res.status_code == 400 and "final_value is required" in res.json()["detail"]
    assert state(opp["id"]) == before and sent == []
    assert win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], final_value="0").status_code == 200  # 0 is allowed


@pytest.mark.parametrize("name, data, status, message", [
    ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, 415, "old Word files (.doc)"),
    ("report.pdf", png_file(), 415, "is really a PNG image"),
    ("empty.pdf", b"", 422, "empty.pdf is empty"),
    ("proposal.docx", b"PK\x03\x04" + b"\x00" * 200, 422, "looks damaged"),
    ("one-byte-over.pdf", pdf_file(MAX_FILE_BYTES + 1), 413, "larger than 20 MB"),
])
def test_a_refused_file_means_the_deal_is_not_won(client, sent, name, data, status, message):
    opp = new_opportunity(client)
    move(client, opp["id"], "Proposal")
    before = state(opp["id"])
    sent.clear()
    res = win(client, opp["id"], [("good.pdf", pdf_file(), PDF), (name, data, PDF)], final_value="2000",
              note="Should not be saved", notify_customer="true")
    assert res.status_code == status, res.text
    assert message in res.json()["detail"]
    assert state(opp["id"]) == before  # still Proposal: no amount, closed date, history, task change or file
    assert sent == []  # no thank-you email, no Won notification


def test_a_failed_won_save_can_be_retried_without_duplicates(client, sent):
    opp = new_opportunity(client)
    move(client, opp["id"], "Proposal")
    before = state(opp["id"])
    sent.clear()

    def broken_commit(self):
        raise RuntimeError("database went away")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Session, "commit", broken_commit)
        with pytest.raises(RuntimeError):
            win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], final_value="900", notify_customer="true")
    assert state(opp["id"]) == before and sent == []  # the queued email was never sent

    assert win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], final_value="900", notify_customer="true").status_code == 200
    again = win(client, opp["id"], [("quote.pdf", pdf_file(), PDF)], final_value="900", notify_customer="true")
    assert again.status_code == 400 and "closed" in again.json()["detail"]  # e.g. a double click
    after = state(opp["id"])
    assert (after["stage"], after["final_value"], after["files"]) == ("Won", 900, 1)
    assert len(after["history"]) == len(before["history"]) + 1
    assert len(customer_emails(sent)) == 1


@pytest.mark.parametrize("save", [
    lambda client, opp_id: change(client, opp_id, "Proposal", [("quote.pdf", pdf_file(), PDF)]),
    lambda client, opp_id: win(client, opp_id, [("quote.pdf", pdf_file(), PDF)], completed_stages=["Proposal"],
                               notify_customer="true"),
])
def test_a_failure_after_the_files_are_added_saves_nothing(client, sent, save):
    """The files are added first; if a later step of the same save fails, they are not kept on their own."""
    opp = new_opportunity(client)
    before = state(opp["id"])
    sent.clear()

    def broken_notice(*args, **kwargs):
        raise RuntimeError("notification failed")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(opportunities, "stage_notice", broken_notice)
        with pytest.raises(RuntimeError):
            save(client, opp["id"])
    assert state(opp["id"]) == before and sent == []


def test_the_won_form_is_checked(client):
    opp = new_opportunity(client)
    move(client, opp["id"], "Proposal")
    before = state(opp["id"])
    pdf = ("quote.pdf", pdf_file(), PDF)
    assert win(client, opp["id"], [], final_value="10").status_code == 422  # no files: POST /won is for that
    assert win(client, opp["id"], [pdf] * (STAGE_MAX_FILES + 1)).status_code == 400
    extra = win(client, opp["id"], [pdf], lost_reason="Price")
    assert extra.status_code == 400 and "Unknown form field: lost_reason" in extra.json()["detail"]

    def chunked():
        yield b"--x\r\nContent-Disposition: form-data; name=\"files\"; filename=\"a.pdf\"\r\n\r\n" + pdf_file() + b"\r\n--x--\r\n"
    no_length = client.post(won_url(opp["id"]), content=chunked(), headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert no_length.status_code == 411
    assert state(opp["id"]) == before


def test_only_people_who_can_edit_the_deal_can_mark_it_won_with_files(client):
    opp = new_opportunity(client)  # owned by Ravi
    move(client, opp["id"], "Proposal")
    pdf = [("quote.pdf", pdf_file(), PDF)]
    before = state(opp["id"])
    token = client.headers.pop("Authorization").split(" ", 1)[1]
    assert win(client, opp["id"], pdf).status_code == 401
    assert client.post(won_url(opp["id"]), params={"token": token}, files=[("files", pdf[0])]).status_code == 401

    sam = add_salesperson(client)
    assert win(login_as(client, sam), opp["id"], pdf).status_code == 404
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    assert win(login_as(client, sam), opp["id"], pdf).status_code == 403
    assert login_as(client, ASHA).put("/api/permissions", json={"role": "Manager", "permission": "edit_team_records",
                                                                "allowed": False}).status_code == 200
    assert win(login_as(client, PRIYA), opp["id"], pdf).status_code == 403
    assert state(opp["id"]) == before

    assert login_as(client, ASHA).put("/api/permissions", json={"role": "Manager", "permission": "edit_team_records",
                                                                "allowed": True}).status_code == 200
    res = win(login_as(client, PRIYA), opp["id"], pdf, notify_customer="false")
    assert res.status_code == 200 and res.json()["stage"] == "Won"
    assert [(f["uploaded_by_name"], f["stage"]) for f in client.get(url(opp["id"])).json()] == [("Priya Sharma", "Proposal")]


@pytest.mark.parametrize("close", [
    lambda client, opp_id: client.post(f"/api/opportunities/{opp_id}/won", json={"completed_stages": ["Proposal"]}),
    lambda client, opp_id: client.post(f"/api/opportunities/{opp_id}/lost", json={"lost_reason": "Price"}),
])
def test_closed_deals_cant_be_won_with_files(client, sent, close):
    opp = new_opportunity(client)
    assert close(client, opp["id"]).status_code == 200
    before = state(opp["id"])
    sent.clear()
    res = win(client, opp["id"], [("late.pdf", pdf_file(), PDF)], completed_stages=["Proposal"], notify_customer="true")
    assert res.status_code == 400 and "closed" in res.json()["detail"]
    assert state(opp["id"]) == before and sent == []
    assert saved_status(client, opp["id"]) == 409  # the Attachments card stays closed too
