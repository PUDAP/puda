-- Initialization script for PostgreSQL database
-- This file is automatically executed when the database is first created

-- Enable UUID extension for gen_random_uuid() function
-- Note: PostgreSQL 13+ has gen_random_uuid() built-in, but enabling pgcrypto ensures compatibility
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- 0. THE MACHINE TABLE
CREATE TABLE machine (
    machine_id VARCHAR(50) PRIMARY KEY,
    machine_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 1. THE RUN TABLE
-- Represents the "Batch" or high-level project.
CREATE TABLE run (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id VARCHAR(50) REFERENCES machine(machine_id) ON DELETE CASCADE,
    description TEXT, -- "Higher level description of sample, measurement"
    data_payload JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. THE SAMPLE TABLE
-- A run can have multiple samples.
CREATE TABLE sample (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES run(run_id) ON DELETE CASCADE,
    data_payload JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. THE MEASUREMENT TABLE
-- A sample can have multiple measurements.
-- Each measurement records a property (what is being measured) and the method used to measure it.
CREATE TABLE measurement (
    measurement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID REFERENCES sample(sample_id) ON DELETE CASCADE,
    data_payload JSONB, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. THE COMMAND_LOG TABLE
-- Logs all command responses received from machines via NATS
CREATE TABLE command_log (
    command_log_id SERIAL PRIMARY KEY,
    run_id UUID, -- update to reference run table
    step_number INTEGER,
    payload JSONB NOT NULL,
    machine_id VARCHAR(50) REFERENCES machine(machine_id) ON DELETE CASCADE,
    command_type VARCHAR(100) CHECK (command_type IN ('queue', 'immediate')),
    created_at TIMESTAMP NOT NULL
);

-- Create indexes for efficient querying
CREATE INDEX idx_command_log_machine_id ON command_log(machine_id);
CREATE INDEX idx_command_log_run_id ON command_log(run_id);
CREATE INDEX idx_command_log_step_number ON command_log(step_number);
CREATE INDEX idx_command_log_created_at ON command_log(created_at);