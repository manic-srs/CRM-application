"""SalesTrack AI Assistant: do CRM work from one sentence ("Create a lead Ravi Kumar at Acme, source Website").

It only helps with this CRM (leads, opportunities, accounts, contacts, tasks, demos, reports): other questions and web
searches are politely declined. Details can be given in any format (a sentence, a pasted signature or email, an
attached file); the model picks the fields out. Numbers for reports come from the database (assistant_reports.py).

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
import re
from datetime import datetime
from decimal import Decimal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app import schemas
from app.assistant_reports import PERIODS, crm_report
from app.constants import (LEAD_FLOW, LEAD_STAGES, OPPORTUNITY_FLOW, OPPORTUNITY_STAGES, REVISIT_REASONS,
                           UNQUALIFIED_REASONS)
from app.models import Lead, User
from app.routers import accounts, activity, home, leads, opportunities, tasks
from app.security import acting_user
from app.services import log_activity

log = logging.getLogger("crm.assistant")
MAX_STEPS = 10         # model <-> tool round trips per message
MAX_LIST = 25          # rows a list tool returns to the model
MAX_USER_CHARS = 90_000  # a message with pasted details or attached files' text (kept whole in the history)
MAX_TOOL_CHARS = 12_000  # a tool result the model reads


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
NOTE = {"type": "string", "description": "Required: the user's own note for this stage change, in their words. "
        "Ask the user for it; never write it yourself."}
CONVERSION_COMMENT = {"type": "string", "description": "Required: the user's own Conversion Comment (why the lead is "
                      "converted), in their words. Ask the user for it; never write it yourself."}
# Every stage change except Lost needs the user's new task (on Won: a post-sale task such as handover or onboarding)
TASK_ARGS = {
    "task_title": {"type": "string", "description": "Required: the subject of the new task the user wants with this "
                   "change (for Won, a post-sale task such as handover or onboarding). Ask the user; never make it up."},
    "task_due_date": {"type": "string", "description": "Required: when the new task is due, ISO date and time "
                      "(e.g. 2026-11-05T15:00). Ask the user; never make it up."},
    "task_priority": {"type": "string", "enum": ["Low", "Normal", "High"], "description": "Default Normal"},
    "task_description": S,
}
TASK_REQUIRED = ["task_title", "task_due_date"]
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
        "stage": {"type": "string", "enum": LEAD_STAGES},
        "search": S, "owner_name": {"type": "string", "description": "Only this user's leads"}}),
    _tool("get_lead", "Full details of one lead: fields, open tasks, notes, stage and transfer history.",
          {"lead_id": I}, ["lead_id"]),
    _tool("list_opportunities", "List opportunities (deals) the user can see.", {
        "stage": {"type": "string", "enum": OPPORTUNITY_STAGES}, "search": S,
        "owner_name": S}),
    _tool("get_opportunity", "Full details of one opportunity.", {"opportunity_id": I}, ["opportunity_id"]),
    _tool("list_tasks", "List open tasks (follow-ups, demos, reminders).", {
        "due": {"type": "string", "enum": ["overdue", "today", "upcoming"]},
        "mine_only": {"type": "boolean", "description": "Default true: only the user's own tasks"}}),
    _tool("list_users", "Active users (for owners and transfers)."),
    _tool("pipeline_summary", "Numbers for the dashboard: leads per stage, open deals, won and lost, today's tasks.", {
        "mine_only": {"type": "boolean", "description": "Default false: the whole team the user can see"}}),
    _tool("crm_report", "Exact statistics and reports counted in the database: leads created / converted / lost, "
          "conversion rate, opportunities created / won / lost with amounts, win rate, average deal, pipeline by "
          "stage, won by owner, lost reasons, biggest open deals, tasks open / overdue / completed. Use it for EVERY "
          "number, total, rate or comparison (never count from list results, which are capped).", {
              "period": {"type": "string", "enum": PERIODS, "description": "Default all_time"},
              "date_from": DATE, "date_to": DATE,
              "owner_name": {"type": "string", "description": "Only this user's records"}}),
    _tool("list_accounts", "List accounts (companies) the user can see.", {"search": S}),
    _tool("get_account", "One account with its contacts and opportunities.", {"account_id": I}, ["account_id"]),
    _tool("list_contacts", "List contacts (people at accounts).", {"search": S, "account_id": I}),
    _tool("create_account", "Create an account (company) without a lead. Industry and phone are required: take them "
          "from what the user gave, otherwise ask; never make them up.", {
        "name": S, "industry": S, "phone": S, "website": S, "address": S}, ["name", "industry", "phone"]),
    _tool("create_contact", "Add a contact (person) to an account. Email and phone are required: take them from what "
          "the user gave, otherwise ask; never make them up.", {
        "account_id": I, "salutation": LEAD_FIELDS["salutation"], "first_name": S, "last_name": S, "job_title": S,
        "email": S, "phone": S}, ["account_id", "last_name", "email", "phone"]),
    _tool("create_opportunity", "Create a new opportunity directly (without converting a lead). Give the account "
          "(account_id, or account_name: an existing account with that company name is reused) and the contact "
          "(contact_id, or contact_last_name and the rest: an existing contact with that email or name is reused). "
          "The same open opportunity for the same person and company can't be created twice.", {
              "name": {"type": "string", "description": "Opportunity name"}, "account_id": I, "account_name": S,
              "contact_id": I, "contact_first_name": S, "contact_last_name": S, "contact_email": S, "contact_title": S,
              "contact_phone": S, "amount": N, "close_date": DATE,
              "owner_name": {"type": "string", "description": "Only when the user names another owner"},
              "note": {"type": "string", "description": "Required: why the opportunity is opened, in the user's own "
                       "words (take them from what the user said; ask only if they gave no reason)."},
              **TASK_ARGS}, ["name", "note", *TASK_REQUIRED]),
    _tool("update_opportunity", "Change an opportunity's name, amount, close date, contact or discovery details "
          "(not its stage or owner).", {
              "opportunity_id": I, "name": S, "amount": N, "close_date": DATE, "primary_contact_id": I,
              "discovery_needs": S, "discovery_budget": S, "discovery_decision_maker": S, "discovery_timeline": S},
          ["opportunity_id"]),
    _tool("update_task", "Change a task: reschedule it, rename it or change its priority or description.", {
        "task_id": I, "title": S, "due_date": DATE_TIME, "priority": {"type": "string", "enum": ["Low", "Normal", "High"]},
        "description": S}, ["task_id"]),
    _tool("reopen_lead", "Bring an Unqualified lead back to New.", {"lead_id": I, "note": NOTE, **TASK_ARGS},
          ["lead_id", "note", *TASK_REQUIRED]),
    _tool("create_lead", "Create a lead at stage New. Required, like the New Lead form: Last Name, Company, Email, "
          "Company Website and Company LinkedIn URL (Lead Source defaults to Other). Take them from what the user gave; "
          "ask only for the missing required ones, never make them up.", {
        **LEAD_FIELDS, "owner_name": {"type": "string", "description": "Only when the user names another owner"}},
        ["last_name", "company", "email", "company_website", "company_linkedin_url"]),
    _tool("update_lead", "Change details of a lead (not its stage or owner).", {"lead_id": I, **LEAD_FIELDS}, ["lead_id"]),
    _tool("move_lead_stage", "Move a lead to New, Nurturing, Revisit or Demo. Demo needs demo_date; Revisit needs revisit_date and revisit_reason.", {
        "lead_id": I, "stage": {"type": "string", "enum": LEAD_FLOW}, "demo_date": DATE_TIME,
        "revisit_date": DATE_TIME, "revisit_reason": {"type": "string", "enum": REVISIT_REASONS},
        "note": NOTE, "completed_stages": COMPLETED, **TASK_ARGS}, ["lead_id", "stage", "note", *TASK_REQUIRED]),
    _tool("reschedule_demo", "Move a booked demo to a new date and time (the lead stays at Demo).", {
        "lead_id": I, "new_date": DATE_TIME, "reason": S}, ["lead_id", "new_date"]),
    _tool("convert_lead", "Convert a lead into an account, contact and opportunity.", {
        "lead_id": I, "note": CONVERSION_COMMENT, "opportunity_name": S, "amount": N, "close_date": DATE,
        "completed_stages": COMPLETED, **TASK_ARGS}, ["lead_id", "note", *TASK_REQUIRED]),
    _tool("move_opportunity_stage", "Move an opportunity to Opportunity, Discovery or Proposal.", {
        "opportunity_id": I, "stage": {"type": "string", "enum": OPPORTUNITY_FLOW}, "note": NOTE,
        "completed_stages": COMPLETED,
        **TASK_ARGS}, ["opportunity_id", "stage", "note", *TASK_REQUIRED]),
    _tool("create_task", "Create a follow-up task, optionally on a lead or an opportunity.", {
        "title": S, "due_date": DATE_TIME, "priority": {"type": "string", "enum": ["Low", "Normal", "High"]},
        "description": S, "lead_id": I, "opportunity_id": I}, ["title", "due_date"]),
    _tool("complete_task", "Mark a task as done.", {"task_id": I}, ["task_id"]),
    _tool("add_note", "Add a note to a lead or an opportunity.", {"body": S, "lead_id": I, "opportunity_id": I}, ["body"]),
    # the user confirms these in the app before they run
    _tool("mark_lead_lost", "Close a lead as Lost (needs the user's confirmation).", {
        "lead_id": I, "reason": LOST, "notes": NOTE},
        ["lead_id", "reason", "notes"]),
    _tool("cancel_demo", "Cancel a demo and move the lead back to Revisit (needs confirmation). "
          "To change the date instead, use reschedule_demo.", {"lead_id": I, "reason": NOTE, **TASK_ARGS},
          ["lead_id", "reason", *TASK_REQUIRED]),
    _tool("transfer_lead", "Give a lead to another user (needs confirmation).", {
        "lead_id": I, "to_user_name": S, "note": S}, ["lead_id", "to_user_name"]),
    _tool("mark_opportunity_won", "Close a deal as Won (needs confirmation).", {
        "opportunity_id": I, "final_amount": N, "note": NOTE, "completed_stages": COMPLETED, **TASK_ARGS},
        ["opportunity_id", "note", *TASK_REQUIRED]),
    _tool("mark_opportunity_lost", "Close a deal as Lost (needs confirmation).", {
        "opportunity_id": I, "reason": LOST, "notes": NOTE},
        ["opportunity_id", "reason", "notes"]),
    _tool("delete_lead", "Delete a lead (needs confirmation).", {"lead_id": I}, ["lead_id"]),
    _tool("mark_lead_unqualified", "Close a lead as Unqualified: not eligible (needs confirmation).", {
        "lead_id": I, "reason": {"type": "string", "enum": UNQUALIFIED_REASONS}, "notes": NOTE},
        ["lead_id", "reason", "notes"]),
]
CONFIRM_FIRST = {"mark_lead_lost", "cancel_demo", "transfer_lead", "mark_opportunity_won", "mark_opportunity_lost",
                 "delete_lead", "mark_lead_unqualified"}
# Stage changes and the argument that carries the user's note (required, like on the screens)
NOTE_ARGS = {"move_lead_stage": "note", "convert_lead": "note", "move_opportunity_stage": "note",
             "mark_lead_lost": "notes", "cancel_demo": "reason", "mark_opportunity_won": "note",
             "mark_opportunity_lost": "notes", "create_opportunity": "note", "reopen_lead": "note",
             "mark_lead_unqualified": "notes"}
NOTE_MISSING = f"{schemas.STAGE_NOTE_REQUIRED} Ask the user for their note; don't write one for them."
COMMENT_MISSING = (f"{schemas.CONVERSION_COMMENT_REQUIRED} Ask the user for their conversion comment; "
                   "don't write one for them.")
TASK_TOOLS = {"move_lead_stage", "convert_lead", "move_opportunity_stage", "mark_opportunity_won", "cancel_demo",
              "create_opportunity", "reopen_lead"}
TASK_MISSING = (f"{schemas.STAGE_TASK_REQUIRED} Ask the user for the task's subject and due date (for Won, a post-sale "
                "task such as handover or onboarding); don't make them up.")


# The required fields of each form in the app (the red * on the screen). A create call missing any of them isn't
# run: the model is told to ask the user for exactly those, in one question. (New account / contact: the API's own
# checks already name the missing Industry, Phone or Email.)
REQUIRED_FIELDS = {
    "create_lead": [("last_name", "Last Name"), ("company", "Company"), ("email", "Email"),
                    ("company_website", "Company Website"), ("company_linkedin_url", "Company LinkedIn URL")],
    "create_task": [("title", "Subject"), ("due_date", "Due Date")],
    "create_opportunity": [("name", "Opportunity Name"), (("account_id", "account_name"), "Account (company)"),
                           (("contact_id", "contact_last_name"), "Contact Last Name")],
}


def missing_required(name: str, args: dict) -> list[str]:
    """The labels of the required fields the call leaves empty (as the app names them)."""
    def given(key):
        value = args.get(key)
        return value is not None and (not isinstance(value, str) or value.strip() != "")
    missing = []
    for keys, label in REQUIRED_FIELDS.get(name, []):
        if not any(given(k) for k in (keys if isinstance(keys, tuple) else (keys,))):
            missing.append(label)
    return missing


def required_message(missing: list[str]) -> str:
    return (f"Not created yet. Required fields missing: {', '.join(missing)}. Ask the user for only these, in one short "
            "question (other fields are optional; don't list them). Never make them up.")


# ---------- what each role is offered (the API still checks every call) ----------

READ_TOOLS = {"search", "list_leads", "get_lead", "list_opportunities", "get_opportunity", "list_tasks", "list_users",
              "pipeline_summary", "crm_report", "list_accounts", "get_account", "list_contacts"}
SALES_TOOLS = {"create_lead", "update_lead", "move_lead_stage", "reschedule_demo", "convert_lead", "move_opportunity_stage",
               "mark_lead_lost", "cancel_demo", "mark_opportunity_won", "mark_opportunity_lost", "mark_lead_unqualified",
               "reopen_lead"}
NEEDS_PERMISSION = {"transfer_lead": ("transfer_leads", "reassign_owner")}


def tools_for(me) -> list[dict]:
    """The tools offered to this user, by role and permissions:
    - Admin: reports, lists and user information only - no sales actions (leads, stages, deals, tasks)
    - Manager / Salesperson: the sales tools; transfer and delete only with those permissions.
    Record access is unchanged: every tool runs through the same API as the screens, as this user."""
    if me.role == "Admin":
        return [t for t in TOOLS if t["function"]["name"] in READ_TOOLS]
    return [t for t in TOOLS if not (need := NEEDS_PERMISSION.get(t["function"]["name"])) or any(me.can(p) for p in need)]


def role_guidance(me) -> str:
    if me.role == "Admin":
        return ("Role: Admin. Help with reports, statistics, record look-ups and user information. You don't do sales "
                "work (creating or changing leads, deals, stages, tasks or notes): if asked, say that the record's owner "
                "or their Manager does it in SalesTrack.\n")
    if me.role == "Manager":
        return ("Role: Manager. You can work on the team's records and report on the team. For a report about one "
                "salesperson, pass their name as the owner.\n")
    scope = "the whole team's records (view only)" if me.can("view_team_records") else "only your own records"
    return f"Role: Salesperson. You work on {scope}; reports cover your own records unless the user has team access.\n"


def stage_task(args: dict) -> dict | None:
    """The user's new task from the tool arguments (None when they gave none; the API then refuses the change)."""
    if not any(args.get(k) for k in ("task_title", "task_due_date")):
        return None
    task = {"title": args.get("task_title"), "due_date": args.get("task_due_date"),
            "priority": args.get("task_priority"), "description": args.get("task_description")}
    return {k: v for k, v in task.items() if v is not None}


