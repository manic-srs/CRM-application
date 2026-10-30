"""SalesTrack AI Assistant: do CRM work from one sentence ("Create a lead Ravi Kumar at Acme, source Website").

How it works
- The app sends the conversation to POST /api/assistant/chat. The model (OpenAI, function calling) picks tools below.
- Every tool calls the same API function the screens use, as the logged-in user, so the same permission rules,
  notifications, stage rules and history apply. The assistant can never do more than the user could by hand.
- Closing / hard-to-undo actions (Lost, Won, transfer, cancel demo, delete) are NOT run straight away: the reply
  carries a "pending" action and the user clicks Confirm (POST /api/assistant/confirm) before anything happens.

Settings (.env)
  OPENAI_API_KEY    required to turn the assistant on
  OPENAI_MODEL      default gpt-4o-mini
  OPENAI_BASE_URL   default https://api.openai.com/v1 (any OpenAI-compatible endpoint)
"""
import json
import logging
import os
from datetime import datetime
from decimal import Decimal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app import schemas
from app.models import User
from app.routers import activity, home, leads, opportunities, tasks
from app.security import acting_user

log = logging.getLogger("crm.assistant")
MAX_STEPS = 8          # model <-> tool round trips per message
MAX_LIST = 25          # rows a list tool returns to the model


def settings() -> dict:
    return {
        "key": os.getenv("OPENAI_API_KEY", "").strip(),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
    }


def enabled() -> bool:
    return bool(settings()["key"])


# ---------- tool definitions (what the model can ask for) ----------

def _tool(name, description, properties=None, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}}}


S, I, N, B = {"type": "string"}, {"type": "integer"}, {"type": "number"}, {"type": "boolean"}
DATE_TIME = {"type": "string", "description": "ISO date and time, e.g. 2026-11-05T15:00"}
DATE = {"type": "string", "description": "ISO date, e.g. 2026-11-30"}
COMPLETED = {"type": "array", "items": S, "description": "Earlier stages the user confirmed were already done "
             "(stages can't be skipped). Only fill this after the user says so."}
LEAD_FIELDS = {
    "salutation": {"type": "string", "enum": ["Mr.", "Ms.", "Mrs.", "Dr.", "Prof."]},
    "first_name": S, "last_name": S, "company": S, "title": S, "industry": S, "email": S, "phone": S,
    "source": {"type": "string", "enum": ["Website", "Referral", "Phone", "Email", "Event", "Social Media", "Other"]},
    "location": S, "linkedin_url": S, "company_website": S, "company_linkedin_url": S,
    "annual_revenue": {"type": "number", "description": "Turnover in USD"},
    "employees": {"type": "integer", "description": "Headcount"},
}
LOST = {"type": "string", "enum": ["Price", "Competitor", "No response", "No budget", "Not interested", "Other"]}

