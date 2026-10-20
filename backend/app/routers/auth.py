"""Login (placeholder: checks email + password, no tokens yet) and the user list.

Passwords are bcrypt hashes, as in database/seed-data.sql. Sample users' password: Password@123
"""
import bcrypt
from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    """For owner / assigned-to dropdowns."""
    return db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all()
