-- Order Service schema
CREATE SCHEMA IF NOT EXISTS order_svc;

CREATE TABLE IF NOT EXISTS order_svc.carts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_carts_user_id ON order_svc.carts(user_id);
CREATE INDEX IF NOT EXISTS idx_carts_expires ON order_svc.carts(expires_at);

CREATE TABLE IF NOT EXISTS order_svc.cart_items (
    id UUID PRIMARY KEY,
    cart_id UUID NOT NULL REFERENCES order_svc.carts(id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(19, 2) NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    seller_id UUID NOT NULL,
    reserved BOOLEAN NOT NULL DEFAULT FALSE,
    reservation_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(cart_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_cart_items_cart_id ON order_svc.cart_items(cart_id);

CREATE TABLE IF NOT EXISTS order_svc.orders (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    total_amount DECIMAL(19, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'IDR',
    shipping_address TEXT NOT NULL,
    shipping_cost DECIMAL(19, 2) NOT NULL DEFAULT 0,
    tax_amount DECIMAL(19, 2) NOT NULL DEFAULT 0,
    payment_method VARCHAR(50),
    payment_id UUID,
    expires_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancel_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_order_status CHECK (
        status IN ('PENDING', 'PAID', 'CONFIRMED', 'SHIPPED', 'DELIVERED', 'COMPLETED', 'CANCELLED', 'REFUNDED')
    )
);
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON order_svc.orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON order_svc.orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON order_svc.orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_payment_id ON order_svc.orders(payment_id) WHERE payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS order_svc.order_items (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES order_svc.orders(id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    product_sku VARCHAR(100),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(19, 2) NOT NULL,
    subtotal DECIMAL(19, 2) NOT NULL,
    reservation_id UUID,
    seller_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_svc.order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_seller_id ON order_svc.order_items(seller_id);

-- Audit trigger for orders
CREATE OR REPLACE FUNCTION order_svc.audit_order_change() RETURNS TRIGGER AS $$
BEGIN
    -- In production, this writes to local audit table & publishes Kafka event
    -- For simplicity, just log via NOTIFY
    PERFORM pg_notify('order_audit', json_build_object(
        'table', TG_TABLE_NAME,
        'action', TG_OP,
        'old', row_to_json(OLD),
        'new', row_to_json(NEW),
        'timestamp', NOW()
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_orders_audit ON order_svc.orders;
CREATE TRIGGER trg_orders_audit AFTER INSERT OR UPDATE OR DELETE ON order_svc.orders
    FOR EACH ROW EXECUTE FUNCTION order_svc.audit_order_change();
