# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --user poetry

# Install deps without project (we only have pyproject.toml)
RUN pip install --no-cache-dir \
    "fastapi==0.111.0" \
    "uvicorn[standard]==0.30.1" \
    "pydantic==2.8.2" \
    "pydantic-settings==2.3.4" \
    "sqlalchemy[asyncio]==2.0.31" \
    "asyncpg==0.29.0" \
    "alembic==1.13.2" \
    "redis==5.0.7" \
    "python-jose[cryptography]==3.3.0" \
    "passlib[argon2]==1.7.4" \
    "pyotp==2.9.0" \
    "python-multipart==0.0.9" \
    "email-validator==2.2.0" \
    "kafka-python==2.0.2" \
    "opentelemetry-api==1.27.0" \
    "opentelemetry-sdk==1.27.0" \
    "opentelemetry-instrumentation-fastapi==0.48b0" \
    "opentelemetry-instrumentation-sqlalchemy==0.48b0" \
    "opentelemetry-instrumentation-redis==0.48b0" \
    "opentelemetry-exporter-otlp==1.27.0" \
    "structlog==24.2.0" \
    "tenacity==8.4.2" \
    "httpx==0.27.0" \
    "cryptography==42.0.8" \
    "pyyaml==6.0.1" \
    "prometheus-client==0.20.0"

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -u 10001 -m appuser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
