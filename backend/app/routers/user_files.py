"""Bulk add users (Admin): upload an Excel / CSV of people, check it, then create them all.

Same rules as adding one user: a company email (ALLOWED_EMAIL_DOMAINS), no email that already has an account, and a
role of Salesperson, Manager or Admin (Salesperson when the column is empty). Each new user gets the usual welcome
email with a temporary password (from the file, or generated when the file has none). Logged in the Activity Log.
"""
import secrets
import string

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.auth import EMAIL_RE, account_email, allowed_domains, hash_password
from app.routers.lead_files import issue_list, key, read_rows, text_of
from app.security import require_admin
from app.services import log_activity

router = APIRouter(prefix="/api/users", tags=["Login and users"])

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 500
COLUMNS = {
    "full_name": ("fullname", "name", "username", "employeename"),
    "first_name": ("firstname", "first"),
    "last_name": ("lastname", "last", "surname"),
    "email": ("email", "emailaddress", "workemail", "officeemail"),
    "role": ("role", "userrole", "profile", "type"),
    "password": ("password", "temporarypassword", "temppassword"),
}
LOOKUP = {alias: field for field, aliases in COLUMNS.items() for alias in aliases}
ROLES = {"salesperson": "Salesperson", "sales": "Salesperson", "salesrep": "Salesperson", "sales rep": "Salesperson",
         "manager": "Manager", "salesmanager": "Manager", "sales manager": "Manager", "admin": "Admin",
         "administrator": "Admin"}
SAMPLE = "Full Name,Email,Role\nPriya Menon,priya.menon@srsconsultinginc.com,Salesperson\n"


def temporary_password() -> str:
    """10 characters with letters and numbers (the user changes it after logging in)."""
    while True:
        value = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        if any(c.isalpha() for c in value) and any(c.isdigit() for c in value):
            return value


@router.post("/import")
async def import_users(file: UploadFile = File(...), dry_run: bool = Form(True), db: Session = Depends(get_db)):
    """Admin: add many users from a file (columns Full Name or First/Last Name, Email, Role, optional Password).
    dry_run=true (default) only checks the file and shows what would happen; nothing is saved."""
    me = require_admin("add users")
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 5 MB.")
    header, rows = read_rows(file, content)
    if not rows:
        raise HTTPException(status_code=400, detail="The file has no rows.")
    if len(rows) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"Add up to {MAX_ROWS} users per file.")
    fields = [LOOKUP.get(key(h)) for h in header]
    if "email" not in fields or not ({"full_name", "last_name"} & set(fields)):
        raise HTTPException(status_code=400, detail="The file needs Full Name (or First Name and Last Name) and Email columns.")
    domains = allowed_domains()
    taken = set(db.scalars(select(func.lower(User.email))).all())
    ready, errors, seen = [], [], set()
    for number_in_file, row in enumerate(rows, start=2):  # row 1 is the heading
        raw = {}
        for field, value in zip(fields, row):
            if field and field not in raw:
                raw[field] = text_of(value)
        name = " ".join((raw.get("full_name") or f"{raw.get('first_name', '')} {raw.get('last_name', '')}").split())
        email = (raw.get("email") or "").lower()
        role_text = (raw.get("role") or "Salesperson").strip().lower()
        role = ROLES.get(role_text) or ROLES.get(role_text.replace(" ", ""))
        password = raw.get("password") or ""
        problem = None
        if not name:
            problem = "Name is missing"
        elif len(name) > 100:
            problem = "Name is longer than 100 characters"
        elif not EMAIL_RE.match(email):
            problem = f"Email '{email}' is not valid" if email else "Email is missing"
        elif domains and email.rsplit("@", 1)[1] not in domains:
            problem = f"{email} is not a company email (" + " or ".join("@" + d for d in domains) + ")"
        elif role is None:
            problem = f"Role '{raw.get('role')}' is not Salesperson, Manager or Admin"
        elif password and (len(password) < 8 or not (any(c.isalpha() for c in password)
                                                       and any(c.isdigit() for c in password))):
            problem = "Password must have at least 8 characters, with letters and numbers"
        if problem:
            errors.append({"row": number_in_file, "reason": problem})
        elif email in taken:
            errors.append({"row": number_in_file, "reason": f"{email} already has an account", "duplicate": True})
        elif email in seen:
            errors.append({"row": number_in_file, "reason": f"{email} is repeated in this file", "duplicate": True})
        else:
            seen.add(email)
            ready.append({"row": number_in_file, "full_name": name, "email": email, "role": role, "password": password})
    duplicates = sum(1 for e in errors if e.get("duplicate"))
    result = {
        "file": file.filename,
        "rows": len(rows),
        "ready": len(ready),
        "duplicates": duplicates,
        "invalid": len(errors) - duplicates,
        "errors": issue_list(errors, header, rows, LOOKUP),
        "roles": {r: sum(1 for u in ready if u["role"] == r) for r in ("Salesperson", "Manager", "Admin")},
        "preview": [{k: u[k] for k in ("full_name", "email", "role")} for u in ready[:10]],
        "created": 0,
    }
    if dry_run or not ready:
        return result
    for person in ready:
        password = person["password"] or temporary_password()
        user = User(full_name=person["full_name"], email=person["email"], role=person["role"],
                    password_hash=hash_password(password))
        db.add(user)
        db.flush()
        account_email(db, user, password, new=True)  # the usual welcome email, sent after the save
        result["created"] += 1
    counts = ", ".join(f"{n} {r}{'s' if n != 1 else ''}" for r, n in result["roles"].items() if n)
    log_activity(db, me.id, "Users uploaded", file.filename or "file",
                 f"{result['created']} created ({counts}) • {duplicates} already had an account or repeated"
                 f" • {result['invalid']} invalid rows")
    db.commit()
    return result
