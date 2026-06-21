CREATE SCHEMA IF NOT EXISTS flashsale;

CREATE TABLE IF NOT EXISTS flashsale.sales (
    id UUID PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_fs_status CHECK (status IN ('SCHEDULED', 'ACTIVE', 'ENDED', 'CANCELLED')),
    CONSTRAINT chk_fs_dates CHECK (end_at > start_at)
);
CREATE INDEX IF NOT EXISTS idx_fs_active ON flashsale.sales(status, start_at, end_at);

CREATE TABLE IF NOT EXISTS flashsale.items (
    id UUID PRIMARY KEY,
    sale_id UUID NOT NULL REFERENCES flashsale.sales(id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    original_price INTEGER NOT NULL,
    sale_price INTEGER NOT NULL CHECK (sale_price < original_price),
    quota INTEGER NOT NULL CHECK (quota > 0),
    sold INTEGER NOT NULL DEFAULT 0,
    max_per_user INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_sold CHECK (sold <= quota)
);
CREATE INDEX IF NOT EXISTS idx_fs_items_sale ON flashsale.items(sale_id);
