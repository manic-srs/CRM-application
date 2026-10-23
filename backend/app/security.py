"""Login tokens and role checks (RBAC).

- After login the API returns a signed token. The app sends it on every request:
      Authorization: Bearer <token>
  (file downloads may pass it as ?token=... because a plain link can't send headers).
- Roles:
      Salesperson  sees the team's records; edits only records they own; can't change the owner
      Manager      edits every record and can reassign owners
      Admin        everything a Manager can do, plus managing users (add, role, deactivate, transfer records)
- A default Admin is created on start when no active Admin exists (ADMIN_EMAIL / ADMIN_PASSWORD in .env).

Settings (environment variables):
  SECRET_KEY      signs the tokens. Set your own value in .env (anyone with it could make tokens).
  TOKEN_HOURS     how long a login lasts, default 12
  ADMIN_NAME / ADMIN_EMAIL / ADMIN_PASSWORD   the default Admin account
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

log = logging.getLogger("crm.security")

ROLES = ("Salesperson", "Manager", "Admin")
MANAGERS = ("Manager", "Admin")

DEFAULT_ADMIN_EMAIL = "admin@salestrack.local"
DEFAULT_ADMIN_PASSWORD = "Admin@2026"


def _secret() -> bytes:
    return os.getenv("SECRET_KEY", "salestrack-dev-secret-change-me").encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(user_id: int) -> str:
    hours = float(os.getenv("TOKEN_HOURS", "12"))
    payload = _b64(json.dumps({"uid": user_id, "exp": int(time.time() + hours * 3600)}).encode())
    signature = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def read_token(token: str) -> int | None:
    """The user id in a valid, unexpired token; otherwise None."""
    try:
        payload, signature = token.split(".")
        expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_unb64(payload))
        return int(data["uid"]) if data["exp"] > time.time() else None
    except (ValueError, KeyError, TypeError):
        return None


@dataclass(frozen=True)
class Acting:
    """The logged-in user for this request (a plain copy, safe to use anywhere)."""
    id: int
    role: str
    full_name: str
    email: str

    @property
    def is_manager(self) -> bool:
        return self.role in MANAGERS

    @property
    def is_admin(self) -> bool:
        return self.role == "Admin"


_acting: ContextVar[Acting | None] = ContextVar("acting_user", default=None)
# Shows an "Authorize" button in the API docs: paste the token from POST /api/auth/login there
bearer = HTTPBearer(auto_error=False, description="The token from POST /api/auth/login")


async def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                       db: Session = Depends(get_db)) -> Acting:
    """Dependency on every protected API: checks the token and remembers the user for this request.
    (async on purpose: the user is then visible to the sync endpoint that runs after it.)"""
    token = credentials.credentials if credentials else request.query_params.get("token", "")
    user_id = read_token(token) if token else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Please log in again", headers={"WWW-Authenticate": "Bearer"})
    acting = Acting(id=user.id, role=user.role, full_name=user.full_name, email=user.email)
    _acting.set(acting)
    return acting


def acting_user() -> Acting:
    acting = _acting.get()
    if acting is None:  # only possible if a route forgot the authenticate dependency
        raise HTTPException(status_code=401, detail="Please log in again")
    return acting


def acting_user_id() -> int:
    return acting_user().id


# ---------- role checks ----------

def require_manager(action: str = "do this") -> Acting:
    me = acting_user()
    if not me.is_manager:
        raise HTTPException(status_code=403, detail=f"Only a Manager or Admin can {action}")
    return me


def require_admin(action: str = "manage users") -> Acting:
    me = acting_user()
    if not me.is_admin:
        raise HTTPException(status_code=403, detail=f"Only an Admin can {action}")
    return me


def require_edit(owner_id: int | None, label: str = "record") -> Acting:
    """Salespeople may change only the records they own; Managers and Admins may change any."""
    me = acting_user()
    if not me.is_manager and owner_id != me.id:
        raise HTTPException(status_code=403, detail=f"You can only change your own {label}s. Contact a Manager to reassign it.")
    return me


def owner_for_new(owner_id: int | None) -> int:
    """Owner of a new record: the logged-in user by default. Only Managers/Admins may give it to someone else."""
    me = acting_user()
    if owner_id is None or owner_id == me.id:
        return me.id
    if not me.is_manager:
        raise HTTPException(status_code=403, detail="Only a Manager or Admin can assign a record to someone else")
    return owner_id


def check_owner_change(old_owner_id: int, new_owner_id: int | None) -> None:
    if new_owner_id is not None and new_owner_id != old_owner_id:
        require_manager("change the owner")


# ---------- default Admin ----------

def ensure_default_admin(db: Session) -> User | None:
    """Creates the default Admin when there is no active Admin yet. Returns it when created."""
    from app.routers.auth import hash_password  # avoid a circular import

    if db.scalar(select(User.id).where(User.role == "Admin", User.is_active.is_(True)).limit(1)) is not None:
        return None
    email = os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL).strip().lower()
    password = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(full_name=os.getenv("ADMIN_NAME", "Administrator"), email=email, password_hash=hash_password(password))
        db.add(user)
    user.role, user.is_active = "Admin", True
    db.commit()
    log.info("Default Admin ready: %s (change the password after the first login)", email)
    return user
