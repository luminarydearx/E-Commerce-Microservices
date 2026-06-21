CREATE SCHEMA IF NOT EXISTS fraud;

CREATE TABLE IF NOT EXISTS fraud.fraud_flags (
    id UUID PRIMARY KEY,
    user_id UUID,
    ip_address INET,
    device_id VARCHAR(255),
    rule_name VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'warning',
    score FLOAT NOT NULL DEFAULT 0,
    description TEXT NOT NULL,
    context JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    action_taken VARCHAR(50),
    resolved_at TIMESTAMPTZ,
    resolved_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ff_user ON fraud.fraud_flags(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ff_status ON fraud.fraud_flags(status, created_at DESC);

CREATE TABLE IF NOT EXISTS fraud.blocked_ips (
    id UUID PRIMARY KEY,
    ip_address INET UNIQUE NOT NULL,
    reason VARCHAR(200),
    blocked_until TIMESTAMPTZ,
    blocked_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bi_ip ON fraud.blocked_ips(ip_address);

CREATE TABLE IF NOT EXISTS fraud.blocked_users (
    id UUID PRIMARY KEY,
    user_id UUID UNIQUE NOT NULL,
    reason VARCHAR(200),
    blocked_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
