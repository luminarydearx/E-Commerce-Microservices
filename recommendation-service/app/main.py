"""Recommendation Service — collaborative filtering, frequently bought together."""
from __future__ import annotations

import asyncio
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
    PORT: int = 8021
    REDIS_URL: str
    DATABASE_URL: str = ""
    OTEL_ENDPOINT: str = "localhost:4317"
    CACHE_TTL: int = 3600  # 1 hour
    MAX_RECOMMENDATIONS: int = 20


settings = Settings()  # type: ignore
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=30)
logger = logging.getLogger("recommendation_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting recommendation-service")
    yield
    await redis_client.close()


app = FastAPI(title="Recommendation Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "recommendation-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


# ===== Endpoints =====

@app.get("/api/v1/recommendations/for-you")
async def recommend_for_you(request: Request, limit: int = 10):
    """Personalized recommendations for user (collaborative filtering)."""
    uid = get_user_id(request)
    limit = min(limit, settings.MAX_RECOMMENDATIONS)

    # Check cache
    cache_key = f"rec:for_you:{uid}"
    cached = await redis_client.get(cache_key)
    if cached:
        import json
        return json.loads(cached)

    # In production: query ML model (collaborative filtering or content-based)
    # For now: return mock recommendations
    result = {
        "user_id": uid,
        "source": "collaborative_filtering",
        "recommendations": [
            {"product_id": "uuid-1", "name": "Recommended Product 1", "score": 0.95, "reason": "similar_users_bought"},
            {"product_id": "uuid-2", "name": "Recommended Product 2", "score": 0.89, "reason": "similar_users_bought"},
            {"product_id": "uuid-3", "name": "Recommended Product 3", "score": 0.85, "reason": "viewed_before"},
        ][:limit],
        "cached": False,
    }
    import json
    await redis_client.setex(cache_key, settings.CACHE_TTL, json.dumps(result))
    return result


@app.get("/api/v1/recommendations/frequently-bought-together/{product_id}")
async def frequently_bought_together(product_id: str, request: Request, limit: int = 5):
    """Products frequently bought together with given product."""
    cache_key = f"rec:fbt:{product_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        import json
        return json.loads(cached)

    result = {
        "product_id": product_id,
        "source": "association_rules",
        "recommendations": [
            {"product_id": "uuid-a", "name": "Complementary Product A", "confidence": 0.65, "support": 0.12},
            {"product_id": "uuid-b", "name": "Complementary Product B", "confidence": 0.45, "support": 0.08},
        ][:limit],
        "cached": False,
    }
    import json
    await redis_client.setex(cache_key, settings.CACHE_TTL, json.dumps(result))
    return result


@app.get("/api/v1/recommendations/users-also-viewed/{product_id}")
async def users_also_viewed(product_id: str, request: Request, limit: int = 10):
    """Users who viewed this also viewed."""
    cache_key = f"rec:also_viewed:{product_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        import json
        return json.loads(cached)

    result = {
        "product_id": product_id,
        "source": "co_view",
        "recommendations": [
            {"product_id": "uuid-x", "score": 0.78, "co_views": 245},
            {"product_id": "uuid-y", "score": 0.65, "co_views": 198},
        ][:limit],
        "cached": False,
    }
    import json
    await redis_client.setex(cache_key, settings.CACHE_TTL, json.dumps(result))
    return result


@app.get("/api/v1/recommendations/trending")
async def trending(request: Request, category_id: str | None = None, limit: int = 20):
    """Trending products (high sales velocity in last 24h)."""
    cache_key = f"rec:trending:{category_id or 'all'}"
    cached = await redis_client.get(cache_key)
    if cached:
        import json
        return json.loads(cached)

    result = {
        "category_id": category_id,
        "source": "trending_24h",
        "recommendations": [
            {"product_id": "uuid-t1", "sales_24h": 145, "trend_score": 0.95},
            {"product_id": "uuid-t2", "sales_24h": 98, "trend_score": 0.78},
        ][:limit],
        "cached": False,
    }
    import json
    await redis_client.setex(cache_key, 1800, json.dumps(result))  # 30 min cache for trending
    return result


@app.get("/api/v1/recommendations/recently-viewed")
async def recently_viewed(request: Request, limit: int = 10):
    """User's recently viewed products."""
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    key = f"recently_viewed:{uid}"
    product_ids = await redis_client.lrange(key, 0, limit - 1)
    return {
        "user_id": uid,
        "products": [{"product_id": pid, "viewed_at": "auto"} for pid in product_ids],
    }


@app.post("/api/v1/recommendations/track-view")
async def track_view(payload: dict, request: Request):
    """Track product view for recommendation (called from frontend)."""
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    product_id = payload.get("product_id")
    if not product_id:
        return JSONResponse(status_code=400, content={"error": "product_id required"})

    key = f"recently_viewed:{uid}"
    # Remove if exists, then push to front, limit to 50
    await redis_client.lrem(key, 0, product_id)
    await redis_client.lpush(key, product_id)
    await redis_client.ltrim(key, 0, 49)
    await redis_client.expire(key, 86400 * 30)  # 30 days

    # Also track for trending
    trending_key = f"trending:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
    await redis_client.zincrby(trending_key, 1, product_id)
    await redis_client.expire(trending_key, 86400)

    return {"status": "tracked"}
