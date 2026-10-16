-- =====================================================
-- CRM Application - Sample data for testing
-- Run AFTER schema.sql
-- All users' password: Password@123
-- =====================================================
USE crm_db;

-- ---------- USERS ----------
INSERT INTO users (id, full_name, email, password_hash, role) VALUES
(1, 'Priya Sharma', 'priya@crm.test', '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Manager'),
(2, 'Ravi Kumar',   'ravi@crm.test',  '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Salesperson'),
(3, 'Anita Desai',  'anita@crm.test', '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Salesperson');

-- ---------- ACCOUNTS ----------
INSERT INTO accounts (id, name, industry, phone, website, owner_id) VALUES
(1, 'Sunrise Hospitals', 'Healthcare',    '+91 80 4000 1000', 'sunrisehospitals.in', 2),
(2, 'GreenLeaf Foods',   'FMCG',          '+91 80 4000 2000', 'greenleaffoods.in',   3),
(3, 'Apex Logistics',    'Logistics',     '+91 80 4000 3000', 'apexlogistics.in',    2),
(4, 'Nova Textiles',     'Manufacturing', '+91 80 4000 4000', 'novatextiles.in',     3);

-- ---------- CONTACTS ----------
INSERT INTO contacts (id, full_name, job_title, email, account_id, owner_id) VALUES
(1, 'Dr. Meera Iyer', 'Director of Operations', 'meera@sunrisehospitals.in', 1, 2),
(2, 'Rahul Nair',     'IT Manager',             'rahul@sunrisehospitals.in', 1, 2),
(3, 'Arjun Mehta',    'Head of Sales',          'arjun@greenleaffoods.in',   2, 3),
(4, 'Kavya Reddy',    'COO',                    'kavya@apexlogistics.in',    3, 2),
(5, 'Sanjay Patel',   'Purchase Manager',       'sanjay@novatextiles.in',    4, 3);

-- ---------- LEADS (one in every stage) ----------
INSERT INTO leads (id, name, company, email, phone, source, stage, demo_date, lost_reason, lost_notes, converted_at, closed_at, owner_id) VALUES
(1, 'Vikram Singh',   'BrightPath Schools', 'vikram@brightpath.in',      '+91 98450 11111', 'Website',  'New',       NULL, NULL, NULL, NULL, NULL, 2),
(2, 'Neha Gupta',     'UrbanNest Realty',   'neha@urbannest.in',         '+91 98450 22222', 'Referral', 'Nurturing', NULL, NULL, NULL, NULL, NULL, 3),
(3, 'Rohit Verma',    'CloudKart',          'rohit@cloudkart.in',        '+91 98450 33333', 'Event',    'Demo', NOW() + INTERVAL 3 DAY, NULL, NULL, NULL, NULL, 2),
(4, 'Pooja Joshi',    'FreshMart',          'pooja@freshmart.in',        '+91 98450 44444', 'Phone',    'Lost', NULL, 'No response', 'No reply after 3 calls and 2 emails', NULL, NOW() - INTERVAL 5 DAY, 3),
-- converted leads (each became an opportunity)
(5, 'Dr. Meera Iyer', 'Sunrise Hospitals',  'meera@sunrisehospitals.in', NULL, 'Referral', 'Converted', NULL, NULL, NULL, NOW() - INTERVAL 4 DAY,  NULL, 2),
(6, 'Arjun Mehta',    'GreenLeaf Foods',    'arjun@greenleaffoods.in',   NULL, 'Website',  'Converted', NULL, NULL, NULL, NOW() - INTERVAL 12 DAY, NULL, 3),
(7, 'Kavya Reddy',    'Apex Logistics',     'kavya@apexlogistics.in',    NULL, 'Event',    'Converted', NULL, NULL, NULL, NOW() - INTERVAL 30 DAY, NULL, 2),
(8, 'Sanjay Patel',   'Nova Textiles',      'sanjay@novatextiles.in',    NULL, 'Email',    'Converted', NULL, NULL, NULL, NOW() - INTERVAL 25 DAY, NULL, 3);

