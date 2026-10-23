"""Login, your own password, and user management (Admin only).

There is no public sign up: a default Admin is created on the first start (see app/security.py),
and the Admin adds Managers and Salespeople from the Users page.
Passwords are stored as bcrypt hashes. Login returns a token the app sends on every request.
"""
import re

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import mailer, schemas
from app.constants import LEAD_OPEN_STAGES, OPPORTUNITY_OPEN_STAGES
from app.database import get_db
from app.models import Account, Contact, Lead, Opportunity, Task, User
from app.security import acting_user, authenticate, make_token, require_admin
from app.services import get_or_404, notify

router = APIRouter(prefix="/api", tags=["Login and users"])
protected = APIRouter(prefix="/api", tags=["Login and users"], dependencies=[Depends(authenticate)])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def check_password(password: str, stored: str | None) -> bool:
    try:
        return bool(stored) and bcrypt.checkpw(password.encode(), stored.encode())
    except ValueError:  # stored value is not a bcrypt hash
        return False


def strong_enough(password: str) -> str:
    if len(password) < 8 or not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise HTTPException(status_code=422, detail="Password must have at least 8 characters, with letters and numbers")
    return password


@router.post("/auth/login", response_model=schemas.LoginResponse)
def login(data: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user is None or not check_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is deactivated. Contact your Admin.")
    return {"message": "Login successful", "user": user, "token": make_token(user.id)}


@protected.get("/auth/me", response_model=schemas.UserOut)
def me(db: Session = Depends(get_db)):
    """The logged-in user (the app calls this to check the saved login is still valid)."""
    return db.get(User, acting_user().id)


@protected.put("/auth/me", response_model=schemas.UserOut)
def update_my_profile(data: schemas.ProfileUpdate, db: Session = Depends(get_db)):
    """My Profile: your name and which notifications you also get by email."""
    user = db.get(User, acting_user().id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "full_name" in changes:
        changes["full_name"] = " ".join(changes["full_name"].split())
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@protected.put("/auth/password")
def change_my_password(data: schemas.PasswordChange, db: Session = Depends(get_db)):
    user = db.get(User, acting_user().id)
    if not check_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    user.password_hash = hash_password(strong_enough(data.new_password))
    db.commit()
    return {"message": "Password changed"}


@protected.get("/users", response_model=list[schemas.UserOut])
def list_users(include_inactive: bool = False, db: Session = Depends(get_db)):
    """Active users for the owner / assigned-to dropdowns. include_inactive=true (Admin): everyone."""
    query = select(User).order_by(User.full_name)
    if not (include_inactive and acting_user().is_admin):
        query = query.where(User.is_active.is_(True))
    return db.scalars(query).all()


# ---------- Admin: users ----------

def account_email(db: Session, user: User, password: str, *, new: bool) -> None:
    """Welcome email (new user) or password-reset email, sent from the CRM mailbox after the save."""
    link = mailer.app_link("/")
    if new:
        subject = "[SalesTrack] Your account is ready"
        intro = f"Hi {user.full_name},\n\nAn account was created for you in SalesTrack CRM as {user.role}."
    else:
        subject = "[SalesTrack] Your password was reset"
        intro = f"Hi {user.full_name},\n\nYour SalesTrack CRM password was reset by your Admin."
    body = (f"{intro}\n\nLog in at: {link}\nUsername: {user.email}\nTemporary password: {password}\n\n"
            "Please change this password after you log in: click your profile picture (top right) > Change Password.\n\n"
            "This is an automatic email. Please don't reply to it.")
    mailer.queue(db, user.email, subject, body)


def active_admins(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == "Admin", User.is_active.is_(True)))


@protected.post("/users", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: schemas.UserCreate, db: Session = Depends(get_db)):
    """Admin adds a Manager, Salesperson or another Admin. They get a welcome email with their login details."""
    require_admin("add users")
    email = data.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(full_name=" ".join(data.full_name.split()), email=email,
                password_hash=hash_password(strong_enough(data.password)), role=data.role)
    db.add(user)
    db.flush()
    account_email(db, user, data.password, new=True)  # sent after the save succeeds
    db.commit()
    db.refresh(user)
    return user


@protected.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, data: schemas.UserUpdate, db: Session = Depends(get_db)):
    """Admin changes a user's name, email (their username), role, or activates / deactivates them."""
    me = require_admin("change users")
    user = get_or_404(db, User, user_id, "User")
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    losing_admin = user.role == "Admin" and user.is_active and (
        changes.get("role", "Admin") != "Admin" or changes.get("is_active") is False)
    if losing_admin and user.id == me.id:
        raise HTTPException(status_code=400, detail="You can't remove your own Admin access. Contact another Admin.")
    if losing_admin and active_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="There must be at least one active Admin")
    if "full_name" in changes:
        changes["full_name"] = " ".join(changes["full_name"].split())
    if "email" in changes:
        email = changes["email"].strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Enter a valid email address")
        if db.scalar(select(User.id).where(User.email == email, User.id != user.id)) is not None:
            raise HTTPException(status_code=409, detail="A user with this email already exists")
        changes["email"] = email
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@protected.put("/users/{user_id}/password")
def reset_password(user_id: int, data: schemas.PasswordReset, db: Session = Depends(get_db)):
    """Admin sets a new password (e.g. the user forgot it)."""
    require_admin("reset passwords")
    user = get_or_404(db, User, user_id, "User")
    user.password_hash = hash_password(strong_enough(data.password))
    account_email(db, user, data.password, new=False)
    db.commit()
    return {"message": f"Password reset for {user.full_name}. The new password was emailed to {user.email}."}


@protected.post("/users/{user_id}/transfer")
def transfer_records(user_id: int, data: schemas.TransferRecords, db: Session = Depends(get_db)):
    """Moves a user's open leads, open opportunities, accounts, contacts and open tasks to another user
    (e.g. when someone leaves). Closed records keep their owner, so the history stays correct."""
    me = require_admin("transfer records")
    source = get_or_404(db, User, user_id, "User")
    target = get_or_404(db, User, data.to_user_id, "User")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="Pick a different user to receive the records")
    if not target.is_active:
        raise HTTPException(status_code=400, detail=f"{target.full_name} is deactivated")
    moved = {}
    for label, model, extra in (
        ("leads", Lead, Lead.stage.in_(LEAD_OPEN_STAGES)),
        ("opportunities", Opportunity, Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES)),
        ("accounts", Account, None),
        ("contacts", Contact, None),
        ("tasks", Task, Task.status == "Open"),
    ):
        query = update(model).where(model.owner_id == source.id)
        if extra is not None:
            query = query.where(extra)
        moved[label] = db.execute(query.values(owner_id=target.id)).rowcount
    if data.deactivate:
        if source.id == me.id:
            raise HTTPException(status_code=400, detail="You can't deactivate yourself")
        if source.role == "Admin" and source.is_active and active_admins(db) <= 1:
            raise HTTPException(status_code=400, detail="There must be at least one active Admin")
        source.is_active = False
    total = sum(moved.values())
    if total:
        summary = ", ".join(f"{n} {label}" for label, n in moved.items() if n)
        notify(db, target.id, "Records assigned to you", category="assignment", message=
               f"{me.full_name} moved {source.full_name}'s records to you: {summary}.", link="/")
    db.commit()
    return {"moved": moved, "total": total, "deactivated": bool(data.deactivate)}
