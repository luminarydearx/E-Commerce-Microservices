"""Seller Service — seller dashboard, analytics, inventory, payouts."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime, Float, Numeric
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8018
    DATABASE_URL: str
    REDIS_URL: str
    OTEL_ENDPOINT: str = "localhost:4317"


settings = Settings()  # type: ignore
engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=20)
logger = logging.getLogger("seller_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Base(DeclarativeBase):
    pass


class SellerProfile(Base):
    __tablename__ = "seller_profiles"
    __table_args__ = {"schema": "seller"}

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    store_name: Mapped[str] = mapped_column(String(200), nullable=False)
    store_slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    banner_url: Mapped[str | None] = mapped_column(String(500))

    # Verification
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    ktp_number: Mapped[str | None] = mapped_column(String(50))
    npwp_number: Mapped[str | None] = mapped_column(String(50))
    bank_account: Mapped[str | None] = mapped_column(String(50))
    bank_code: Mapped[str | None] = mapped_column(String(20))
    account_holder: Mapped[str | None] = mapped_column(String(255))

    # Performance metrics (cached, updated by worker)
    rating_avg: Mapped[float] = mapped_column(Float, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    response_time_avg_minutes: Mapped[int] = mapped_column(Integer, default=0)
    fulfillment_rate: Mapped[float] = mapped_column(Float, default=0.0)  # % orders shipped on time
    total_sales: Mapped[int] = mapped_column(Integer, default=0)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)

    # Trust score
    trust_score: Mapped[float] = mapped_column(Float, default=50.0)  # 0-100
    trust_badge: Mapped[str] = mapped_column(String(20), default="NEW")  # NEW, BRONZE, SILVER, GOLD, PLATINUM

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    suspended_reason: Mapped[str | None] = mapped_column(Text)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    version: Mapped[int] = mapped_column(Integer, default=1)


class SellerMetric(Base):
    """Daily aggregated metrics for seller."""
    __tablename__ = "seller_metrics"
    __table_args__ = {"schema": "seller"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    seller_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # date (truncated to day)
    revenue: Mapped[int] = mapped_column(Integer, default=0)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    products_sold: Mapped[int] = mapped_column(Integer, default=0)
    new_reviews: Mapped[int] = mapped_column(Integer, default=0)
    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    page_views: Mapped[int] = mapped_column(Integer, default=0)
    unique_visitors: Mapped[int] = mapped_column(Integer, default=0)


# ===== App =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting seller-service")
    yield
    await redis_client.close()
    await engine.dispose()


app = FastAPI(title="Seller Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "seller-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


def get_user_roles(request: Request) -> list[str]:
    return [r.strip() for r in request.headers.get("X-User-Roles", "").split(",") if r.strip()]


# ===== Routes =====

@app.get("/api/v1/seller/profile")
async def get_my_seller_profile(request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SellerProfile).where(SellerProfile.user_id == user_uuid))
        profile = result.scalar_one_or_none()
        if not profile:
            return JSONResponse(status_code=404, content={"error": "not_a_seller"})
        return _profile_to_dict(profile)


@app.post("/api/v1/seller/profile")
async def create_or_update_profile(payload: dict, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    roles = get_user_roles(request)
    if "seller" not in roles and "admin" not in roles:
        return JSONResponse(status_code=403, content={"error": "seller_role_required"})
    user_uuid = UUID(uid)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SellerProfile).where(SellerProfile.user_id == user_uuid))
        profile = result.scalar_one_or_none()
        if not profile:
            store_name = payload.get("store_name", f"Store {uid[:8]}")
            slug = store_name.lower().replace(" ", "-")[:50] + f"-{uid[:4]}"
            profile = SellerProfile(
                user_id=user_uuid,
                store_name=store_name,
                store_slug=slug,
                description=payload.get("description"),
                logo_url=payload.get("logo_url"),
            )
            db.add(profile)
        else:
            for field in ["store_name", "description", "logo_url", "banner_url", "bank_account", "bank_code", "account_holder"]:
                if field in payload:
                    setattr(profile, field, payload[field])
        await db.commit()
        await db.refresh(profile)
        return _profile_to_dict(profile)


@app.get("/api/v1/seller/dashboard")
async def get_dashboard(request: Request, period: str = "30d"):
    """Get seller dashboard: revenue, orders, top products, recent reviews."""
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)

    days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionLocal() as db:
        # Aggregate metrics
        result = await db.execute(
            select(
                func.coalesce(func.sum(SellerMetric.revenue), 0).label("total_revenue"),
                func.coalesce(func.sum(SellerMetric.orders_count), 0).label("total_orders"),
                func.coalesce(func.sum(SellerMetric.products_sold), 0).label("total_products_sold"),
                func.coalesce(func.avg(SellerMetric.avg_rating), 0).label("avg_rating"),
                func.coalesce(func.sum(SellerMetric.page_views), 0).label("total_views"),
            ).where(
                SellerMetric.seller_id == user_uuid,
                SellerMetric.date >= start_date,
            )
        )
        agg = result.first()

        # Daily breakdown
        daily_result = await db.execute(
            select(SellerMetric).where(
                SellerMetric.seller_id == user_uuid,
                SellerMetric.date >= start_date,
            ).order_by(SellerMetric.date)
        )
        daily = daily_result.scalars().all()

        # Profile
        prof_result = await db.execute(select(SellerProfile).where(SellerProfile.user_id == user_uuid))
        profile = prof_result.scalar_one_or_none()

        return {
            "period": period,
            "summary": {
                "total_revenue": agg.total_revenue if agg else 0,
                "total_orders": agg.total_orders if agg else 0,
                "total_products_sold": agg.total_products_sold if agg else 0,
                "avg_rating": float(agg.avg_rating) if agg and agg.avg_rating else 0.0,
                "total_views": agg.total_views if agg else 0,
            },
            "daily": [
                {
                    "date": d.date.isoformat(),
                    "revenue": d.revenue,
                    "orders": d.orders_count,
                    "products_sold": d.products_sold,
                    "rating": d.avg_rating,
                }
                for d in daily
            ],
            "profile": _profile_to_dict(profile) if profile else None,
        }


@app.get("/api/v1/seller/products")
async def list_my_products(request: Request, page: int = 0, size: int = 20):
    """List seller's own products (calls catalog-service)."""
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    # In production: call catalog-service via HTTP
    return {"data": [], "total": 0, "page": page, "size": size, "message": "proxy to catalog-service"}


