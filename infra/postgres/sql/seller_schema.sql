CREATE SCHEMA IF NOT EXISTS seller;

CREATE TABLE IF NOT EXISTS seller.seller_profiles (
    user_id UUID PRIMARY KEY,
    store_name VARCHAR(200) NOT NULL,
    store_slug VARCHAR(200) UNIQUE NOT NULL,
    description TEXT,
    logo_url VARCHAR(500),
    banner_url VARCHAR(500),
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ktp_number VARCHAR(50),
    npwp_number VARCHAR(50),
    bank_account VARCHAR(50),
    bank_code VARCHAR(20),
    account_holder VARCHAR(255),
    rating_avg FLOAT NOT NULL DEFAULT 0,
    rating_count INTEGER NOT NULL DEFAULT 0,
    response_time_avg_minutes INTEGER NOT NULL DEFAULT 0,
    fulfillment_rate FLOAT NOT NULL DEFAULT 0,
    total_sales INTEGER NOT NULL DEFAULT 0,
    total_orders INTEGER NOT NULL DEFAULT 0,
    trust_score FLOAT NOT NULL DEFAULT 50,
    trust_badge VARCHAR(20) NOT NULL DEFAULT 'NEW',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
    suspended_reason TEXT,
    suspended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS seller.seller_metrics (
    id UUID PRIMARY KEY,
    seller_id UUID NOT NULL,
    date TIMESTAMPTZ NOT NULL,
    revenue INTEGER NOT NULL DEFAULT 0,
    orders_count INTEGER NOT NULL DEFAULT 0,
    products_sold INTEGER NOT NULL DEFAULT 0,
    new_reviews INTEGER NOT NULL DEFAULT 0,
    avg_rating FLOAT NOT NULL DEFAULT 0,
    conversion_rate FLOAT NOT NULL DEFAULT 0,
    page_views INTEGER NOT NULL DEFAULT 0,
    unique_visitors INTEGER NOT NULL DEFAULT 0,
    UNIQUE(seller_id, date)
);
CREATE INDEX IF NOT EXISTS idx_sm_seller_date ON seller.seller_metrics(seller_id, date DESC);
