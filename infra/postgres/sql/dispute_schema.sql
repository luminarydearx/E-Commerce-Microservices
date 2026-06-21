CREATE SCHEMA IF NOT EXISTS dispute;

CREATE TABLE IF NOT EXISTS dispute.disputes (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL,
    order_item_id UUID,
    buyer_id UUID NOT NULL,
    seller_id UUID NOT NULL,
    reason VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    evidence_files JSONB,
    requested_refund_amount INTEGER NOT NULL,
    approved_refund_amount INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    resolution VARCHAR(20),
    resolution_note TEXT,
    seller_response TEXT,
    seller_response_at TIMESTAMPTZ,
    buyer_escalated BOOLEAN NOT NULL DEFAULT FALSE,
    escalated_at TIMESTAMPTZ,
    resolved_by UUID,
    resolved_at TIMESTAMPTZ,
    seller_response_deadline TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_dispute_status CHECK (status IN ('OPEN', 'SELLER_RESPONDED', 'ESCALATED', 'RESOLVED', 'REJECTED', 'CANCELLED')),
    CONSTRAINT chk_dispute_reason CHECK (reason IN ('ITEM_NOT_AS_DESCRIBED', 'DAMAGED', 'NOT_RECEIVED', 'WRONG_ITEM', 'OTHER'))
);
CREATE INDEX IF NOT EXISTS idx_disputes_buyer ON dispute.disputes(buyer_id, status);
CREATE INDEX IF NOT EXISTS idx_disputes_seller ON dispute.disputes(seller_id, status);
CREATE INDEX IF NOT EXISTS idx_disputes_order ON dispute.disputes(order_id);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON dispute.disputes(status, created_at);

CREATE TABLE IF NOT EXISTS dispute.dispute_messages (
    id UUID PRIMARY KEY,
    dispute_id UUID NOT NULL REFERENCES dispute.disputes(id) ON DELETE CASCADE,
    sender_id UUID NOT NULL,
    sender_role VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    attachments JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dispute_messages_dispute ON dispute.dispute_messages(dispute_id, created_at);
