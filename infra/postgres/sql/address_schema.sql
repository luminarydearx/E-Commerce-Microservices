CREATE SCHEMA IF NOT EXISTS address;

CREATE TABLE IF NOT EXISTS address.addresses (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    label VARCHAR(50) NOT NULL,
    recipient_name VARCHAR(255) NOT NULL,
    recipient_phone VARCHAR(50) NOT NULL,
    address_line1 TEXT NOT NULL,
    address_line2 TEXT,
    province VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL,
    district VARCHAR(100),
    subdistrict VARCHAR(100),
    postal_code VARCHAR(10) NOT NULL,
    country VARCHAR(2) NOT NULL DEFAULT 'ID',
    latitude FLOAT,
    longitude FLOAT,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_addresses_user ON address.addresses(user_id, is_primary);
CREATE INDEX IF NOT EXISTS idx_addresses_city ON address.addresses(city, province);

# Address Dockerfile
cat > address-service/Dockerfile << 'EOF'
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/* && \
    useradd -u 10001 -m appuser
RUN pip install --no-cache-dir \
    "fastapi==0.111.0" "uvicorn[standard]==0.30.1" "pydantic==2.8.2" \
    "pydantic-settings==2.3.4" "sqlalchemy[asyncio]==2.0.31" "asyncpg==0.29.0" \
    "redis==5.0.7" "prometheus-client==0.20.0"
COPY --chown=appuser:appuser . /app
USER appuser
EXPOSE 8011
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011", "--workers", "2"]
