"""Accounts (companies) and Contacts (people). Usually created by converting a lead; can also be added directly."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import Account, Contact
from app.serializers import account_detail, account_out, contact_out
from app.services import get_or_404, resolve_user_id

router = APIRouter(prefix="/api", tags=["Accounts and contacts"])


@router.get("/accounts", response_model=list[schemas.AccountOut])
def list_accounts(
    search: str | None = Query(None), owner_id: int | None = Query(None), db: Session = Depends(get_db)
):
    query = select(Account)
    if owner_id is not None:
        query = query.where(Account.owner_id == owner_id)
    if search:
        query = query.where(Account.name.like(f"%{search.strip()}%"))
    return [account_out(a) for a in db.scalars(query.order_by(Account.name)).all()]


@router.post("/accounts", response_model=schemas.AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(data: schemas.AccountCreate, db: Session = Depends(get_db)):
    account = Account(**data.model_dump(exclude={"owner_id"}), owner_id=resolve_user_id(db, data.owner_id))
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_out(account)


@router.get("/accounts/{account_id}", response_model=schemas.AccountDetail)
def get_account(account_id: int, db: Session = Depends(get_db)):
    """The account page: details, its contacts and its opportunities."""
    return account_detail(get_or_404(db, Account, account_id, "Account"))


@router.get("/contacts", response_model=list[schemas.ContactOut])
def list_contacts(
    account_id: int | None = Query(None), search: str | None = Query(None), db: Session = Depends(get_db)
):
    query = select(Contact)
    if account_id is not None:
        query = query.where(Contact.account_id == account_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(Contact.full_name.like(like), Contact.email.like(like)))
    return [contact_out(c) for c in db.scalars(query.order_by(Contact.last_name, Contact.first_name)).all()]


@router.post("/contacts", response_model=schemas.ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(data: schemas.ContactCreate, db: Session = Depends(get_db)):
    account = get_or_404(db, Account, data.account_id, "Account")
    contact = Contact(
        **data.model_dump(exclude={"owner_id"}), owner_id=resolve_user_id(db, data.owner_id, account.owner_id)
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact_out(contact)


@router.get("/contacts/{contact_id}", response_model=schemas.ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    return contact_out(get_or_404(db, Contact, contact_id, "Contact"))
