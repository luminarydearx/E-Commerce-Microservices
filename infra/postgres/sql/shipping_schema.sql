CREATE SCHEMA IF NOT EXISTS shipping;

CREATE TABLE IF NOT EXISTS shipping.shipments (
    id UUID PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL,
    tracking_number VARCHAR(100) NOT NULL UNIQUE,
    courier VARCHAR(50) NOT NULL,
    service VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'CREATED',
    weight_grams INTEGER NOT NULL,
    recipient_name VARCHAR(255) NOT NULL,
    recipient_phone VARCHAR(50) NOT NULL,
    recipient_address TEXT NOT NULL,
    origin VARCHAR(50),
    destination VARCHAR(50),
    provider VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_shipment_status CHECK (status IN ('CREATED', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'FAILED_DELIVERY', 'RETURNED', 'CANCELLED'))
);
CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipping.shipments(order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipping.shipments(tracking_number);
CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipping.shipments(status, created_at);

CREATE TABLE IF NOT EXISTS shipping.shipment_events (
    id UUID PRIMARY KEY,
    shipment_id UUID NOT NULL REFERENCES shipping.shipments(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    note TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_shipment_events_shipment ON shipping.shipment_events(shipment_id, occurred_at DESC);