TOOLS = [
    _tool("search", "Find leads, opportunities, accounts, contacts and tasks by name, company or email. "
          "Use it to get ids before acting on a record.", {"query": S}, ["query"]),
    _tool("list_leads", "List leads the user can see.", {
        "stage": {"type": "string", "enum": ["New", "Nurturing", "Demo", "Converted", "Lost"]},
        "search": S, "owner_name": {"type": "string", "description": "Only this user's leads"}}),
    _tool("get_lead", "Full details of one lead: fields, open tasks, notes, stage and transfer history.",
          {"lead_id": I}, ["lead_id"]),
    _tool("list_opportunities", "List opportunities (deals) the user can see.", {
        "stage": {"type": "string", "enum": ["Opportunity", "Proposal", "Won", "Lost"]}, "search": S,
        "owner_name": S}),
    _tool("get_opportunity", "Full details of one opportunity.", {"opportunity_id": I}, ["opportunity_id"]),
    _tool("list_tasks", "List open tasks (follow-ups, demos, reminders).", {
        "due": {"type": "string", "enum": ["overdue", "today", "upcoming"]},
        "mine_only": {"type": "boolean", "description": "Default true: only the user's own tasks"}}),
    _tool("list_users", "Active users (for owners and transfers)."),
    _tool("pipeline_summary", "Numbers for the dashboard: leads per stage, open deals, won and lost, today's tasks.", {
        "mine_only": {"type": "boolean", "description": "Default false: the whole team the user can see"}}),
    _tool("create_lead", "Create a lead at stage New. Last name and company are required.", {
        **LEAD_FIELDS, "owner_name": {"type": "string", "description": "Only when the user names another owner"},
        "send_welcome_email": {"type": "boolean", "description": "Default false. True only if the user asks to email the lead"}},
        ["last_name", "company"]),
    _tool("update_lead", "Change details of a lead (not its stage or owner).", {"lead_id": I, **LEAD_FIELDS}, ["lead_id"]),
    _tool("move_lead_stage", "Move a lead to New, Nurturing or Demo. Demo needs demo_date.", {
        "lead_id": I, "stage": {"type": "string", "enum": ["New", "Nurturing", "Demo"]}, "demo_date": DATE_TIME,
        "note": S, "completed_stages": COMPLETED}, ["lead_id", "stage"]),
    _tool("reschedule_demo", "Move a booked demo to a new date and time (the lead stays at Demo).", {
        "lead_id": I, "new_date": DATE_TIME, "reason": S}, ["lead_id", "new_date"]),
    _tool("convert_lead", "Convert a lead into an account, contact and opportunity.", {
        "lead_id": I, "opportunity_name": S, "amount": N, "close_date": DATE, "completed_stages": COMPLETED}, ["lead_id"]),
    _tool("move_opportunity_stage", "Move an opportunity to Opportunity or Proposal.", {
        "opportunity_id": I, "stage": {"type": "string", "enum": ["Opportunity", "Proposal"]}, "note": S},
        ["opportunity_id", "stage"]),
    _tool("create_task", "Create a follow-up task, optionally on a lead or an opportunity.", {
        "title": S, "due_date": DATE_TIME, "priority": {"type": "string", "enum": ["Low", "Normal", "High"]},
        "description": S, "lead_id": I, "opportunity_id": I}, ["title", "due_date"]),
    _tool("complete_task", "Mark a task as done.", {"task_id": I}, ["task_id"]),
    _tool("add_note", "Add a note to a lead or an opportunity.", {"body": S, "lead_id": I, "opportunity_id": I}, ["body"]),
    # the user confirms these in the app before they run
    _tool("mark_lead_lost", "Close a lead as Lost (needs the user's confirmation).", {
        "lead_id": I, "reason": LOST, "notes": S,
        "notify_customer": {"type": "boolean", "description": "Default false. True only if the user asks to email the customer"}},
        ["lead_id", "reason"]),
    _tool("cancel_demo", "Cancel a demo and move the lead back to Nurturing (needs confirmation). "
          "To change the date instead, use reschedule_demo.", {"lead_id": I, "reason": S}, ["lead_id"]),
    _tool("transfer_lead", "Give a lead to another user (needs confirmation).", {
        "lead_id": I, "to_user_name": S, "note": S}, ["lead_id", "to_user_name"]),
    _tool("mark_opportunity_won", "Close a deal as Won (needs confirmation).", {
        "opportunity_id": I, "final_amount": N, "note": S, "completed_stages": COMPLETED,
        "notify_customer": {"type": "boolean", "description": "Default false"}}, ["opportunity_id"]),
    _tool("mark_opportunity_lost", "Close a deal as Lost (needs confirmation).", {
        "opportunity_id": I, "reason": LOST, "notes": S, "notify_customer": {"type": "boolean"}},
        ["opportunity_id", "reason"]),
    _tool("delete_lead", "Delete a lead (needs confirmation).", {"lead_id": I}, ["lead_id"]),
]
CONFIRM_FIRST = {"mark_lead_lost", "cancel_demo", "transfer_lead", "mark_opportunity_won", "mark_opportunity_lost",
                 "delete_lead"}


# ---------- running a tool ----------

