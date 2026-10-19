-- =====================================================
-- CRM Application - Queries to test the data
-- =====================================================
USE crm_db;

-- 1. Row count per table
SELECT 'users' AS tbl, COUNT(*) AS total FROM users
UNION ALL SELECT 'accounts', COUNT(*) FROM accounts
UNION ALL SELECT 'contacts', COUNT(*) FROM contacts
UNION ALL SELECT 'leads', COUNT(*) FROM leads
UNION ALL SELECT 'opportunities', COUNT(*) FROM opportunities
UNION ALL SELECT 'tasks', COUNT(*) FROM tasks
UNION ALL SELECT 'stage_history', COUNT(*) FROM stage_history
UNION ALL SELECT 'notes', COUNT(*) FROM notes
UNION ALL SELECT 'notifications', COUNT(*) FROM notifications;

-- 2. Pipeline board: number of records per stage
SELECT stage, COUNT(*) AS total FROM leads
WHERE stage IN ('New','Nurturing','Demo') GROUP BY stage
UNION ALL
SELECT stage, COUNT(*) FROM opportunities GROUP BY stage;

-- 3. Leads with owner name
SELECT l.id, l.name, l.company, l.stage, l.source, u.full_name AS owner
FROM leads l JOIN users u ON u.id = l.owner_id
ORDER BY l.id;

-- 4. Opportunities with account, contact and owner (opportunity belongs to an account)
SELECT o.name, o.stage, o.expected_value, o.final_value,
       a.name AS account, c.full_name AS contact, u.full_name AS owner
FROM opportunities o
JOIN accounts a      ON a.id = o.account_id
LEFT JOIN contacts c ON c.id = o.primary_contact_id
JOIN users u         ON u.id = o.owner_id;

-- 5. All tasks with what they belong to (lead, opportunity or general)
SELECT t.title, t.status, t.due_date,
       COALESCE(l.name, o.name) AS related_to,
       CASE WHEN t.lead_id IS NOT NULL THEN 'Lead' WHEN t.opportunity_id IS NOT NULL THEN 'Opportunity' ELSE 'General' END AS related_type,
       u.full_name AS owner
FROM tasks t
LEFT JOIN leads l         ON l.id = t.lead_id
LEFT JOIN opportunities o ON o.id = t.opportunity_id
JOIN users u              ON u.id = t.owner_id
ORDER BY t.due_date;

-- 6. Overdue open tasks (for reminders)
SELECT t.title, t.due_date, u.full_name AS owner
FROM tasks t JOIN users u ON u.id = t.owner_id
WHERE t.status = 'Open' AND t.due_date < NOW();

-- 7. Full history of one opportunity including its lead stages (GreenLeaf, opportunity id 2)
SELECT h.changed_at, h.from_stage, h.to_stage, u.full_name AS changed_by
FROM stage_history h JOIN users u ON u.id = h.changed_by_id
WHERE h.opportunity_id = 2
   OR h.lead_id = (SELECT lead_id FROM opportunities WHERE id = 2)
ORDER BY h.changed_at, h.id;

-- 8. Dashboard: pipeline value, won vs lost, lost reasons
SELECT SUM(expected_value) AS open_pipeline_value
FROM opportunities WHERE stage IN ('Opportunity','Proposal');

SELECT stage, COUNT(*) AS deals, SUM(COALESCE(final_value, expected_value)) AS value
FROM opportunities WHERE stage IN ('Won','Lost') GROUP BY stage;

SELECT lost_reason, COUNT(*) AS total FROM (
  SELECT lost_reason FROM leads WHERE stage = 'Lost'
  UNION ALL
  SELECT lost_reason FROM opportunities WHERE stage = 'Lost'
) x GROUP BY lost_reason;

-- 9. Rule checks: each of these should FAIL with "Check constraint ... is violated"
-- INSERT INTO leads (name, stage, owner_id) VALUES ('Test', 'Lost', 1);
-- INSERT INTO opportunities (name, stage, account_id, owner_id) VALUES ('Test', 'Won', 1, 1);
-- INSERT INTO tasks (title, due_date, owner_id, lead_id, opportunity_id) VALUES ('Test', NOW(), 1, 1, 1);