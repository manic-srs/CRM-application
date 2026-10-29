"""Bulk upload of opportunities from Excel / CSV (e.g. deals kept in a spreadsheet before the CRM) and download of
opportunities to Excel / CSV (filter by Open / Won / Lost...). Works like the lead upload and download:
the file is checked first, every upload and download is recorded in the Activity Log, and a download needs a reason.

Each row needs an opportunity (deal) name or a company. The company becomes an Account (reused when it exists);
a contact is added when the row has a contact name or email. Rows that match an existing deal (same name, same
account) are skipped. No automatic tasks, emails or per-row notifications.
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants import OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES, STAGE_PROBABILITY
from app.database import get_db
from app.models import Account, Contact, Opportunity, StageHistory, User
from app.routers.lead_files import EMAIL_RE, MAX_FILE_BYTES, MAX_ROWS, key, number, read_rows, text_of
from app.security import owner_for_new, require, visible
from app.services import log_activity, notify

router = APIRouter(prefix="/api/opportunities", tags=["Opportunities: upload and download"])

COLUMNS = {
    "name": ("opportunityname", "opportunity", "dealname", "deal", "name"),
    "company": ("company", "companyname", "account", "accountname", "organization", "organisation", "client"),
    "amount": ("amount", "expectedvalue", "value", "dealvalue", "dealamount", "expectedamount"),
    "final_amount": ("finalamount", "finalvalue", "wonamount"),
    "close_date": ("closedate", "expectedclosedate", "closingdate"),
    "stage": ("stage", "status", "dealstage"),
    "lost_reason": ("lostreason", "reason"),
    "first_name": ("contactfirstname", "firstname"),
    "last_name": ("contactlastname", "lastname"),
    "contact_name": ("contact", "contactname", "primarycontact"),
    "email": ("contactemail", "email"),
    "phone": ("contactphone", "phone"),
    "title": ("contacttitle", "title", "jobtitle"),
    "industry": ("industry",),
    "website": ("website", "companywebsite"),
}
LOOKUP = {alias: field for field, aliases in COLUMNS.items() for alias in aliases}
STAGES = {s.lower(): s for s in OPPORTUNITY_STAGES} | {"open": "Opportunity", "closed won": "Won", "closedwon": "Won",
                                                       "closed lost": "Lost", "closedlost": "Lost", "new": "Opportunity"}
LOST_REASONS = ("Price", "Competitor", "No response", "No budget", "Not interested", "Other")


def as_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d %b %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Close date '{text}' is not a date (use YYYY-MM-DD)")


def parse(header, rows):
    fields = [LOOKUP.get(key(h)) for h in header]
    mapped = sorted({h for h, f in zip(header, fields) if f})
    ignored = [h for h, f in zip(header, fields) if not f and h]
    if "name" not in fields and "company" not in fields:
        raise HTTPException(status_code=400, detail="The file needs an 'Opportunity Name' or 'Company' column.")
    deals, errors = [], []
    for row_no, row in enumerate(rows, start=2):
        raw = {}
        for field, value in zip(fields, row):
            if field and field not in raw:
                raw[field] = value if field == "close_date" else text_of(value)
        company = (raw.get("company") or "")[:200]
        name = (raw.get("name") or "")[:200] or (f"{company} - Opportunity" if company else "")
        if not company and not name:
            errors.append({"row": row_no, "reason": "Opportunity name or company is missing"})
            continue
        stage = STAGES.get((raw.get("stage") or "Opportunity").strip().lower())
        if stage is None:
            errors.append({"row": row_no, "reason": f"Stage '{raw.get('stage')}' is not Opportunity, Proposal, Won or Lost"})
            continue
        try:
            amount = number(raw.get("amount", ""))
            final = number(raw.get("final_amount", "")) or (amount if stage == "Won" else None)
            close = as_date(raw.get("close_date"))
        except (ValueError, InvalidOperation) as err:
            errors.append({"row": row_no, "reason": str(err) if "date" in str(err) else "Amount is not a number"})
            continue
        if stage == "Won" and final is None:
            errors.append({"row": row_no, "reason": "A Won deal needs an amount"})
            continue
        email = (raw.get("email") or "").lower()
        if email and not EMAIL_RE.match(email):
            errors.append({"row": row_no, "reason": f"Email '{email}' is not valid"})
            continue
        first, last = raw.get("first_name") or None, raw.get("last_name") or None
        if not last and raw.get("contact_name"):
            parts = raw["contact_name"].split(" ")
            first, last = " ".join(parts[:-1]) or None, parts[-1]
        if not last and email:
            last = email.split("@")[0]
        reason = next((r for r in LOST_REASONS if r.lower() == (raw.get("lost_reason") or "").strip().lower()), "Other")
        deals.append({
            "_row": row_no, "name": name, "company": company or name, "stage": stage, "amount": amount,
            "final": final, "close": close, "lost_reason": reason if stage == "Lost" else None,
            "contact": {"first_name": (first or "")[:50] or None, "last_name": last[:50], "email": email or None,
                        "phone": (raw.get("phone") or "")[:30] or None, "job_title": (raw.get("title") or "")[:100] or None}
            if last else None,
            "industry": (raw.get("industry") or "")[:100] or None, "website": (raw.get("website") or "")[:255] or None,
        })
    return deals, errors, mapped, ignored


@router.post("/import")
async def import_opportunities(
    file: UploadFile = File(...),
    owner_id: int | None = Form(None),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Upload opportunities from Excel / CSV. dry_run=true (default) only checks the file."""
    me = require("import_leads")
    if me.role == "Admin":
        if owner_id is None or owner_id == me.id:
            raise HTTPException(status_code=400, detail="Choose who will own the uploaded opportunities.")
    else:
        owner_id = owner_for_new(owner_id)
    target = db.get(User, owner_id)
    if target is None or not target.is_active or target.role == "Admin":
        raise HTTPException(status_code=400, detail="The owner must be an active Manager or Salesperson.")
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 50 MB. Split it into smaller files.")
    header, rows = read_rows(file, content)
    if not rows:
        raise HTTPException(status_code=400, detail="The file has no rows to upload.")
    if len(rows) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"Upload up to {MAX_ROWS:,} rows per file.")
    deals, errors, mapped, ignored = parse(header, rows)

    # skip deals that already exist (same name on an account with the same company name) or repeat in the file
    accounts = {a.name.strip().lower(): a for a in db.scalars(select(Account)).all()}
    existing = {(n.strip().lower(), aid) for n, aid in db.execute(select(Opportunity.name, Opportunity.account_id)).all()}
    keep, seen = [], set()
    for d in deals:
        account = accounts.get(d["company"].strip().lower())
        pair = (d["name"].strip().lower(), d["company"].strip().lower())
        if account is not None and (pair[0], account.id) in existing or pair in seen:
            errors.append({"row": d["_row"], "reason": "This opportunity already exists (duplicate)", "duplicate": True})
        else:
            keep.append(d)
            seen.add(pair)
    errors.sort(key=lambda e: e["row"])
    duplicates = sum(1 for e in errors if e.get("duplicate"))
    result = {
        "file": file.filename, "rows": len(rows), "ready": len(keep), "duplicates": duplicates,
        "invalid": len(errors) - duplicates, "owner": target.full_name, "columns_used": mapped,
        "columns_ignored": ignored, "errors": [{"row": e["row"], "reason": e["reason"]} for e in errors[:500]],
        "preview": [{"name": d["name"], "company": d["company"], "stage": d["stage"],
                     "amount": float(d["amount"]) if d["amount"] is not None else None,
                     "close_date": d["close"].isoformat() if d["close"] else None,
                     "contact": " ".join(x for x in ((d["contact"] or {}).get("first_name"),
                                                     (d["contact"] or {}).get("last_name")) if x)}
                    for d in keep[:5]],
        "created": 0, "accounts_created": 0,
    }
    if dry_run or not keep:
        return result
    contacts = {c.email.lower(): c for c in db.scalars(select(Contact).where(Contact.email.is_not(None))).all()}
    note = f"Uploaded from {file.filename}"
    for d in keep:
        account = accounts.get(d["company"].strip().lower())
        if account is None:
            account = Account(name=d["company"], industry=d["industry"], website=d["website"], owner_id=owner_id)
            db.add(account)
            db.flush()
            accounts[d["company"].strip().lower()] = account
            result["accounts_created"] += 1
        contact = None
        if d["contact"]:
            contact = contacts.get(d["contact"]["email"] or "")
            if contact is None:
                contact = Contact(**d["contact"], account_id=account.id, owner_id=owner_id)
                db.add(contact)
                db.flush()
                if contact.email:
                    contacts[contact.email] = contact
        closed = d["stage"] in ("Won", "Lost")
        opp = Opportunity(
            name=d["name"], stage=d["stage"], probability=STAGE_PROBABILITY[d["stage"]], expected_value=d["amount"],
            final_value=d["final"] if d["stage"] == "Won" else None, expected_close_date=d["close"],
            lost_reason=d["lost_reason"], closed_at=datetime.now() if closed else None, account_id=account.id,
            primary_contact_id=contact.id if contact else None, owner_id=owner_id,
        )
        db.add(opp)
        db.flush()
        db.add(StageHistory(opportunity_id=opp.id, from_stage=None, to_stage=d["stage"], changed_by_id=me.id, note=note))
        result["created"] += 1
    log_activity(db, me.id, "Opportunities uploaded", file.filename or "file",
                 f"{result['created']:,} created • {duplicates:,} duplicates skipped • {result['invalid']:,} invalid rows"
                 f" • {result['accounts_created']:,} new accounts • Owner: {target.full_name}")
    if owner_id != me.id:
        notify(db, owner_id, "Opportunities assigned to you",
               f"{me.full_name} uploaded {result['created']:,} opportunities and assigned them to you ({file.filename}).",
               link="/opportunities", category="assignment")
    db.commit()
    return result


