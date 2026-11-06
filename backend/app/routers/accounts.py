"""Accounts (companies) and Contacts (people). Usually created by converting a lead; can also be added directly."""
from fastapi import APIRouter, Depends, Query, status
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.security import acting_user, can_view, owner_for_new, require_view, visible
from app.models import Account, Contact, Email, Opportunity, Task
from app.serializers import account_detail, account_out, contact_out
from app.services import get_or_404, resolve_user_id

router = APIRouter(prefix="/api", tags=["Accounts and contacts"])


def _worked_on(user_id: int):
    """Accounts where the user has a contact or an opportunity. One company has one account, so a salesperson whose deal
    is on another salesperson's account can still open that account (and sees only their own contacts and deals there)."""
    return or_(Account.id.in_(select(Opportunity.account_id).where(Opportunity.owner_id == user_id)),
               Account.id.in_(select(Contact.account_id).where(Contact.owner_id == user_id)))


@router.get("/accounts", response_model=list[schemas.AccountOut])
def list_accounts(
    search: str | None = Query(None), owner_id: int | None = Query(None), db: Session = Depends(get_db)
):
    me = acting_user()
    query = select(Account) if me.sees_team else select(Account).where(or_(Account.owner_id == me.id, _worked_on(me.id)))
    if owner_id is not None:
        query = query.where(Account.owner_id == owner_id)
    if search:
        query = query.where(Account.name.ilike(f"%{search.strip()}%"))
    accounts = db.scalars(query.order_by(Account.name)).all()
    latest = last_activity(db, [a.id for a in accounts])
    out = []
    for a in accounts:
        row = account_out(a)
        stamps = [s for s in (a.updated_at, a.created_at, latest.get(a.id)) if s]
        out.append(row.model_copy(update={"last_activity_at": max(stamps) if stamps else None}))
    return out


def last_activity(db: Session, account_ids: list[int]) -> dict[int, datetime]:
    """Accounts list > Last Activity: the latest update to each account's contacts, opportunities, their tasks, or an
    email sent to the account, its contacts or its deals."""
    if not account_ids:
        return {}
    latest: dict[int, datetime] = {}

    def take(rows):
        for account_id, stamp in rows:
            if account_id is not None and stamp is not None and (account_id not in latest or stamp > latest[account_id]):
                latest[account_id] = stamp

    take(db.execute(select(Contact.account_id, func.max(Contact.updated_at))
                    .where(Contact.account_id.in_(account_ids)).group_by(Contact.account_id)).all())
    take(db.execute(select(Opportunity.account_id, func.max(Opportunity.updated_at))
                    .where(Opportunity.account_id.in_(account_ids)).group_by(Opportunity.account_id)).all())
    take(db.execute(select(Opportunity.account_id, func.max(Task.updated_at)).join(Task, Task.opportunity_id == Opportunity.id)
                    .where(Opportunity.account_id.in_(account_ids)).group_by(Opportunity.account_id)).all())
    take(db.execute(select(Email.account_id, func.max(Email.sent_at))
                    .where(Email.account_id.in_(account_ids)).group_by(Email.account_id)).all())
    take(db.execute(select(Contact.account_id, func.max(Email.sent_at)).join(Email, Email.contact_id == Contact.id)
                    .where(Contact.account_id.in_(account_ids)).group_by(Contact.account_id)).all())
    take(db.execute(select(Opportunity.account_id, func.max(Email.sent_at)).join(Email, Email.opportunity_id == Opportunity.id)
                    .where(Opportunity.account_id.in_(account_ids)).group_by(Opportunity.account_id)).all())
    return latest


@router.post("/accounts", response_model=schemas.AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(data: schemas.AccountCreate, db: Session = Depends(get_db)):
    account = Account(**data.model_dump(exclude={"owner_id"}), owner_id=resolve_user_id(db, owner_for_new(data.owner_id)))
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_out(account)


@router.get("/accounts/{account_id}", response_model=schemas.AccountDetail)
def get_account(account_id: int, db: Session = Depends(get_db)):
    """The account page: details, its contacts and its opportunities."""
    account = get_or_404(db, Account, account_id, "Account")
    me = acting_user()
    if not can_view(account.owner_id) and not db.scalar(select(Account.id).where(Account.id == account.id,
                                                                                   _worked_on(me.id))):
        require_view(account.owner_id, "account")  # 404, like any record the user can't open
    detail = account_detail(account)
    if not me.sees_team:  # without team access: only your own contacts and deals on the account
        detail.contacts = [c for c in detail.contacts if c.owner_id == me.id]
        detail.opportunities = [o for o in detail.opportunities if o.owner_id == me.id]
    return detail


@router.get("/contacts", response_model=list[schemas.ContactOut])
def list_contacts(
    account_id: int | None = Query(None), search: str | None = Query(None), db: Session = Depends(get_db)
):
    query = visible(select(Contact), Contact)
    if account_id is not None:
        query = query.where(Contact.account_id == account_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(Contact.full_name.ilike(like), Contact.email.ilike(like)))
    return [contact_out(c) for c in db.scalars(query.order_by(Contact.last_name, Contact.first_name)).all()]


@router.post("/contacts", response_model=schemas.ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(data: schemas.ContactCreate, db: Session = Depends(get_db)):
    account = get_or_404(db, Account, data.account_id, "Account")
    require_view(account.owner_id, "account")
    contact = Contact(
        **data.model_dump(exclude={"owner_id"}), owner_id=resolve_user_id(db, owner_for_new(data.owner_id))
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact_out(contact)


@router.get("/contacts/{contact_id}", response_model=schemas.ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = get_or_404(db, Contact, contact_id, "Contact")
    require_view(contact.owner_id, "contact")
    return contact_out(contact)