-- ---------- OPPORTUNITIES (one in every stage) ----------
INSERT INTO opportunities (id, name, stage, expected_value, final_value, expected_close_date, lost_reason, lost_notes, closed_at, account_id, primary_contact_id, lead_id, owner_id) VALUES
(1, 'Sunrise Hospitals - CRM rollout',    'Opportunity',  850000.00, NULL,      CURDATE() + INTERVAL 40 DAY, NULL, NULL, NULL, 1, 1, 5, 2),
(2, 'GreenLeaf Foods - Sales automation', 'Proposal',    1200000.00, NULL,      CURDATE() + INTERVAL 20 DAY, NULL, NULL, NULL, 2, 3, 6, 3),
(3, 'Apex Logistics - Fleet CRM',         'Won',          700000.00, 640000.00, CURDATE() - INTERVAL 3 DAY,  NULL, NULL, NOW() - INTERVAL 3 DAY, 3, 4, 7, 2),
(4, 'Nova Textiles - Dealer portal',      'Lost',         500000.00, NULL,      NULL, 'Competitor', 'Chose a cheaper local vendor', NOW() - INTERVAL 7 DAY, 4, 5, 8, 3);

-- ---------- TASKS (on leads and on opportunities) ----------
INSERT INTO tasks (title, due_date, reminder_at, status, priority, is_auto, completed_at, owner_id, lead_id, opportunity_id) VALUES
('Make first contact',           CURDATE() + INTERVAL 17 HOUR, CURDATE() + INTERVAL 16 HOUR,                    'Open',        'High',   TRUE,  NULL,                   2, 1,    NULL),
('Follow-up call',               NOW() - INTERVAL 2 DAY,  NULL,                    'Open',        'Normal', TRUE,  NULL,                   3, 2,    NULL),  -- OVERDUE
('Conduct demo',                 NOW() + INTERVAL 3 DAY,  NOW() + INTERVAL 2 DAY,  'Open',        'High',   TRUE,  NULL,                   2, 3,    NULL),
('Follow-up call',               NOW() - INTERVAL 6 DAY,  NULL,                    'Auto-closed', 'Normal', TRUE,  NOW() - INTERVAL 5 DAY, 3, 4,    NULL),
('Prepare pricing for proposal', CURDATE() + INTERVAL 15 HOUR, NULL,                    'Open',        'Normal', FALSE, NULL,                   2, NULL, 1),
('Send proposal',                NOW() - INTERVAL 5 DAY,  NULL,                    'Done',        'Normal', TRUE,  NOW() - INTERVAL 5 DAY, 3, NULL, 2),
('Follow up on proposal',        NOW() + INTERVAL 3 DAY,  NOW() + INTERVAL 2 DAY,  'Open',        'High',   TRUE,  NULL,                   3, NULL, 2),
('Follow up on proposal',        NOW() - INTERVAL 10 DAY, NULL,                    'Done',        'Normal', TRUE,  NOW() - INTERVAL 10 DAY,2, NULL, 3),
('Schedule onboarding call',     NOW() + INTERVAL 1 DAY,  NULL,                    'Auto-closed', 'Normal', FALSE, NOW() - INTERVAL 3 DAY, 2, NULL, 3),
('Follow up on proposal',        NOW() - INTERVAL 8 DAY,  NULL,                    'Auto-closed', 'Normal', TRUE,  NOW() - INTERVAL 7 DAY, 3, NULL, 4),
('Weekly pipeline review',       CURDATE() + INTERVAL 11 HOUR, NULL,           'Open',        'Normal', FALSE, NULL,                   1, NULL, NULL);  -- general task (no lead/opportunity)

