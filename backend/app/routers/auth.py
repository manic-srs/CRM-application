"""Login, your own password, and user management (Admin only).

There is no public sign up: a default Admin is created on the first start (see app/security.py),
and the Admin adds Managers and Salespeople from the Users page.
Passwords are stored as bcrypt hashes. Login returns a token the app sends on every request.
"""
import os
import re
from datetime import datetime

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app import mailer, schemas
from app.constants import LEAD_OPEN_STAGES, OPPORTUNITY_OPEN_STAGES
from app.database import get_db
from app.models import Account, Contact, Lead, LeadTransfer, Opportunity, Task, User
from app.models import ActivityLog, RolePermission
from app.security import (PERMISSION_GROUPS, PERMISSIONS, ROLES, acting_user, default_permissions, authenticate, make_token, require, require_admin, team_ids,
                          role_permissions, user_permissions)
from app.services import get_or_404, log_activity, notify

router = APIRouter(prefix="/api", tags=["Login and users"])
protected = APIRouter(prefix="/api", tags=["Login and users"], dependencies=[Depends(authenticate)])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def allowed_domains() -> list[str]:
    """Email domains new users may have (ALLOWED_EMAIL_DOMAINS in .env, comma separated). Empty = any domain."""
    raw = os.getenv("ALLOWED_EMAIL_DOMAINS", "srsconsultinginc.com")
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


def check_user_email(email: str) -> str:
    """A valid company email: personal addresses (Gmail, Outlook.com...) are refused."""
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    domains = allowed_domains()
    if domains and email.rsplit("@", 1)[1] not in domains:
        raise HTTPException(status_code=422, detail="Use a company email address ending in "
                            + " or ".join("@" + d for d in domains) + ". Personal emails aren't allowed.")
    return email


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
    return {"message": "Login successful", "user": with_permissions(db, user), "token": make_token(user.id)}


def with_permissions(db: Session, user: User) -> schemas.UserOut:
    """The user plus what they are allowed to do (the app shows or hides buttons with it)."""
    return schemas.UserOut.model_validate(user).model_copy(update={"permissions": sorted(user_permissions(db, user))})


@protected.get("/auth/me", response_model=schemas.UserOut)
def me(db: Session = Depends(get_db)):
    """The logged-in user and their permissions (the app calls this to check the saved login is still valid)."""
    return with_permissions(db, db.get(User, acting_user().id))


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
    return with_permissions(db, user)


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
    me = acting_user()
    if not (include_inactive and (me.can("manage_users") or me.can("grant_team_access") or me.can("manage_team"))):
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


def check_manager(db: Session, manager_id: int | None) -> User | None:
    """The Manager a Salesperson reports to: an active Manager (None / 0 = no Manager)."""
    if not manager_id:
        return None
    manager = db.get(User, manager_id)
    if manager is None or manager.role != "Manager" or not manager.is_active:
        raise HTTPException(status_code=400, detail="Reports To must be an active Manager")
    return manager


def require_team_member(db: Session, user: User):
    """A Manager (Manage own team) may change only the Salespeople who report to them."""
    me = acting_user()
    if me.can("manage_users"):
        return me
    if not me.can("manage_team"):
        require("manage_users")
    if user.role != "Salesperson" or user.reports_to_id != me.id:
        raise HTTPException(status_code=403, detail=f"{user.full_name} isn't in your team. Only the Admin can change this user.")
    return me


