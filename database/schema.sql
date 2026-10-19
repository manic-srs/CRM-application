-- =====================================================
-- CRM Application - Database Schema
-- Run in MySQL Workbench as root 
-- =====================================================

CREATE DATABASE IF NOT EXISTS crm_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE crm_db;

-- Drop in reverse order so the script can be re-run
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS stage_history;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS opportunities;
DROP TABLE IF EXISTS leads;
DROP TABLE IF EXISTS contacts;
DROP TABLE IF EXISTS accounts;
DROP TABLE IF EXISTS users;

-- 1. USERS: salespeople, managers, admins
CREATE TABLE users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  full_name     VARCHAR(100) NOT NULL,
  email         VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role          ENUM('Salesperson','Manager','Admin') NOT NULL DEFAULT 'Salesperson',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 2. ACCOUNTS: customer companies
CREATE TABLE accounts (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  name       VARCHAR(200) NOT NULL,
  industry   VARCHAR(100),
  phone      VARCHAR(30),
  website    VARCHAR(255),
  address    VARCHAR(500),
  owner_id   INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_accounts_name (name),
  CONSTRAINT fk_accounts_owner FOREIGN KEY (owner_id) REFERENCES users(id)
);

-- 3. CONTACTS: people at an account (contact belongs to an account)
CREATE TABLE contacts (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  salutation ENUM('Mr.','Ms.','Mrs.','Dr.','Prof.'),
  first_name VARCHAR(50),
  last_name  VARCHAR(50) NOT NULL,
  -- full_name is filled automatically from first + last name (like Salesforce)
  full_name  VARCHAR(101) GENERATED ALWAYS AS (TRIM(CONCAT_WS(' ', first_name, last_name))) STORED,
  job_title  VARCHAR(100),
  email      VARCHAR(255),
  phone      VARCHAR(30),
  account_id INT NOT NULL,
  owner_id   INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_contacts_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
  CONSTRAINT fk_contacts_owner   FOREIGN KEY (owner_id)   REFERENCES users(id)
);

-- 4. LEADS: enquiries. New -> Nurturing -> Demo -> Converted (to Opportunity) or Lost
--    Fields follow the Salesforce lead form: Salutation, First Name, Last Name (required), Company, Title, Industry
CREATE TABLE leads (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  salutation   ENUM('Mr.','Ms.','Mrs.','Dr.','Prof.'),
  first_name   VARCHAR(50),
  last_name    VARCHAR(50) NOT NULL,
  -- name is filled automatically from first + last name, so views and lists keep using "name"
  name         VARCHAR(101) GENERATED ALWAYS AS (TRIM(CONCAT_WS(' ', first_name, last_name))) STORED,
  company      VARCHAR(200),
  title        VARCHAR(100),
  industry     VARCHAR(100),
  email        VARCHAR(255),
  phone        VARCHAR(30),
  source       ENUM('Website','Referral','Phone','Email','Event','Social Media','Other') NOT NULL DEFAULT 'Other',
  stage        ENUM('New','Nurturing','Demo','Converted','Lost') NOT NULL DEFAULT 'New',
  demo_date    DATETIME,
  lost_reason  ENUM('Price','Competitor','No response','No budget','Not interested','Other'),
  lost_notes   TEXT,
  converted_at DATETIME,
  closed_at    DATETIME,
  owner_id     INT NOT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_leads_stage (stage),
  INDEX idx_leads_name (name),
  INDEX idx_leads_company (company),
  INDEX idx_leads_email (email),
  CONSTRAINT fk_leads_owner FOREIGN KEY (owner_id) REFERENCES users(id),
  -- Rule: a Lost lead must have a lost reason
  CONSTRAINT ck_leads_lost_reason CHECK (stage <> 'Lost' OR lost_reason IS NOT NULL)
);

