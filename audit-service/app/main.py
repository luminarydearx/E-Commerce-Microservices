"""Audit Service — centralized audit log + error tracking."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings
from app.core.database import engine
from app.core.logging import setup_logging
from app.core.redis import redis_client
from app.observability.metrics import register_metrics
from app.workers.audit_consumer import AuditConsumer
from app.workers.error_consumer import ErrorConsumer

setup_logging()
logger = logging.getLogger("audit_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting audit-service")
    register_metrics()
    audit_consumer = AuditConsumer()
    error_consumer = ErrorConsumer()
    audit_task = asyncio.create_task(audit_consumer.start())
    error_task = asyncio.create_task(error_consumer.start())
    try:
        await redis_client.ping()
    except Exception as e:
        logger.error("redis ping failed", extra={"error": str(e)})
    yield
    logger.info("shutting down audit-service")
    audit_consumer.stop()
    error_consumer.stop()
    try:
        await asyncio.wait_for(asyncio.gather(audit_task, error_task), timeout=5)
    except asyncio.TimeoutError:
        audit_task.cancel()
        error_task.cancel()
    await redis_client.close()
    await engine.dispose()


app = FastAPI(
    title="Audit Service",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "audit-service"}


@app.get("/health/ready")
async def readiness():
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
    code = 200 if (db_ok and redis_ok) else 503
    return JSONResponse(status_code=code, content={"db": db_ok, "redis": redis_ok})


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


# ===== API endpoints =====

@app.get("/api/v1/admin/audit")
async def list_audit(
    request: Request,
    action: str | None = None,
    actor_user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 0,
    size: int = 50,
):
    """List audit log entries (superadmin only)."""
    # Authorization check — header X-User-Roles
    roles = request.headers.get("X-User-Roles", "")
    if "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    from app.services.audit_query import AuditQueryService
    svc = AuditQueryService()
    return await svc.list_audit(
        action=action, actor_user_id=actor_user_id,
        resource_type=resource_type, resource_id=resource_id,
        start=start, end=end, page=page, size=size,
    )


@app.get("/api/v1/admin/errors")
async def list_errors(
    request: Request,
    service: str | None = None,
    level: str | None = None,
    fingerprint: str | None = None,
    page: int = 0,
    size: int = 50,
):
    """List error log entries (admin only)."""
    roles = request.headers.get("X-User-Roles", "")
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    from app.services.audit_query import AuditQueryService
    svc = AuditQueryService()
    return await svc.list_errors(
        service=service, level=level, fingerprint=fingerprint, page=page, size=size,
    )


@app.post("/api/v1/internal/errors")
async def ingest_error(payload: dict[str, Any]):
    """Endpoint for services to push errors directly (sync fallback to Kafka)."""
    from app.services.error_ingest import ErrorIngestService
    svc = ErrorIngestService()
    await svc.ingest(payload)
    return {"status": "ingested"}


@app.get("/api/v1/admin/audit/verify")
async def verify_audit_chain(request: Request, start: str, end: str):
    """Verify hash chain integrity of audit log (superadmin only)."""
    roles = request.headers.get("X-User-Roles", "")
    if "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    from app.services.audit_query import AuditQueryService
    svc = AuditQueryService()
    return await svc.verify_chain(start, end)
