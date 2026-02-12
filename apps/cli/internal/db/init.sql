-- Initialization script for SQLite database
-- This file is automatically executed when the database is first created

-- 0. THE PROTOCOL TABLE
-- Represents a protocol definition with commands and metadata.
CREATE TABLE IF NOT EXISTS protocol (
    protocol_id TEXT PRIMARY KEY,
    user_id TEXT,
    username TEXT,
    description TEXT,
    commands TEXT, -- JSON array of command requests
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 1. THE RUN TABLE (when protocols are executed, they create runs)
CREATE TABLE IF NOT EXISTS run (
    run_id TEXT PRIMARY KEY,
    protocol_id TEXT REFERENCES protocol(protocol_id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. THE SAMPLE TABLE (when runs are executed, they create samples)
CREATE TABLE IF NOT EXISTS sample (
    sample_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES run(run_id) ON DELETE CASCADE,
    data_payload TEXT, -- JSON object
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. THE MEASUREMENT TABLE
-- A sample can have multiple measurements.
-- Each measurement records a property (what is being measured) and the method used to measure it.
CREATE TABLE IF NOT EXISTS measurement (
    measurement_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES sample(sample_id) ON DELETE CASCADE,
    data_payload TEXT, -- JSON object
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. THE COMMAND_LOG TABLE
-- Logs all command responses received from machines via NATS
CREATE TABLE IF NOT EXISTS command_log (
    command_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES run(run_id) ON DELETE CASCADE,
    step_number INTEGER,
    command_name TEXT,
    payload TEXT NOT NULL, -- JSON object
    machine_id TEXT,
    command_type TEXT CHECK (command_type IN ('queue', 'immediate')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_command_log_machine_id ON command_log(machine_id);
CREATE INDEX IF NOT EXISTS idx_command_log_run_id ON command_log(run_id);
CREATE INDEX IF NOT EXISTS idx_command_log_step_number ON command_log(step_number);
CREATE INDEX IF NOT EXISTS idx_command_log_created_at ON command_log(created_at);
