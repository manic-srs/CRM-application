"""Login (placeholder: checks email + password, no tokens yet) and the user list.

Passwords are stored as bcrypt hashes. The role (Salesperson, Manager or Admin) is picked on the Sign Up form.
"""
import re

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/api", tags=["Login and users"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def check_password(password: str, stored: str | None) -> bool:
    try:
        return bool(stored) and bcrypt.checkpw(password.encode(), stored.encode())
    except ValueError:  # stored value is not a bcrypt hash
        return False


@router.post("/auth/login", response_model=schemas.LoginResponse)
def login(data: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user is None or not user.is_active or not check_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    return {"message": "Login successful", "user": user}


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/auth/signup", response_model=schemas.LoginResponse, status_code=status.HTTP_201_CREATED)
def signup(data: schemas.SignupRequest, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if not (re.search(r"[A-Za-z]", data.password) and re.search(r"\d", data.password)):
        raise HTTPException(status_code=422, detail="Password must have at least 8 characters, with letters and numbers")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Log in instead.")
    user = User(
        full_name=" ".join(data.full_name.split()),
        email=email,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Account created", "user": user}


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    """For owner / assigned-to dropdowns."""
    return db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all()