def has_task(args: dict) -> bool:
    return all(isinstance(args.get(k), str) and args[k].strip() for k in TASK_REQUIRED)


def user_note(name: str, args: dict) -> str:
    """The note the user gave for this stage change ("" when there is none)."""
    note = args.get(NOTE_ARGS.get(name, ""))
    return note.strip() if isinstance(note, str) else ""


def fill_defaults(db: Session, name: str, args: dict) -> dict:
    """Booking a demo needs no extra typing: when the user gives the lead and the demo date and time, the demo itself
    is the new task (due at the demo) and the note says when it was booked, unless the user said otherwise."""
    if name != "move_lead_stage" or args.get("stage") != "Demo" or not args.get("demo_date"):
        return args
    args = dict(args)
    lead = db.get(Lead, args["lead_id"]) if isinstance(args.get("lead_id"), int) else None
    who = lead.name if lead else "the lead"
    if not any(isinstance(args.get(k), str) and args[k].strip() for k in ("task_title", "task_due_date")):
        args["task_title"], args["task_due_date"] = f"Demo with {who}", args["demo_date"]
    if not user_note(name, args):
        try:
            when = datetime.fromisoformat(str(args["demo_date"])[:16])
            args["note"] = f"Demo booked for {when:%d %b %Y, %I:%M %p}."
        except ValueError:
            args["note"] = f"Demo booked for {args['demo_date']}."
    return args


