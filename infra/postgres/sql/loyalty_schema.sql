CREATE SCHEMA IF NOT EXISTS loyalty;

CREATE TABLE IF NOT EXISTS loyalty.members (
    user_id UUID PRIMARY KEY,
    tier VARCHAR(20) NOT NULL DEFAULT 'SILVER',
    points_balance INTEGER NOT NULL DEFAULT 0,
    lifetime_points INTEGER NOT NULL DEFAULT 0,
    cashback_balance INTEGER NOT NULL DEFAULT 0,
    tier_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_tier CHECK (tier IN ('SILVER', 'GOLD', 'PLATINUM', 'DIAMOND'))
);

CREATE TABLE IF NOT EXISTS loyalty.point_transactions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    type VARCHAR(20) NOT NULL,
    points INTEGER NOT NULL,
    reason VARCHAR(100) NOT NULL,
    reference_id VARCHAR(64),
    balance_after INTEGER NOT NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_pt_type CHECK (type IN ('EARN', 'REDEEM', 'EXPIRE', 'ADJUST'))
);
CREATE INDEX IF NOT EXISTS idx_pt_user ON loyalty.point_transactions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS loyalty.rewards (
    id UUID PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    type VARCHAR(20) NOT NULL,
    points_cost INTEGER NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    min_tier VARCHAR(20) NOT NULL DEFAULT 'SILVER',
    stock INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS loyalty.reward_redemptions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    reward_id UUID NOT NULL,
    points_spent INTEGER NOT NULL,
    voucher_code VARCHAR(50) UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ISSUED',
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rr_user ON loyalty.reward_redemptions(user_id);
