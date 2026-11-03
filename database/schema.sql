-- =========================================================================
-- MediExplain Database Schema (PostgreSQL)
-- =========================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Users Table
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Documents Table (Uploaded Files)
CREATE TABLE lab_documents (
    document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_type VARCHAR(20) NOT NULL, -- 'pdf', 'png', 'jpg'
    raw_ocr_text TEXT,
    upload_status VARCHAR(50) DEFAULT 'processed', -- 'pending', 'processed', 'failed'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Extracted Metrics Table (Parsed Key-Value Pairs)
CREATE TABLE lab_metrics (
    metric_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES lab_documents(document_id) ON DELETE CASCADE,
    marker_name VARCHAR(100) NOT NULL,  -- e.g., "Hemoglobin", "WBC"
    measured_value NUMERIC(10, 2) NOT NULL,
    reference_range_min NUMERIC(10, 2),
    reference_range_max NUMERIC(10, 2),
    unit VARCHAR(30),                    -- e.g., "g/dL", "10^3/uL"
    status_flag VARCHAR(20)              -- 'NORMAL', 'HIGH', 'LOW', 'CRITICAL'
);

-- 4. Explanations & Summaries Table
CREATE TABLE explanation_reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES lab_documents(document_id) ON DELETE CASCADE,
    plain_text_summary TEXT NOT NULL,
    generated_questions JSONB,          -- List of questions for the doctor
    disclaimer_accepted BOOLEAN DEFAULT TRUE,
    model_version VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