# ---------- running a tool ----------

def _plain(value):
    """API results -> JSON the model can read (short)."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    def default(o):
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        return float(o) if isinstance(o, Decimal) else str(o)

    return json.loads(json.dumps(value, default=default))


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


def _account_row(a):
    return {k: a.get(k) for k in ("id", "name", "industry", "phone", "website", "owner_name")}


def _contact_row(c):
    return {k: c.get(k) for k in ("id", "full_name", "job_title", "email", "phone", "account_id", "account_name")}


def _link(kind: str, record: dict | None) -> dict | None:
    if not record or "id" not in record:
        return None
    return {"type": kind, "id": record["id"],
            "name": record.get("name") or record.get("full_name") or record.get("title") or f"{kind} {record['id']}"}


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
    if name == "crm_report":
        return crm_report(db, period=a.get("period"), date_from=a.get("date_from"), date_to=a.get("date_to"),
                          owner_id=_user_id(db, a.get("owner_name"))), None
    if name == "list_accounts":
        rows = [_account_row(_plain(r)) for r in accounts.list_accounts(search=a.get("search"), owner_id=None, db=db)]
        return {"count": len(rows), "accounts": rows[:MAX_LIST], "more": max(0, len(rows) - MAX_LIST)}, None
    if name == "get_account":
        out = _plain(accounts.get_account(account_id=a["account_id"], db=db))
        out["contacts"] = [_contact_row(c) for c in out.get("contacts", [])][:MAX_LIST]
        out["opportunities"] = [_opp_row(o) for o in out.get("opportunities", [])][:MAX_LIST]
        return out, _link("Account", out)
    if name == "list_contacts":
        rows = [_contact_row(_plain(r)) for r in accounts.list_contacts(account_id=a.get("account_id"),
                                                                        search=a.get("search"), db=db)]
        return {"count": len(rows), "contacts": rows[:MAX_LIST], "more": max(0, len(rows) - MAX_LIST)}, None
    if name == "create_account":
        data = schemas.AccountCreate(**{k: a[k] for k in ("name", "industry", "phone", "website", "address") if k in a})
        out = _plain(accounts.create_account(data=data, db=db))
        return _account_row(out), _link("Account", out)
    if name == "create_contact":
        fields = {k: a[k] for k in ("salutation", "first_name", "last_name", "job_title", "email", "phone", "account_id")
                  if k in a}
        out = _plain(accounts.create_contact(data=schemas.ContactCreate(**fields), db=db))
        return _contact_row(out), _link("Contact", out)
    if name == "create_opportunity":
        data = schemas.OpportunityCreate(
            name=a["name"], note=a.get("note"), task=stage_task(a), expected_value=a.get("amount"),
            expected_close_date=a.get("close_date"), owner_id=_user_id(db, a.get("owner_name")),
            account_id=a.get("account_id"), account_name=a.get("account_name"), primary_contact_id=a.get("contact_id"),
            contact_first_name=a.get("contact_first_name"), contact_last_name=a.get("contact_last_name"),
            contact_email=a.get("contact_email"), contact_title=a.get("contact_title"),
            contact_phone=a.get("contact_phone"))
        out = _plain(opportunities.create_opportunity(data=data, db=db))
        opp = out.get("opportunity") or {}
        return {"opportunity": _opp_row(opp), "account": (out.get("account") or {}).get("name"),
                "contact": (out.get("contact") or {}).get("full_name"), "reused": out.get("reused")}, \
            _link("Opportunity", opp)
    if name == "update_opportunity":
        fields = {"name": a.get("name"), "expected_value": a.get("amount"), "expected_close_date": a.get("close_date"),
                  "primary_contact_id": a.get("primary_contact_id"),
                  **{k: a.get(k) for k in ("discovery_needs", "discovery_budget", "discovery_decision_maker",
                                           "discovery_timeline")}}
        data = schemas.OpportunityUpdate(**{k: v for k, v in fields.items() if v is not None})
        out = _plain(opportunities.update_opportunity(opportunity_id=a["opportunity_id"], data=data, db=db))
        return _opp_row(out), _link("Opportunity", out)
    if name == "update_task":
        fields = {k: a[k] for k in ("title", "due_date", "priority", "description") if k in a}
        out = _plain(tasks.update_task(task_id=a["task_id"], data=schemas.TaskUpdate(**fields), db=db))
        return _task_row(out), _link("Task", out)
    if name == "reopen_lead":
        data = schemas.ReopenLead(note=a.get("note"), task=stage_task(a))
        out = _plain(leads.reopen(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "mark_lead_unqualified":
        data = schemas.MarkUnqualified(reason=a["reason"], notes=a.get("notes"))
        out = _plain(leads.mark_unqualified(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "create_lead":
        fields = {k: a[k] for k in LEAD_FIELDS if k in a}
        data = schemas.LeadCreate(**fields, owner_id=_user_id(db, a.get("owner_name")))
        out = _plain(leads.create_lead(data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "update_lead":
        fields = {k: a[k] for k in LEAD_FIELDS if k in a}
        out = _plain(leads.update_lead(lead_id=a["lead_id"], data=schemas.LeadUpdate(**fields), db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "move_lead_stage":
        data = schemas.LeadStageChange(stage=a["stage"], demo_date=a.get("demo_date"), note=a.get("note"),
                                       revisit_date=a.get("revisit_date"), revisit_reason=a.get("revisit_reason"),
                                       completed_stages=a.get("completed_stages", []), task=stage_task(a))
        out = _plain(leads.change_stage(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "reschedule_demo":
        data = schemas.CancelDemo(reason=a.get("reason"), reschedule_to=a["new_date"])
        out = _plain(leads.cancel_demo(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "convert_lead":
        data = schemas.ConvertLead(note=a.get("note"), opportunity_name=a.get("opportunity_name"),
                                   expected_value=a.get("amount"), expected_close_date=a.get("close_date"),
                                   completed_stages=a.get("completed_stages", []), task=stage_task(a))
        out = _plain(leads.convert_lead(lead_id=a["lead_id"], data=data, db=db))
        opp = out.get("opportunity") or {}
        return {"opportunity": _opp_row(opp), "account": (out.get("account") or {}).get("name")}, _link("Opportunity", opp)
    if name == "move_opportunity_stage":
        data = schemas.OpportunityStageChange(stage=a["stage"], note=a.get("note"), task=stage_task(a),
                                              completed_stages=a.get("completed_stages", []))
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
        data = schemas.MarkLost(lost_reason=a["reason"], lost_notes=a.get("notes"))
        out = _plain(leads.mark_lost(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "cancel_demo":
        out = _plain(leads.cancel_demo(lead_id=a["lead_id"], db=db,
                                       data=schemas.CancelDemo(reason=a.get("reason"), task=stage_task(a))))
        return _lead_row(out), _link("Lead", out)
    if name == "transfer_lead":
        data = schemas.LeadTransfer(to_user_id=_user_id(db, a["to_user_name"]), note=a.get("note"))
        out = _plain(leads.transfer(lead_id=a["lead_id"], data=data, db=db))
        return _lead_row(out), _link("Lead", out)
    if name == "mark_opportunity_won":
        data = schemas.MarkWon(final_value=a.get("final_amount"), note=a.get("note"),
                               completed_stages=a.get("completed_stages", []), task=stage_task(a))
        out = _plain(opportunities.mark_won(opportunity_id=a["opportunity_id"], data=data, db=db))
        return _opp_row(out), _link("Opportunity", out)
    if name == "mark_opportunity_lost":
        data = schemas.MarkLost(lost_reason=a["reason"], lost_notes=a.get("notes"))
        out = _plain(opportunities.mark_lost(opportunity_id=a["opportunity_id"], data=data, db=db))
        return _opp_row(out), _link("Opportunity", out)
    if name == "delete_lead":
        return _plain(leads.delete_lead(lead_id=a["lead_id"], db=db)), None
    raise HTTPException(status_code=400, detail=f"Unknown action {name}")


def safe_run(db: Session, name: str, args: dict) -> tuple[dict, dict | None]:
    """Like run_tool, but a refusal (no permission, missing field, wrong stage...) goes back to the model as text.
    Every change made through the assistant is also written to the Admin's Activity Log (AI Assistant tab)."""
    try:
        result, link = run_tool(db, name, args)
        if name not in READ_TOOLS and "error" not in result:
            log_ai_action(db, name, args, link)
        return result, link
    except HTTPException as exc:
        db.rollback()
        return {"error": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)}, None
    except ValidationError as exc:
        db.rollback()
        return {"error": "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())}, None
    except (KeyError, TypeError, ValueError) as exc:
        db.rollback()
        return {"error": f"Missing or wrong value: {exc}"}, None


def log_ai_action(db: Session, name: str, args: dict, link: dict | None) -> None:
    """Activity Log line for a change made by the AI Assistant: 'AI Assistant: Move lead stage', the record, and
    what was done. Saved straight away (the change itself is already saved by the screen's own API)."""
    try:
        details = describe(db, name, args)
    except Exception:  # noqa: BLE001 - the log line must never break the action
        details = None
    target = (link or {}).get("name") or (details or name.replace("_", " "))
    log_activity(db, acting_user().id, f"AI Assistant: {name.replace('_', ' ').capitalize()}"[:60], target[:200],
                 (details or "")[:1000] or None)
    db.commit()


def describe(db: Session, name: str, a: dict) -> str:
    """One line for the Confirm card."""
    from app.models import Lead, Opportunity  # noqa: avoid a wide import at module load

    lead = db.get(Lead, a["lead_id"]) if a.get("lead_id") else None
    opp = db.get(Opportunity, a["opportunity_id"]) if a.get("opportunity_id") else None
    lname = f'"{lead.name}" ({lead.company})' if lead else f"lead {a.get('lead_id')}"
    oname = f'"{opp.name}"' if opp else f"opportunity {a.get('opportunity_id')}"
    line = {
        "mark_lead_lost": f"Mark lead {lname} as Lost (reason: {a.get('reason')}).",
        "cancel_demo": f"Cancel the demo with {lname} and move it back to Revisit.",
        "transfer_lead": f"Transfer lead {lname} to {a.get('to_user_name')}.",
        "mark_opportunity_won": f"Mark {oname} as Won"
                                + (f" for {a['final_amount']:,.0f}" if a.get("final_amount") is not None else "") + ".",
        "mark_opportunity_lost": f"Mark {oname} as Lost (reason: {a.get('reason')}).",
        "delete_lead": f"Delete lead {lname}. This can't be undone.",
        "mark_lead_unqualified": f"Mark lead {lname} as Unqualified (reason: {a.get('reason')}).",
    }.get(name, name)
    note = user_note(name, a)  # the user sees the note that will be saved in the stage history
    if note:
        line = f'{line} Note: "{note}"'
    if name in TASK_TOOLS and has_task(a):  # ...and the new task that will be created
        line = f'{line} New task: "{a["task_title"].strip()}", due {a["task_due_date"].strip()}.'
    return line


# ---------- talking to the model ----------

SUGGESTION_MARK = "NEXT:"
OFF_TOPIC_REPLY = "Sorry, I can help with SalesTrack CRM tasks & related information."
GREETINGS = re.compile(r"^\s*(hi+|hello+|hey+|hiya|howdy|greetings|good\s+(morning|afternoon|evening|day)|"
                       r"namaste|hola)(\s+(there|team|all|everyone|assistant|salestrack))?[\s!.,:)]*$", re.IGNORECASE)


def greeting_reply(message: str, now: datetime | None = None) -> str | None:
    """A plain 'hi' / 'hello' is answered at once (no AI call): good morning / afternoon / evening, with the user's
    first name, and how can I help with SalesTrack CRM. None for anything else."""
    if not GREETINGS.match(message or ""):
        return None
    hour = (now or datetime.now()).hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    first = (acting_user().full_name or "").split()[0] if acting_user().full_name else ""
    return f"Good {part}{', ' + first if first else ''}! How can I help you with SalesTrack CRM today?"


def system_prompt() -> str:
    me = acting_user()
    now = datetime.now()
    return (
        "You are the SalesTrack CRM assistant. You help the logged-in user do their CRM work by calling tools. "
        f"Today is {now:%A, %d %B %Y}, time {now:%I:%M %p} (America/New_York). "
        f"The user is {me.full_name} ({me.role}).\n"
        + role_guidance(me) +
        "Scope:\n"
        "- Help with SalesTrack CRM work and related information: leads, opportunities (deals), accounts, contacts, "
        "tasks, demos, notes, stages, the sales pipeline, statistics and reports, how to use SalesTrack, files the "
        "user attaches for CRM work, and writing for that work (e.g. drafting an email or message to a lead or "
        "contact about a demo, a stage change, a proposal or a follow-up; summarising a record). These are CRM tasks: "
        "do them.\n"
        f"- For anything unrelated to SalesTrack CRM (general knowledge, maths, news, web searches, coding, personal "
        f"topics), reply with exactly: \"{OFF_TOPIC_REPLY}\" and nothing else. You can't browse the web.\n"
        "Working style:\n"
        "- Do the work with as little back-and-forth as possible. Users give details in any order or format: a "
        "sentence, a list, a pasted email signature or message, or an attached file (business card, resume, lead "
        "list, meeting notes). Pick out every field yourself (name, title, company, email, phone, website, LinkedIn, "
        "location, source, dates, amounts) and act. Ask only for details that are required and truly missing, all in "
        "one short question.\n"
        "- Use tools for every fact and action. Never invent ids, names or numbers: search or list first. If "
        "several records match, ask which one.\n"
        "- Dates: understand words like 'tomorrow 3pm', 'next Friday', 'end of month' and turn them into ISO dates "
        "yourself.\n"
        "- For several records (e.g. leads in an attached list), call the tools once per record in the same step.\n"
        "- Lead stages go New -> Nurturing -> Revisit (optional) -> Demo -> Convert (a lead can be closed as "
        "Unqualified or Lost); deals go Opportunity -> Discovery -> Proposal -> Won. Stages can't be skipped: if a "
        "tool says a stage is missing, ask the user whether it was already done, and only then pass it in "
        "completed_stages.\n"
        "- Every stage change (move, convert, Won, Lost, Unqualified, cancel demo, reopen) and a new opportunity "
        "need the user's own note (for a conversion, the Conversion Comment). Use the user's own words when they said "
        "why (e.g. 'they loved the pricing'); if they gave no reason, ask in one short question. Never invent one. "
        "Booking a demo is the exception: with the lead and the demo date and time, just book it (the demo itself "
        "becomes the task and the note says when it was booked).\n"
        "- Every stage change except Lost and Unqualified also needs a new task: its subject and due date (for Won, "
        "a post-sale task such as handover or onboarding). Take them from what the user said; otherwise ask.\n"
        "- Required fields are the ones marked * in SalesTrack's forms:\n"
        "  - New lead: Last Name, Company, Email, Company Website, Company LinkedIn URL (Lead Source defaults to Other).\n"
        "  - New account: Account Name, Industry, Phone. New contact: Account, Last Name, Email, Phone.\n"
        "  - New task: Subject and Due Date (Priority defaults to Normal).\n"
        "  - New opportunity: Opportunity Name, Account (company), Contact Last Name, the user's comment, and a task "
        "(subject and due date).\n"
        "  When the user starts a task without the details (e.g. 'Create a new lead'), ask for the required fields of "
        "that form only, as a short list, and add one line saying any other details (title, phone, industry...) are "
        "optional. Never list optional fields one by one or mark fields '(optional)'. Take what the user already gave "
        "and ask only for what is still missing. Never invent required values.\n"
        "- New opportunity without a lead: use create_opportunity (existing accounts and contacts are reused; the "
        "same open deal for the same person can't be added twice). To turn a lead into a deal, use convert_lead.\n"
        "- Closing actions (Lost, Unqualified, Won, transfer, cancel demo, delete) are confirmed by the user in the "
        "app: call the tool, then tell the user to press Confirm.\n"
        "- Statistics and reports: always use crm_report (and pipeline_summary) for numbers, totals, rates and "
        "comparisons, and quote its figures exactly. Say which period and scope they cover. Never count list "
        "results, which are capped at 25. Show reports as short sections with bullet points or a markdown table.\n"
        "- The CRM never emails leads or customers automatically; only the salesperson sends emails, from Send Email.\n"
        "- If a tool returns an error, explain it plainly (e.g. missing permission) and suggest what to do.\n"
        "- Answer briefly. Use short lists for several records. Dates like 5 Nov 2026, 3:00 PM. Amounts like 25,000.\n"
        "- Don't end replies with suggested next requests or a list of things you could do next."
    )


def split_suggestions(text: str) -> tuple[str, list[str]]:
    """The reply without its closing 'NEXT: a | b | c' part (on its own line or at the end of the last one), and the
    suggestions in it."""
    text = (text or "").rstrip()
    match = None
    for match in re.finditer(r"[*_]*\bNEXT\s*:[*_]*", text, flags=re.IGNORECASE):
        pass
    if match is None or "\n" in text[match.end():].strip():
        return text.strip(), []
    items = [x.strip().strip("*_\"' ").rstrip(".") for x in text[match.end():].split("|")]
    return text[:match.start()].strip(), [x[:120] for x in items if x][:3]


def suggestions_for(model_items: list[str], tools_used: list[str], links: list[dict]) -> list[str]:
    """Suggested next requests are no longer shown after replies (users found them distracting)."""
    return []


def call_model(messages: list[dict]) -> dict:
    """One Chat Completions call. Returns the assistant message (may contain tool_calls)."""
    cfg = settings()
    try:
        res = httpx.post(f"{cfg['base_url']}/chat/completions", timeout=60,
                         headers={"Authorization": f"Bearer {cfg['key']}"},
                         json={"model": cfg["model"], "messages": messages, "tools": tools_for(acting_user()), "temperature": 0.1})
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
    links, done, used = [], [], []
    for _ in range(MAX_STEPS):
        reply = call_model([{"role": "system", "content": system_prompt()}, *messages])
        msg = {"role": "assistant", "content": reply.get("content") or ""}
        calls = reply.get("tool_calls") or []
        if calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                                 for c in calls]
        if not calls:
            msg["content"], items = split_suggestions(msg["content"])
            messages.append(msg)
            return {"messages": messages, "reply": msg["content"], "links": links, "done": done, "pending": None,
                    "suggestions": suggestions_for(items, used, links)}
        messages.append(msg)
        pending = None
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except ValueError:
                args = {}
            args = fill_defaults(db, name, args)
            used.append(name)
            offered = {t["function"]["name"] for t in tools_for(acting_user())}
            if name not in offered:  # e.g. a sales action asked of the Admin
                result, link = {"error": f"{name} isn't available for the {acting_user().role} role."}, None
            elif missing := missing_required(name, args):
                result, link = {"error": required_message(missing)}, None  # e.g. a lead without its Email
            elif name in NOTE_ARGS and not user_note(name, args):
                # a stage change without a note: not run, no Confirm card
                result, link = {"error": COMMENT_MISSING if name == "convert_lead" else NOTE_MISSING}, None
            elif name in TASK_TOOLS and not has_task(args):
                result, link = {"error": TASK_MISSING}, None  # ...or without the user's new task
            elif name in CONFIRM_FIRST:
                if pending is None:
                    pending = {"call_id": c["id"], "tool": name, "args": args, "summary": describe(db, name, args)}
                    continue  # answered when the user clicks Confirm or Cancel
                result, link = {"error": "Only one action can wait for confirmation at a time. Ask again after this one."}, None
            else:
                result, link = safe_run(db, name, args)
                if link and "error" not in result:
                    links.append(link)
                    done.append(name)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)[:MAX_TOOL_CHARS]})
        if pending:
            text, _ = split_suggestions(msg["content"])
            msg["content"] = text
            return {"messages": messages, "reply": text or "This needs your confirmation:", "links": links, "done": done,
                    "pending": pending, "suggestions": []}
    return {"messages": messages, "reply": "That took too many steps. Please break it into smaller requests.",
            "links": links, "done": done, "pending": None, "suggestions": []}


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
    messages = [*history, {"role": "tool", "tool_call_id": pending["call_id"], "content": json.dumps(result)[:MAX_TOOL_CHARS]}]
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
            out.append({"role": "user", "content": m["content"][:MAX_USER_CHARS]})
        elif role == "assistant":
            msg = {"role": "assistant", "content": str(m.get("content") or "")[:8000]}
            calls = [c for c in m.get("tool_calls") or [] if isinstance(c, dict) and c.get("id") and c.get("function")]
            if calls:
                msg["tool_calls"] = [{"id": str(c["id"]), "type": "function", "function": {
                    "name": str(c["function"].get("name", "")), "arguments": str(c["function"].get("arguments", "{}"))}}
                    for c in calls]
            out.append(msg)
        elif role == "tool" and m.get("tool_call_id"):
            out.append({"role": "tool", "tool_call_id": str(m["tool_call_id"]), "content": str(m.get("content", ""))[:MAX_TOOL_CHARS]})
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
