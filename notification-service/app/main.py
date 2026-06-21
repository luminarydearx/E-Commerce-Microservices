"""Notification Service — async multi-channel notifications."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.database import engine
from app.core.redis import redis_client
from app.workers.kafka_consumer import NotificationConsumer
from app.observability.metrics import register_metrics

setup_logging()
logger = logging.getLogger("notification_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting notification-service")
    register_metrics()
    consumer = NotificationConsumer()
    consumer_task = asyncio.create_task(consumer.start())
    try:
        await redis_client.ping()
    except Exception as e:
        logger.error("redis ping failed", extra={"error": str(e)})
    yield
    logger.info("shutting down notification-service")
    consumer.stop()
    try:
        await asyncio.wait_for(consumer_task, timeout=5)
    except asyncio.TimeoutError:
        consumer_task.cancel()
    await redis_client.close()
    await engine.dispose()


app = FastAPI(
    title="Notification Service",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "notification-service"}


@app.get("/health/ready")
async def readiness():
    redis_ok = True
    try:
        await redis_client.ping()
    except Exception:
        redis_ok = False
    return JSONResponse(
        status_code=200 if redis_ok else 503,
        content={"status": "ready" if redis_ok else "degraded", "redis": redis_ok},
    )


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


# Internal API for sending notifications directly (e.g. from auth-service)
@app.post("/internal/send")
async def send_notification(payload: dict):
    from app.services.notification_service import NotificationService
    svc = NotificationService()
    await svc.send(payload)
    return {"status": "queued"}
