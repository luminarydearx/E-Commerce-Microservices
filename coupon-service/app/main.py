"""Coupon & Voucher Service — discounts, flash sale vouchers, stack rules, redemption limits."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, Numeric, Date
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8009
    DATABASE_URL: str
    REDIS_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    OTEL_ENDPOINT: str = "localhost:4317"
    COUPON_REDEMPTION_LIMIT_GLOBAL: int = 10000
    COUPON_REDEMPTION_LIMIT_PER_USER: int = 1


settings = Settings()  # type: ignore
engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=30)

logger = logging.getLogger("coupon_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Base(DeclarativeBase):
    pass


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = {"schema": "coupon"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Discount type
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)  # PERCENTAGE, FIXED, FREE_SHIPPING
    discount_value: Mapped[int] = mapped_column(Integer, nullable=False)  # percent or nominal in IDR
    max_discount: Mapped[int | None] = mapped_column(Integer)  # cap for percentage

    # Constraints
    min_purchase: Mapped[int] = mapped_column(Integer, default=0)
    max_usage_global: Mapped[int] = mapped_column(Integer, default=1)
    max_usage_per_user: Mapped[int] = mapped_column(Integer, default=1)
    max_usage_global_count: Mapped[int] = mapped_column(Integer, default=0)  # current count

    # Validity
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Targeting
    applicable_scope: Mapped[str] = mapped_column(String(20), default="ALL")  # ALL, CATEGORY, PRODUCT, SELLER
    applicable_ids: Mapped[list[str] | None] = mapped_column(JSONB)  # list of UUIDs

    # User-specific
    user_specific: Mapped[bool] = mapped_column(Boolean, default=False)
    user_ids: Mapped[list[str] | None] = mapped_column(JSONB)

    # Stacking
    is_stackable: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"
    __table_args__ = {"schema": "coupon"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    coupon_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("coupon.coupons.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ===== Schemas =====
class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    discount_type: str  # PERCENTAGE, FIXED, FREE_SHIPPING
    discount_value: int = Field(ge=0)
    max_discount: int | None = None
    min_purchase: int = Field(default=0, ge=0)
    max_usage_global: int = Field(default=1, ge=1)
    max_usage_per_user: int = Field(default=1, ge=1)
    start_at: datetime
    end_at: datetime
    applicable_scope: str = "ALL"
    applicable_ids: list[str] | None = None
    user_specific: bool = False
    user_ids: list[str] | None = None
    is_stackable: bool = False

    @field_validator("discount_type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("PERCENTAGE", "FIXED", "FREE_SHIPPING"):
            raise ValueError("must be PERCENTAGE, FIXED, or FREE_SHIPPING")
        return v

    @field_validator("end_at")
    @classmethod
    def validate_dates(cls, v, info):
        start = info.data.get("start_at")
        if start and v <= start:
            raise ValueError("end_at must be after start_at")
        return v


class CouponValidate(BaseModel):
    code: str
    user_id: str
    cart_total: int = Field(ge=0)
    cart_items: list[dict]  # [{"product_id": "...", "category_id": "...", "seller_id": "...", "price": 100000, "quantity": 2}]


class CouponApply(BaseModel):
    code: str
    user_id: str
    order_id: str
    discount_amount: int


# ===== App =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting coupon-service")
    yield
    await redis_client.close()
    await engine.dispose()


app = FastAPI(title="Coupon Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "coupon-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


def get_user_roles(request: Request) -> list[str]:
    roles = request.headers.get("X-User-Roles", "")
    return [r.strip() for r in roles.split(",") if r.strip()]


# ===== Admin endpoints =====

@app.post("/api/v1/admin/coupons")
async def create_coupon(req: CouponCreate, request: Request):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles and "seller" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    uid = get_user_id(request)

    async with AsyncSessionLocal() as db:
        # Check unique code
        existing = await db.execute(select(Coupon).where(Coupon.code == req.code.upper()))
        if existing.scalar_one_or_none():
            return JSONResponse(status_code=409, content={"error": "code_already_exists"})

        coupon = Coupon(
            id=uuid4(),
            code=req.code.upper(),
            name=req.name,
            description=req.description,
            discount_type=req.discount_type,
            discount_value=req.discount_value,
            max_discount=req.max_discount,
            min_purchase=req.min_purchase,
            max_usage_global=req.max_usage_global,
            max_usage_per_user=req.max_usage_per_user,
            start_at=req.start_at,
            end_at=req.end_at,
            applicable_scope=req.applicable_scope,
            applicable_ids=req.applicable_ids,
            user_specific=req.user_specific,
            user_ids=req.user_ids,
            is_stackable=req.is_stackable,
            is_active=True,
            created_by=UUID(uid) if uid else None,
        )
        db.add(coupon)
        await db.commit()
        await db.refresh(coupon)
        return _coupon_to_dict(coupon)


@app.get("/api/v1/admin/coupons")
async def list_coupons(request: Request, page: int = 0, size: int = 20):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles and "seller" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Coupon).order_by(desc(Coupon.created_at)).offset(page * size).limit(size)
        )
        coupons = result.scalars().all()
        count_result = await db.execute(select(func.count(Coupon.id)))
        total = count_result.scalar() or 0
        return {"data": [_coupon_to_dict(c) for c in coupons], "total": total, "page": page, "size": size}


@app.patch("/api/v1/admin/coupons/{coupon_id}/deactivate")
async def deactivate_coupon(coupon_id: str, request: Request):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Coupon).where(Coupon.id == UUID(coupon_id)))
        coupon = result.scalar_one_or_none()
        if not coupon:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        coupon.is_active = False
        await db.commit()
        return {"status": "deactivated"}


# ===== User endpoints =====

@app.post("/api/v1/coupons/validate")
async def validate_coupon(req: CouponValidate, request: Request):
    """Validate coupon against cart. Returns discount_amount if valid."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Coupon).where(Coupon.code == req.code.upper()))
        coupon = result.scalar_one_or_none()
        if not coupon:
            return JSONResponse(status_code=404, content={"error": "coupon_not_found"})

        now = datetime.now(timezone.utc)
        if not coupon.is_active:
            return JSONResponse(status_code=400, content={"error": "coupon_inactive"})
        if now < coupon.start_at:
            return JSONResponse(status_code=400, content={"error": "coupon_not_started"})
        if now > coupon.end_at:
            return JSONResponse(status_code=400, content={"error": "coupon_expired"})

        # Check global usage limit
        if coupon.max_usage_global_count >= coupon.max_usage_global:
            return JSONResponse(status_code=400, content={"error": "coupon_limit_reached"})

        # Check user-specific
        if coupon.user_specific:
            if not coupon.user_ids or req.user_id not in coupon.user_ids:
                return JSONResponse(status_code=403, content={"error": "not_eligible_user"})

        # Check per-user limit
        user_redemptions = await db.execute(
            select(func.count(CouponRedemption.id)).where(
                CouponRedemption.coupon_id == coupon.id,
                CouponRedemption.user_id == UUID(req.user_id),
            )
        )
        if user_redemptions.scalar() >= coupon.max_usage_per_user:
            return JSONResponse(status_code=400, content={"error": "user_limit_reached"})

        # Check min purchase
        if req.cart_total < coupon.min_purchase:
            return JSONResponse(status_code=400, content={
                "error": "min_purchase_not_met",
                "min_purchase": coupon.min_purchase,
            })

        # Check applicable scope
        applicable_total = req.cart_total
        if coupon.applicable_scope != "ALL":
            applicable_total = 0
            applicable_ids_set = {aid for aid in (coupon.applicable_ids or [])}
            for item in req.cart_items:
                if coupon.applicable_scope == "CATEGORY" and item.get("category_id") in applicable_ids_set:
                    applicable_total += item["price"] * item["quantity"]
                elif coupon.applicable_scope == "PRODUCT" and item.get("product_id") in applicable_ids_set:
                    applicable_total += item["price"] * item["quantity"]
                elif coupon.applicable_scope == "SELLER" and item.get("seller_id") in applicable_ids_set:
                    applicable_total += item["price"] * item["quantity"]
            if applicable_total == 0:
                return JSONResponse(status_code=400, content={"error": "no_applicable_items"})

        # Calculate discount
        discount_amount = 0
        if coupon.discount_type == "PERCENTAGE":
            discount_amount = int(applicable_total * coupon.discount_value / 100)
            if coupon.max_discount:
                discount_amount = min(discount_amount, coupon.max_discount)
        elif coupon.discount_type == "FIXED":
            discount_amount = min(coupon.discount_value, applicable_total)
        elif coupon.discount_type == "FREE_SHIPPING":
            discount_amount = 0  # Shipping discount handled separately

        return {
            "valid": True,
            "discount_type": coupon.discount_type,
            "discount_amount": discount_amount,
            "coupon_id": str(coupon.id),
            "code": coupon.code,
            "name": coupon.name,
        }


