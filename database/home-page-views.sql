-- =====================================================
-- CRM Application - Views for the Home page (SalesTrack "Sales Overview")
-- One view per section of the page. Run AFTER schema.sql.
-- =====================================================
USE crm_db;

-- 1. The 4 cards: Total leads | Open opportunities | Won deals | Tasks due today
CREATE OR REPLACE VIEW v_home_summary AS
SELECT
  (SELECT COUNT(*) FROM leads)                                              AS total_leads,
  (SELECT COUNT(*) FROM opportunities WHERE stage IN ('Opportunity','Proposal')) AS open_opportunities,
  (SELECT COUNT(*) FROM opportunities WHERE stage = 'Won')                  AS won_deals,
  (SELECT COUNT(*) FROM tasks
     WHERE status = 'Open' AND DATE(due_date) = CURDATE())                  AS tasks_due_today;

-- 2. Sales pipeline: New | Nurturing | Demo | Opportunity | Proposal | Won | Lost
CREATE OR REPLACE VIEW v_sales_pipeline AS
SELECT s.sort_order, s.stage, s.unit,
       CASE
         WHEN s.stage IN ('New','Nurturing','Demo')
           THEN (SELECT COUNT(*) FROM leads l WHERE l.stage = s.stage)
         WHEN s.stage = 'Lost'
           THEN (SELECT COUNT(*) FROM leads l WHERE l.stage = 'Lost')
              + (SELECT COUNT(*) FROM opportunities o WHERE o.stage = 'Lost')
         ELSE (SELECT COUNT(*) FROM opportunities o WHERE o.stage = s.stage)
       END AS total
FROM (
  SELECT 1 AS sort_order, 'New' AS stage, 'leads' AS unit
  UNION ALL SELECT 2, 'Nurturing',   'leads'
  UNION ALL SELECT 3, 'Demo',        'leads'
  UNION ALL SELECT 4, 'Opportunity', 'opportunities'
  UNION ALL SELECT 5, 'Proposal',    'opportunities'
  UNION ALL SELECT 6, 'Won',         'closed deals'
  UNION ALL SELECT 7, 'Lost',        'closed deals'
) s;

-- 3. Today's tasks: open tasks due today, plus overdue ones (flagged)
CREATE OR REPLACE VIEW v_todays_tasks AS
SELECT t.id, t.title, t.due_date, t.priority, t.owner_id,
       u.full_name AS owner,
       CASE WHEN t.lead_id IS NOT NULL THEN 'Lead'
            WHEN t.opportunity_id IS NOT NULL THEN 'Opportunity'
            ELSE 'General' END                     AS related_type,
       COALESCE(l.name, o.name)                    AS related_to,
       (t.due_date < CURDATE())                    AS is_overdue
FROM tasks t
JOIN users u              ON u.id = t.owner_id
LEFT JOIN leads l         ON l.id = t.lead_id
LEFT JOIN opportunities o ON o.id = t.opportunity_id
WHERE t.status = 'Open'
  AND t.due_date < CURDATE() + INTERVAL 1 DAY;

-- 4. Won vs Lost: number of closed deals and their value
CREATE OR REPLACE VIEW v_won_vs_lost AS
SELECT 'Won' AS outcome,
       COUNT(*) AS deals,
       COALESCE(SUM(final_value), 0) AS value
FROM opportunities WHERE stage = 'Won'
UNION ALL
SELECT 'Lost',
       (SELECT COUNT(*) FROM leads WHERE stage = 'Lost') + COUNT(*),
       COALESCE(SUM(expected_value), 0)
FROM opportunities WHERE stage = 'Lost';

-- ---------- Try them ----------
-- SELECT * FROM v_home_summary;
-- SELECT * FROM v_sales_pipeline ORDER BY sort_order;
-- SELECT * FROM v_todays_tasks ORDER BY is_overdue DESC, due_date;
-- SELECT * FROM v_won_vs_lost;

-- ---------- "Search anything..." box (backend runs this with the typed text) ----------
-- SELECT 'Lead' AS type, id, name, company AS detail FROM leads
--   WHERE name LIKE CONCAT('%', 'sun', '%') OR company LIKE CONCAT('%', 'sun', '%') OR email LIKE CONCAT('%', 'sun', '%')
-- UNION ALL
-- SELECT 'Opportunity', id, name, stage FROM opportunities WHERE name LIKE CONCAT('%', 'sun', '%')
-- UNION ALL
-- SELECT 'Task', id, title, status FROM tasks WHERE title LIKE CONCAT('%', 'sun', '%');

-- ---------- Bell icon ----------
-- SELECT * FROM notifications WHERE user_id = 2 AND is_read = FALSE ORDER BY created_at DESC;