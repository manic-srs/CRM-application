"""Allowed values. They match the ENUM lists in database/schema.sql."""

LEAD_STAGES = ["New", "Nurturing", "Demo", "Converted", "Lost"]
LEAD_OPEN_STAGES = ["New", "Nurturing", "Demo"]
LEAD_SOURCES = ["Website", "Referral", "Phone", "Email", "Event", "Social Media", "Other"]

OPPORTUNITY_STAGES = ["Opportunity", "Proposal", "Won", "Lost"]
OPPORTUNITY_OPEN_STAGES = ["Opportunity", "Proposal"]

LOST_REASONS = ["Price", "Competitor", "No response", "No budget", "Not interested", "Other"]

TASK_STATUSES = ["Open", "Done", "Auto-closed"]
TASK_PRIORITIES = ["Low", "Normal", "High"]

USER_ROLES = ["Salesperson", "Manager", "Admin"]
SALUTATIONS = ["Mr.", "Ms.", "Mrs.", "Dr.", "Prof."]

# Win probability (%) per opportunity stage, like Salesforce
STAGE_PROBABILITY = {"Opportunity": 20, "Proposal": 75, "Won": 100, "Lost": 0}

# Follow-up task the system creates when a record reaches a stage:  stage -> (title, days until due, priority)
AUTO_TASKS = {
    "New": ("Make first contact", 1, "High"),
    "Nurturing": ("Follow-up call", 2, "Normal"),
    "Demo": ("Conduct demo", 3, "High"),
    "Opportunity": ("Send proposal", 3, "Normal"),
    "Proposal": ("Follow up on proposal", 3, "High"),
}
