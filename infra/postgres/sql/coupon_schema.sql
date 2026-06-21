-- Coupon schema
CREATE SCHEMA IF NOT EXISTS coupon;

CREATE TABLE IF NOT EXISTS coupon.coupons (
    id UUID PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    discount_type VARCHAR(20) NOT NULL,
    discount_value INTEGER NOT NULL,
    max_discount INTEGER,
    min_purchase INTEGER NOT NULL DEFAULT 0,
    max_usage_global INTEGER NOT NULL DEFAULT 1,
    max_usage_per_user INTEGER NOT NULL DEFAULT 1,
    max_usage_global_count INTEGER NOT NULL DEFAULT 0,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    applicable_scope VARCHAR(20) NOT NULL DEFAULT 'ALL',
    applicable_ids JSONB,
    user_specific BOOLEAN NOT NULL DEFAULT FALSE,
    user_ids JSONB,
    is_stackable BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_discount_type CHECK (discount_type IN ('PERCENTAGE', 'FIXED', 'FREE_SHIPPING')),
    CONSTRAINT chk_scope CHECK (applicable_scope IN ('ALL', 'CATEGORY', 'PRODUCT', 'SELLER')),
    CONSTRAINT chk_dates CHECK (end_at > start_at)
);
CREATE INDEX IF NOT EXISTS idx_coupons_code ON coupon.coupons(code);
CREATE INDEX IF NOT EXISTS idx_coupons_active ON coupon.coupons(is_active, start_at, end_at);

CREATE TABLE IF NOT EXISTS coupon.coupon_redemptions (
    id UUID PRIMARY KEY,
    coupon_id UUID NOT NULL REFERENCES coupon.coupons(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    order_id UUID NOT NULL UNIQUE,
    discount_amount INTEGER NOT NULL,
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_redemptions_coupon ON coupon.coupon_redemptions(coupon_id);
CREATE INDEX IF NOT EXISTS idx_redemptions_user ON coupon.coupon_redemptions(user_id);
CREATE INDEX IF NOT EXISTS idx_redemptions_order ON coupon.coupon_redemptions(order_id);