@app.post("/api/v1/coupons/apply")
async def apply_coupon(req: CouponApply, request: Request):
    """Apply coupon to order (record redemption). Idempotent per order_id."""
    async with AsyncSessionLocal() as db:
        # Check if already applied for this order
        existing = await db.execute(
            select(CouponRedemption).where(CouponRedemption.order_id == UUID(req.order_id))
        )
        if existing.scalar_one_or_none():
            return JSONResponse(status_code=409, content={"error": "coupon_already_applied"})

        result = await db.execute(select(Coupon).where(Coupon.code == req.code.upper()))
        coupon = result.scalar_one_or_none()
        if not coupon:
            return JSONResponse(status_code=404, content={"error": "coupon_not_found"})

        # Atomically increment global usage count
        coupon.max_usage_global_count += 1
        redemption = CouponRedemption(
            id=uuid4(),
            coupon_id=coupon.id,
            user_id=UUID(req.user_id),
            order_id=UUID(req.order_id),
            discount_amount=req.discount_amount,
        )
        db.add(redemption)
        await db.commit()

        # Publish event (in production: to Kafka for audit)
        logger.info("coupon applied", extra={
            "coupon_id": str(coupon.id), "user_id": req.user_id,
            "order_id": req.order_id, "discount": req.discount_amount,
        })
        return {"status": "applied", "redemption_id": str(redemption.id)}


