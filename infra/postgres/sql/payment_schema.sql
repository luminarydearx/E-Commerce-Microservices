-- Payment Service schema
CREATE SCHEMA IF NOT EXISTS payment_svc;

CREATE TABLE IF NOT EXISTS payment_svc.payments (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL,
    user_id UUID NOT NULL,
    amount DECIMAL(19, 2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'IDR',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    method VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    provider_tx_id VARCHAR(255),
    provider_response TEXT,
    failure_reason TEXT,
    idempotency_key VARCHAR(64) UNIQUE,
    refunded_amount DECIMAL(19, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_payment_status CHECK (
        status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'REFUNDED', 'PARTIAL_REFUND')
    ),
    CONSTRAINT chk_refunded_amount CHECK (refunded_amount >= 0 AND refunded_amount <= amount)
);
CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payment_svc.payments(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payment_svc.payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payment_svc.payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_idempotency ON payment_svc.payments(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS payment_svc.refunds (
    id UUID PRIMARY KEY,
    payment_id UUID NOT NULL REFERENCES payment_svc.payments(id) ON DELETE RESTRICT,
    amount DECIMAL(19, 2) NOT NULL CHECK (amount > 0),
    reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    provider_ref_id VARCHAR(255),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_refund_status CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED'))
);
CREATE INDEX IF NOT EXISTS idx_refunds_payment_id ON payment_svc.refunds(payment_id);
CREATE INDEX IF NOT EXISTS idx_refunds_status ON payment_svc.refunds(status);

CREATE TABLE IF NOT EXISTS payment_svc.withdrawals (
    id UUID PRIMARY KEY,
    seller_id UUID NOT NULL,
    amount DECIMAL(19, 2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'IDR',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    bank_account VARCHAR(50) NOT NULL,
    bank_code VARCHAR(20) NOT NULL,
    account_holder VARCHAR(255) NOT NULL,
    provider_ref_id VARCHAR(255),
    notes TEXT,
    processed_by UUID,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_withdrawal_status CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'PAID', 'FAILED')
    )
);
CREATE INDEX IF NOT EXISTS idx_withdrawals_seller_id ON payment_svc.withdrawals(seller_id);
CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON payment_svc.withdrawals(status);