-- 5. OPPORTUNITIES: serious deals (opportunity belongs to an account)
--    Opportunity -> Proposal -> Won / Lost
CREATE TABLE opportunities (
  id                  INT AUTO_INCREMENT PRIMARY KEY,
  name                VARCHAR(200) NOT NULL,
  stage               ENUM('Opportunity','Proposal','Won','Lost') NOT NULL DEFAULT 'Opportunity',
  expected_value      DECIMAL(14,2),
  final_value         DECIMAL(14,2),
  expected_close_date DATE,
  probability         TINYINT UNSIGNED NOT NULL DEFAULT 20,  -- % chance to win: Opportunity 20, Proposal 75, Won 100, Lost 0
  lost_reason         ENUM('Price','Competitor','No response','No budget','Not interested','Other'),
  lost_notes          TEXT,
  closed_at           DATETIME,
  account_id          INT NOT NULL,
  primary_contact_id  INT,
  lead_id             INT UNIQUE,          -- the lead it was converted from
  owner_id            INT NOT NULL,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_opps_stage (stage),
  INDEX idx_opps_name (name),
  CONSTRAINT fk_opps_account FOREIGN KEY (account_id)         REFERENCES accounts(id),
  CONSTRAINT fk_opps_contact FOREIGN KEY (primary_contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
  CONSTRAINT fk_opps_lead    FOREIGN KEY (lead_id)            REFERENCES leads(id)    ON DELETE SET NULL,
  CONSTRAINT fk_opps_owner   FOREIGN KEY (owner_id)           REFERENCES users(id),
  -- Rules: Lost needs a reason, Won needs a final value
  CONSTRAINT ck_opps_lost_reason CHECK (stage <> 'Lost' OR lost_reason IS NOT NULL),
  CONSTRAINT ck_opps_won_value   CHECK (stage <> 'Won'  OR final_value IS NOT NULL)
);

-- 6. TASKS: follow-ups. Linked to a lead OR an opportunity, or to neither (general task from "Add task")
CREATE TABLE tasks (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  title          VARCHAR(200) NOT NULL,
  description    TEXT,
  due_date       DATETIME NOT NULL,
  reminder_at    DATETIME,
  reminder_sent  BOOLEAN NOT NULL DEFAULT FALSE,
  status         ENUM('Open','Done','Auto-closed') NOT NULL DEFAULT 'Open',
  priority       ENUM('Low','Normal','High') NOT NULL DEFAULT 'Normal',
  is_auto        BOOLEAN NOT NULL DEFAULT FALSE,   -- created by the system
  completed_at   DATETIME,
  owner_id       INT NOT NULL,
  lead_id        INT,
  opportunity_id INT,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_tasks_due (due_date),
  INDEX idx_tasks_status (status),
  INDEX idx_tasks_owner_due (owner_id, status, due_date),   -- "Today's tasks" for one user
  CONSTRAINT fk_tasks_owner FOREIGN KEY (owner_id)       REFERENCES users(id),
  CONSTRAINT fk_tasks_lead  FOREIGN KEY (lead_id)        REFERENCES leads(id),
  CONSTRAINT fk_tasks_opp   FOREIGN KEY (opportunity_id) REFERENCES opportunities(id),
  CONSTRAINT ck_tasks_parent CHECK (lead_id IS NULL OR opportunity_id IS NULL)   -- never both
);

-- 7. STAGE_HISTORY: every stage change, who and when
CREATE TABLE stage_history (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  from_stage     VARCHAR(30),                -- NULL when the record is created
  to_stage       VARCHAR(30) NOT NULL,
  note           TEXT,
  changed_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  changed_by_id  INT NOT NULL,
  lead_id        INT,
  opportunity_id INT,
  INDEX idx_history_changed_at (changed_at),
  CONSTRAINT fk_history_user FOREIGN KEY (changed_by_id)  REFERENCES users(id),
  CONSTRAINT fk_history_lead FOREIGN KEY (lead_id)        REFERENCES leads(id),
  CONSTRAINT fk_history_opp  FOREIGN KEY (opportunity_id) REFERENCES opportunities(id),
  CONSTRAINT ck_history_parent CHECK ((lead_id IS NULL) <> (opportunity_id IS NULL))
);

-- 8. NOTES: call/demo notes on a lead OR an opportunity
CREATE TABLE notes (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  body           TEXT NOT NULL,
  created_by_id  INT NOT NULL,
  lead_id        INT,
  opportunity_id INT,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_notes_user FOREIGN KEY (created_by_id)  REFERENCES users(id),
  CONSTRAINT fk_notes_lead FOREIGN KEY (lead_id)        REFERENCES leads(id),
  CONSTRAINT fk_notes_opp  FOREIGN KEY (opportunity_id) REFERENCES opportunities(id),
  CONSTRAINT ck_notes_parent CHECK ((lead_id IS NULL) <> (opportunity_id IS NULL))
);

-- 9. NOTIFICATIONS: the bell icon (task reminders, overdue alerts)
CREATE TABLE notifications (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT NOT NULL,
  task_id    INT,
  title      VARCHAR(200) NOT NULL,
  message    VARCHAR(500),
  is_read    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_notif_user_unread (user_id, is_read),
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_notif_task FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);