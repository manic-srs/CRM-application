"""Opportunity attachments: file checks, size limit, stages, access, soft delete. All files are made up here."""
import io
import itertools
import struct
import zipfile
import zlib

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app import mailer
from app.database import get_db
from app.main import app
from app.models import ActivityLog, OpportunityAttachment
from app.routers.attachments import MAX_FILE_BYTES, MAX_REQUEST_BYTES
from app.security import make_token
from conftest import login_as

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin (see conftest.py)
PDF, DOCX, JPEG, PNG = ("application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "image/jpeg", "image/png")
LEADS = itertools.count(1)


@pytest.fixture(autouse=True)
def no_email(monkeypatch):
    """Nothing in these tests is ever sent (notification emails go nowhere)."""
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)


def db_session():
    return next(app.dependency_overrides[get_db]())


# ---------- made-up files ----------

def pdf_file(size: int | None = None) -> bytes:
    head = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n"
    end = b"%%EOF\n"
    if size is None:
        return head + end
    return head + b"%" + b"0" * (size - len(head) - len(end) - 2) + b"\n" + end


def png_file() -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def jpeg_file() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 32 + b"\xff\xd9"


WORD_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType="{main}"/></Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="word/document.xml"/></Relationships>')
DOCUMENT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Synthetic test proposal</w:t></w:r></w:p></w:body></w:document>')


