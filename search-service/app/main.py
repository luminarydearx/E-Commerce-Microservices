"""Search Service — real Elasticsearch integration."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis

from app.services.es_client import es_client
from app.services.search_service import search_service


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8012
    REDIS_URL: str = "redis://redis:6379/8"
    ELASTICSEARCH_URL: str = "http://elasticsearch:9200"
    ES_USERNAME: str = ""
    ES_PASSWORD: str = ""
    ES_REPLICAS: int = 0
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    OTEL_ENDPOINT: str = "localhost:4317"
    SEARCH_INDEX: str = "products"
    SEARCH_MIN_QUERY_LENGTH: int = 2
    SEARCH_MAX_PAGE_SIZE: int = 100
    AUTOCOMPLETE_LIMIT: int = 10
    AUTOCOMPLETE_CACHE_TTL: int = 300
    SEARCH_CACHE_TTL: int = 300


settings = Settings()  # type: ignore
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=20)
logger = logging.getLogger("search_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting search-service")
    # Init Elasticsearch
    await es_client.get_client()
    await es_client.ensure_index()
    # Start Kafka consumer for product events (in background)
    consumer_task = asyncio.create_task(_consume_product_events())
    yield
    logger.info("shutting down search-service")
    consumer_task.cancel()
    try:
        await asyncio.wait_for(consumer_task, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    await redis_client.close()
    await es_client.close()


app = FastAPI(title="Search Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    es_count = await es_client.count()
    return {
        "status": "alive",
        "service": "search-service",
        "elasticsearch": "connected" if es_count >= 0 else "disconnected",
        "indexed_documents": es_count,
    }


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


# ===== Schemas =====
class SearchRequest(BaseModel):
    query: str = Field(default="", max_length=200)
    category_id: str | None = None
    seller_id: str | None = None
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    min_rating: int | None = Field(default=None, ge=1, le=5)
    in_stock: bool = False
    sort_by: str = "relevance"
    page: int = Field(default=0, ge=0)
    size: int = Field(default=20, ge=1, le=100)


class IndexProduct(BaseModel):
    id: str
    name: str
    description: str | None = None
    sku: str
    slug: str
    category_id: str | None = None
    category_name: str | None = None
    seller_id: str
    seller_name: str | None = None
    price: int
    currency: str = "IDR"
    stock: int = 0
    available_stock: int = 0
    weight_grams: int | None = None
    image_urls: list[str] = []
    status: str = "ACTIVE"
    is_active: bool = True
    rating_avg: float = 0.0
    rating_count: int = 0
    sales_count: int = 0


# ===== Routes =====
@app.post("/api/v1/search")
async def search(req: SearchRequest, request: Request):
    # Cache key
    cache_key = f"search:{req.model_dump_json()}"
    cached = await redis_client.get(cache_key)
    if cached:
        result = json.loads(cached)
        result["cached"] = True
        return result

    result = await search_service.search_products(
        query=req.query,
        category_id=req.category_id,
        seller_id=req.seller_id,
        min_price=req.min_price,
        max_price=req.max_price,
        min_rating=req.min_rating,
        in_stock=req.in_stock,
        sort_by=req.sort_by,
        page=req.page,
        size=req.size,
    )
    # Cache for 5 min
    if not result.get("fallback"):
        await redis_client.setex(cache_key, settings.SEARCH_CACHE_TTL, json.dumps(result))
    return result


@app.get("/api/v1/search/autocomplete")
async def autocomplete(q: str, request: Request):
    if len(q) < settings.SEARCH_MIN_QUERY_LENGTH:
        return {"suggestions": []}

    cache_key = f"ac:{q}"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    suggestions = await search_service.autocomplete(q)
    result = {"suggestions": suggestions}
    await redis_client.setex(cache_key, settings.AUTOCOMPLETE_CACHE_TTL, json.dumps(result))
    return result


@app.get("/api/v1/search/popular")
async def popular_searches(request: Request):
    cached = await redis_client.get("popular_searches")
    if cached:
        return json.loads(cached)
    # Default trending
    return {
        "searches": ["iphone 15", "sepatu running", "tas wanita", "kemeja pria", "laptop gaming"],
        "cached": False,
    }


@app.post("/api/v1/search/index")
async def index_product_endpoint(req: IndexProduct, request: Request):
    doc = req.model_dump()
    success = await search_service.index_product(doc)
    if success:
        await _invalidate_search_cache()
        return {"status": "indexed", "product_id": req.id}
    return JSONResponse(status_code=500, content={"error": "index_failed"})


@app.post("/api/v1/search/bulk-index")
async def bulk_index_endpoint(products: list[IndexProduct], request: Request):
    docs = [p.model_dump() for p in products]
    count = await search_service.bulk_index(docs)
    if count > 0:
        await _invalidate_search_cache()
    return {"status": "indexed", "count": count}


@app.delete("/api/v1/search/index/{product_id}")
async def delete_product_endpoint(product_id: str, request: Request):
    success = await search_service.delete_product(product_id)
    if success:
        await _invalidate_search_cache()
    return {"status": "deleted" if success else "failed", "product_id": product_id}


@app.post("/api/v1/admin/search/reindex")
async def reindex_all(request: Request):
    roles = request.headers.get("X-User-Roles", "")
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    result = await search_service.reindex_all()
    return result


async def _invalidate_search_cache() -> None:
    """Clear search result caches (autocomplete kept)."""
    async for key in redis_client.scan_iter(match="search:*", count=200):
        await redis_client.delete(key)


async def _consume_product_events() -> None:
    """Consume product events from Kafka and update ES index."""
    try:
        from kafka import KafkaConsumer
        consumer = KafkaConsumer(
            "ecommerce.product.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="search-service",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            consumer_timeout_ms=1000,
        )
        logger.info("Kafka consumer started for product events")
    except Exception as e:
        logger.warning(f"Kafka unavailable, indexing only via API: {e}")
        return

    while True:
        try:
            records = consumer.poll(timeout_ms=500, max_records=100)
            if not records:
                await asyncio.sleep(0.5)
                continue
            for tp, messages in records.items():
                for msg in messages:
                    event = msg.value
                    action = event.get("action", "")
                    resource = event.get("resource", {}) or {}
                    after = resource.get("after")

                    if action in ("product.create", "product.update") and after:
                        await search_service.index_product(after)
                    elif action == "product.delete":
                        pid = resource.get("id")
                        if pid:
                            await search_service.delete_product(pid)
                consumer.commit()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Consumer error: {e}")
            await asyncio.sleep(1)

    try:
        consumer.close()
    except Exception:
        pass
