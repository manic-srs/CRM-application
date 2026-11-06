"""AI Assistant: saved chats (history panel), attachments, greetings, the CRM-only scope, free-format demo booking,
new opportunities, accurate reports and access for every role. A scripted stand-in replaces the AI model; all data
is made up."""
import io
import json
import zipfile
from datetime import datetime, timedelta

import pytest
from openpyxl import Workbook

from app import assistant
from app.assistant_reports import period_range
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai: a scripted stand-in for the AI model)


def tool(tool_name, args):
    """A tool call whose arguments include a 'name' (call() uses that word for the tool)."""
    return {"id": f"call_{tool_name}_{len(json.dumps(args))}", "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(args)}}

PRIYA, RAVI, ASHA = 1, 2, 3
TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}
NOTE = "Synthetic test note"


def chat(client, message, conversation_id=None, **extra):
    res = client.post("/api/assistant/chat", json={"message": message, "conversation_id": conversation_id, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def upload(client, name, data, conversation_id=None):
    form = {"conversation_id": str(conversation_id)} if conversation_id else {}
    return client.post("/api/assistant/files", files={"file": (name, data)}, data=form)


def user_text(messages):
    return [m["content"] for m in messages if m["role"] == "user"][-1]


# ---------- saved chats ----------

def test_chats_are_saved_continued_renamed_and_deleted(client, ai):
    script, seen = ai
    script += ["Hello! NEXT: Show my open leads | What is overdue?", "You have no tasks."]
    first = chat(client, "  Hi there, what can you do for my pipeline today?  ")
    conv = first["conversation"]
    assert conv["title"] == "Hi there, what can you do for my pipeline today?" and conv["created_at"]
    assert first["reply"] == "Hello!" and first["suggestions"] == []  # a stray NEXT: line is removed, nothing shown
    assert [e["from"] for e in first["chat"]] == ["me", "ai"]
    second = chat(client, "show my tasks", conv["id"])
    # the server loaded the saved history: the model saw the first message too
    assert [m["content"] for m in seen[-1] if m["role"] == "user"] == ["Hi there, what can you do for my pipeline today?",
                                                                    "show my tasks"]
    assert len(second["chat"]) == 4 and second["conversation"]["id"] == conv["id"]
    listed = client.get("/api/assistant/conversations").json()
    assert [c["id"] for c in listed] == [conv["id"]] and listed[0]["updated_at"]
    renamed = client.patch(f"/api/assistant/conversations/{conv['id']}", json={"title": "  Monday   planning "}).json()
    assert renamed["title"] == "Monday planning"
    assert client.patch(f"/api/assistant/conversations/{conv['id']}", json={"title": "   "}).status_code == 422
    full = client.get(f"/api/assistant/conversations/{conv['id']}").json()
    assert full["title"] == "Monday planning" and len(full["chat"]) == 4 and full["pending"] is None
    assert client.delete(f"/api/assistant/conversations/{conv['id']}").status_code == 200
    assert client.get("/api/assistant/conversations").json() == []


def test_each_user_sees_only_their_own_chats(client, ai):
    script, _ = ai
    script += ["Hi"]
    conv = chat(client, "hello")["conversation"]
    priya = login_as(client, PRIYA)
    assert priya.get("/api/assistant/conversations").json() == []
    assert priya.get(f"/api/assistant/conversations/{conv['id']}").status_code == 404
    assert priya.patch(f"/api/assistant/conversations/{conv['id']}", json={"title": "x"}).status_code == 404
    assert priya.delete(f"/api/assistant/conversations/{conv['id']}").status_code == 404
    assert priya.post("/api/assistant/chat", json={"message": "hi", "conversation_id": conv["id"]}).status_code == 404


def test_confirm_uses_the_saved_action_not_what_the_browser_sends(client, ai):
    script, _ = ai
    keep = client.post("/api/leads", json={"last_name": "Keep", "company": "Acme"}).json()
    target = client.post("/api/leads", json={"last_name": "Sen", "company": "Acme"}).json()
    script += [[call("delete_lead", lead_id=target["id"])]]
    first = chat(client, "delete Sen")
    assert first["pending"]["tool"] == "delete_lead" and first["chat"][-1]["pending"]
    tampered = {**first["pending"], "args": {"lead_id": keep["id"]}}
    script += ["Deleted."]
    res = client.post("/api/assistant/confirm", json={"conversation_id": first["conversation"]["id"], "pending": tampered,
                                                      "confirmed": True}).json()
    assert client.get(f"/api/leads/{target['id']}").status_code == 404
    assert client.get(f"/api/leads/{keep['id']}").status_code == 200
    assert [e["text"] for e in res["chat"][-2:]] == ["Confirm", "Deleted."] and res["chat"][1]["pending"] is None
    again = client.post("/api/assistant/confirm", json={"conversation_id": first["conversation"]["id"], "confirmed": True})
    assert again.status_code == 400  # nothing is waiting any more


# ---------- no suggestions; greetings; off-topic questions ----------

def test_no_suggestions_are_shown_after_replies(client, ai):
    assert assistant.split_suggestions("Done.\n**NEXT:** Book a demo | Add a task.") == ("Done.", ["Book a demo", "Add a task"])
    assert assistant.split_suggestions("- Win rate: **50%**\nNEXT: Compare") == ("- Win rate: **50%**", ["Compare"])
    script, seen = ai
    script += [[call("create_lead", last_name="Rao", company="Zeta", email="rao@zeta.example", company_website="zeta.example",
                     company_linkedin_url="https://www.linkedin.com/company/zeta-example")], "Created Rao. NEXT: Book a demo with Rao"]
    res = chat(client, "create lead Rao at Zeta")
    assert res["reply"] == "Created Rao." and res["suggestions"] == [] and res["chat"][-1]["suggestions"] == []
    assert "Don't end replies with suggested next requests" in seen[0][0]["content"]
    assert "NEXT:" not in seen[0][0]["content"]


@pytest.mark.parametrize("message", ["hi", "Hello!", "hey there", "Good morning", "hii", " HELLO team "])
def test_a_greeting_is_answered_with_the_time_of_day_without_the_ai(client, ai, message):
    script, seen = ai  # nothing scripted: the AI isn't asked
    res = chat(client, message)
    assert seen == [] and res["pending"] is None and res["suggestions"] == []
    assert res["reply"].startswith("Good ") and res["reply"].endswith(
        ", Ravi! How can I help you with SalesTrack CRM today?")
    # the greeting is part of the saved chat, so the next message continues normally
    script += ["You have 0 overdue tasks."]
    chat(client, "what is overdue?", res["conversation"]["id"])
    assert [m["content"] for m in seen[-1] if m["role"] == "assistant"][0] == res["reply"]


def test_greeting_wording_follows_the_clock(monkeypatch):
    from datetime import datetime as dt
    from types import SimpleNamespace

    monkeypatch.setattr(assistant, "acting_user", lambda: SimpleNamespace(full_name="Ravi Kumar"))
    assert assistant.greeting_reply("hi", dt(2026, 1, 5, 9)).startswith("Good morning, Ravi!")
    assert assistant.greeting_reply("hi", dt(2026, 1, 5, 13)).startswith("Good afternoon, Ravi!")
    assert assistant.greeting_reply("hi", dt(2026, 1, 5, 19)).startswith("Good evening, Ravi!")
    assert assistant.greeting_reply("hi, show my leads", dt(2026, 1, 5, 9)) is None  # a real request goes to the AI


def test_off_topic_questions_get_the_sorry_reply_and_crm_writing_is_allowed(client, ai):
    script, seen = ai
    script += [assistant.OFF_TOPIC_REPLY]
    res = chat(client, "what is 10+10")
    prompt = seen[0][0]["content"]
    assert assistant.OFF_TOPIC_REPLY == "Sorry, I can help with SalesTrack CRM tasks & related information."
    assert f'reply with exactly: "{assistant.OFF_TOPIC_REPLY}"' in prompt and "can't browse the web" in prompt
    assert "drafting an email or message to a lead" in prompt  # e.g. telling a lead about a stage change is CRM work
    assert res["reply"] == assistant.OFF_TOPIC_REPLY


# ---------- attachments ----------

def docx_bytes(paragraphs):
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body>" + "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs) + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def pptx_bytes(text):
    xml = ('<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
           'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody>'
           f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/slides/slide1.xml", xml)
    return buf.getvalue()


def pdf_bytes(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def xlsx_bytes():
    book = Workbook()
    book.active.append(["Name", "Company", "Email"])
    book.active.append(["Lena Park", "Orbit Analytics", "lena@orbit.test"])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.mark.parametrize("name,data,expected", [
    ("card.txt", b"Mohan Reddy\nSenior Consultant, PwC\nmohan@pwc.example", "Senior Consultant, PwC"),
    ("leads.csv", b"name,company\nAsha,Globex\n", "Asha,Globex"),
    ("notes.docx", docx_bytes(["Meeting with Orbit", "Budget approved"]), "Meeting with Orbit\nBudget approved"),
    ("deck.pptx", pptx_bytes("Q4 pricing"), "[Slide 1]\nQ4 pricing"),
    ("list.xlsx", xlsx_bytes(), "Lena Park,Orbit Analytics,lena@orbit.test"),
    ("brief.pdf", pdf_bytes("Demo requested by Northwind"), "Demo requested by Northwind"),
    ("page.html", b"<html><script>x()</script><p>Hello &amp; welcome</p></html>", "Hello & welcome"),
])
def test_documents_are_read_and_the_ai_gets_their_text(client, ai, name, data, expected):
    script, seen = ai
    res = upload(client, name, data)
    assert res.status_code == 201, res.text
    file = res.json()
    assert file["kind"] == "text" and file["chars"] > 0
    script += ["Read it."]
    out = chat(client, "Create leads from this file", file_ids=[file["id"]])
    sent = user_text(seen[-1])
    assert f"[Attached file: {name}]" in sent and expected in sent
    assert out["chat"][0]["files"][0]["filename"] == name


def test_an_image_is_shown_to_the_ai_once_and_not_kept_in_the_history(client, ai):
    script, seen = ai
    file = upload(client, "card.png", PNG).json()
    assert file["kind"] == "image"
    script += ["That's Mohan's card.", "OK"]
    first = chat(client, "Who is this?", file_ids=[file["id"]])
    parts = seen[-1][-1]["content"]
    assert parts[0]["type"] == "text" and "[Attached image: card.png]" in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    chat(client, "thanks", first["conversation"]["id"])
    earlier = [m["content"] for m in seen[-1] if m["role"] == "user"][0]
    assert isinstance(earlier, str) and "[Attached image: card.png]" in earlier  # no picture sent again


def test_files_that_cant_be_used_are_refused(client, ai):
    assert upload(client, "virus.exe", b"MZ....").status_code == 400
    assert upload(client, "empty.txt", b"").status_code == 400
    assert upload(client, "fake.png", b"not an image").status_code == 400
    assert upload(client, "broken.docx", b"not a zip").status_code == 400
    assert upload(client, "broken.pdf", b"%PDF-1.4 nothing").status_code == 400
    assert upload(client, "big.txt", b"x" * (10 * 1024 * 1024 + 1)).status_code == 400
    # another user's file can't be used
    other = upload(login_as(client, PRIYA), "p.txt", b"Priya's notes").json()
    login_as(client, RAVI)
    res = client.post("/api/assistant/chat", json={"message": "read it", "file_ids": [other["id"]]})
    assert res.status_code == 404


# ---------- free-format work ----------

def test_a_demo_is_booked_from_just_the_lead_and_the_time(client, ai):
    script, seen = ai
    lead = client.post("/api/leads", json={"first_name": "Mira", "last_name": "Shah", "company": "Orbit"}).json()
    when = (datetime.now() + timedelta(days=3)).replace(hour=15, minute=0).strftime("%Y-%m-%dT%H:%M")
    script += [[call("move_lead_stage", lead_id=lead["id"], stage="Demo", demo_date=when,
                     completed_stages=["Nurturing"])], "Booked."]
    chat(client, "demo with Mira from Orbit on Friday 3pm, nurturing is done")
    detail = client.get(f"/api/leads/{lead['id']}").json()
    assert detail["stage"] == "Demo"
    assert any(t["title"] == "Demo with Mira Shah" for t in detail["tasks"])
    history = client.get(f"/api/leads/{lead['id']}/history").json()
    assert history[-1]["to_stage"] == "Demo" and history[-1]["note"].startswith("Demo booked for")
    # other stage changes still need the user's note
    script += [[call("move_lead_stage", lead_id=lead["id"], stage="Nurturing")], "Why?"]
    chat(client, "move her back to nurturing")
    assert "error" in json.loads(seen[-1][-1]["content"])


def test_new_opportunity_from_the_chat(client, ai):
    script, seen = ai
    script += [[tool("create_opportunity", dict(name="Orbit BI rollout", account_name="Orbit Analytics",
                     contact_first_name="Lena", contact_last_name="Park", contact_email="lena@orbit.test", amount=40000,
                     note="They asked for a quote", task_title="Send quote", task_due_date="2030-01-15T10:00"))],
               "Created."]
    res = chat(client, "new deal Orbit BI rollout 40k with Lena Park at Orbit Analytics, they asked for a quote, "
                       "send quote by Jan 15 2030")
    link = res["links"][0]
    assert link["type"] == "Opportunity" and link["name"] == "Orbit BI rollout"
    opp = client.get(f"/api/opportunities/{link['id']}").json()
    assert opp["expected_value"] == 40000 and opp["account_name"] == "Orbit Analytics"
    # the same deal again is refused (no duplicates); without a note it isn't tried at all
    script += [[tool("create_opportunity", dict(name="Orbit BI Rollout", account_name="Orbit Analytics", contact_last_name="Park",
                     contact_first_name="Lena", note="again", task_title="t", task_due_date="2030-01-15T10:00"))], "Exists."]
    chat(client, "add Orbit BI rollout again")
    assert "already" in json.loads(seen[-1][-1]["content"])["error"]
    script += [[tool("create_opportunity", dict(name="Other", account_name="Orbit Analytics", contact_last_name="Park",
                     task_title="t", task_due_date="2030-01-15T10:00"))], "What's the reason?"]
    chat(client, "add another deal")
    assert "error" in json.loads(seen[-1][-1]["content"])


def test_more_crm_tools(client, ai):
    script, seen = ai
    acc = client.post("/api/accounts", json={"name": "Northwind Health", "industry": "Healthcare", "phone": "+1 555 0100"}).json()
    task = client.post("/api/tasks", json={"title": "Call back", "due_date": "2030-01-10T09:00"}).json()
    lead = client.post("/api/leads", json={"last_name": "Iyer", "company": "Globex"}).json()
    script += [[call("list_accounts", search="North"), call("create_contact", account_id=acc["id"], first_name="Dev",
                                                              last_name="Rao", email="dev@northwind.test", phone="+1 555 0101")],
               [call("get_account", account_id=acc["id"]), call("update_task", task_id=task["id"], due_date="2030-02-01T09:00",
                                                                priority="High")],
               "Done."]
    chat(client, "add Dev Rao to Northwind and move my call back to Feb 1, high priority")
    results = [json.loads(m["content"]) for m in seen[-1] if m["role"] == "tool"]
    assert results[0]["count"] == 1 and results[1]["full_name"] == "Dev Rao"
    assert [c["full_name"] for c in results[2]["contacts"]] == ["Dev Rao"]
    updated = client.get(f"/api/tasks/{task['id']}").json()
    assert updated["priority"] == "High" and updated["due_date"].startswith("2030-02-01")
    # Unqualified waits for Confirm, then reopen brings the lead back
    script += [[call("mark_lead_unqualified", lead_id=lead["id"], reason="Bad timing", notes="Not this year")]]
    pending = chat(client, "Iyer isn't ready")
    assert pending["pending"]["tool"] == "mark_lead_unqualified" and "Unqualified" in pending["pending"]["summary"]
    script += ["Marked."]
    client.post("/api/assistant/confirm", json={"conversation_id": pending["conversation"]["id"], "confirmed": True})
    assert client.get(f"/api/leads/{lead['id']}").json()["stage"] == "Unqualified"
    script += [[call("reopen_lead", lead_id=lead["id"], note="They called back", task_title="Call Iyer",
                     task_due_date="2030-01-20T10:00")], "Reopened."]
    chat(client, "Iyer called back, reopen it and call him on Jan 20 2030")
    assert client.get(f"/api/leads/{lead['id']}").json()["stage"] == "New"


# ---------- reports ----------

def test_reports_are_counted_in_the_database(client, ai):
    script, seen = ai
    # Ravi: 3 leads (1 converted, 1 lost), 2 deals (1 won 30,000; 1 open 10,000). Priya: 1 lead, 1 open deal 50,000
    leads = [client.post("/api/leads", json={"last_name": f"L{i}", "company": f"C{i}", "source": "Referral"}).json()
             for i in range(3)]
    won = client.post(f"/api/leads/{leads[0]['id']}/convert", json={
        "task": TASK, "note": NOTE, "expected_value": 30000, "completed_stages": ["Nurturing", "Demo"]}).json()["opportunity"]
    client.post(f"/api/opportunities/{won['id']}/won", json={"task": TASK, "note": NOTE, "completed_stages": ["Discovery", "Proposal"]})
    client.post(f"/api/leads/{leads[1]['id']}/lost", json={"lost_reason": "Price", "lost_notes": NOTE})
    client.post("/api/opportunities", json={"name": "Open deal", "account_name": "C9", "contact_last_name": "X",
                                             "expected_value": 10000, "note": NOTE, "task": TASK})
    priya = login_as(client, PRIYA)
    priya.post("/api/leads", json={"last_name": "P", "company": "PC"})
    priya.post("/api/opportunities", json={"name": "Big deal", "account_name": "PC", "contact_last_name": "P",
                                           "expected_value": 50000, "note": NOTE, "task": TASK})
    # Ravi sees only his own records
    login_as(client, RAVI)
    script += [[call("crm_report", period="this_month")], "Here is your report."]
    chat(client, "report for this month")
    report = json.loads(seen[-1][-1]["content"])
    leads_part, opps = report["leads"], report["opportunities"]
    assert report["scope"] == "your own records"
    assert (leads_part["created_in_period"], leads_part["converted_in_period"], leads_part["lost_in_period"]) == (3, 1, 1)
    assert leads_part["conversion_rate_pct"] == 50.0 and leads_part["created_by_source"] == {"Referral": 3}
    assert (opps["won_in_period"], opps["won_value"], opps["win_rate_pct"]) == (1, 30000.0, 100.0)
    assert opps["open_now"]["count"] == 1 and opps["open_now"]["value"] == 10000.0
    assert opps["won_by_owner"] == {"Ravi Kumar": {"count": 1, "value": 30000.0}}
    # the Manager sees the team
    script += [[call("crm_report")], "Team report."]
    chat(login_as(client, PRIYA), "team report")
    team = json.loads(seen[-1][-1]["content"])
    assert team["scope"] == "the whole team" and team["opportunities"]["open_now"]["value"] == 60000.0
    assert team["opportunities"]["biggest_open_deals"][0]["name"] == "Big deal"
    assert team["leads"]["all_by_stage"]["Converted"] == 1 and team["leads"]["all_by_stage"]["New"] == 2
    # a period with nothing in it
    script += [[call("crm_report", period="last_year")], "Nothing."]
    chat(client, "last year")
    empty = json.loads(seen[-1][-1]["content"])
    assert empty["leads"]["created_in_period"] == 0 and empty["opportunities"]["win_rate_pct"] is None


def test_period_ranges():
    from datetime import date
    start, end, label = period_range("last_month", today=date(2026, 3, 15))
    assert (start.date(), end.date(), label) == (date(2026, 2, 1), date(2026, 3, 1), "February 2026")
    start, end, _ = period_range("this_quarter", today=date(2026, 5, 2))
    assert (start.date(), end) == (date(2026, 4, 1), None)  # up to now
    start, end, _ = period_range("today", today=date(2026, 5, 2))
    assert (start.date(), end) == (date(2026, 5, 2), None)
    start, end, _ = period_range("last_quarter", today=date(2026, 1, 10))
    assert (start.date(), end.date()) == (date(2025, 10, 1), date(2026, 1, 1))
    start, end, _ = period_range(None, "2026-01-01", "2026-01-31")
    assert (start.date(), end.date()) == (date(2026, 1, 1), date(2026, 2, 1))
    assert period_range("all_time")[:2] == (None, None)


# ---------- every role ----------

@pytest.mark.parametrize("user_id,role", [(PRIYA, "Manager"), (RAVI, "Salesperson"), (ASHA, "Admin")])
def test_every_role_can_use_the_assistant(client, ai, user_id, role):
    script, seen = ai
    script += [[call("pipeline_summary"), call("crm_report", period="this_year")], "Here you go."]
    res = chat(login_as(client, user_id), "how is the pipeline?")
    assert res["reply"] == "Here you go." and f"({role})" in seen[0][0]["content"]
    assert all("error" not in json.loads(m["content"]) for m in seen[-1] if m["role"] == "tool")
    assert len(client.get("/api/assistant/conversations").json()) == 1
    assert upload(client, "n.txt", b"notes").status_code == 201


# ---------- pasted and uploaded details ----------

SIGNATURE = """Hi team, please add this contact we met at the expo.

--
Kavya Menon | Head of Operations
Brightline Logistics Inc.
kavya.menon@brightline.test | +1 415 555 0142
www.brightline.test
"""


def test_pasted_details_reach_the_ai_whole_and_the_lead_is_created(client, ai):
    script, seen = ai
    long_thread = SIGNATURE + "\n" + ("> earlier message in the thread\n" * 400)  # a long pasted email (~13,000 chars)
    script += [[call("create_lead", first_name="Kavya", last_name="Menon", title="Head of Operations",
                     company="Brightline Logistics", email="kavya.menon@brightline.test", phone="+1 415 555 0142",
                     company_website="https://www.brightline.test", source="Event",
                     company_linkedin_url="https://www.linkedin.com/company/brightline-test")], "Created Kavya Menon."]
    res = chat(client, "Create a lead from this:\n" + long_thread)
    assert user_text(seen[0]) == ("Create a lead from this:\n" + long_thread).strip()  # nothing cut off
    lead = client.get(f"/api/leads/{res['links'][0]['id']}").json()
    assert (lead["name"], lead["company"], lead["title"], lead["source"]) == ("Kavya Menon", "Brightline Logistics",
                                                                              "Head of Operations", "Event")
    assert lead["email"] == "kavya.menon@brightline.test" and lead["phone"]


def test_an_uploaded_list_creates_every_lead_and_stays_readable_later(client, ai):
    script, seen = ai
    rows = "\n".join(f"Person{i},Lastname{i},Company {i},person{i}@company{i}.test" for i in range(1, 121))
    file = upload(client, "expo-leads.csv", ("first,last,company,email\n" + rows).encode()).json()
    script += [[call("create_lead", first_name=f"Person{i}", last_name=f"Lastname{i}", company=f"Company {i}",
                     email=f"person{i}@company{i}.test", company_website=f"company{i}.test",
                     company_linkedin_url=f"https://www.linkedin.com/company/company{i}") for i in range(1, 4)], "Created the first 3 leads."]
    first = chat(client, "Create leads for the first three rows", file_ids=[file["id"]])
    assert len(first["links"]) == 3
    assert {client.get(f"/api/leads/{l['id']}").json()["company"] for l in first["links"]} == {"Company 1", "Company 2", "Company 3"}
    # a later message in the same chat still has the whole file (the last row too)
    script += ["Row 120 is Person120."]
    chat(client, "who is in the last row?", first["conversation"]["id"])
    earlier = [m["content"] for m in seen[-1] if m["role"] == "user"][0]
    assert "Person120,Lastname120,Company 120" in earlier


def test_a_very_long_paste_is_accepted(client, ai):
    script, _ = ai
    script += ["Got it."]
    assert chat(client, "notes: " + "x" * 19_000)["reply"] == "Got it."
    too_long = client.post("/api/assistant/chat", json={"message": "x" * 20_001})
    assert too_long.status_code == 422
