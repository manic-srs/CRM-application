"""Bulk upload: unique emails, the company-domain rule, and who owns the uploaded leads (one person, the file's
Lead Owner column, or shared evenly), like Salesforce's Data Import Wizard. All data is made up."""
import csv
import io

from tests.conftest import login_as

HEADER = ["First Name", "Last Name", "Company", "Email", "Website", "Lead Owner"]


def upload(client, rows, dry_run=False, **form):
    out = io.StringIO()
    csv.writer(out).writerows([HEADER, *rows])
    data = {"dry_run": str(dry_run).lower(), **{k: v for k, v in form.items() if k not in ("owner_ids", "counts")}}
    if "owner_ids" in form:
        data["owner_ids"] = [str(i) for i in form["owner_ids"]]
    if "counts" in form:
        data["counts"] = form["counts"]
    return client.post("/api/leads/import", files={"file": ("team.csv", out.getvalue().encode(), "text/csv")}, data=data)


def add_salesperson(client, name, email):
    res = login_as(client, 3).post("/api/users", json={"full_name": name, "email": email, "password": "Start2026",
                                                       "role": "Salesperson"})
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


def owners_of(client, *last_names):
    items = login_as(client, 1).get("/api/leads/page", params={"view": "all", "limit": 500}).json()["items"]
    return {l["last_name"]: l["owner_id"] for l in items if l["last_name"] in last_names}


def rows(n, prefix="Row", owner=""):
    return [["A", f"{prefix}{i}", "Acme", f"{prefix.lower()}{i}@acme-example.com", "acme-example.com", owner]
            for i in range(n)]


def test_email_on_another_domain_is_kept_with_a_note(client):
    res = upload(client, [["Asha", "Iyer", "Acme", "asha@acme-group.example", "acme-example.com", ""],
                          ["Ben", "Cole", "Acme", "ben@acme-example.com", "https://www.acme-example.com", ""]])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 2 and body["with_blanks"] == 1
    assert "on another domain than the company website (acme-example.com)" in body["warnings"][0]["reason"]
    emails = {l["last_name"]: l["email"] for l in client.get("/api/leads/page").json()["items"]}
    assert emails == {"Iyer": "asha@acme-group.example", "Cole": "ben@acme-example.com"}


def test_emails_already_in_the_crm_are_skipped_whatever_the_stage(client):
    lead = client.post("/api/leads", json={"last_name": "Old", "company": "Acme", "email": "old@acme-example.com"}).json()
    client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic"})
    res = upload(client, [["A", "Again", "Acme", "OLD@acme-example.com", "acme-example.com", ""],
                          ["B", "Fresh", "Acme", "fresh@acme-example.com", "acme-example.com", ""],
                          ["C", "Twice", "Acme", "fresh@acme-example.com", "acme-example.com", ""]], dry_run=True)
    body = res.json()
    assert (body["ready"], body["duplicates"]) == (1, 2)
    assert "old@acme-example.com is already in the CRM" in body["errors"][0]["reason"]


def test_a_salesperson_can_assign_uploads_to_teammates(client):
    login_as(client, 2)  # Ravi, Salesperson
    assert upload(client, rows(2), dry_run=True).json()["owners"] == [{"id": 2, "name": "Ravi Kumar", "count": 2}]
    assert upload(client, rows(2), dry_run=True, owner_id="1").json()["owners"] == [{"id": 1, "name": "Priya Sharma", "count": 2}]
    assert upload(client, rows(2), dry_run=True, assign="even", owner_ids=[2, 1]).status_code == 200
    assert upload(client, rows(2), dry_run=True, owner_id="3").status_code == 400  # the Admin doesn't own leads