-- ---------- STAGE HISTORY ----------
INSERT INTO stage_history (from_stage, to_stage, changed_at, changed_by_id, lead_id, opportunity_id) VALUES
-- lead 1: new
(NULL,        'New',        NOW() - INTERVAL 12 HOUR, 2, 1, NULL),
-- lead 2: Lead -> Nurturing
(NULL,        'New',        NOW() - INTERVAL 10 DAY, 3, 2, NULL),
('New',       'Nurturing',   NOW() - INTERVAL 8 DAY,  3, 2, NULL),
-- lead 3: Lead -> Nurturing -> Demo
(NULL,        'New',        NOW() - INTERVAL 14 DAY, 2, 3, NULL),
('New',       'Nurturing',   NOW() - INTERVAL 11 DAY, 2, 3, NULL),
('Nurturing', 'Demo',        NOW() - INTERVAL 2 DAY,  2, 3, NULL),
-- lead 4: lost early
(NULL,        'New',        NOW() - INTERVAL 20 DAY, 3, 4, NULL),
('New',       'Nurturing',   NOW() - INTERVAL 18 DAY, 3, 4, NULL),
('Nurturing', 'Lost',        NOW() - INTERVAL 5 DAY,  3, 4, NULL),
-- lead 5 -> opportunity 1
(NULL,        'New',        NOW() - INTERVAL 15 DAY, 2, 5, NULL),
('New',       'Nurturing',   NOW() - INTERVAL 12 DAY, 2, 5, NULL),
('Nurturing', 'Demo',        NOW() - INTERVAL 7 DAY,  2, 5, NULL),
('Demo',      'Converted',   NOW() - INTERVAL 4 DAY,  2, 5, NULL),
(NULL,        'Opportunity', NOW() - INTERVAL 4 DAY,  2, NULL, 1),
-- lead 6 -> opportunity 2 (Proposal)
(NULL,        'New',        NOW() - INTERVAL 25 DAY, 3, 6, NULL),
('New',       'Nurturing',   NOW() - INTERVAL 22 DAY, 3, 6, NULL),
('Nurturing', 'Demo',        NOW() - INTERVAL 16 DAY, 3, 6, NULL),
('Demo',      'Converted',   NOW() - INTERVAL 12 DAY, 3, 6, NULL),
(NULL,        'Opportunity', NOW() - INTERVAL 12 DAY, 3, NULL, 2),
('Opportunity','Proposal',   NOW() - INTERVAL 5 DAY,  3, NULL, 2),
-- lead 7 -> opportunity 3 (Won)
(NULL,        'New',        NOW() - INTERVAL 50 DAY, 2, 7, NULL),
('New',       'Nurturing',   NOW() - INTERVAL 45 DAY, 2, 7, NULL),
('Nurturing', 'Demo',        NOW() - INTERVAL 38 DAY, 2, 7, NULL),
('Demo',      'Converted',   NOW() - INTERVAL 30 DAY, 2, 7, NULL),
(NULL,        'Opportunity', NOW() - INTERVAL 30 DAY, 2, NULL, 3),
('Opportunity','Proposal',   NOW() - INTERVAL 15 DAY, 2, NULL, 3),
('Proposal',  'Won',         NOW() - INTERVAL 3 DAY,  2, NULL, 3),
-- lead 8 -> opportunity 4 (Lost)
(NULL,        'New',        NOW() - INTERVAL 40 DAY, 3, 8, NULL),
('New',       'Nurturing',   NOW() - INTERVAL 35 DAY, 3, 8, NULL),
('Nurturing', 'Demo',        NOW() - INTERVAL 30 DAY, 3, 8, NULL),
('Demo',      'Converted',   NOW() - INTERVAL 25 DAY, 3, 8, NULL),
(NULL,        'Opportunity', NOW() - INTERVAL 25 DAY, 3, NULL, 4),
('Opportunity','Proposal',   NOW() - INTERVAL 15 DAY, 3, NULL, 4),
('Proposal',  'Lost',        NOW() - INTERVAL 7 DAY,  3, NULL, 4);

-- ---------- NOTES ----------
INSERT INTO notes (body, created_by_id, lead_id, opportunity_id, created_at) VALUES
('Interested in attendance + fee tracking. Call back after 4 PM.', 2, 1, NULL, NOW() - INTERVAL 10 HOUR),
('Demo went well. Wants pricing for 200 users.',                    2, 5, NULL, NOW() - INTERVAL 7 DAY),
('Proposal sent with 10% early-signup discount.',                   3, NULL, 2, NOW() - INTERVAL 5 DAY);

-- ---------- NOTIFICATIONS (bell icon) ----------
INSERT INTO notifications (user_id, task_id, title, message, is_read, created_at) VALUES
(3, 2, 'Task overdue',   'Follow-up call with Neha Gupta was due 2 days ago', FALSE, NOW() - INTERVAL 1 DAY),
(2, 1, 'Task due today', 'Make first contact with Vikram Singh',             FALSE, NOW() - INTERVAL 1 HOUR),
(2, 5, 'Task due today', 'Prepare pricing for proposal - Sunrise Hospitals', TRUE,  NOW() - INTERVAL 2 HOUR);