"""Auth Service - main entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.logging import setup_logging
from app.core.redis import redis_client
from app.middleware.error_handler import register_error_handlers
from app.middleware.security import SecurityHeadersMiddleware
from app.observability.metrics import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    register_metrics,
)

setup_logging()
logger = logging.getLogger("auth_service")
tracer = trace.get_tracer("auth_service")


def init_tracing() -> None:
    """Init OpenTelemetry tracing."""
    resource = Resource.create(
        {
            "service.name": "auth-service",
            "service.version": "1.0.0",
            "deployment.environment": settings.ENVIRONMENT,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.OTEL_ENDPOINT,
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


init_tracing()
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
RedisInstrumentor().instrument()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup & shutdown."""
    logger.info("starting auth-service", extra={"env": settings.ENVIRONMENT})
    register_metrics()
    try:
        await redis_client.ping()
        logger.info("redis connection established")
    except Exception as e:
        logger.error("redis connection failed", extra={"error": str(e)})
    yield
    logger.info("shutting down auth-service")
    await redis_client.close()
    await engine.dispose()


app = FastAPI(
    title="E-Commerce Auth Service",
    version="1.0.0",
    description="Authentication, authorization, user management",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

# Middleware
app.add_middleware(SecurityHeadersMiddleware)
FastAPIInstrumentor.instrument_app(app)

# Error handlers
register_error_handlers(app)

# Routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Liveness probe."""
    return {"status": "alive", "service": "auth-service", "version": "1.0.0"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict:
    """Readiness probe — checks DB and Redis."""
    db_ok = True
    redis_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
    except Exception:
        db_ok = False
    try:
        await redis_client.ping()
    except Exception:
        redis_ok = False
    status_code = status.HTTP_200_OK if (db_ok and redis_ok) else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if (db_ok and redis_ok) else "degraded",
            "checks": {"database": db_ok, "redis": redis_ok},
        },
    )


@app.get("/metrics", tags=["metrics"])
async def metrics():
    """Prometheus metrics endpoint."""
    return JSONResponse(
        content=generate_latest().decode(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record request count and latency."""
    method = request.method
    path = request.url.path
    REQUEST_COUNT.labels(method=method, path=path).inc()
    with REQUEST_LATENCY.labels(method=method, path=path).time():
        response = await call_next(request)
    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.ENVIRONMENT == "development",
        workers=4 if settings.ENVIRONMENT == "production" else 1,
        log_config=None,  # use structlog
    )