@protected.post("/users", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: schemas.UserCreate, db: Session = Depends(get_db)):
    """Admin adds a Manager, Salesperson or another Admin; a Manager (Manage own team) adds a Salesperson to their
    own team. They get a welcome email with their login details. Every add is in the Admin's Activity Log."""
    me = acting_user()
    if me.can("manage_users"):
        manager = check_manager(db, data.reports_to_id) if data.role == "Salesperson" else None
    elif me.can("manage_team"):
        if data.role != "Salesperson":
            raise HTTPException(status_code=403, detail="Managers can add Salespeople only. Ask the Admin to add a Manager or Admin.")
        manager = db.get(User, me.id)  # always in the Manager's own team
    else:
        require_admin("add users")
    email = check_user_email(data.email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(full_name=" ".join(data.full_name.split()), email=email,
                password_hash=hash_password(strong_enough(data.password)), role=data.role,
                reports_to_id=manager.id if manager else None)
    db.add(user)
    db.flush()
    account_email(db, user, data.password, new=True)  # sent after the save succeeds
    team = f" • Reports to {manager.full_name}" if manager else ""
    log_activity(db, me.id, "User added", user.full_name, f"{user.role} • {user.email}{team}"
                 + (" • added by their Manager" if not me.can("manage_users") else ""))
    db.commit()
    db.refresh(user)
    return user


@protected.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, data: schemas.UserUpdate, db: Session = Depends(get_db)):
    """Admin changes a user's name, email (their username), role, Manager (Reports To), or activates / deactivates
    them. A Manager (Manage own team) can only deactivate or activate the Salespeople in their team.
    Role and access changes are saved with the date and time (role_changed_at / access_changed_at) and logged."""
    user = get_or_404(db, User, user_id, "User")
    me = require_team_member(db, user)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if not me.can("manage_users") and set(changes) - {"is_active"}:
        raise HTTPException(status_code=403, detail="Managers can only deactivate or activate people in their team")
    if "reports_to_id" in changes:
        role = changes.get("role", user.role)
        manager = check_manager(db, changes["reports_to_id"]) if role == "Salesperson" else None
        if changes["reports_to_id"] and manager is None:
            raise HTTPException(status_code=400, detail="Only Salespeople report to a Manager")
        new_id = manager.id if manager else None
        if new_id != user.reports_to_id:
            log_activity(db, me.id, "Manager changed", user.full_name,
                         f"{user.reports_to_name or 'No Manager'} → {manager.full_name if manager else 'No Manager'}")
            if manager:
                notify(db, manager.id, "Salesperson added to your team",
                       f"{me.full_name} added {user.full_name} to your team.", link="/users", category="assignment")
        changes["reports_to_id"] = new_id
    if "is_active" in changes and changes["is_active"] is False and user.id == me.id:
        raise HTTPException(status_code=400, detail="You can't deactivate yourself")
    if changes.get("role") == user.role:
        changes.pop("role")
    losing_admin = user.role == "Admin" and user.is_active and (
        changes.get("role", "Admin") != "Admin" or changes.get("is_active") is False)
    if losing_admin and user.id == me.id:
        raise HTTPException(status_code=400, detail="You can't remove your own Admin access. Contact another Admin.")
    if losing_admin and active_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="There must be at least one active Admin")
    if "full_name" in changes:
        changes["full_name"] = " ".join(changes["full_name"].split())
    if "email" in changes and changes["email"].strip().lower() == user.email:
        changes.pop("email")
    if "email" in changes:
        email = check_user_email(changes["email"])
        if db.scalar(select(User.id).where(User.email == email, User.id != user.id)) is not None:
            raise HTTPException(status_code=409, detail="A user with this email already exists")
        changes["email"] = email
    changed = [label for field, label in (("full_name", "name"), ("email", "email"))
               if field in changes and changes[field] != getattr(user, field)]
    if changed:
        log_activity(db, me.id, "User details changed", user.full_name, "Changed " + " and ".join(changed))
    stamp = datetime.now().replace(microsecond=0)
    if "is_active" in changes and changes["is_active"] != user.is_active:
        log_activity(db, me.id, "User activated" if changes["is_active"] else "User deactivated", user.full_name,
                     None if me.can("manage_users") else "By their Manager")
        user.access_changed_at = stamp
    if "role" in changes:
        log_activity(db, me.id, "Role changed", user.full_name, f"{user.role} → {changes['role']}")
        notify(db, user.id, "Your role was changed", f"{me.full_name} changed your role from {user.role} to {changes['role']}.",
               link="/", category="assignment")
        user.role_changed_at = stamp
        if changes["role"] != "Salesperson":
            user.team_access = False  # team access is only for Salespeople (others already see the team)
            changes["reports_to_id"] = None  # only Salespeople report to a Manager
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@protected.put("/users/{user_id}/password")
def reset_password(user_id: int, data: schemas.PasswordReset, db: Session = Depends(get_db)):
    """Admin sets a new password (e.g. the user forgot it)."""
    me = require_admin("reset passwords")
    user = get_or_404(db, User, user_id, "User")
    user.password_hash = hash_password(strong_enough(data.password))
    account_email(db, user, data.password, new=False)
    log_activity(db, me.id, "Password reset", user.full_name)
    db.commit()
    return {"message": f"Password reset for {user.full_name}. The new password was emailed to {user.email}."}


