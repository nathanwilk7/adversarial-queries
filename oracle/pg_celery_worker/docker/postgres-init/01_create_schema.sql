-- ============================================================================
-- BayesQO PostgreSQL Job Queue Schema
-- ============================================================================
--
-- INSTRUCTIONS:
-- This file contains the database schema for the BayesQO job queue system.
-- When you start the PostgreSQL container for the first time, this file will
-- be executed automatically to set up the required tables.
--
-- USER ACTION REQUIRED:
-- Replace the contents of this file with your production schema export.
-- You can export your production schema using:
--
--   pg_dump -h pg.rm.cab -U bayesopt -d bayesopt --schema-only > 01_create_schema.sql
--
-- Then paste the contents here and restart the PostgreSQL container.
--
-- ============================================================================

-- The schema below is a minimal example for local development.
-- Replace this with your production schema export.

-- Drop existing tables if they exist (for development/testing)
DROP TABLE IF EXISTS query_connected_tables CASCADE;
DROP TABLE IF EXISTS predicate_values CASCADE;
DROP TABLE IF EXISTS template_jobs CASCADE;
DROP TYPE IF EXISTS job_status CASCADE;

-- Job status enumeration
CREATE TYPE job_status AS ENUM ('issued', 'in-progress', 'complete');

-- Main job queue table
-- This table stores all query execution jobs submitted to the system
CREATE TABLE template_jobs (
    id BIGSERIAL PRIMARY KEY,
    request JSONB NOT NULL,                    -- Pydantic RequestType serialized as JSON
    status job_status NOT NULL DEFAULT 'issued',
    issued_at TIMESTAMP NOT NULL DEFAULT NOW(),
    schema TEXT NOT NULL DEFAULT 'JOB',        -- 'JOB' (IMDB) or 'SQLStorm' (StackOverflow)
    taken_by TEXT,                              -- Worker hostname that claimed this job
    taken_at TIMESTAMP,
    result JSONB,                               -- Pydantic ResponseType serialized as JSON
    finished_at TIMESTAMP
);

-- Index for efficient job polling by workers
CREATE INDEX idx_template_jobs_status_issued ON template_jobs(issued_at) WHERE taken_by IS NULL;
CREATE INDEX idx_template_jobs_worker ON template_jobs(taken_by, status) WHERE status = 'in-progress';

-- Predicate values cache table
-- Caches resolved predicate values for adversarial query generation
CREATE TABLE predicate_values (
    schema TEXT NOT NULL,                      -- 'JOB' or 'SQLStorm'
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    predicate_name TEXT NOT NULL,              -- e.g., 'first', 'median', 'last', 'mode', 'most_popular'
    predicate_value TEXT NOT NULL,             -- The actual resolved value
    PRIMARY KEY (schema, table_name, column_name, predicate_name)
);

-- Query connected tables cache
-- Caches the Steiner tree results for join resolution
CREATE TABLE query_connected_tables (
    schema TEXT NOT NULL,                      -- 'JOB' or 'SQLStorm'
    input_tables TEXT[] NOT NULL,              -- Sorted array of input table names
    connected_tables TEXT[] NOT NULL,          -- Steiner tree result
    PRIMARY KEY (schema, input_tables)
);

-- ============================================================================
-- PostgreSQL LISTEN/NOTIFY Setup
-- ============================================================================
-- The system uses NOTIFY/LISTEN for real-time job notifications.
-- Workers will execute:
--   LISTEN new_job    -- To be notified when new jobs are submitted
--   LISTEN job_complete -- To be notified when jobs finish
--
-- No additional setup needed here - workers handle this in their connections.
-- ============================================================================
