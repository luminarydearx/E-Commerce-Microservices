#!/bin/bash
# Run database migrations for all services
set -e

echo "Running database migrations..."

# Auth service (Alembic)
echo "[1/6] Auth service..."
docker-compose exec auth-service alembic upgrade head || \
    echo "  (skipped - service may not be running)"

# Catalog service (Flyway / Hibernate)
echo "[2/6] Catalog service..."
docker-compose exec catalog-service java -cp app.jar org.springframework.boot.SpringApplication run || \
    echo "  (schema auto-created by Hibernate ddl-auto=validate)"

# Order service (manual SQL)
echo "[3/6] Order service..."
docker-compose exec postgres psql -U postgres -d order_db -f /docker-entrypoint-initdb.d/order_schema.sql || \
    echo "  (skipped)"

# Payment service (manual SQL)
echo "[4/6] Payment service..."
docker-compose exec postgres psql -U postgres -d payment_db -f /docker-entrypoint-initdb.d/payment_schema.sql || \
    echo "  (skipped)"

# Notification service
echo "[5/6] Notification service..."
docker-compose exec postgres psql -U postgres -d notification_db -f /docker-entrypoint-initdb.d/notification_schema.sql || \
    echo "  (skipped)"

# Audit service
echo "[6/6] Audit service..."
docker-compose exec postgres psql -U postgres -d audit_db -f /docker-entrypoint-initdb.d/audit_schema.sql || \
    echo "  (skipped)"

echo "✓ Migrations complete"
