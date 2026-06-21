"""Wishlist Service — save products, price drop alerts, restock notifications."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis

settings_obj = BaseSettings()
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8008
    DATABASE_URL: str
    REDIS_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    OTEL_ENDPOINT: str = "localhost:4317"

settings = Settings()  # type: ignore

engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=30)

logger = logging.getLogger("wishlist_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Base(DeclarativeBase):
    pass


class Wishlist(Base):
    __tablename__ = "wishlists"
    __table_args__ = {"schema": "wishlist"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), default="My Wishlist")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = {"schema": "wishlist"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    wishlist_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("wishlist.wishlists.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_when_added: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notify_price_drop: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_restock: Mapped[bool] = mapped_column(Boolean, default=False)
    target_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PriceDropAlert(Base):
    __tablename__ = "price_drop_alerts"
    __table_args__ = {"schema": "wishlist"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    old_price: Mapped[int] = mapped_column(Integer, nullable=False)
    new_price: Mapped[int] = mapped_column(Integer, nullable=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ===== Schemas =====
class WishlistItemCreate(BaseModel):
    product_id: str
    note: str | None = Field(default=None, max_length=500)
    notify_price_drop: bool = True
    notify_restock: bool = False
    target_price: int | None = Field(default=None, ge=0)


class WishlistItemUpdate(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    notify_price_drop: bool | None = None
    notify_restock: bool | None = None
    target_price: int | None = Field(default=None, ge=0)


# ===== App =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting wishlist-service")
    yield
    await redis_client.close()
    await engine.dispose()


app = FastAPI(title="Wishlist Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "wishlist-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


# ===== Routes =====

@app.get("/api/v1/wishlist")
async def get_wishlist(request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        # Get or create default wishlist
        result = await db.execute(select(Wishlist).where(Wishlist.user_id == user_uuid))
        wishlist = result.scalar_one_or_none()
        if not wishlist:
            wishlist = Wishlist(id=uuid4(), user_id=user_uuid, name="My Wishlist")
            db.add(wishlist)
            await db.commit()
            await db.refresh(wishlist)

        # Get items
        items_result = await db.execute(
            select(WishlistItem).where(WishlistItem.wishlist_id == wishlist.id).order_by(desc(WishlistItem.created_at))
        )
        items = items_result.scalars().all()
        return {
            "wishlist": {
                "id": str(wishlist.id),
                "name": wishlist.name,
                "is_public": wishlist.is_public,
            },
            "items": [
                {
                    "id": str(i.id),
                    "product_id": str(i.product_id),
                    "note": i.note,
                    "price_when_added": i.price_when_added,
                    "notify_price_drop": i.notify_price_drop,
                    "notify_restock": i.notify_restock,
                    "target_price": i.target_price,
                    "created_at": i.created_at.isoformat(),
                }
                for i in items
            ],
            "total_items": len(items),
        }


@app.post("/api/v1/wishlist/items")
async def add_to_wishlist(req: WishlistItemCreate, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    product_uuid = UUID(req.product_id)

    async with AsyncSessionLocal() as db:
        # Get or create wishlist
        result = await db.execute(select(Wishlist).where(Wishlist.user_id == user_uuid))
        wishlist = result.scalar_one_or_none()
        if not wishlist:
            wishlist = Wishlist(id=uuid4(), user_id=user_uuid, name="My Wishlist")
            db.add(wishlist)
            await db.flush()

        # Check if already in wishlist
        existing = await db.execute(
            select(WishlistItem).where(
                WishlistItem.wishlist_id == wishlist.id,
                WishlistItem.product_id == product_uuid,
            )
        )
        if existing.scalar_one_or_none():
            return JSONResponse(status_code=409, content={"error": "already_in_wishlist"})

        item = WishlistItem(
            id=uuid4(),
            wishlist_id=wishlist.id,
            product_id=product_uuid,
            user_id=user_uuid,
            note=req.note,
            notify_price_drop=req.notify_price_drop,
            notify_restock=req.notify_restock,
            target_price=req.target_price,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return {
            "id": str(item.id),
            "product_id": str(item.product_id),
            "note": item.note,
            "created_at": item.created_at.isoformat(),
        }


@app.put("/api/v1/wishlist/items/{item_id}")
async def update_wishlist_item(item_id: str, req: WishlistItemUpdate, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    item_uuid = UUID(item_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WishlistItem).where(WishlistItem.id == item_uuid, WishlistItem.user_id == user_uuid)
        )
        item = result.scalar_one_or_none()
        if not item:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        if req.note is not None:
            item.note = req.note
        if req.notify_price_drop is not None:
            item.notify_price_drop = req.notify_price_drop
        if req.notify_restock is not None:
            item.notify_restock = req.notify_restock
        if req.target_price is not None:
            item.target_price = req.target_price
        await db.commit()
        return {"status": "updated"}


@app.delete("/api/v1/wishlist/items/{item_id}")
async def remove_from_wishlist(item_id: str, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    item_uuid = UUID(item_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WishlistItem).where(WishlistItem.id == item_uuid, WishlistItem.user_id == user_uuid)
        )
        item = result.scalar_one_or_none()
        if not item:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        await db.delete(item)
        await db.commit()
        return JSONResponse(status_code=204, content=None)


@app.get("/api/v1/wishlist/check/{product_id}")
async def check_in_wishlist(product_id: str, request: Request):
    """Check if product is in user's wishlist."""
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    product_uuid = UUID(product_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WishlistItem).where(
                WishlistItem.user_id == user_uuid,
                WishlistItem.product_id == product_uuid,
            )
        )
        item = result.scalar_one_or_none()
        return {"in_wishlist": item is not None, "item_id": str(item.id) if item else None}


@app.post("/api/v1/internal/wishlist/price-update")
async def trigger_price_update(payload: dict):
    """Internal: called when product price changes. Triggers price drop alerts."""
    product_id = UUID(payload["product_id"])
    old_price = payload["old_price"]
    new_price = payload["new_price"]

    if new_price >= old_price:
        return {"alerts_created": 0}

    async with AsyncSessionLocal() as db:
        # Find all wishlist items with notify_price_drop=True for this product
        result = await db.execute(
            select(WishlistItem).where(
                WishlistItem.product_id == product_id,
                WishlistItem.notify_price_drop == True,
            )
        )
        items = result.scalars().all()
        alerts_created = 0
        for item in items:
            # Check target_price if set
            if item.target_price and new_price > item.target_price:
                continue
            alert = PriceDropAlert(
                id=uuid4(),
                user_id=item.user_id,
                product_id=product_id,
                old_price=old_price,
                new_price=new_price,
            )
            db.add(alert)
            alerts_created += 1
        await db.commit()
        return {"alerts_created": alerts_created}