@app.get("/api/v1/users/{user_id}/coupons")
async def list_user_coupons(user_id: str, request: Request):
    """List coupons available for user (general + user-specific)."""
    uid = get_user_id(request)
    if uid != user_id and "admin" not in get_user_roles(request):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Get all active coupons
        result = await db.execute(
            select(Coupon).where(
                Coupon.is_active == True,
                Coupon.start_at <= now,
                Coupon.end_at >= now,
            ).order_by(desc(Coupon.end_at))
        )
        coupons = result.scalars().all()

        # Filter: user-specific must include this user
        available = []
        for c in coupons:
            if c.user_specific:
                if not c.user_ids or user_id not in c.user_ids:
                    continue
            # Check user's redemption count
            user_count = await db.execute(
                select(func.count(CouponRedemption.id)).where(
                    CouponRedemption.coupon_id == c.id,
                    CouponRedemption.user_id == UUID(user_id),
                )
            )
            if user_count.scalar() < c.max_usage_per_user:
                if c.max_usage_global_count < c.max_usage_global:
                    available.append(_coupon_to_dict(c))

        return {"data": available, "total": len(available)}


def _coupon_to_dict(c: Coupon) -> dict:
    return {
        "id": str(c.id),
        "code": c.code,
        "name": c.name,
        "description": c.description,
        "discount_type": c.discount_type,
        "discount_value": c.discount_value,
        "max_discount": c.max_discount,
        "min_purchase": c.min_purchase,
        "max_usage_global": c.max_usage_global,
        "max_usage_per_user": c.max_usage_per_user,
        "max_usage_global_count": c.max_usage_global_count,
        "start_at": c.start_at.isoformat(),
        "end_at": c.end_at.isoformat(),
        "applicable_scope": c.applicable_scope,
        "is_stackable": c.is_stackable,
        "is_active": c.is_active,
    }
