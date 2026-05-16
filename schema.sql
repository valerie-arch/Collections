-- Wahu Collections Reconciliation — Postgres DDL Schema
-- Sprint 0 MVP

CREATE TYPE user_role AS ENUM (
  'Finance Officer',
  'Collections Lead',
  'Collections Analyst',
  'Ops Analyst',
  'Recovery Officer',
  'Admin'
);

CREATE TYPE fleet_type AS ENUM ('Wahu', 'TSA');

CREATE TYPE rider_status_enum AS ENUM ('active', 'paused', 'completed', 'churned');

CREATE TYPE payment_channel AS ENUM ('mtn', 'telecel', 'hero', 'bolt_deduction', 'suspense');

CREATE TYPE run_status AS ENUM ('queued', 'running', 'succeeded', 'failed');

CREATE TYPE step_status AS ENUM ('pending', 'running', 'succeeded', 'failed');

CREATE TYPE exception_severity AS ENUM ('info', 'warning', 'error', 'critical');

CREATE TYPE exception_status_enum AS ENUM ('open', 'resolved', 'escalated');

CREATE TYPE signoff_status AS ENUM ('pending', 'approved', 'rejected');

-- Users & RBAC
CREATE TABLE users (
  user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  google_id VARCHAR(255),
  first_name VARCHAR(100),
  last_name VARCHAR(100),
  role user_role NOT NULL,
  fleet_context fleet_type DEFAULT 'Wahu',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_google_id ON users(google_id);

-- Run Orchestration (Step 1-12)
CREATE TABLE runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_date DATE NOT NULL,
  trigger_step INT NOT NULL CHECK (trigger_step BETWEEN 1 AND 12),
  status run_status DEFAULT 'queued',
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_runs_date ON runs(run_date);
CREATE INDEX idx_runs_step ON runs(trigger_step);
CREATE INDEX idx_runs_status ON runs(status);

-- Step Results
CREATE TABLE step_results (
  result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  step INT NOT NULL CHECK (step BETWEEN 1 AND 12),
  status step_status DEFAULT 'pending',
  output_path VARCHAR(512),
  exception_count INT DEFAULT 0,
  warning_count INT DEFAULT 0,
  row_count INT DEFAULT 0,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  duration_ms INT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_step_results_run ON step_results(run_id);
CREATE INDEX idx_step_results_step ON step_results(step);

-- Exceptions
CREATE TABLE exceptions (
  exception_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  step INT NOT NULL,
  severity exception_severity NOT NULL,
  status exception_status_enum DEFAULT 'open',
  error_code VARCHAR(50),
  message TEXT NOT NULL,
  context JSONB,
  assigned_to UUID REFERENCES users(user_id),
  resolved_at TIMESTAMP,
  resolution_note TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_exceptions_run ON exceptions(run_id);
CREATE INDEX idx_exceptions_severity ON exceptions(severity);
CREATE INDEX idx_exceptions_status ON exceptions(status);

-- Sign-offs (Four-eyes principle)
CREATE TABLE signoffs (
  signoff_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  step INT NOT NULL,
  signed_by UUID NOT NULL REFERENCES users(user_id),
  approval_status signoff_status DEFAULT 'approved',
  approval_note TEXT,
  signed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_signoffs_run ON signoffs(run_id);

-- Suspense Ledger
CREATE TABLE suspense_items (
  suspense_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_date DATE NOT NULL,
  channel payment_channel NOT NULL,
  channel_reference VARCHAR(255) UNIQUE,
  amount_ghs DECIMAL(10, 2) NOT NULL,
  msisdn VARCHAR(20),
  received_at TIMESTAMP,
  status exception_status_enum DEFAULT 'open',
  rider_id VARCHAR(50),
  invoice_id VARCHAR(100),
  cleared_by UUID REFERENCES users(user_id),
  cleared_at TIMESTAMP,
  clearance_note TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_suspense_status ON suspense_items(status);
CREATE INDEX idx_suspense_msisdn ON suspense_items(msisdn);
CREATE INDEX idx_suspense_channel_ref ON suspense_items(channel_reference);

-- Payment Application Log (idempotency key per Step 4)
CREATE TABLE payment_application_log (
  log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_date DATE NOT NULL,
  channel_txn_id VARCHAR(255) NOT NULL,
  channel payment_channel NOT NULL,
  rider_id VARCHAR(50) NOT NULL,
  invoice_id VARCHAR(100),
  amount_applied_ghs DECIMAL(10, 2) NOT NULL,
  applied_at TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(channel_txn_id)
);

CREATE INDEX idx_payment_log_rider ON payment_application_log(rider_id);
CREATE INDEX idx_payment_log_invoice ON payment_application_log(invoice_id);

-- Zoho ↔ QB Mapping
CREATE TABLE zoho_qb_invoice_map (
  mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  zoho_invoice_id VARCHAR(100) NOT NULL,
  qb_invoice_id VARCHAR(100),
  rider_id VARCHAR(50) NOT NULL,
  fleet fleet_type NOT NULL,
  mapped_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(zoho_invoice_id)
);

CREATE TABLE zoho_qb_payment_map (
  mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  zoho_payment_id VARCHAR(100) NOT NULL,
  qb_payment_id VARCHAR(100),
  rider_id VARCHAR(50) NOT NULL,
  channel payment_channel NOT NULL,
  fleet fleet_type NOT NULL,
  mapped_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(zoho_payment_id)
);

-- Completion Events (feeds Report C)
CREATE TABLE completion_events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscription_id VARCHAR(100) NOT NULL,
  rider_id VARCHAR(50) NOT NULL,
  customer_id VARCHAR(100),
  completion_date DATE NOT NULL,
  total_weeks_billed INT NOT NULL,
  total_amount_paid_ghs DECIMAL(12, 2) NOT NULL,
  signed_off_by UUID REFERENCES users(user_id),
  certificate_issued_date DATE,
  certificate_path VARCHAR(512),
  fleet fleet_type NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_completion_rider ON completion_events(rider_id);
CREATE INDEX idx_completion_date ON completion_events(completion_date);

-- MTD Rankings (Step 9 output snapshot)
CREATE TABLE mtd_rankings (
  ranking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_date DATE NOT NULL,
  rider_id VARCHAR(50) NOT NULL,
  subscription_id VARCHAR(100),
  fleet fleet_type NOT NULL,
  composite_score DECIMAL(5, 2),
  paid_factor DECIMAL(5, 2),
  on_time_factor DECIMAL(5, 2),
  retention_factor DECIMAL(5, 2),
  outstandings_factor DECIMAL(5, 2),
  band VARCHAR(20),
  rank INT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_mtd_date ON mtd_rankings(report_date);
CREATE INDEX idx_mtd_rider ON mtd_rankings(rider_id);

-- SMS Opt-outs
CREATE TABLE sms_optouts (
  optout_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id VARCHAR(50),
  msisdn VARCHAR(20) NOT NULL,
  opted_out_at TIMESTAMP DEFAULT NOW(),
  opt_in_at TIMESTAMP
);

CREATE INDEX idx_sms_optout_msisdn ON sms_optouts(msisdn);
CREATE INDEX idx_sms_optout_rider ON sms_optouts(rider_id);

-- SMS Log (Step 10)
CREATE TABLE sms_logs (
  log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_date DATE NOT NULL,
  rider_id VARCHAR(50) NOT NULL,
  msisdn VARCHAR(20),
  template_version VARCHAR(50),
  message_text TEXT,
  gateway_reference VARCHAR(100),
  send_status VARCHAR(20),
  delivered_at TIMESTAMP,
  failed_reason TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sms_log_rider ON sms_logs(rider_id);
CREATE INDEX idx_sms_log_date ON sms_logs(run_date);

-- Audit Log
CREATE TABLE audit_log (
  log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(user_id),
  action VARCHAR(255) NOT NULL,
  resource_type VARCHAR(100),
  resource_id VARCHAR(255),
  changes JSONB,
  timestamp TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_user ON audit_log(user_id);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
