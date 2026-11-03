"""Keeps accounts, contacts and opportunities free of duplicates when an opportunity is created (converting a lead, or
"New Opportunity" on the Opportunities or Account page).

- A company has one account: the same company name (case, punctuation and "Inc", "LLC"... ignored) reuses it.
- A person has one contact per account: the same email, or the same name (first + last), reuses it.
- One person at one company can't have the same open opportunity twice, so two salespeople never work the same deal.
  "The same opportunity" = the same opportunity name (case and punctuation ignored) for that contact and account.
"""
import re

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import OPPORTUNITY_OPEN_STAGES
from app.models import Account, Contact, Opportunity
from app.routers.lead_files import company_key
from app.security import acting_user, can_view


def name_key(text: str | None) -> str:
    """'Acme - CRM Rollout!' -> 'acme crm rollout' (case, punctuation and extra spaces ignored)."""
    return " ".join(re.sub(r"[^a-z0-9& ]", " ", (text or "").lower()).split())


def find_account(db: Session, company: str | None) -> Account | None:
    """The existing account for this company name, if there is one (the oldest, if there are several)."""
    wanted = company_key(company)
    if len(wanted) < 2:
        return None
    like = f"%{wanted.split()[0]}%"
    for account in db.scalars(select(Account).where(Account.name.ilike(like)).order_by(Account.id)).all():
        if company_key(account.name) == wanted:
            return account
    return None


def find_contact(db: Session, account_id: int | None, *, email: str | None = None, first_name: str | None = None,
                 last_name: str | None = None) -> Contact | None:
    """The existing contact for this person on the account: the same email, or else the same full name (the same person
    often comes in again with another email, e.g. through another salesperson)."""
    if account_id is None:
        return None
    email = (email or "").strip().lower()
    if email:
        found = db.scalars(select(Contact).where(Contact.account_id == account_id, func.lower(Contact.email) == email)
                           .order_by(Contact.id)).first()
        if found is not None:
            return found
    wanted = name_key(f"{first_name or ''} {last_name or ''}")
    if not wanted:
        return None
    for contact in db.scalars(select(Contact).where(Contact.account_id == account_id).order_by(Contact.id)).all():
        if name_key(f"{contact.first_name or ''} {contact.last_name}") == wanted:
            return contact
    return None


def open_opportunities(db: Session, account_id: int | None, contact_id: int | None, exclude_id: int | None = None):
    """Open opportunities for this person at this company."""
    if account_id is None or contact_id is None:
        return []
    query = select(Opportunity).where(Opportunity.account_id == account_id, Opportunity.primary_contact_id == contact_id,
                                      Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES))
    if exclude_id is not None:
        query = query.where(Opportunity.id != exclude_id)
    return db.scalars(query.order_by(Opportunity.id)).all()


def same_opportunity(db: Session, account_id: int | None, contact_id: int | None, name: str,
                     exclude_id: int | None = None) -> Opportunity | None:
    wanted = name_key(name)
    return next((o for o in open_opportunities(db, account_id, contact_id, exclude_id) if name_key(o.name) == wanted), None)


def ensure_no_duplicate(db: Session, account: Account | None, contact: Contact | None, name: str,
                        exclude_id: int | None = None) -> None:
    """Refuses a second open opportunity with the same name for the same person at the same company."""
    if account is None or contact is None:
        return
    existing = same_opportunity(db, account.id, contact.id, name, exclude_id)
    if existing is None:
        return
    who = "You already have" if existing.owner_id == acting_user().id else \
        f"{existing.owner.full_name if existing.owner else 'Another salesperson'} already has"
    raise HTTPException(status_code=409, detail=(
        f'{who} the open opportunity "{existing.name}" ({existing.stage}) for {contact.full_name} at {account.name}. '
        "One opportunity is handled by one salesperson: ask for it to be transferred, or use a different opportunity name."))


def default_name(account_name: str) -> str:
    return f"{account_name} - Opportunity"


# ---------- what the screens show before saving ----------

def _record(owner, owner_id: int, **fields) -> dict:
    mine = owner_id == acting_user().id
    return {**fields, "owner": owner.full_name if owner else None, "owner_id": owner_id, "mine": mine,
            "can_open": can_view(owner_id)}


def check(db: Session, *, company: str | None = None, account_id: int | None = None, contact_id: int | None = None,
          email: str | None = None, first_name: str | None = None, last_name: str | None = None,
          name: str | None = None) -> dict:
    """What would happen: which account and contact get reused, and whether the opportunity already exists.
    Records the user can't open show only their owner and stage (no link)."""
    account = db.get(Account, account_id) if account_id else find_account(db, company)
    contact = db.get(Contact, contact_id) if contact_id else None
    if contact is not None and account is not None and contact.account_id != account.id:
        contact = None
    if contact is None and account is not None:
        contact = find_contact(db, account.id, email=email, first_name=first_name, last_name=last_name)
    out = {"account": None, "contact": None, "duplicate": None, "related": []}
    if account is not None:
        out["account"] = _record(account.owner, account.owner_id, id=account.id if can_view(account.owner_id) else None,
                                 name=account.name)
    if contact is not None:
        visible = can_view(contact.owner_id)
        out["contact"] = _record(contact.owner, contact.owner_id, id=contact.id if visible else None, name=contact.full_name)
    if account is None or contact is None:
        return out
    opp_name = (name or "").strip() or default_name(account.name)
    for opp in open_opportunities(db, account.id, contact.id):
        visible = can_view(opp.owner_id)
        item = _record(opp.owner, opp.owner_id, id=opp.id if visible else None, name=opp.name, stage=opp.stage)
        if name_key(opp.name) == name_key(opp_name) and out["duplicate"] is None:
            out["duplicate"] = item
        else:
            out["related"].append(item)
    return out
