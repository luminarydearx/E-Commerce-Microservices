-- Audit Service schema (immutable audit log + error tracking)
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.audit_log (
    audit_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    producer VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    actor_user_id VARCHAR(64),
    actor_role VARCHAR(50),
    actor_ip INET,
    actor_user_agent TEXT,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(64),
    before JSONB,
    after JSONB,
    correlation_id VARCHAR(64),
    request_id VARCHAR(64),
    prev_hash CHAR(64),
    row_hash CHAR(64) NOT NULL,
    event_id VARCHAR(64) UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit.audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit.audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_producer ON audit.audit_log(producer);
CREATE INDEX IF NOT EXISTS idx_audit_actor_user ON audit.audit_log(actor_user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit.audit_log(resource_type, resource_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit.audit_log(correlation_id);

CREATE TABLE IF NOT EXISTS audit.error_log (
    error_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    service VARCHAR(50) NOT NULL,
    environment VARCHAR(20) NOT NULL,
    level VARCHAR(20) NOT NULL,
    error_type VARCHAR(200),
    message TEXT NOT NULL,
    stack_trace TEXT,
    context JSONB,
    request_id VARCHAR(64),
    correlation_id VARCHAR(64),
    user_id VARCHAR(64),
    fingerprint CHAR(32) NOT NULL,
    pii_redacted BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_error_timestamp ON audit.error_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_error_service ON audit.error_log(service, timestamp);
CREATE INDEX IF NOT EXISTS idx_error_fingerprint ON audit.error_log(fingerprint, timestamp);
CREATE INDEX IF NOT EXISTS idx_error_level ON audit.error_log(level, timestamp);
CREATE INDEX IF NOT EXISTS idx_error_correlation ON audit.error_log(correlation_id);

CREATE TABLE IF NOT EXISTS audit.anomaly_alerts (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rule_name VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    description TEXT NOT NULL,
    actor_user_id VARCHAR(64),
    actor_ip INET,
    evidence JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(64),
    CONSTRAINT chk_severity CHECK (severity IN ('info', 'warning', 'critical')),
    CONSTRAINT chk_alert_status CHECK (status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'FALSE_POSITIVE'))
);
CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON audit.anomaly_alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_anomaly_status ON audit.anomaly_alerts(status);
CREATE INDEX IF NOT EXISTS idx_anomaly_rule ON audit.anomaly_alerts(rule_name, timestamp);

-- Retention policy: 7 years for audit_log (compliance)
-- Implement via pg_partman or cron job
ALTER TABLE audit.audit_log SET (fillfactor = 90);  -- Optimize for append-only

-- Function to verify hash chain integrity
CREATE OR REPLACE FUNCTION audit.verify_chain(start_ts TIMESTAMPTZ, end_ts TIMESTAMPTZ)
RETURNS TABLE(total INTEGER, broken INTEGER) AS $$
DECLARE
    rec RECORD;
    prev VARCHAR(64) := NULL;
    cnt INTEGER := 0;
    brk INTEGER := 0;
BEGIN
    FOR rec IN
        SELECT audit_id, prev_hash, row_hash
        FROM audit.audit_log
        WHERE timestamp >= start_ts AND timestamp <= end_ts
        ORDER BY timestamp ASC, audit_id ASC
    LOOP
        cnt := cnt + 1;
        IF rec.prev_hash IS DISTINCT FROM prev THEN
            brk := brk + 1;
        END IF;
        prev := rec.row_hash;
    END LOOP;
    RETURN QUERY SELECT cnt, brk;
END;
$$ LANGUAGE plpgsql;
