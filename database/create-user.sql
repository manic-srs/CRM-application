-- =====================================================
-- Run once as the "postgres" superuser (pgAdmin Query Tool on the "postgres" database,
-- or: psql -U postgres -f database/create-user.sql)
-- Creates the app's login and the crm_db database owned by it.
-- Not needed with Docker: docker-compose.yml creates both.
-- =====================================================
CREATE ROLE crm_user WITH LOGIN PASSWORD 'crm_pass';
CREATE DATABASE crm_db OWNER crm_user ENCODING 'UTF8';
