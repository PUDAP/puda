-- Initialization script for PostgreSQL database
-- This file is automatically executed when the database is first created

-- Enable UUID extension for gen_random_uuid() function
-- Note: PostgreSQL 13+ has gen_random_uuid() built-in, but enabling pgcrypto ensures compatibility
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. THE RUN TABLE
-- Represents the "Batch" or high-level project.
CREATE TABLE run (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT, -- "Higher level description of sample, measurement"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. THE SAMPLE TABLE
-- A run can have multiple samples.
CREATE TABLE sample (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    substrate_info TEXT,
    composition_info TEXT,
    pretreatment_info TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign Key linking to Run
    CONSTRAINT fk_run
      FOREIGN KEY(run_id) 
      REFERENCES run(run_id)
      ON DELETE CASCADE
);

-- 3. THE MEASUREMENT TABLE
-- A sample can have multiple measurements.
-- Each measurement records a property (what is being measured) and the method used to measure it.
CREATE TABLE measurement (
    measurement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL,
    
    -- The property being measured (e.g., electrical conductivity, flow rate, composition)
    -- Example values: 'Electrical Conductivity', 'Flow Rate', 'Composition', 'Crystal Structure', 'Surface Morphology'
    property VARCHAR(50) NOT NULL,
    
    -- The measurement technique or instrument used
    -- Example values: 'EC', 'MFC', 'GCMS', 'XRD', 'SEM', 'FTIR'
    technique VARCHAR(50) NOT NULL,
    
    -- Optional numeric value for simple measurements or aggregated results.
    -- Use this when the measurement can be represented as a single number (e.g., average flow rate, peak value).
    value_numeric DECIMAL(10, 4),
    
    -- The unit of the measurement
    -- Example values: 'S/cm', 'mL/min', 'wt%', 'nm', 'μm'
    unit VARCHAR(50),
    
    -- Flexible column to store raw measurement data in JSON format.
    -- Useful for complex measurements with varying structures (e.g., spectra, time series, multi-dimensional data).
    -- PostgreSQL JSONB provides efficient storage and querying of structured data.
    data_payload JSONB, 
    
    -- Timestamp when the measurement was taken
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Foreign Key linking to Sample
    CONSTRAINT fk_sample
      FOREIGN KEY(sample_id) 
      REFERENCES sample(sample_id)
      ON DELETE CASCADE
);