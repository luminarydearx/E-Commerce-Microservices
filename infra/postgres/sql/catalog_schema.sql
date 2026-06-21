-- Catalog Service schema
CREATE SCHEMA IF NOT EXISTS catalog;

CREATE TABLE IF NOT EXISTS catalog.categories (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(500),
    parent_id UUID REFERENCES catalog.categories(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_categories_slug ON catalog.categories(slug);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON catalog.categories(parent_id);

CREATE TABLE IF NOT EXISTS catalog.products (
    id UUID PRIMARY KEY,
    seller_id UUID NOT NULL,
    category_id UUID REFERENCES catalog.categories(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    price DECIMAL(19, 2) NOT NULL CHECK (price > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'IDR',
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    reserved_stock INTEGER NOT NULL DEFAULT 0 CHECK (reserved_stock >= 0),
    weight_grams INTEGER,
    image_urls TEXT,  -- JSON array
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT chk_product_status CHECK (status IN ('DRAFT', 'ACTIVE', 'INACTIVE', 'ARCHIVED')),
    CONSTRAINT chk_stock_reserved CHECK (reserved_stock <= stock)
);
CREATE INDEX IF NOT EXISTS idx_products_seller ON catalog.products(seller_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON catalog.products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_status ON catalog.products(status, is_active);
CREATE INDEX IF NOT EXISTS idx_products_price ON catalog.products(price);
CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON catalog.products USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_metadata ON catalog.products USING gin (metadata);

CREATE TABLE IF NOT EXISTS catalog.stock_reservations (
    id UUID PRIMARY KEY,
    product_id UUID NOT NULL REFERENCES catalog.products(id) ON DELETE CASCADE,
    cart_id UUID NOT NULL,
    user_id UUID NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    expires_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(product_id, cart_id),
    CONSTRAINT chk_reservation_status CHECK (status IN ('ACTIVE', 'CONFIRMED', 'RELEASED', 'EXPIRED'))
);
CREATE INDEX IF NOT EXISTS idx_reservations_product ON catalog.stock_reservations(product_id, status);
CREATE INDEX IF NOT EXISTS idx_reservations_user ON catalog.stock_reservations(user_id);
CREATE INDEX IF NOT EXISTS idx_reservations_expires ON catalog.stock_reservations(expires_at) WHERE status = 'ACTIVE';

-- Trigger to auto-expire reservations
CREATE OR REPLACE FUNCTION catalog.expire_reservations() RETURNS void AS $$
BEGIN
    UPDATE catalog.stock_reservations
    SET status = 'EXPIRED'
    WHERE status = 'ACTIVE' AND expires_at < NOW();
    -- Also release reserved stock
    UPDATE catalog.products p
    SET reserved_stock = reserved_stock - r.qty
    FROM (
        SELECT product_id, SUM(quantity) AS qty
        FROM catalog.stock_reservations
        WHERE status = 'EXPIRED'
        GROUP BY product_id
    ) r
    WHERE p.id = r.product_id;
END;
$$ LANGUAGE plpgsql;
