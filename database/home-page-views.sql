-- =====================================================
-- CRM Application - Views for the Home page (SalesTrack "Sales Overview")
-- One view per section of the page. Run AFTER schema.sql, connected to crm_db.
-- =====================================================

-- 1. The 4 cards: Total leads | Open opportunities | Won deals | Tasks due today
CREATE OR REPLACE VIEW v_home_summary AS
SELECT
  (SELECT COUNT(*) FROM leads)                                                   AS total_leads,
  (SELECT COUNT(*) FROM opportunities WHERE stage IN ('Opportunity','Discovery','Proposal')) AS open_opportunities,
  (SELECT COUNT(*) FROM opportunities WHERE stage = 'Won')                       AS won_deals,
  (SELECT COUNT(*) FROM tasks
     WHERE status = 'Open' AND due_date::date = CURRENT_DATE)                    AS tasks_due_today;

-- 2. Sales pipeline: Unqualified | New | Nurturing | Revisit | Demo | Opportunity | Discovery | Proposal | Won | Lost
CREATE OR REPLACE VIEW v_sales_pipeline AS
SELECT s.sort_order, s.stage, s.unit,
       CASE
         WHEN s.stage IN ('Unqualified','New','Nurturing','Revisit','Demo')
           THEN (SELECT COUNT(*) FROM leads l WHERE l.stage = s.stage)
         WHEN s.stage = 'Lost'
           THEN (SELECT COUNT(*) FROM leads l WHERE l.stage = 'Lost')
              + (SELECT COUNT(*) FROM opportunities o WHERE o.stage = 'Lost')
         ELSE (SELECT COUNT(*) FROM opportunities o WHERE o.stage = s.stage)
       END AS total
FROM (VALUES
  (1,  'Unqualified', 'leads'),
  (2,  'New',         'leads'),
  (3,  'Nurturing',   'leads'),
  (4,  'Revisit',     'leads'),
  (5,  'Demo',        'leads'),
  (6,  'Opportunity', 'opportunities'),
  (7,  'Discovery',   'opportunities'),
  (8,  'Proposal',    'opportunities'),
  (9,  'Won',         'closed deals'),
  (10, 'Lost',        'closed deals')
) AS s(sort_order, stage, unit);

-- 3. Today's tasks: open tasks due today, plus overdue ones (flagged)
CREATE OR REPLACE VIEW v_todays_tasks AS
SELECT t.id, t.title, t.due_date, t.priority, t.owner_id,
       u.full_name AS owner,
       CASE WHEN t.lead_id IS NOT NULL THEN 'Lead'
            WHEN t.opportunity_id IS NOT NULL THEN 'Opportunity'
            ELSE 'General' END                     AS related_type,
       COALESCE(l.name, o.name)                    AS related_to,
       (t.due_date < CURRENT_DATE)                 AS is_overdue
FROM tasks t
JOIN users u              ON u.id = t.owner_id
LEFT JOIN leads l         ON l.id = t.lead_id
LEFT JOIN opportunities o ON o.id = t.opportunity_id
WHERE t.status = 'Open'
  AND t.due_date < CURRENT_DATE + 1;

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

-- ---------- "Search anything..." box (ILIKE = case-insensitive) ----------
-- SELECT 'Lead' AS type, id, name, company AS detail FROM leads
--   WHERE name ILIKE '%sun%' OR company ILIKE '%sun%' OR email ILIKE '%sun%'
-- UNION ALL
-- SELECT 'Opportunity', id, name, stage FROM opportunities WHERE name ILIKE '%sun%'
-- UNION ALL
-- SELECT 'Task', id, title, status FROM tasks WHERE title ILIKE '%sun%';

-- ---------- Bell icon ----------
-- SELECT * FROM notifications WHERE user_id = 2 AND is_read = FALSE ORDER BY created_at DESC;