def zip_file(parts: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in parts.items():
            package.writestr(name, content)
    return buffer.getvalue()


def docx_file(main: str = WORD_MAIN, changes: dict | None = None) -> bytes:
    """A minimal Word package; changes replaces parts (None removes one)."""
    parts = {"[Content_Types].xml": CONTENT_TYPES.format(main=main), "_rels/.rels": RELS, "word/document.xml": DOCUMENT}
    parts.update(changes or {})
    return zip_file({k: v for k, v in parts.items() if v is not None})


DOCX_SAMPLE = docx_file()  # zip files carry a timestamp: build once so downloads can be compared byte for byte


# ---------- helpers ----------

def new_opportunity(client, owner=RAVI) -> dict:
    login_as(client, owner)
    res = client.post("/api/leads", json={"first_name": "Test", "last_name": f"Buyer{next(LEADS)}",
                                          "company": "Synthetic Co", "email": f"buyer{next(LEADS)}@example.test",
                                          "welcome_email": False})
    assert res.status_code == 201, res.text
    res = client.post(f"/api/leads/{res.json()['id']}/convert", json={"completed_stages": ["Nurturing", "Demo"],
                                                                      "expected_value": 1000})
    assert res.status_code == 200, res.text
    return res.json()["opportunity"]


def url(opp_id, attachment_id=None, suffix=""):
    base = f"/api/opportunities/{opp_id}/attachments"
    return f"{base}/{attachment_id}{suffix}" if attachment_id is not None else base


def upload(client, opp_id, name, data, browser_type="application/octet-stream"):
    return client.post(url(opp_id), files={"file": (name, data, browser_type)})


def saved(client, opp_id, name, data):
    res = upload(client, opp_id, name, data)
    assert res.status_code == 201, res.text
    return res.json()


def stored_rows():
    with db_session() as db:
        return db.scalars(select(OpportunityAttachment)).all()


def move(client, opp_id, stage):
    res = client.put(f"/api/opportunities/{opp_id}/stage", json={"stage": stage})
    assert res.status_code == 200, res.text


def add_salesperson(client, name="Sam Tester", email="sam@crm.test") -> int:
    res = login_as(client, ASHA).post("/api/users", json={"full_name": name, "email": email,
                                                          "password": "Password123", "role": "Salesperson"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ---------- formats, preview and download ----------

def test_each_supported_format_is_saved_with_the_type_the_server_detected(client):
    opp = new_opportunity(client)
    files = [("proposal.pdf", pdf_file(), PDF), ("Contract.DOCX", DOCX_SAMPLE, DOCX), ("site.jpg", jpeg_file(), JPEG),
             ("team.jpeg", jpeg_file(), JPEG), ("logo.png", png_file(), PNG)]
    for name, data, kind in files:
        # the browser's file type is ignored (here it claims every file is text)
        res = upload(client, opp["id"], name, data, browser_type="text/html")
        assert res.status_code == 201, res.text
        body = res.json()
        assert (body["filename"], body["content_type"], body["size_bytes"]) == (name, kind, len(data))
        assert (body["stage"], body["uploaded_by_id"], body["uploaded_by_name"]) == ("Opportunity", RAVI, "Ravi Kumar")
        assert body["uploaded_at"] and "data" not in body

    listed = client.get(url(opp["id"]))
    assert listed.status_code == 200
    assert [a["filename"] for a in listed.json()] == [f[0] for f in reversed(files)]  # newest first
    assert all("data" not in a for a in listed.json())

    for item, (name, data, kind) in zip(reversed(listed.json()), files):
        preview = client.get(url(opp["id"], item["id"], "/file"))
        assert preview.status_code == 200 and preview.content == data
        assert preview.headers["content-type"] == kind
        assert preview.headers["x-content-type-options"] == "nosniff"
        assert preview.headers["cache-control"] == "private, no-store"
        disposition = preview.headers["content-disposition"]
        assert disposition.startswith("attachment" if kind == DOCX else "inline")  # Word files are never shown inline
        assert f"filename*=UTF-8''{name}" in disposition
        saved_copy = client.get(url(opp["id"], item["id"], "/file"), params={"download": "true"})
        assert saved_copy.headers["content-disposition"].startswith("attachment;") and saved_copy.content == data


def test_list_never_reads_the_file_bytes(client):
    opp = new_opportunity(client)
    saved(client, opp["id"], "big.pdf", pdf_file(200_000))
    statements = []
    engine = db_session().get_bind()
    listener = lambda conn, cursor, sql, *a: statements.append(sql)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert len(client.get(url(opp["id"])).json()) == 1
        list_sql = [s for s in statements if "opportunity_attachments" in s]
        assert list_sql and not any("opportunity_attachments.data" in s for s in list_sql)
        statements.clear()
        client.get(url(opp["id"], stored_rows()[0].id, "/file"))
        assert any("opportunity_attachments.data" in s for s in statements)  # only the download loads them
    finally:
        event.remove(engine, "before_cursor_execute", listener)


def test_file_names_are_cleaned_and_sent_safely(client):
    opp = new_opportunity(client)
    assert saved(client, opp["id"], "../../etc/passwd/report.pdf", pdf_file())["filename"] == "report.pdf"
    assert saved(client, opp["id"], "C:\\Users\\x\\plan.pdf", pdf_file())["filename"] == "plan.pdf"
    assert saved(client, opp["id"], "inv\u202egnp.pdf", pdf_file())["filename"] == "invgnp.pdf"  # text-direction trick
    assert saved(client, opp["id"], "  quote\t\t v2 .pdf", pdf_file())["filename"] == "quote v2 .pdf"
    assert saved(client, opp["id"], "line\nbreak.pdf", pdf_file())["filename"] == "line break.pdf"
    long = saved(client, opp["id"], "a" * 300 + ".pdf", pdf_file())["filename"]
    assert len(long) == 255 and long.endswith(".pdf")
    odd = saved(client, opp["id"], 'Préis "Angebot"; x.pdf', pdf_file())
    disposition = client.get(url(opp["id"], odd["id"], "/file")).headers["content-disposition"]
    assert disposition.startswith('inline; filename="Pr_is _Angebot__ x.pdf"; ')  # ASCII fallback without quotes
    assert "filename*=UTF-8''Pr%C3%A9is%20%22Angebot%22%3B%20x.pdf" in disposition


# ---------- size ----------

def test_size_limit_is_20_mib_per_file(client):
    opp = new_opportunity(client)
    exact = saved(client, opp["id"], "exactly-20mib.pdf", pdf_file(MAX_FILE_BYTES))
    assert exact["size_bytes"] == 20 * 1024 * 1024
    one_over = upload(client, opp["id"], "one-byte-over.pdf", pdf_file(MAX_FILE_BYTES + 1))
    assert one_over.status_code == 413 and "larger than 20 MB" in one_over.json()["detail"]
    far_over = upload(client, opp["id"], "far-over.pdf", pdf_file(MAX_REQUEST_BYTES + 1))
    assert far_over.status_code == 413  # refused from the request size, before the file is read
    assert upload(client, opp["id"], "empty.pdf", b"").status_code == 422
    assert [r.filename for r in stored_rows()] == ["exactly-20mib.pdf"]


def test_one_file_per_request(client):
    opp = new_opportunity(client)
    two = client.post(url(opp["id"]), files=[("file", ("a.pdf", pdf_file(), PDF)), ("file", ("b.pdf", pdf_file(), PDF))])
    assert two.status_code == 400
    extra_field = client.post(url(opp["id"]), data={"note": "x"}, files={"file": ("a.pdf", pdf_file(), PDF)})
    assert extra_field.status_code == 400
    assert client.post(url(opp["id"]), files={"other": ("a.pdf", pdf_file(), PDF)}).status_code == 422
    assert client.post(url(opp["id"]), json={"file": "a.pdf"}).status_code == 422

    def chunked():
        yield b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.pdf\"\r\n\r\n"
        yield pdf_file() + b"\r\n--x--\r\n"
    no_length = client.post(url(opp["id"]), content=chunked(), headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert no_length.status_code == 411
    assert stored_rows() == []


# ---------- unsupported, mismatched and damaged files ----------

@pytest.mark.parametrize("name, data, status, message", [
    ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, 415, "old Word files (.doc)"),
    ("notes.txt", b"hello", 415, "only PDF, Word (.docx), JPG and PNG"),
    ("setup.exe", b"MZ\x90\x00", 415, "only PDF"),
    ("page.html", b"<html><script>alert(1)</script></html>", 415, "only PDF"),
    ("no-extension", pdf_file(), 415, "only PDF"),
    ("logo.png", pdf_file(), 415, "is really a PDF"),
    ("report.pdf", png_file(), 415, "is really a PNG image"),
    ("photo.jpg", png_file(), 415, "is really a PNG image"),
    ("report.pdf", DOCX_SAMPLE, 415, "is really a Word document"),
    ("fake.pdf", b"<html><script>alert(1)</script></html>", 415, "isn't a real PDF"),
    ("fake.png", b"GIF89a" + b"\x00" * 40, 415, "isn't a real PNG image"),
    ("cut-off.pdf", pdf_file()[:-8], 422, "damaged or incomplete"),
    ("cut-off.png", png_file()[:-12], 422, "damaged or incomplete"),
    ("cut-off.jpg", jpeg_file()[:-2], 422, "damaged or incomplete"),
])
def test_unsupported_and_mismatched_files_are_refused(client, name, data, status, message):
    opp = new_opportunity(client)
    res = upload(client, opp["id"], name, data, browser_type=PDF)  # the browser's type can't make a file pass
    assert res.status_code == status, res.text
    assert message in res.json()["detail"]
    assert stored_rows() == []


@pytest.mark.parametrize("data, status, message", [
    (zip_file({"readme.txt": "just a zip"}), 415, "isn't a Word document"),
    (docx_file(main="application/vnd.ms-word.document.macroEnabled.main+xml"), 415, "isn't a Word document"),  # .docm
    (docx_file(main="application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"), 415,
     "isn't a Word document"),  # .dotx
    (docx_file(main="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"), 415,
     "isn't a Word document"),  # a spreadsheet package
    (docx_file(changes={"word/document.xml": None}), 415, "isn't a Word document"),  # the main part is missing
    (docx_file(changes={"_rels/.rels": None}), 415, "isn't a Word document"),
    (docx_file(changes={"_rels/.rels": RELS.replace("/officeDocument", "/other")}), 415, "isn't a Word document"),
    (docx_file(changes={"[Content_Types].xml": "<Types><broken"}), 422, "looks damaged"),
    (docx_file(changes={"[Content_Types].xml": '<!DOCTYPE x [<!ENTITY a "aaaa">]><Types>&a;</Types>'}), 422,
     "looks damaged"),
    (docx_file(changes={"[Content_Types].xml": " " * (300 * 1024)}), 422, "looks damaged"),  # oversized part (zip bomb style)
    (b"PK\x03\x04" + b"\x00" * 200, 422, "looks damaged"),  # zip header, no real archive
    (DOCX_SAMPLE[: len(DOCX_SAMPLE) // 2], 422, "looks damaged"),  # cut off
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, 415, "old-format or password-protected"),
    (b"junk" + DOCX_SAMPLE, 415, "isn't a real Word document"),  # data before the zip
])
def test_invalid_docx_packages_are_refused(client, data, status, message):
    opp = new_opportunity(client)
    res = upload(client, opp["id"], "proposal.docx", data, browser_type=DOCX)
    assert res.status_code == status, res.text
    assert message in res.json()["detail"]
    assert stored_rows() == []


def test_failed_save_leaves_no_partial_upload(client):
    opp = new_opportunity(client)

    def broken_commit(self):
        raise RuntimeError("database went away")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Session, "commit", broken_commit)
        with pytest.raises(RuntimeError):
            upload(client, opp["id"], "proposal.pdf", pdf_file())
    assert stored_rows() == []
    assert saved(client, opp["id"], "proposal.pdf", pdf_file())["filename"] == "proposal.pdf"  # works again afterwards


# ---------- login and access ----------

def test_every_request_needs_the_login_header(client):
    opp = new_opportunity(client)
    item = saved(client, opp["id"], "proposal.pdf", pdf_file())
    token = client.headers.pop("Authorization").split(" ", 1)[1]
    requests = [("get", url(opp["id"])), ("post", url(opp["id"])), ("get", url(opp["id"], item["id"], "/file")),
                ("delete", url(opp["id"], item["id"]))]
    for method, path in requests:
        assert getattr(client, method)(path).status_code == 401
        # a token in the address is not accepted for files (no shareable file links)
        assert getattr(client, method)(path, params={"token": token}).status_code == 401
    assert client.get(url(opp["id"]), headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get(url(opp["id"]), headers={"Authorization": f"Bearer {make_token(RAVI)}"}).status_code == 200


def test_access_follows_the_opportunity(client):
    opp = new_opportunity(client)  # owned by Ravi
    item = saved(client, opp["id"], "proposal.pdf", pdf_file())
    sam = add_salesperson(client)

    # another salesperson can't see Ravi's deal, so its files "don't exist"
    login_as(client, sam)
    assert client.get(url(opp["id"])).status_code == 404
    assert client.get(url(opp["id"], item["id"], "/file")).status_code == 404
    assert upload(client, opp["id"], "mine.pdf", pdf_file()).status_code == 404
    assert client.delete(url(opp["id"], item["id"])).status_code == 404

    # with team access (read-only) Sam can view and download, but not upload or delete
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    login_as(client, sam)
    assert [a["id"] for a in client.get(url(opp["id"])).json()] == [item["id"]]
    assert client.get(url(opp["id"], item["id"], "/file")).status_code == 200
    assert upload(client, opp["id"], "mine.pdf", pdf_file()).status_code == 403
    assert client.delete(url(opp["id"], item["id"])).status_code == 403

    # Manager and Admin can edit any deal, so they can upload
    assert saved(login_as(client, PRIYA), opp["id"], "manager.pdf", pdf_file())["uploaded_by_name"] == "Priya Sharma"
    assert saved(login_as(client, ASHA), opp["id"], "admin.png", png_file())["uploaded_by_name"] == "Asha Rao"

    # a Manager whose "Edit team records" permission is removed can't upload or delete on someone else's deal
    assert login_as(client, ASHA).put("/api/permissions", json={"role": "Manager", "permission": "edit_team_records",
                                                                "allowed": False}).status_code == 200
    login_as(client, PRIYA)
    assert client.get(url(opp["id"])).status_code == 200  # still sees it (View team records)
    assert upload(client, opp["id"], "again.pdf", pdf_file()).status_code == 403
    assert client.delete(url(opp["id"], item["id"])).status_code == 403
    assert len(login_as(client, RAVI).get(url(opp["id"])).json()) == 3


def test_an_attachment_can_only_be_reached_through_its_own_opportunity(client):
    first, second = new_opportunity(client), new_opportunity(client)
    item = saved(client, first["id"], "first.pdf", pdf_file())
    assert client.get(url(second["id"], item["id"], "/file")).status_code == 404
    assert client.delete(url(second["id"], item["id"])).status_code == 404
    assert client.get(url(second["id"])).json() == []
    assert client.get(url(first["id"], item["id"], "/file")).status_code == 200  # untouched
    assert client.get(url(999, item["id"], "/file")).status_code == 404
    assert client.get(url(999)).status_code == 404


# ---------- stages ----------

def test_files_keep_their_stage_and_are_read_only_after_won(client):
    opp = new_opportunity(client)
    early = saved(client, opp["id"], "brief.pdf", pdf_file())
    move(client, opp["id"], "Proposal")
    proposal = saved(client, opp["id"], "proposal.docx", DOCX_SAMPLE)
    assert (early["stage"], proposal["stage"]) == ("Opportunity", "Proposal")
    move(client, opp["id"], "Opportunity")  # moving back keeps every file and its stage
    assert {a["filename"]: a["stage"] for a in client.get(url(opp["id"])).json()} == {
        "brief.pdf": "Opportunity", "proposal.docx": "Proposal"}
    move(client, opp["id"], "Proposal")

    won = client.post(f"/api/opportunities/{opp['id']}/won", json={"final_value": 900, "notify_customer": False})
    assert won.status_code == 200 and won.json()["stage"] == "Won" and won.json()["probability"] == 100
    blocked = upload(client, opp["id"], "late.pdf", pdf_file())
    assert blocked.status_code == 409 and "Won" in blocked.json()["detail"]
    assert client.delete(url(opp["id"], early["id"])).status_code == 409
    for role in (RAVI, PRIYA, ASHA):  # nobody can change the files of a closed deal
        assert upload(login_as(client, role), opp["id"], "late.pdf", pdf_file()).status_code == 409
    login_as(client, RAVI)
    assert {a["filename"]: a["stage"] for a in client.get(url(opp["id"])).json()} == {
        "brief.pdf": "Opportunity", "proposal.docx": "Proposal"}
    assert client.get(url(opp["id"], proposal["id"], "/file")).content == DOCX_SAMPLE
    history = [h["to_stage"] for h in client.get(f"/api/opportunities/{opp['id']}/history").json()]
    assert history == ["Opportunity", "Proposal", "Opportunity", "Proposal", "Won"]  # stage flow unchanged


def test_files_are_read_only_after_lost(client):
    opp = new_opportunity(client)
    item = saved(client, opp["id"], "quote.png", png_file())
    lost = client.post(f"/api/opportunities/{opp['id']}/lost", json={"lost_reason": "Price", "notify_customer": False})
    assert lost.status_code == 200
    assert upload(client, opp["id"], "late.pdf", pdf_file()).status_code == 409
    assert client.delete(url(opp["id"], item["id"])).status_code == 409
    assert client.get(url(opp["id"], item["id"], "/file")).status_code == 200
    assert client.get(url(opp["id"])).json()[0]["stage"] == "Opportunity"


# ---------- delete ----------

def test_soft_delete_rules_and_activity_log(client):
    opp = new_opportunity(client)
    by_ravi = saved(client, opp["id"], "ravi.pdf", pdf_file())
    by_priya = saved(login_as(client, PRIYA), opp["id"], "priya.pdf", pdf_file())
    by_asha = saved(login_as(client, ASHA), opp["id"], "asha.pdf", pdf_file())

    login_as(client, RAVI)
    refused = client.delete(url(opp["id"], by_priya["id"]))  # the owner can't delete a Manager's file
    assert refused.status_code == 403 and "uploaded this file" in refused.json()["detail"]
    assert client.delete(url(opp["id"], by_ravi["id"])).json() == {"deleted": True, "id": by_ravi["id"]}
    assert login_as(client, PRIYA).delete(url(opp["id"], by_asha["id"])).status_code == 200  # Manager: any file
    assert login_as(client, ASHA).delete(url(opp["id"], by_priya["id"])).status_code == 200  # Admin: any file

    # deleted files are hidden and can't be downloaded or deleted again
    login_as(client, RAVI)
    assert client.get(url(opp["id"])).json() == []
    assert client.get(url(opp["id"], by_ravi["id"], "/file")).status_code == 404
    assert client.delete(url(opp["id"], by_ravi["id"])).status_code == 404

    # ...but kept in the database with who deleted them and when
    rows = {r.filename: r for r in stored_rows()}
    assert (rows["ravi.pdf"].deleted_by_id, rows["asha.pdf"].deleted_by_id, rows["priya.pdf"].deleted_by_id) == (RAVI, PRIYA, ASHA)
    assert all(r.deleted_at is not None for r in rows.values())
    log = login_as(client, ASHA).get("/api/activity-log").json()
    deleted = [e for e in log if e["action"] == "Attachment deleted"]
    assert len(deleted) == 3 and {e["by"] for e in deleted} == {"Ravi Kumar", "Priya Sharma", "Asha Rao"}
    assert any(e["target"].endswith("• ravi.pdf") and "Opportunity stage" in e["details"] for e in deleted)
    with db_session() as db:
        assert db.scalars(select(ActivityLog).where(ActivityLog.action == "Attachment deleted")).all()


# ---------- email attachments are unchanged ----------

def test_email_attachments_keep_their_own_rules(client):
    opp = new_opportunity(client)
    base = {"to": "buyer@example.test", "subject": "Quote", "body": "Hello", "opportunity_id": str(opp["id"])}
    any_type = client.post("/api/emails", data=base, files=[("files", ("notes.txt", b"plain text", "text/plain"))])
    assert any_type.status_code == 201  # email attachments still accept any type
    big = ("files", ("big.bin", b"0" * (10 * 1024 * 1024 + 1), "application/octet-stream"))
    assert client.post("/api/emails", data=base, files=[big]).status_code == 413  # and keep their 10 MB limit
    attachment = any_type.json()["attachments"][0]
    token = client.headers["Authorization"].split(" ", 1)[1]
    client.headers.pop("Authorization")
    link = client.get(f"/api/emails/attachments/{attachment['id']}", params={"token": token})
    assert link.status_code == 200 and link.content == b"plain text"  # email download links work as before
    assert client.get(url(opp["id"]), params={"token": token}).status_code == 401  # attachments don't
    assert stored_rows() == []
