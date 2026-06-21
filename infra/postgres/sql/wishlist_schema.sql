-- Wishlist schema
CREATE SCHEMA IF NOT EXISTS wishlist;

CREATE TABLE IF NOT EXISTS wishlist.wishlists (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    name VARCHAR(100) NOT NULL DEFAULT 'My Wishlist',
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wishlists_user ON wishlist.wishlists(user_id);

CREATE TABLE IF NOT EXISTS wishlist.wishlist_items (
    id UUID PRIMARY KEY,
    wishlist_id UUID NOT NULL REFERENCES wishlist.wishlists(id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    user_id UUID NOT NULL,
    note TEXT,
    price_when_added INTEGER,
    notify_price_drop BOOLEAN NOT NULL DEFAULT TRUE,
    notify_restock BOOLEAN NOT NULL DEFAULT FALSE,
    target_price INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wishlist_product UNIQUE (wishlist_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_wishlist_items_user ON wishlist.wishlist_items(user_id);
CREATE INDEX IF NOT EXISTS idx_wishlist_items_product ON wishlist.wishlist_items(product_id);

CREATE TABLE IF NOT EXISTS wishlist.price_drop_alerts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    product_id UUID NOT NULL,
    old_price INTEGER NOT NULL,
    new_price INTEGER NOT NULL,
    notified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_price_alerts_user ON wishlist.price_drop_alerts(user_id, notified);
CREATE INDEX IF NOT EXISTS idx_price_alerts_product ON wishlist.price_drop_alerts(product_id);
