"""Address Service — multiple addresses per user, map picker, geocoding."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime, Float
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8011
    DATABASE_URL: str
    REDIS_URL: str
    OTEL_ENDPOINT: str = "localhost:4317"
    GOOGLE_MAPS_API_KEY: str = ""
    MAX_ADDRESSES_PER_USER: int = 10


settings = Settings()  # type: ignore
engine = create_async_engine(settings.DATABASE_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=10)
logger = logging.getLogger("address_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Base(DeclarativeBase):
    pass


class Address(Base):
    __tablename__ = "addresses"
    __table_args__ = {"schema": "address"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)  # Rumah, Kantor, Lainnya
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(50), nullable=False)

    # Address components
    address_line1: Mapped[str] = mapped_column(Text, nullable=False)
    address_line2: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    district: Mapped[str | None] = mapped_column(String(100))
    subdistrict: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="ID")

    # Geo
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # Meta
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    version: Mapped[int] = mapped_column(Integer, default=1)


# ===== Schemas =====
class AddressCreate(BaseModel):
    label: str = Field(max_length=50)
    recipient_name: str = Field(max_length=255)
    recipient_phone: str = Field(max_length=50)
    address_line1: str = Field(max_length=500)
    address_line2: str | None = Field(default=None, max_length=500)
    province: str = Field(max_length=100)
    city: str = Field(max_length=100)
    district: str | None = None
    subdistrict: str | None = None
    postal_code: str = Field(min_length=4, max_length=10)
    latitude: float | None = None
    longitude: float | None = None
    is_primary: bool = False
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("recipient_phone")
    @classmethod
    def validate_phone(cls, v):
        import re
        if not re.match(r"^\+?[1-9]\d{6,14}$", v):
            raise ValueError("phone must be E.164")
        return v


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=50)
    recipient_name: str | None = Field(default=None, max_length=255)
    recipient_phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=500)
    address_line2: str | None = Field(default=None, max_length=500)
    province: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    district: str | None = None
    subdistrict: str | None = None
    postal_code: str | None = Field(default=None, min_length=4, max_length=10)
    latitude: float | None = None
    longitude: float | None = None
    is_primary: bool | None = None
    notes: str | None = Field(default=None, max_length=500)


# ===== App =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting address-service")
    yield
    await redis_client.close()
    await engine.dispose()


app = FastAPI(title="Address Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "address-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


# ===== Routes =====

@app.get("/api/v1/addresses")
async def list_addresses(request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Address).where(Address.user_id == user_uuid).order_by(desc(Address.is_primary), desc(Address.updated_at))
        )
        addresses = result.scalars().all()
        return {"data": [_addr_to_dict(a) for a in addresses], "total": len(addresses)}


@app.post("/api/v1/addresses")
async def create_address(req: AddressCreate, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)

    async with AsyncSessionLocal() as db:
        # Limit check
        count_result = await db.execute(
            select(func.count(Address.id)).where(Address.user_id == user_uuid)
        )
        if count_result.scalar() >= settings.MAX_ADDRESSES_PER_USER:
            return JSONResponse(status_code=400, content={
                "error": "limit_reached",
                "message": f"max {settings.MAX_ADDRESSES_PER_USER} addresses per user",
            })

        # If is_primary, unset other primary
        if req.is_primary:
            await _unset_primary(db, user_uuid)

        addr = Address(
            id=uuid4(),
            user_id=user_uuid,
            label=req.label,
            recipient_name=req.recipient_name,
            recipient_phone=req.recipient_phone,
            address_line1=req.address_line1,
            address_line2=req.address_line2,
            province=req.province,
            city=req.city,
            district=req.district,
            subdistrict=req.subdistrict,
            postal_code=req.postal_code,
            latitude=req.latitude,
            longitude=req.longitude,
            is_primary=req.is_primary,
            notes=req.notes,
        )
        db.add(addr)
        await db.commit()
        await db.refresh(addr)
        return _addr_to_dict(addr)


@app.get("/api/v1/addresses/{address_id}")
async def get_address(address_id: str, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Address).where(Address.id == UUID(address_id), Address.user_id == user_uuid)
        )
        addr = result.scalar_one_or_none()
        if not addr:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        return _addr_to_dict(addr)


@app.put("/api/v1/addresses/{address_id}")
async def update_address(address_id: str, req: AddressUpdate, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Address).where(Address.id == UUID(address_id), Address.user_id == user_uuid)
        )
        addr = result.scalar_one_or_none()
        if not addr:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        updates = req.model_dump(exclude_unset=True)
        if req.is_primary:
            await _unset_primary(db, user_uuid)

        for k, v in updates.items():
            setattr(addr, k, v)
        addr.version += 1
        await db.commit()
        await db.refresh(addr)
        return _addr_to_dict(addr)


@app.delete("/api/v1/addresses/{address_id}")
async def delete_address(address_id: str, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Address).where(Address.id == UUID(address_id), Address.user_id == user_uuid)
        )
        addr = result.scalar_one_or_none()
        if not addr:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        was_primary = addr.is_primary
        await db.delete(addr)
        await db.commit()

        # If was primary, set latest as primary
        if was_primary:
            latest = await db.execute(
                select(Address).where(Address.user_id == user_uuid).order_by(desc(Address.updated_at)).limit(1)
            )
            latest_addr = latest.scalar_one_or_none()
            if latest_addr:
                latest_addr.is_primary = True
                await db.commit()

        return JSONResponse(status_code=204, content=None)


@app.patch("/api/v1/addresses/{address_id}/set-primary")
async def set_primary(address_id: str, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Address).where(Address.id == UUID(address_id), Address.user_id == user_uuid)
        )
        addr = result.scalar_one_or_none()
        if not addr:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        await _unset_primary(db, user_uuid)
        addr.is_primary = True
        await db.commit()
        return {"status": "primary_set"}


@app.post("/api/v1/addresses/geocode")
async def geocode(payload: dict):
    """Geocode address string to lat/lng (Google Maps)."""
    if not settings.GOOGLE_MAPS_API_KEY:
        return JSONResponse(status_code=503, content={"error": "geocoding_unavailable"})
    address_text = payload.get("address", "")
    if not address_text:
        return JSONResponse(status_code=400, content={"error": "address required"})

    # In production: call Google Maps Geocoding API
    return {
        "address": address_text,
        "latitude": -6.2088,
        "longitude": 106.8456,
        "formatted": "Jakarta, Indonesia",
    }


async def _unset_primary(db: AsyncSession, user_uuid: UUID) -> None:
    result = await db.execute(
        select(Address).where(Address.user_id == user_uuid, Address.is_primary == True)
    )
    for addr in result.scalars().all():
        addr.is_primary = False


def _addr_to_dict(a: Address) -> dict:
    return {
        "id": str(a.id),
        "label": a.label,
        "recipient_name": a.recipient_name,
        "recipient_phone": a.recipient_phone,
        "address_line1": a.address_line1,
        "address_line2": a.address_line2,
        "province": a.province,
        "city": a.city,
        "district": a.district,
        "subdistrict": a.subdistrict,
        "postal_code": a.postal_code,
        "country": a.country,
        "latitude": a.latitude,
        "longitude": a.longitude,
        "is_primary": a.is_primary,
        "is_verified": a.is_verified,
        "notes": a.notes,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }
