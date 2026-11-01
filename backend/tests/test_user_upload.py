"""Admin adds many users at once from Excel / CSV: checked first, then created with the usual welcome email.
All data is made up."""
import csv
import io

import pytest
from openpyxl import Workbook

from app import mailer
from tests.conftest import login_as


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append({"to": to, "subject": subject, "body": body}))
    return sent


@pytest.fixture(autouse=True)
def company_domain(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "srs-example.com")


def upload(client, rows, dry_run=False, name="people.csv"):
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return client.post("/api/users/import", data={"dry_run": str(dry_run).lower()},
                       files={"file": (name, out.getvalue().encode(), "text/csv")})


PEOPLE = [
    ["Full Name", "Email", "Role", "Password"],
    ["Tara Nair", "Tara.Nair@srs-example.com", "Sales Rep", ""],
    ["Kiran Rao", "kiran@srs-example.com", "manager", "Start2026"],
    ["Repeat", "kiran@srs-example.com", "", ""],                 # repeated in the file
    ["Old Account", "ravi@crm.test", "", ""],                     # not a company email
    ["Gmail User", "someone@gmail.com", "Salesperson", ""],       # personal email
    ["Bad Role", "bad.role@srs-example.com", "Director", ""],
    ["", "noname@srs-example.com", "", ""],
]


def test_check_then_create_with_welcome_emails(client, outbox):
    admin = login_as(client, 3)
    check = upload(admin, PEOPLE, dry_run=True)
    assert check.status_code == 200, check.text
    body = check.json()
    assert (body["rows"], body["ready"], body["duplicates"], body["invalid"], body["created"]) == (7, 2, 1, 4, 0)
    assert body["roles"] == {"Salesperson": 1, "Manager": 1, "Admin": 0}
    reasons = {e["row"]: e["reason"] for e in body["errors"]}
    assert "repeated in this file" in reasons[4] and "not a company email" in reasons[6]
    assert "'Director' is not Salesperson, Manager or Admin" in reasons[7] and reasons[8] == "Name is missing"
    assert outbox == [] and len(admin.get("/api/users").json()) == 3  # nothing saved by the check

    done = upload(admin, PEOPLE).json()
    assert done["created"] == 2
    users = {u["email"]: u for u in admin.get("/api/users").json()}
    assert (users["tara.nair@srs-example.com"]["role"], users["kiran@srs-example.com"]["role"]) == ("Salesperson", "Manager")
    welcome = {m["to"][0] if isinstance(m["to"], list) else m["to"]: m for m in outbox}
    assert "Temporary password: Start2026" in welcome["kiran@srs-example.com"]["body"]
    tara_mail = welcome["tara.nair@srs-example.com"]["body"]
    temp = tara_mail.split("Temporary password: ")[1].split("\n")[0]
    assert len(temp) == 10 and client.post("/api/auth/login", json={"email": "tara.nair@srs-example.com",
                                                                     "password": temp}).status_code == 200
    log = login_as(client, 3).get("/api/activity-log").json()[0]
    assert log["action"] == "Users uploaded" and "2 created (1 Salesperson, 1 Manager)" in log["details"]
    # the same file again: everyone already has an account
    again = upload(admin, PEOPLE[:3], dry_run=True).json()
    assert (again["ready"], again["duplicates"]) == (0, 2)


def test_excel_with_first_and_last_name_columns(client, outbox):
    book = Workbook()
    sheet = book.active
    sheet.append(["First Name", "Last Name", "Work Email"])
    sheet.append(["Meera", "Joshi", "meera@srs-example.com"])
    out = io.BytesIO()
    book.save(out)
    res = login_as(client, 3).post("/api/users/import", data={"dry_run": "false"}, files={"file": (
        "team.xlsx", out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 1 and res.json()["preview"][0] == {
        "full_name": "Meera Joshi", "email": "meera@srs-example.com", "role": "Salesperson"}


def test_only_the_admin_can_add_users_in_bulk(client):
    for user_id in (1, 2):  # Manager, Salesperson
        assert upload(login_as(client, user_id), PEOPLE, dry_run=True).status_code == 403
    res = upload(login_as(client, 3), [["Email"], ["x@srs-example.com"]], dry_run=True)
    assert res.status_code == 400 and "Full Name" in res.json()["detail"]
