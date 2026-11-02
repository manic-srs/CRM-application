"""Allowed values. They match the ENUM lists in database/schema.sql."""

# Lead path: New -> Nurturing -> Revisit (optional) -> Demo -> Converted (becomes an Opportunity).
# Closed without converting, from any open stage (like Salesforce "Closed - Not Converted"):
#   Unqualified = not eligible / not a fit (a reason is required; the lead can be reopened later, Salesforce "recycle")
#   Lost        = was a fit but didn't go ahead (price, competitor...)
# Leads start at New (created by hand, uploaded or from the assistant).
# Shown in this order (the lead path and board): Unqualified first, as the requirement lists it
LEAD_STAGES = ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted", "Lost"]
LEAD_OPEN_STAGES = ["New", "Nurturing", "Revisit", "Demo"]
LEAD_CLOSED_STAGES = ["Converted", "Unqualified", "Lost"]
LEAD_START = "New"
# The order a lead or deal must follow: no required stage can be skipped. A salesperson may confirm that a stage
# was already done (for example the demo happened outside the CRM); that is saved in the stage history.
# Optional stages (Revisit: only when a lead asks to be contacted again later) may be passed over.
LEAD_FLOW = ["New", "Nurturing", "Revisit", "Demo"]   # then Convert
LEAD_OPTIONAL_STAGES = ["Revisit"]
LEAD_SOURCES = ["Website", "Referral", "Phone", "Email", "Event", "Social Media", "Other", "Upload"]  # Upload: bulk upload

# Opportunity path: Opportunity -> Discovery -> Proposal -> Won; Lost from any open stage
OPPORTUNITY_STAGES = ["Opportunity", "Discovery", "Proposal", "Won", "Lost"]
OPPORTUNITY_OPEN_STAGES = ["Opportunity", "Discovery", "Proposal"]
OPPORTUNITY_FLOW = ["Opportunity", "Discovery", "Proposal"]           # then Won

LOST_REASONS = ["Price", "Competitor", "No response", "No budget", "Not interested", "Other"]
# Why a lead isn't eligible. Not a fit and Bad data are permanent; the others can be revisited later (Reopen).
UNQUALIFIED_REASONS = ["Not a fit", "No budget", "No authority", "No current need", "Bad timing", "Bad data", "Other"]
# Revisit = "not now": the lead asked to be contacted later. A date to come back and the reason are required.
REVISIT_REASONS = ["Bad timing", "Budget next period", "Asked to call back", "No response yet", "Demo cancelled", "Other"]

TASK_STATUSES = ["Open", "Done", "Auto-closed"]
TASK_PRIORITIES = ["Low", "Normal", "High"]

USER_ROLES = ["Salesperson", "Manager", "Admin"]
SALUTATIONS = ["Mr.", "Ms.", "Mrs.", "Dr.", "Prof."]

# Win probability (%) per opportunity stage, like Salesforce
STAGE_PROBABILITY = {"Opportunity": 20, "Discovery": 40, "Proposal": 75, "Won": 100, "Lost": 0}

# Follow-up task the system creates when a record reaches a stage:  stage -> (title, days until due, priority)
AUTO_TASKS = {
    "New": ("Make first contact", 1, "High"),
    "Nurturing": ("Follow-up call", 2, "Normal"),
    "Revisit": ("Revisit lead", 7, "Normal"),  # due on the chosen revisit date
    "Demo": ("Conduct demo", 3, "High"),
    "Opportunity": ("Schedule discovery call", 2, "Normal"),
    "Discovery": ("Send proposal", 3, "Normal"),
    "Proposal": ("Follow up on proposal", 3, "High"),
}

# Timeline reminders: tasks the system keeps in step with important dates (see services.schedule_*).
# Each task's reminder_at is its due time, so the scheduler reminds the owner (bell + email) when it is due.
DEMO_PREP_TASK = "Prepare for demo"          # due at 9 AM the day before the demo
DEMO_REMINDER_MINUTES = 60                   # "Conduct demo" reminder this long before the demo starts
CLOSE_DATE_TASK = "Close date coming up"     # due at 9 AM a few days before the expected close date
CLOSE_DATE_NOTICE_DAYS = 3
WORKDAY_START_HOUR = 9