def test_set_how_many_each_person_gets_and_they_are_told(client):
    tara = add_salesperson(client, "Tara Nair", "tara@crm.test")
    ravi = login_as(client, 2)
    res = upload(ravi, rows(6), dry_run=True, assign="counts", counts=[f"{tara}:3", "1:2"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["owners"] == [{"id": tara, "name": "Tara Nair", "count": 3}, {"id": 1, "name": "Priya Sharma", "count": 2},
                              {"id": 2, "name": "Ravi Kumar", "count": 1}]
    assert body["assign_note"] == "The other 1 go to Ravi Kumar."
    done = upload(ravi, rows(6), assign="counts", counts=[f"{tara}:3", "1:2"]).json()
    assert done["created"] == 6
    got = owners_of(client, *[f"Row{i}" for i in range(6)])
    assert [got[f"Row{i}"] for i in range(6)] == [tara, tara, tara, 1, 1, 2]
    bell = login_as(client, tara).get("/api/notifications").json()
    assert any(n["title"] == "Leads assigned to you" and "Ravi Kumar uploaded 3 leads" in n["message"] for n in bell)
    # asking for more than the file has: the last people get fewer, and the screen says so
    short = upload(login_as(client, 2), rows(2, prefix="Short"), dry_run=True, assign="counts", counts=["1:5"]).json()
    assert short["owners"] == [{"id": 1, "name": "Priya Sharma", "count": 2}] and "asked for 5" in short["assign_note"]
    assert upload(client, rows(1), dry_run=True, assign="counts", counts=["1:0"]).status_code == 400
    assert upload(client, rows(1), dry_run=True, assign="counts").status_code == 400


def test_share_evenly_round_robin(client):
    tara = add_salesperson(client, "Tara Nair", "tara@crm.test")
    manager = login_as(client, 1)  # Priya, Manager: may assign to others
    res = upload(manager, rows(5), assign="even", owner_ids=[2, tara])
    assert res.status_code == 200, res.text
    assert res.json()["owners"] == [{"id": 2, "name": "Ravi Kumar", "count": 3}, {"id": tara, "name": "Tara Nair", "count": 2}]
    got = owners_of(client, *[f"Row{i}" for i in range(5)])
    assert [got[f"Row{i}"] for i in range(5)] == [2, tara, 2, tara, 2]
    # each owner gets one "Leads assigned to you" notification with their count
    ravi_bell = login_as(client, 2).get("/api/notifications").json()
    assert any(n["title"] == "Leads assigned to you" and "uploaded 3 leads" in n["message"] for n in ravi_bell)
    manager = login_as(client, 1)
    assert upload(manager, rows(1), assign="even", owner_ids=[3]).status_code == 400  # the Admin doesn't own leads
    assert upload(manager, rows(1), assign="even").status_code == 400  # nobody chosen


def test_lead_owner_column_by_email_or_name_with_a_default(client):
    tara = add_salesperson(client, "Tara Nair", "tara@crm.test")
    data = [["A", "ByEmail", "Acme", "byemail@acme-example.com", "acme-example.com", "TARA@crm.test"],
            ["A", "ByName", "Acme", "byname@acme-example.com", "acme-example.com", "ravi kumar"],
            ["A", "Blank", "Acme", "blank@acme-example.com", "acme-example.com", ""],
            ["A", "Unknown", "Acme", "unknown@acme-example.com", "acme-example.com", "Nobody Here"],
            ["A", "AdminRow", "Acme", "adminrow@acme-example.com", "acme-example.com", "Asha Rao"]]
    res = upload(login_as(client, 3), data, assign="column", owner_id=str(tara))  # the Admin, default owner Tara
    assert res.status_code == 200, res.text
    got = owners_of(client, "ByEmail", "ByName", "Blank", "Unknown", "AdminRow")
    assert got == {"ByEmail": tara, "ByName": 2, "Blank": tara, "Unknown": tara, "AdminRow": tara}
    notes = {w["row"]: w["reason"] for w in res.json()["warnings"]}
    assert "Owner 'Nobody Here' isn't an active Manager or Salesperson; assigned to Tara Nair" in notes[5]
    # the column is needed for this choice
    out = io.StringIO()
    csv.writer(out).writerows([["Last Name", "Company"], ["NoOwner", "Acme"]])
    res = login_as(client, 1).post("/api/leads/import", data={"assign": "column", "dry_run": "true"},
                                   files={"file": ("x.csv", out.getvalue().encode(), "text/csv")})
    assert res.status_code == 400 and "Lead Owner column" in res.json()["detail"]


def test_skipped_rows_are_listed_with_name_company_and_email(client):
    client.post("/api/leads", json={"last_name": "Old", "company": "Acme", "email": "old@acme-example.com",
                                    "company_website": "acme-example.com"})
    body = upload(client, [["Asha", "Iyer", "Acme", "OLD@acme-example.com", "acme-example.com", ""],
                           ["Ben", "", "Acme", "ben@acme-example.com", "acme-example.com", ""],
                           ["Cara", "Lee", "Acme", "cara@gmail.com", "acme-example.com", ""]], dry_run=True).json()
    assert body["errors"] == [
        {"row": 2, "type": "Duplicate", "reason": "Email old@acme-example.com is already in the CRM (duplicate)",
         "name": "Asha Iyer", "company": "Acme", "email": "OLD@acme-example.com"},
        {"row": 3, "type": "Invalid", "reason": "Last name is missing", "name": "Ben", "company": "Acme",
         "email": "ben@acme-example.com"}]
    note = body["warnings"][0]
    assert (note["row"], note["type"], note["name"], note["email"]) == (4, "Changed", "Cara Lee", "cara@gmail.com")
    assert note["reason"].startswith("Left blank: email 'cara@gmail.com' isn't on the company's domain")
