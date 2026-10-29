"""Login tokens and role checks (RBAC).

- After login the API returns a signed token. The app sends it on every request:
      Authorization: Bearer <token>
  (file downloads may pass it as ?token=... because a plain link can't send headers).
- Permissions (see PERMISSIONS): each role has a set of permissions, which the Admin can change on the
  Roles & Permissions page (saved in the role_permissions table). The API checks permissions, not role names.
      Salesperson  sees and changes only their own records (unless given team access)
      Manager      sees and changes the team's records, reassigns owners, gives team access to salespeople
      Admin        everything, plus users and permissions (the Admin's permissions can't be changed)
- Team access: a Manager can let one salesperson see the whole team's records (users.team_access).
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

# key: (label, description, default roles). The Admin always has every permission.
# Shown as sections on the Permissions page
PERMISSION_GROUPS = {
    "Records": ("view_team_records", "view_team_dashboard", "edit_team_records", "reassign_owner", "transfer_leads"),
    "Team": ("grant_team_access",),
    "Email": ("send_emails",),
    "Data": ("import_leads", "export_data"),
    "Administration": ("manage_users", "manage_permissions"),
}
PERMISSIONS = {
    "view_team_records": ("View team records", "See leads, deals, accounts, contacts and tasks owned by others",
                          ("Manager",)),
    "view_team_dashboard": ("View team dashboard", "Use the Whole team view on Home", ("Manager",)),
    "edit_team_records": ("Edit team records", "Change stages and details of records owned by others", ("Manager",)),
    "reassign_owner": ("Reassign owner", "Give any record you can see to another user, including transferring leads",
                       ("Manager",)),
    "transfer_leads": ("Transfer own leads", "Give your own leads to another user (changes only the owner, no approval needed)",
                       ("Salesperson",)),
    "grant_team_access": ("Give team access", "Let a salesperson see the whole team's records", ("Manager",)),
    "send_emails": ("Send emails", "Send emails to leads and contacts", ("Manager", "Salesperson")),
    "import_leads": ("Upload data", "Create many leads or opportunities at once from an Excel or CSV file",
                     ("Manager", "Salesperson")),
    "export_data": ("Download data", "Download leads or opportunities to Excel or CSV (a reason is required and recorded)",
                    ("Manager", "Salesperson")),
    "manage_users": ("Manage users", "Add users, reset passwords, deactivate, transfer leads", ()),
    "manage_permissions": ("Manage roles & permissions", "Change this permission matrix", ()),
}
LOCKED_FOR_ADMIN = True  # the Admin keeps every permission, so nobody can lock themselves out


def default_permissions(role: str) -> set[str]:
    if role == "Admin":
        return set(PERMISSIONS)
    return {key for key, (_, _, roles) in PERMISSIONS.items() if role in roles}


def role_permissions(db: Session, role: str) -> set[str]:
    """The permissions of a role: the defaults, changed by what the Admin saved in role_permissions."""
    from app.models import RolePermission  # avoid a circular import

    if role == "Admin":
        return set(PERMISSIONS)
    allowed = default_permissions(role)
    for row in db.scalars(select(RolePermission).where(RolePermission.role == role)).all():
        if row.permission in PERMISSIONS:
            (allowed.add if row.allowed else allowed.discard)(row.permission)
    return allowed


def user_permissions(db: Session, user: User) -> set[str]:
    allowed = role_permissions(db, user.role)
    if user.team_access:  # given by a Manager: see (not change) the whole team's records
        allowed |= {"view_team_records", "view_team_dashboard"}
    return allowed

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
    permissions: frozenset = frozenset()

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def is_admin(self) -> bool:
        return self.role == "Admin"

    @property
    def sees_team(self) -> bool:
        return self.can("view_team_records")


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
    acting = Acting(id=user.id, role=user.role, full_name=user.full_name, email=user.email,
                    permissions=frozenset(user_permissions(db, user)))
    _acting.set(acting)
    return acting


def acting_user() -> Acting:
    acting = _acting.get()
    if acting is None:  # only possible if a route forgot the authenticate dependency
        raise HTTPException(status_code=401, detail="Please log in again")
    return acting


def acting_user_id() -> int:
    return acting_user().id


# ---------- permission checks ----------

def require(permission: str) -> Acting:
    me = acting_user()
    if not me.can(permission):
        label = PERMISSIONS[permission][0]
        raise HTTPException(status_code=403, detail=f"You don't have the \"{label}\" permission. Contact your Admin.")
    return me


def forbid_admin_create(what: str) -> Acting:
    """Admins can create leads, but opportunities still come from Managers and Salespeople converting a lead."""
    me = acting_user()
    if me.role == "Admin":
        raise HTTPException(status_code=403, detail=f"Admins can't create {what}. "
                            "Opportunities are created by Managers and Salespeople when they convert a lead.")
    return me


def can_transfer_lead(owner_id: int) -> bool:
    """Who can give a lead to someone else: the Admin and Managers (Reassign owner: any lead they can see),
    or a user with Transfer own leads (Salespeople: their own leads)."""
    me = acting_user()
    return me.is_admin or me.can("reassign_owner") or (me.can("transfer_leads") and owner_id == me.id)


def require_transfer(owner_id: int) -> Acting:
    if not can_transfer_lead(owner_id):
        raise HTTPException(status_code=403, detail="Only the Admin, a Manager, or the lead's owner can transfer this lead")
    return acting_user()


def require_admin(action: str = "manage users") -> Acting:
    """Kept for the user screens: needs the Manage users permission."""
    return require("manage_users")


def can_view(owner_id: int | None) -> bool:
    me = acting_user()
    return owner_id == me.id or me.sees_team


def require_view(owner_id: int | None, label: str = "record") -> Acting:
    """Without team access, a user can open only the records they own (others look like they don't exist)."""
    if not can_view(owner_id):
        raise HTTPException(status_code=404, detail=f"This {label} doesn't exist or you don't have access to it")
    return acting_user()


def visible(query, model):
    """Adds "owned by me" to a list query when the user can't see the team's records."""
    me = acting_user()
    return query if me.sees_team else query.where(model.owner_id == me.id)


def require_edit(owner_id: int | None, label: str = "record") -> Acting:
    """Users change their own records; changing someone else's needs Edit team records."""
    require_view(owner_id, label)
    me = acting_user()
    if owner_id != me.id and not me.can("edit_team_records"):
        raise HTTPException(status_code=403, detail=f"You can only change your own records. This {label} belongs to someone else.")
    return me


def owner_for_new(owner_id: int | None) -> int:
    """Owner of a new record: the logged-in user by default. Giving it to someone else needs Reassign owner."""
    me = acting_user()
    if owner_id is None or owner_id == me.id:
        return me.id
    if not me.can("reassign_owner"):
        raise HTTPException(status_code=403, detail="Only a Manager or Admin can assign a record to someone else")
    return owner_id


def check_owner_change(old_owner_id: int, new_owner_id: int | None) -> None:
    if new_owner_id is not None and new_owner_id != old_owner_id:
        require("reassign_owner")


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