@app.get("/api/v1/seller/orders")
async def list_seller_orders(request: Request, page: int = 0, size: int = 20, status: str | None = None):
    """List orders containing seller's products."""
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    # In production: query order_svc.order_items where seller_id = uid
    return {"data": [], "total": 0, "page": page, "size": size, "message": "proxy to order-service"}


@app.get("/api/v1/seller/analytics/top-products")
async def top_products(request: Request, period: str = "30d"):
    """Top selling products for seller."""
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return {"data": [], "message": "aggregation requires query to order-service"}


@app.post("/api/v1/admin/sellers/{seller_id}/verify")
async def verify_seller(seller_id: str, request: Request):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SellerProfile).where(SellerProfile.user_id == UUID(seller_id)))
        profile = result.scalar_one_or_none()
        if not profile:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        profile.is_verified = True
        profile.trust_score = min(100, profile.trust_score + 20)
        if profile.trust_score >= 80:
            profile.trust_badge = "PLATINUM"
        elif profile.trust_score >= 60:
            profile.trust_badge = "GOLD"
        elif profile.trust_score >= 40:
            profile.trust_badge = "SILVER"
        else:
            profile.trust_badge = "BRONZE"
        await db.commit()
        return _profile_to_dict(profile)


@app.post("/api/v1/admin/sellers/{seller_id}/suspend")
async def suspend_seller(seller_id: str, payload: dict, request: Request):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    reason = payload.get("reason", "")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SellerProfile).where(SellerProfile.user_id == UUID(seller_id)))
        profile = result.scalar_one_or_none()
        if not profile:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        profile.is_suspended = True
        profile.suspended_reason = reason
        profile.suspended_at = datetime.now(timezone.utc)
        profile.is_active = False
        await db.commit()
        return _profile_to_dict(profile)


def _profile_to_dict(p: SellerProfile) -> dict:
    return {
        "user_id": str(p.user_id),
        "store_name": p.store_name,
        "store_slug": p.store_slug,
        "description": p.description,
        "logo_url": p.logo_url,
        "banner_url": p.banner_url,
        "is_verified": p.is_verified,
        "rating_avg": p.rating_avg,
        "rating_count": p.rating_count,
        "response_time_avg_minutes": p.response_time_avg_minutes,
        "fulfillment_rate": p.fulfillment_rate,
        "total_sales": p.total_sales,
        "total_orders": p.total_orders,
        "trust_score": p.trust_score,
        "trust_badge": p.trust_badge,
        "is_active": p.is_active,
        "is_suspended": p.is_suspended,
        "suspended_reason": p.suspended_reason,
        "created_at": p.created_at.isoformat(),
    }
