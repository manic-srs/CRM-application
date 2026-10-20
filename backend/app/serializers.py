"""Turn database rows into API responses, adding readable names (owner, account, related record)."""
from app import schemas
from app.models import Account, Contact, Lead, Note, Opportunity, StageHistory, Task
from app.services import start_of_today, task_related


def task_out(t: Task) -> schemas.TaskOut:
    related_type, related_to = task_related(t)
    return schemas.TaskOut.model_validate(t).model_copy(
        update={
            "owner_name": t.owner.full_name if t.owner else None,
            "related_type": related_type,
            "related_to": related_to,
            "is_overdue": t.status == "Open" and t.due_date < start_of_today(),
        }
    )


def note_out(n: Note) -> schemas.NoteOut:
    return schemas.NoteOut.model_validate(n).model_copy(
        update={"created_by_name": n.created_by.full_name if n.created_by else None}
    )


def history_out(h: StageHistory) -> schemas.StageHistoryOut:
    return schemas.StageHistoryOut.model_validate(h).model_copy(
        update={"changed_by_name": h.changed_by.full_name if h.changed_by else None}
    )


def lead_out(lead: Lead) -> schemas.LeadOut:
    return schemas.LeadOut.model_validate(lead).model_copy(
        update={
            "owner_name": lead.owner.full_name if lead.owner else None,
            "opportunity_id": lead.opportunity.id if lead.opportunity else None,
        }
    )


def lead_detail(lead: Lead) -> schemas.LeadDetail:
    base = lead_out(lead).model_dump()
    return schemas.LeadDetail(
        **base,
        tasks=[task_out(t) for t in sorted(lead.tasks, key=lambda t: (t.status != "Open", t.due_date))],
        notes=[note_out(n) for n in sorted(lead.notes, key=lambda n: n.id, reverse=True)],
        history=[history_out(h) for h in sorted(lead.history, key=lambda h: h.id)],
    )


def account_out(a: Account) -> schemas.AccountOut:
    return schemas.AccountOut.model_validate(a).model_copy(update={"owner_name": a.owner.full_name if a.owner else None})


def contact_out(c: Contact) -> schemas.ContactOut:
    return schemas.ContactOut.model_validate(c).model_copy(update={"account_name": c.account.name if c.account else None})


def opportunity_out(o: Opportunity) -> schemas.OpportunityOut:
    return schemas.OpportunityOut.model_validate(o).model_copy(
        update={
            "account_name": o.account.name if o.account else None,
            "primary_contact_name": o.primary_contact.full_name if o.primary_contact else None,
            "owner_name": o.owner.full_name if o.owner else None,
        }
    )


def opportunity_detail(o: Opportunity) -> schemas.OpportunityDetail:
    base = opportunity_out(o).model_dump()
    return schemas.OpportunityDetail(
        **base,
        tasks=[task_out(t) for t in sorted(o.tasks, key=lambda t: (t.status != "Open", t.due_date))],
        notes=[note_out(n) for n in sorted(o.notes, key=lambda n: n.id, reverse=True)],
        history=[history_out(h) for h in sorted(o.history, key=lambda h: h.id)],
    )


def account_detail(a: Account) -> schemas.AccountDetail:
    base = account_out(a).model_dump()
    return schemas.AccountDetail(
        **base,
        contacts=[contact_out(c) for c in a.contacts],
        opportunities=[opportunity_out(o) for o in a.opportunities],
    )
