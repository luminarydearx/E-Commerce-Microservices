"""Admin Service — central admin endpoints aggregating all services."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic_settings import BaseSettings, SettingsConfigDict
import httpx
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8020
    REDIS_URL: str
    AUTH_SERVICE_URL: str = "http://auth-service:8001"
    CATALOG_SERVICE_URL: str = "http://catalog-service:8002"
    ORDER_SERVICE_URL: str = "http://order-service:8003"
    PAYMENT_SERVICE_URL: str = "http://payment-service:8004"
    AUDIT_SERVICE_URL: str = "http://audit-service:8006"
    FRAUD_SERVICE_URL: str = "http://fraud-service:8017"
    SELLER_SERVICE_URL: str = "http://seller-service:8018"
    ANALYTICS_SERVICE_URL: str = "http://analytics-service:8019"


settings = Settings()  # type: ignore
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=20)
logger = logging.getLogger("admin_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting admin-service")
    yield
    await redis_client.close()


app = FastAPI(title="Admin Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "admin-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


def get_user_roles(request: Request) -> list[str]:
    return [r.strip() for r in request.headers.get("X-User-Roles", "").split(",") if r.strip()]


def require_admin(request: Request) -> JSONResponse | None:
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "admin_required"})
    return None


async def proxy_get(url: str, headers: dict) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        return resp.status_code, resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text


# ===== Admin Dashboard =====

@app.get("/api/v1/admin/dashboard")
async def dashboard(request: Request):
    if err := require_admin(request):
        return err
    uid = get_user_id(request)
    headers = {"X-User-Id": uid, "X-User-Roles": ",".join(get_user_roles(request))}

    # Aggregate from multiple services
    async with httpx.AsyncClient(timeout=5.0) as client:
        import asyncio
        tasks = {
            "analytics": client.get(f"{settings.ANALYTICS_SERVICE_URL}/api/v1/analytics/overview", headers=headers),
            "fraud_flags": client.get(f"{settings.FRAUD_SERVICE_URL}/api/v1/admin/fraud/flags?status_filter=OPEN&size=5", headers=headers),
        }
        results = {}
        for name, task in tasks.items():
            try:
                resp = await asyncio.wait_for(task, timeout=3.0)
                if resp.status_code == 200:
                    results[name] = resp.json()
                else:
                    results[name] = {"error": f"status {resp.status_code}"}
            except Exception as e:
                results[name] = {"error": str(e)}

    return {
        "user_id": uid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": results,
    }


# ===== User Management =====

@app.get("/api/v1/admin/users")
async def list_users(request: Request, page: int = 0, size: int = 20, role: str | None = None):
    if err := require_admin(request):
        return err
    uid = get_user_id(request)
    headers = {"X-User-Id": uid, "X-User-Roles": ",".join(get_user_roles(request))}
    url = f"{settings.AUTH_SERVICE_URL}/api/v1/admin/users?page={page}&size={size}"
    if role:
        url += f"&role={role}"
    status, data = await proxy_get(url, headers)
    return JSONResponse(status_code=status, content=data)


@app.patch("/api/v1/admin/users/{user_id}/role")
async def update_role(user_id: str, payload: dict, request: Request):
    if err := require_admin(request):
        return err
    uid = get_user_id(request)
    headers = {"X-User-Id": uid, "X-User-Roles": ",".join(get_user_roles(request))}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.patch(
            f"{settings.AUTH_SERVICE_URL}/api/v1/admin/users/{user_id}/role",
            json=payload, headers=headers,
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.patch("/api/v1/admin/users/{user_id}/ban")
async def ban_user(user_id: str, payload: dict, request: Request):
    if err := require_admin(request):
        return err
    uid = get_user_id(request)
    headers = {"X-User-Id": uid, "X-User-Roles": ",".join(get_user_roles(request))}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.patch(
            f"{settings.AUTH_SERVICE_URL}/api/v1/admin/users/{user_id}/ban",
            json=payload, headers=headers,
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())


# ===== Audit Log =====

@app.get("/api/v1/admin/audit")
async def list_audit(
    request: Request,
    page: int = 0, size: int = 50,
    action: str | None = None,
    actor_user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    if err := require_admin(request):
        return err
    roles = get_user_roles(request)
    if "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "superadmin_required"})
    uid = get_user_id(request)
    headers = {"X-User-Id": uid, "X-User-Roles": ",".join(roles)}
    params = {"page": page, "size": size}
    if action: params["action"] = action
    if actor_user_id: params["actor_user_id"] = actor_user_id
    if resource_type: params["resource_type"] = resource_type
    if resource_id: params["resource_id"] = resource_id
    if start: params["start"] = start
    if end: params["end"] = end
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.AUDIT_SERVICE_URL}/api/v1/admin/audit",
            params=params, headers=headers,
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/api/v1/admin/errors")
async def list_errors(request: Request, page: int = 0, size: int = 50, service: str | None = None):
    if err := require_admin(request):
        return err
    uid = get_user_id(request)
    headers = {"X-User-Id": uid, "X-User-Roles": ",".join(get_user_roles(request))}
    params = {"page": page, "size": size}
    if service: params["service"] = service
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.AUDIT_SERVICE_URL}/api/v1/admin/errors",
            params=params, headers=headers,
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())


# ===== System Status =====

@app.get("/api/v1/admin/system/health")
async def system_health(request: Request):
    """Check all services health."""
    if err := require_admin(request):
        return err
    services = {
        "auth-service": settings.AUTH_SERVICE_URL,
        "catalog-service": settings.CATALOG_SERVICE_URL,
        "order-service": settings.ORDER_SERVICE_URL,
        "payment-service": settings.PAYMENT_SERVICE_URL,
        "audit-service": settings.AUDIT_SERVICE_URL,
        "fraud-service": settings.FRAUD_SERVICE_URL,
        "seller-service": settings.SELLER_SERVICE_URL,
        "analytics-service": settings.ANALYTICS_SERVICE_URL,
    }
    import asyncio
    results = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in services.items():
            try:
                resp = await asyncio.wait_for(client.get(f"{url}/health"), timeout=2.5)
                results[name] = {"status": "up" if resp.status_code == 200 else "degraded",
                                  "http_status": resp.status_code}
            except Exception as e:
                results[name] = {"status": "down", "error": str(e)[:100]}
    all_up = all(r["status"] == "up" for r in results.values())
    return {
        "overall_status": "healthy" if all_up else "degraded",
        "services": results,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