@protected.post("/users/{user_id}/transfer")
def transfer_records(user_id: int, data: schemas.TransferRecords, db: Session = Depends(get_db)):
    """Moves a user's open leads, open opportunities, accounts, contacts and open tasks to another user
    (e.g. when someone leaves). Closed records keep their owner, so the history stays correct."""
    source = get_or_404(db, User, user_id, "User")
    me = require_team_member(db, source)
    target = get_or_404(db, User, data.to_user_id, "User")
    if not me.can("manage_users") and target.id != me.id and target.id not in team_ids(db, me.id):
        raise HTTPException(status_code=403, detail="Pick yourself or someone in your team to receive the records")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="Pick a different user to receive the records")
    if not target.is_active:
        raise HTTPException(status_code=400, detail=f"{target.full_name} is deactivated")
    # each open lead's Transfer History shows the move (the stage, history and tasks stay as they are)
    for lead_id in db.scalars(select(Lead.id).where(Lead.owner_id == source.id, Lead.stage.in_(LEAD_OPEN_STAGES))).all():
        db.add(LeadTransfer(lead_id=lead_id, from_user_id=source.id, to_user_id=target.id, transferred_by_id=me.id,
                            note=f"{source.full_name}'s records moved to {target.full_name}"))
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
    log_activity(db, me.id, "Records transferred", f"{source.full_name} → {target.full_name}",
                 (", ".join(f"{n} {label}" for label, n in moved.items() if n) or "No open records")
                 + ("; user deactivated" if data.deactivate else ""))
    if total:
        summary = ", ".join(f"{n} {label}" for label, n in moved.items() if n)
        notify(db, target.id, "Records assigned to you", category="assignment", message=
               f"{me.full_name} moved {source.full_name}'s records to you: {summary}.", link="/")
    db.commit()
    return {"moved": moved, "total": total, "deactivated": bool(data.deactivate)}


# ---------- team access (Manager) ----------

@protected.put("/users/{user_id}/team-access", response_model=schemas.UserOut)
def set_team_access(user_id: int, data: schemas.TeamAccess, db: Session = Depends(get_db)):
    """A Manager (or Admin) lets a salesperson see the whole team's records, or takes it back."""
    me = require("grant_team_access")
    user = get_or_404(db, User, user_id, "User")
    if user.role != "Salesperson":
        raise HTTPException(status_code=400, detail="Team access is only for Salespeople (Managers and Admins already have it)")
    if user.team_access != data.team_access:
        user.team_access = data.team_access
        user.access_changed_at = datetime.now().replace(microsecond=0)
        log_activity(db, me.id, "Team access given" if data.team_access else "Team access removed", user.full_name)
        notify(db, user.id, "Team access given" if data.team_access else "Team access removed",
               f"{me.full_name} {'gave you access to see' if data.team_access else 'removed your access to'} "
               "the whole team's records.", link="/", category="assignment")
    db.commit()
    db.refresh(user)
    return user


# ---------- roles & permissions (Admin) ----------

@protected.get("/permissions")
def permission_matrix(db: Session = Depends(get_db)):
    """The Roles & Permissions page: every permission and which roles have it."""
    if not acting_user().can("manage_permissions"):
        require("manage_users")
    changes = {(r.role, r.permission): r for r in db.scalars(select(RolePermission)).all()}
    granted = {role: role_permissions(db, role) for role in ROLES}
    defaults = {role: default_permissions(role) for role in ROLES}
    group_of = {key: group for group, keys in PERMISSION_GROUPS.items() for key in keys}
    rows = []
    for key, (label, description, _) in PERMISSIONS.items():
        roles = {}
        for role in ROLES:
            row = changes.get((role, key))
            roles[role] = {
                "allowed": key in granted[role],
                "default": key in defaults[role],
                "locked": role == "Admin",
                "changed_by": row.updated_by.full_name if row and row.updated_by else None,
                "changed_at": row.updated_at if row else None,
            }
        rows.append({"key": key, "label": label, "description": description, "group": group_of.get(key, "Other"),
                     "roles": roles})
    return {"roles": list(ROLES), "permissions": rows}


@protected.put("/permissions")
def set_permission(data: schemas.PermissionChange, db: Session = Depends(get_db)):
    """Admin turns one permission on or off for Manager or Salesperson (the Admin's own are locked)."""
    me = require("manage_permissions")
    if data.permission not in PERMISSIONS:
        raise HTTPException(status_code=404, detail=f"Unknown permission {data.permission}")
    if data.role == "Admin":
        raise HTTPException(status_code=400, detail="The Admin's permissions can't be changed")
    row = db.get(RolePermission, (data.role, data.permission))
    if row is None:
        row = RolePermission(role=data.role, permission=data.permission, allowed=data.allowed)
        db.add(row)
    row.allowed = data.allowed
    row.updated_by_id = me.id
    label = PERMISSIONS[data.permission][0]
    log_activity(db, me.id, "Permission changed", f"{label} • {data.role}", "Allowed" if data.allowed else "Not allowed")
    db.commit()
    return {"message": f"{label} {'given to' if data.allowed else 'removed from'} {data.role}s"}