EXPORT_COLUMNS = (
    ("Opportunity Name", "name"), ("Account", "account"), ("Primary Contact", "contact"),
    ("Contact Email", "contact_email"), ("Amount (USD)", "expected_value"), ("Final Amount (USD)", "final_value"),
    ("Close Date", "expected_close_date"), ("Stage", "stage"), ("Probability (%)", "probability"),
    ("Lost Reason", "lost_reason"), ("Owner", "owner"), ("Created", "created_at"), ("Closed", "closed_at"),
)
STAGE_FILTERS = {"all": None, "open": OPPORTUNITY_OPEN_STAGES, **{s.lower(): (s,) for s in OPPORTUNITY_STAGES}}


@router.get("/export")
def export_opportunities(
    reason: str = Query(..., min_length=5, max_length=300, description="Why the file is needed (recorded)"),
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    stage: str = Query("all", description="all, open, opportunity, proposal, won or lost"),
    mine: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Download the opportunities you can see to Excel / CSV, recorded in the Activity Log (the Admin is notified)."""
    me = require("export_data")
    reason = " ".join(reason.split())
    if len(reason) < 5:
        raise HTTPException(status_code=422, detail="Give a reason for the download (at least 5 characters).")
    stage = stage.lower()
    if stage not in STAGE_FILTERS:
        raise HTTPException(status_code=400, detail="Unknown stage filter")
    query = visible(select(Opportunity), Opportunity).options(
        selectinload(Opportunity.account), selectinload(Opportunity.primary_contact), selectinload(Opportunity.owner)
    ).order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
    if STAGE_FILTERS[stage]:
        query = query.where(Opportunity.stage.in_(STAGE_FILTERS[stage]))
    if mine:
        query = query.where(Opportunity.owner_id == me.id)
    opps = db.scalars(query).all()

    def values(o: Opportunity) -> list:
        extra = {
            "account": o.account.name if o.account else None,
            "contact": o.primary_contact.full_name if o.primary_contact else None,
            "contact_email": o.primary_contact.email if o.primary_contact else None,
            "owner": o.owner.full_name if o.owner else None,
        }
        out = []
        for _, attr in EXPORT_COLUMNS:
            value = extra[attr] if attr in extra else getattr(o, attr)
            if isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, datetime):
                value = value.strftime("%Y-%m-%d %H:%M")
            elif isinstance(value, date):
                value = value.isoformat()
            out.append(value)
        return out

    label = {"all": "All", "open": "Open"}.get(stage, stage.title())
    filename = f"SalesTrack-Opportunities-{label}{'-Mine' if mine else ''}-{datetime.now():%Y%m%d-%H%M}.{format}"
    headings = [h for h, _ in EXPORT_COLUMNS]
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headings)
        writer.writerows(values(o) for o in opps)
        body, media = ("﻿" + buffer.getvalue()).encode(), "text/csv; charset=utf-8"
    else:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Font
        book = Workbook(write_only=True)
        sheet = book.create_sheet("Opportunities")
        row = []
        for h in headings:
            cell = WriteOnlyCell(sheet, value=h)
            cell.font = Font(bold=True)
            row.append(cell)
        sheet.append(row)
        for o in opps:
            sheet.append(values(o))
        out = io.BytesIO()
        book.save(out)
        body, media = out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    what = f"{len(opps):,} {'opportunity' if len(opps) == 1 else 'opportunities'} ({label}{', mine only' if mine else ''})"
    log_activity(db, me.id, "Opportunities downloaded", what, f"Reason: {reason} • {filename}")
    for admin_id in db.scalars(select(User.id).where(User.role == "Admin", User.is_active.is_(True), User.id != me.id)).all():
        notify(db, admin_id, "Opportunities downloaded", f"{me.full_name} downloaded {what}.\nReason: {reason}",
               link="/activity")
    db.commit()
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Access-Control-Expose-Headers": "Content-Disposition"})