def _plain(value):
    """API results -> JSON the model can read (short)."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.loads(json.dumps(value, default=lambda o: float(o) if isinstance(o, Decimal) else str(o)))


def _user_id(db: Session, name: str | None) -> int | None:
    """'Priya' / 'priya@x.com' -> user id (active users only)."""
    if not name:
        return None
    term = name.strip().lower()
    users = [u for u in db.query(User).filter(User.is_active.is_(True)).all()]
    exact = [u for u in users if term in (u.full_name.lower(), u.email.lower())]
    found = exact or [u for u in users if term in u.full_name.lower() or term in u.email.lower()]
    if len(found) != 1:
        names = ", ".join(u.full_name for u in (found or users))
        raise HTTPException(status_code=400, detail=f'No single user matches "{name}". Users: {names}')
    return found[0].id


def _lead_row(l):
    return {k: l.get(k) for k in ("id", "name", "company", "title", "email", "phone", "stage", "source",
                                  "owner_name", "demo_date", "created_at")}


def _opp_row(o):
    return {k: o.get(k) for k in ("id", "name", "account_name", "stage", "expected_value", "final_value",
                                  "expected_close_date", "owner_name")}


def _task_row(t):
    return {k: t.get(k) for k in ("id", "title", "due_date", "priority", "status", "related_type", "related_to",
                                  "owner_name", "is_overdue")}


def _link(kind: str, record: dict | None) -> dict | None:
    if not record or "id" not in record:
        return None
    return {"type": kind, "id": record["id"], "name": record.get("name") or record.get("title") or f"{kind} {record['id']}"}


def run_tool(db: Session, name: str, args: dict) -> tuple[dict, dict | None]:
    """Runs one tool as the logged-in user. Returns (result for the model, record link for the screen)."""
    a = {k: v for k, v in args.items() if v is not None}
    me = acting_user()
    if name == "search":
        return {"results": _plain(activity.search(q=a["query"], db=db))}, None
    if name == "list_leads":
        rows = leads.list_leads(stage=a.get("stage"), source=None, owner_id=_user_id(db, a.get("owner_name")),
                                search=a.get("search"), include_untouched=False, db=db)
        rows = [_lead_row(_plain(r)) for r in rows]
        return {"count": len(rows), "leads": rows[:MAX_LIST], "more": max(0, len(rows) - MAX_LIST)}, None
    if name == "get_lead":
        out = _plain(leads.get_lead(lead_id=a["lead_id"], db=db))
        out["tasks"] = [_task_row(t) for t in out.get("tasks", []) if t.get("status") == "Open"]
        return out, _link("Lead", out)
    if name == "list_opportunities":
        rows = opportunities.list_opportunities(stage=a.get("stage"), owner_id=_user_id(db, a.get("owner_name")),
                                                account_id=None, search=a.get("search"), db=db)
        rows = [_opp_row(_plain(r)) for r in rows]
        return {"count": len(rows), "opportunities": rows[:MAX_LIST], "more": max(0, len(rows) - MAX_LIST)}, None
    if name == "get_opportunity":
        out = _plain(opportunities.get_opportunity(opportunity_id=a["opportunity_id"], db=db))
        out["tasks"] = [_task_row(t) for t in out.get("tasks", []) if t.get("status") == "Open"]
        return out, _link("Opportunity", out)
    if name == "list_tasks":
        rows = tasks.list_tasks(status_filter="Open", due=a.get("due"),
                                owner_id=me.id if a.get("mine_only", True) else None, lead_id=None, opportunity_id=None, db=db)
        rows = [_task_row(_plain(r)) for r in rows]
        return {"count": len(rows), "tasks": rows[:MAX_LIST], "more": max(0, len(rows) - MAX_LIST)}, None
    if name == "list_users":
        return {"users": [{"id": u.id, "name": u.full_name, "role": u.role, "email": u.email}
                          for u in db.query(User).filter(User.is_active.is_(True)).order_by(User.full_name)]}, None
    if name == "pipeline_summary":
        data = _plain(home.home_page(owner_id=me.id if a.get("mine_only") else None, db=db))
        return {k: data.get(k) for k in ("summary", "pipeline", "won_vs_lost")}, None
    if name == "create_lead":
        fields = {k: a[k] for k in LEAD_FIELDS if k in a}
        data = schemas.LeadCreate(**fields, owner_id=_user_id(db, a.get("owner_name")),
                                  welcome_email=bool(a.get("send_welcome_email")))
        out = _plain(leads.create_lead(data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "update_lead":
        fields = {k: a[k] for k in LEAD_FIELDS if k in a}
        out = _plain(leads.update_lead(lead_id=a["lead_id"], data=schemas.LeadUpdate(**fields), db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "move_lead_stage":
        data = schemas.LeadStageChange(stage=a["stage"], demo_date=a.get("demo_date"), note=a.get("note"),
                                       completed_stages=a.get("completed_stages", []))
        out = _plain(leads.change_stage(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "reschedule_demo":
        data = schemas.CancelDemo(reason=a.get("reason"), reschedule_to=a["new_date"])
        out = _plain(leads.cancel_demo(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "convert_lead":
        data = schemas.ConvertLead(opportunity_name=a.get("opportunity_name"), expected_value=a.get("amount"),
                                   expected_close_date=a.get("close_date"), completed_stages=a.get("completed_stages", []))
        out = _plain(leads.convert_lead(lead_id=a["lead_id"], data=data, db=db))
        opp = out.get("opportunity") or {}
        return {"opportunity": _opp_row(opp), "account": (out.get("account") or {}).get("name")}, _link("Opportunity", opp)
    if name == "move_opportunity_stage":
        data = schemas.OpportunityStageChange(stage=a["stage"], note=a.get("note"))
        out = _plain(opportunities.change_stage(opportunity_id=a["opportunity_id"], data=data, db=db))
        return _opp_row(out), _link("Opportunity", out)
    if name == "create_task":
        data = schemas.TaskCreate(title=a["title"], due_date=a["due_date"], priority=a.get("priority", "Normal"),
                                  description=a.get("description"), lead_id=a.get("lead_id"),
                                  opportunity_id=a.get("opportunity_id"))
        out = _plain(tasks.create_task(data=data, db=db))
        return _task_row(out), _link("Task", out)
    if name == "complete_task":
        out = _plain(tasks.complete_task(task_id=a["task_id"], db=db))
        return _task_row(out), _link("Task", out)
    if name == "add_note":
        data = schemas.NoteCreate(body=a["body"], lead_id=a.get("lead_id"), opportunity_id=a.get("opportunity_id"))
        out = _plain(activity.add_note(data=data, db=db))
        target = ("Lead", {"id": a["lead_id"]}) if a.get("lead_id") else ("Opportunity", {"id": a.get("opportunity_id")})
        return {"note_added": True, "id": out.get("id")}, _link(*target) if target[1]["id"] else None
    if name == "mark_lead_lost":
        data = schemas.MarkLost(lost_reason=a["reason"], lost_notes=a.get("notes"),
                                notify_customer=bool(a.get("notify_customer")))
        out = _plain(leads.mark_lost(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "cancel_demo":
        out = _plain(leads.cancel_demo(lead_id=a["lead_id"], data=schemas.CancelDemo(reason=a.get("reason")), db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "transfer_lead":
        data = schemas.LeadTransfer(to_user_id=_user_id(db, a["to_user_name"]), note=a.get("note"))
        out = _plain(leads.transfer(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "mark_opportunity_won":
        data = schemas.MarkWon(final_value=a.get("final_amount"), note=a.get("note"),
                               completed_stages=a.get("completed_stages", []),
                               notify_customer=bool(a.get("notify_customer")))
        out = _plain(opportunities.mark_won(opportunity_id=a["opportunity_id"], data=data, db=db))
        return _opp_row(out), _link("Opportunity", out)
    if name == "mark_opportunity_lost":
        data = schemas.MarkLost(lost_reason=a["reason"], lost_notes=a.get("notes"),
                                notify_customer=bool(a.get("notify_customer")))
        out = _plain(opportunities.mark_lost(opportunity_id=a["opportunity_id"], data=data, db=db))
        return _opp_row(out), _link("Opportunity", out)
    if name == "delete_lead":
        return _plain(leads.delete_lead(lead_id=a["lead_id"], db=db)), None
    raise HTTPException(status_code=400, detail=f"Unknown action {name}")


def safe_run(db: Session, name: str, args: dict) -> tuple[dict, dict | None]:
    """Like run_tool, but a refusal (no permission, missing field, wrong stage...) goes back to the model as text."""
    try:
        return run_tool(db, name, args)
    except HTTPException as exc:
        db.rollback()
        return {"error": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)}, None
    except ValidationError as exc:
        db.rollback()
        return {"error": "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())}, None
    except (KeyError, TypeError, ValueError) as exc:
        db.rollback()
        return {"error": f"Missing or wrong value: {exc}"}, None


def describe(db: Session, name: str, a: dict) -> str:
    """One line for the Confirm card."""
    from app.models import Lead, Opportunity  # noqa: avoid a wide import at module load

    lead = db.get(Lead, a["lead_id"]) if a.get("lead_id") else None
    opp = db.get(Opportunity, a["opportunity_id"]) if a.get("opportunity_id") else None
    lname = f'"{lead.name}" ({lead.company})' if lead else f"lead {a.get('lead_id')}"
    oname = f'"{opp.name}"' if opp else f"opportunity {a.get('opportunity_id')}"
    mail = " The customer will be emailed." if a.get("notify_customer") else ""
    return {
        "mark_lead_lost": f"Mark lead {lname} as Lost (reason: {a.get('reason')}).{mail}",
        "cancel_demo": f"Cancel the demo with {lname} and move it back to Nurturing.",
        "transfer_lead": f"Transfer lead {lname} to {a.get('to_user_name')}.",
        "mark_opportunity_won": f"Mark {oname} as Won"
                                + (f" for {a['final_amount']:,.0f}" if a.get("final_amount") is not None else "") + f".{mail}",
        "mark_opportunity_lost": f"Mark {oname} as Lost (reason: {a.get('reason')}).{mail}",
        "delete_lead": f"Delete lead {lname}. This can't be undone.",
    }.get(name, name)


# ---------- talking to the model ----------

def system_prompt() -> str:
    me = acting_user()
    now = datetime.now()
    return (
        "You are the SalesTrack CRM assistant. You help the logged-in user do their CRM work by calling tools. "
        f"Today is {now:%A, %d %B %Y}, time {now:%I:%M %p} (America/New_York). "
        f"The user is {me.full_name} ({me.role}).\n"
        "Rules:\n"
        "- Use tools for every fact and action. Never invent ids, names or numbers: search or list first.\n"
        "- If several records match, ask which one. If required details are missing (lead: last name and company; "
        "demo: date and time), ask for them in one short question.\n"
        "- Lead stages go New -> Nurturing -> Demo -> Convert; deals go Opportunity -> Proposal -> Won. Stages can't be "
        "skipped: if a tool says a stage is missing, ask the user whether it was already done, and only then pass it "
        "in completed_stages.\n"
        "- Closing actions (Lost, Won, transfer, cancel demo, delete) are confirmed by the user in the app: call the "
        "tool, then tell the user to press Confirm.\n"
        "- Don't email customers unless the user asks.\n"
        "- If a tool returns an error, explain it plainly (e.g. missing permission) and suggest what to do.\n"
        "- Answer briefly. Use short lists for several records. Dates like 5 Nov 2026, 3:00 PM. Amounts like 25,000."
    )


def call_model(messages: list[dict]) -> dict:
    """One Chat Completions call. Returns the assistant message (may contain tool_calls)."""
    cfg = settings()
    try:
        res = httpx.post(f"{cfg['base_url']}/chat/completions", timeout=60,
                         headers={"Authorization": f"Bearer {cfg['key']}"},
                         json={"model": cfg["model"], "messages": messages, "tools": TOOLS, "temperature": 0.1})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"The AI service could not be reached: {exc}") from exc
    if res.status_code == 401:
        raise HTTPException(status_code=502, detail="The AI service refused the API key. Check OPENAI_API_KEY in .env.")
    if res.status_code >= 400:
        try:
            msg = res.json().get("error", {}).get("message") or res.text
        except ValueError:
            msg = res.text
        raise HTTPException(status_code=502, detail=f"AI service error: {msg[:300]}")
    return res.json()["choices"][0]["message"]


def converse(db: Session, history: list[dict]) -> dict:
    """Runs the tool loop until the model answers in words, or an action needs the user's confirmation.
    history: the conversation so far in OpenAI format (without the system message)."""
    messages = list(history)
    links, done = [], []
    for _ in range(MAX_STEPS):
        reply = call_model([{"role": "system", "content": system_prompt()}, *messages])
        msg = {"role": "assistant", "content": reply.get("content") or ""}
        calls = reply.get("tool_calls") or []
        if calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                                 for c in calls]
        messages.append(msg)
        if not calls:
            return {"messages": messages, "reply": msg["content"], "links": links, "done": done, "pending": None}
        pending = None
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except ValueError:
                args = {}
            if name in CONFIRM_FIRST:
                if pending is None:
                    pending = {"call_id": c["id"], "tool": name, "args": args, "summary": describe(db, name, args)}
                    continue  # answered when the user clicks Confirm or Cancel
                result, link = {"error": "Only one action can wait for confirmation at a time. Ask again after this one."}, None
            else:
                result, link = safe_run(db, name, args)
                if link and "error" not in result:
                    links.append(link)
                    done.append(name)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)[:6000]})
        if pending:
            text = msg["content"] or "This needs your confirmation:"
            return {"messages": messages, "reply": text, "links": links, "done": done, "pending": pending}
    return {"messages": messages, "reply": "That took too many steps. Please break it into smaller requests.",
            "links": links, "done": done, "pending": None}


def resolve(db: Session, history: list[dict], pending: dict, confirmed: bool) -> dict:
    """The user clicked Confirm or Cancel on a pending action: run it (or not), then let the model finish."""
    calls = {c["id"] for m in history if m.get("role") == "assistant" for c in m.get("tool_calls") or []}
    answered = {m.get("tool_call_id") for m in history if m.get("role") == "tool"}
    if pending.get("call_id") not in calls or pending["call_id"] in answered or pending.get("tool") not in CONFIRM_FIRST:
        raise HTTPException(status_code=400, detail="This action is no longer waiting for confirmation")
    links = []
    if confirmed:
        result, link = safe_run(db, pending["tool"], pending.get("args") or {})
        if link and "error" not in result:
            links.append(link)
    else:
        result = {"cancelled": "The user cancelled this action. Nothing was changed."}
    messages = [*history, {"role": "tool", "tool_call_id": pending["call_id"], "content": json.dumps(result)[:6000]}]
    out = converse(db, messages)
    out["links"] = links + out["links"]
    return out


def clean_history(raw: list[dict]) -> list[dict]:
    """Keeps only well-formed messages from the browser, and closes any action that was never confirmed
    (the user typed a new message instead of pressing Confirm), so the conversation stays valid."""
    out = []
    for m in raw[-60:]:
        role = m.get("role")
        if role == "user" and isinstance(m.get("content"), str):
            out.append({"role": "user", "content": m["content"][:4000]})
        elif role == "assistant":
            msg = {"role": "assistant", "content": str(m.get("content") or "")[:8000]}
            calls = [c for c in m.get("tool_calls") or [] if isinstance(c, dict) and c.get("id") and c.get("function")]
            if calls:
                msg["tool_calls"] = [{"id": str(c["id"]), "type": "function", "function": {
                    "name": str(c["function"].get("name", "")), "arguments": str(c["function"].get("arguments", "{}"))}}
                    for c in calls]
            out.append(msg)
        elif role == "tool" and m.get("tool_call_id"):
            out.append({"role": "tool", "tool_call_id": str(m["tool_call_id"]), "content": str(m.get("content", ""))[:6000]})
    # drop tool results whose call is gone (history was cut), and answer calls that never got a result
    calls = {c["id"] for m in out if m["role"] == "assistant" for c in m.get("tool_calls", [])}
    out = [m for m in out if m["role"] != "tool" or m["tool_call_id"] in calls]
    while out and out[0]["role"] != "user":
        out.pop(0)
    fixed = []
    for i, m in enumerate(out):
        fixed.append(m)
        for c in m.get("tool_calls", []) if m["role"] == "assistant" else []:
            later = out[i + 1:]
            if not any(x["role"] == "tool" and x["tool_call_id"] == c["id"] for x in later):
                fixed.append({"role": "tool", "tool_call_id": c["id"],
                              "content": json.dumps({"cancelled": "Not confirmed by the user. Nothing was changed."})})
    return fixed