# ---------- activity log (Admin) and Team Activity (Manager) ----------

# Tabs of the Activity Log. An action's tab comes from its name (see category_of).
ACTIVITY_CATEGORIES = {
    "access": "Users & Access",
    "data": "Uploads & Downloads",
    "transfers": "Lead / Opportunity Transfers",
    "ai": "AI Assistant",
    "records": "Records & Emails",
}
ACCESS_ACTIONS = ("User added", "User details changed", "User activated", "User deactivated", "Role changed",
                  "Password reset", "Permission changed", "Team access given", "Team access removed", "Users uploaded",
                  "Manager changed")


def category_of(action: str) -> str:
    if action.startswith("AI Assistant"):
        return "ai"
    if action in ACCESS_ACTIONS:
        return "access"
    if action.endswith((" uploaded", " downloaded")):
        return "data"
    if action == "Records transferred" or action.endswith((" reassigned", " transferred")):
        return "transfers"
    return "records"


def activity_scope(db: Session) -> set[int] | None:
    """Whose activity the user may see: None = everyone (Admin); a Manager = themselves and their team."""
    me = acting_user()
    if me.can("manage_users"):
        return None
    if me.role == "Manager" and (me.can("manage_team") or me.can("view_team_records")):
        return team_ids(db, me.id) | {me.id}
    raise HTTPException(status_code=403, detail="Only the Admin and Managers can see activity history")


@protected.get("/activity")
def activity_page(category: str | None = None, actor_id: int | None = None, action: str | None = None,
                  date_from: str | None = None, date_to: str | None = None, q: str | None = None,
                  page: int = 1, page_size: int = 25, db: Session = Depends(get_db)):
    """Activity history with tabs, filters and pages.
    Admin: everything (Manage Access > Activity Log). Manager: only their own and their team's activity
    (Manage Access > Team Activity): the Admin's actions are never shown to Managers. Salespeople: no access."""
    scope = activity_scope(db)
    query = select(ActivityLog).options(selectinload(ActivityLog.actor))
    if scope is not None:
        query = query.where(ActivityLog.actor_id.in_(scope))
    rows = db.scalars(query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(5000)).all()
    people = {}
    for r in rows:
        if r.actor:
            people[r.actor.id] = r.actor.full_name
    counts = {key: 0 for key in ACTIVITY_CATEGORIES}
    for r in rows:
        counts[category_of(r.action)] += 1

    def keep(r) -> bool:
        if category and category_of(r.action) != category:
            return False
        if actor_id and r.actor_id != actor_id:
            return False
        if action and r.action != action:
            return False
        day = r.created_at.date().isoformat() if r.created_at else ""
        if date_from and day < date_from:
            return False
        if date_to and day > date_to:
            return False
        if q:
            text_ = " ".join([r.actor.full_name if r.actor else "System", r.action, r.target, r.details or ""]).lower()
            if q.strip().lower() not in text_:
                return False
        return True

    shown = [r for r in rows if keep(r)]
    page_size = min(max(page_size, 5), 100)
    pages = max(1, -(-len(shown) // page_size))
    page = min(max(page, 1), pages)
    chunk = shown[(page - 1) * page_size: page * page_size]
    actions = sorted({r.action for r in rows if not category or category_of(r.action) == category})
    return {
        "rows": [{"id": r.id, "at": r.created_at, "by": r.actor.full_name if r.actor else "System", "by_id": r.actor_id,
                  "action": r.action, "category": category_of(r.action), "target": r.target, "details": r.details}
                 for r in chunk],
        "total": len(shown), "page": page, "pages": pages, "page_size": page_size,
        "counts": counts, "all": len(rows),
        "categories": [{"key": k, "label": v} for k, v in ACTIVITY_CATEGORIES.items()],
        "actions": actions,
        "people": [{"id": i, "name": n} for i, n in sorted(people.items(), key=lambda x: x[1])],
        "scope": "all" if scope is None else "team",
    }


@protected.get("/activity-log")
def activity_log(limit: int = 300, db: Session = Depends(get_db)):
    """Manage Access > Activity Log: who added or changed users, permissions and record owners. Newest first."""
    require("manage_users")
    rows = db.scalars(select(ActivityLog).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
                      .limit(min(max(limit, 1), 1000))).all()
    return [{"id": r.id, "at": r.created_at, "by": r.actor.full_name if r.actor else "System", "action": r.action,
             "target": r.target, "details": r.details} for r in rows]
