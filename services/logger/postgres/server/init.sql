-- Initialization script for PostgreSQL database
-- This file is automatically executed when the database is first created

-- 1. THE RUN TABLE
CREATE TABLE IF NOT EXISTS run (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. THE COMMAND_LOG TABLE
-- Logs all command responses received from machines via NATS
CREATE TABLE IF NOT EXISTS command_log (
    command_log_id SERIAL PRIMARY KEY,
    run_id TEXT REFERENCES run(run_id) ON DELETE CASCADE,
    step_number INTEGER,
    command_name TEXT,
    payload JSONB,
    machine_id TEXT,
    command_type TEXT CHECK (command_type IN ('queue', 'immediate')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_command_log_machine_id ON command_log(machine_id);
CREATE INDEX IF NOT EXISTS idx_command_log_run_id ON command_log(run_id);
CREATE INDEX IF NOT EXISTS idx_command_log_step_number ON command_log(step_number);
CREATE INDEX IF NOT EXISTS idx_command_log_created_at ON command_log(created_at);
