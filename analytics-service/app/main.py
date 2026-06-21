"""Analytics & BI Service — GMV, conversion funnel, cohort, A/B test."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8019
    DATABASE_URL: str
    REDIS_URL: str
    OTEL_ENDPOINT: str = "localhost:4317"


settings = Settings()  # type: ignore
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=20)
logger = logging.getLogger("analytics_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting analytics-service")
    yield
    await redis_client.close()


app = FastAPI(title="Analytics & BI Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "analytics-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_roles(request: Request) -> list[str]:
    return [r.strip() for r in request.headers.get("X-User-Roles", "").split(",") if r.strip()]


def require_admin(request: Request) -> JSONResponse | None:
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    return None


# ===== Endpoints =====

@app.get("/api/v1/analytics/overview")
async def overview(request: Request, period: str = "30d"):
    """High-level KPIs: GMV, orders, users, conversion."""
    if err := require_admin(request):
        return err
    days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)

    # In production: query from data warehouse / aggregate from order/payment tables
    return {
        "period": period,
        "kpis": {
            "gmv": 1_500_000_000,  # IDR 1.5B
            "gmv_change_pct": 12.5,
            "orders_count": 15420,
            "orders_change_pct": 8.3,
            "active_users": 8234,
            "users_change_pct": 5.2,
            "conversion_rate": 3.4,
            "avg_order_value": 97000,
            "refund_rate": 1.2,
            "payment_success_rate": 98.5,
        },
        "trend": [
            {"date": (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat(),
             "gmv": 50_000_000 - i * 1_000_000,
             "orders": 500 - i * 5}
            for i in range(days, 0, -1)
        ],
    }


@app.get("/api/v1/analytics/funnel")
async def conversion_funnel(request: Request, period: str = "30d"):
    """View → Cart → Checkout → Paid → Delivered."""
    if err := require_admin(request):
        return err
    return {
        "period": period,
        "stages": [
            {"stage": "view", "count": 1_000_000, "rate": 100.0},
            {"stage": "add_to_cart", "count": 50_000, "rate": 5.0},
            {"stage": "checkout", "count": 30_000, "rate": 3.0},
            {"stage": "paid", "count": 28_500, "rate": 2.85},
            {"stage": "delivered", "count": 27_000, "rate": 2.7},
        ],
        "drop_off_points": [
            {"from": "view", "to": "add_to_cart", "drop_pct": 95.0},
            {"from": "add_to_cart", "to": "checkout", "drop_pct": 40.0},
            {"from": "checkout", "to": "paid", "drop_pct": 5.0},
        ],
    }


@app.get("/api/v1/analytics/top-products")
async def top_products(request: Request, period: str = "30d", limit: int = 10):
    if err := require_admin(request):
        return err
    return {
        "period": period,
        "data": [
            {"product_id": "uuid1", "name": "Product A", "sold": 1200, "revenue": 240_000_000, "category": "Electronics"},
            {"product_id": "uuid2", "name": "Product B", "sold": 980, "revenue": 98_000_000, "category": "Fashion"},
        ][:limit],
    }


@app.get("/api/v1/analytics/top-sellers")
async def top_sellers(request: Request, period: str = "30d", limit: int = 10):
    if err := require_admin(request):
        return err
    return {
        "period": period,
        "data": [
            {"seller_id": "uuid1", "store_name": "Top Store", "gmv": 250_000_000, "orders": 1200, "rating": 4.8},
        ][:limit],
    }


@app.get("/api/v1/analytics/cohort")
async def cohort_retention(request: Request, months: int = 6):
    """User retention by signup cohort."""
    if err := require_admin(request):
        return err
    cohorts = []
    for i in range(months, 0, -1):
        cohort_date = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=30 * i)).date().isoformat()
        row = {"cohort": cohort_date, "size": 1000 - i * 50}
        for j in range(months):
            retention = max(0, 100 - j * 15 - i * 2)
            row[f"month_{j}"] = retention
        cohorts.append(row)
    return {"cohorts": cohorts}


@app.get("/api/v1/analytics/realtime")
async def realtime_metrics(request: Request):
    """Real-time metrics (last 5 minutes)."""
    if err := require_admin(request):
        return err
    return {
        "active_users": 234,
        "active_carts": 89,
        "orders_last_5min": 12,
        "revenue_last_5min": 4_500_000,
        "active_flash_sale_users": 1234,
        "payment_processing": 8,
        "ws_connections": 56,
    }


@app.post("/api/v1/analytics/track")
async def track_event(payload: dict, request: Request):
    """Track custom event from frontend (anonymized)."""
    event = payload.get("event")
    user_id = payload.get("user_id")  # anonymized hash in production
    properties = payload.get("properties", {})
    if not event:
        return JSONResponse(status_code=400, content={"error": "event required"})

    # In production: write to Kafka topic 'ecommerce.analytics.events'
    # For now: cache in Redis for real-time aggregation
    key = f"analytics:{event}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    await redis_client.hincrby(key, "count", 1)
    await redis_client.expire(key, 86400)

    return {"status": "tracked"}
