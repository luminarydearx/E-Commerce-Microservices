"""Loyalty & Membership Service — points, tiers, rewards, cashback."""
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
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8016
    DATABASE_URL: str
    REDIS_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    OTEL_ENDPOINT: str = "localhost:4317"

    # Tier thresholds (points)
    TIER_SILVER_MIN: int = 0
    TIER_GOLD_MIN: int = 1000
    TIER_PLATINUM_MIN: int = 5000
    TIER_DIAMOND_MIN: int = 20000

    # Points earning rate
    POINTS_PER_RUPIAH: float = 0.01  # 1 point per 100 IDR
    CASHBACK_PERCENT: dict = {"SILVER": 1, "GOLD": 2, "PLATINUM": 3, "DIAMOND": 5}


settings = Settings()  # type: ignore
engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=20)
logger = logging.getLogger("loyalty_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"
    __table_args__ = {"schema": "loyalty"}

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tier: Mapped[str] = mapped_column(String(20), default="SILVER")
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    lifetime_points: Mapped[int] = mapped_column(Integer, default=0)
    cashback_balance: Mapped[int] = mapped_column(Integer, default=0)  # in IDR
    tier_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    version: Mapped[int] = mapped_column(Integer, default=1)


class PointTransaction(Base):
    __tablename__ = "point_transactions"
    __table_args__ = {"schema": "loyalty"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # EARN, REDEEM, EXPIRE, ADJUST
    points: Mapped[int] = mapped_column(Integer, nullable=False)  # positive for earn, negative for redeem
    reason: Mapped[str] = mapped_column(String(100))
    reference_id: Mapped[str | None] = mapped_column(String(64))  # order_id, voucher_id, etc.
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Reward(Base):
    __tablename__ = "rewards"
    __table_args__ = {"schema": "loyalty"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(20))  # VOUCHER, CASHBACK, FREE_SHIPPING, PRODUCT
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[int] = mapped_column(Integer, default=0)  # IDR value or voucher amount
    min_tier: Mapped[str] = mapped_column(String(20), default="SILVER")
    stock: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RewardRedemption(Base):
    __tablename__ = "reward_redemptions"
    __table_args__ = {"schema": "loyalty"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    reward_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    points_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    voucher_code: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="ISSUED")  # ISSUED, USED, EXPIRED, CANCELLED
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ===== App =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting loyalty-service")
    yield
    await redis_client.close()
    await engine.dispose()


app = FastAPI(title="Loyalty Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "loyalty-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


def get_user_roles(request: Request) -> list[str]:
    return [r.strip() for r in request.headers.get("X-User-Roles", "").split(",") if r.strip()]


def get_tier_for_points(points: int) -> str:
    if points >= settings.TIER_DIAMOND_MIN:
        return "DIAMOND"
    if points >= settings.TIER_PLATINUM_MIN:
        return "PLATINUM"
    if points >= settings.TIER_GOLD_MIN:
        return "GOLD"
    return "SILVER"


def tier_rank(tier: str) -> int:
    return {"SILVER": 1, "GOLD": 2, "PLATINUM": 3, "DIAMOND": 4}.get(tier, 1)


# ===== Routes =====

@app.get("/api/v1/loyalty/me")
async def get_my_membership(request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Member).where(Member.user_id == user_uuid))
        member = result.scalar_one_or_none()
        if not member:
            # Auto-create membership
            member = Member(user_id=user_uuid, tier="SILVER", points_balance=0)
            db.add(member)
            await db.commit()
            await db.refresh(member)

        next_tier = None
        next_tier_points = 0
        if member.tier == "SILVER":
            next_tier = "GOLD"; next_tier_points = settings.TIER_GOLD_MIN - member.lifetime_points
        elif member.tier == "GOLD":
            next_tier = "PLATINUM"; next_tier_points = settings.TIER_PLATINUM_MIN - member.lifetime_points
        elif member.tier == "PLATINUM":
            next_tier = "DIAMOND"; next_tier_points = settings.TIER_DIAMOND_MIN - member.lifetime_points

        return {
            "user_id": str(member.user_id),
            "tier": member.tier,
            "points_balance": member.points_balance,
            "lifetime_points": member.lifetime_points,
            "cashback_balance": member.cashback_balance,
            "tier_updated_at": member.tier_updated_at.isoformat(),
            "next_tier": next_tier,
            "points_to_next_tier": max(0, next_tier_points),
            "cashback_rate_percent": settings.CASHBACK_PERCENT.get(member.tier, 1),
        }


@app.post("/api/v1/loyalty/earn")
async def earn_points(payload: dict, request: Request):
    """Internal: award points after order completion. Called by order-service."""
    user_id = payload.get("user_id")
    order_id = payload.get("order_id")
    amount = payload.get("amount", 0)  # in IDR
    if not user_id or amount <= 0:
        return JSONResponse(status_code=400, content={"error": "invalid_payload"})

    user_uuid = UUID(user_id)
    points_to_earn = int(amount * settings.POINTS_PER_RUPIAH)

    async with AsyncSessionLocal() as db:
        # Get or create member
        result = await db.execute(select(Member).where(Member.user_id == user_uuid))
        member = result.scalar_one_or_none()
        if not member:
            member = Member(user_id=user_uuid, tier="SILVER", points_balance=0, lifetime_points=0, cashback_balance=0)
            db.add(member)
            await db.flush()

        # Award points
        member.points_balance += points_to_earn
        member.lifetime_points += points_to_earn

        # Award cashback
        cashback_rate = settings.CASHBACK_PERCENT.get(member.tier, 1)
        cashback_amount = int(amount * cashback_rate / 100)
        member.cashback_balance += cashback_amount

        # Check tier upgrade
        new_tier = get_tier_for_points(member.lifetime_points)
        if tier_rank(new_tier) > tier_rank(member.tier):
            member.tier = new_tier
            member.tier_updated_at = datetime.now(timezone.utc)
            logger.info(f"user {user_id} upgraded to {new_tier}")

        # Record transaction
        tx = PointTransaction(
            id=uuid4(),
            user_id=user_uuid,
            type="EARN",
            points=points_to_earn,
            reason=f"Order {order_id}",
            reference_id=order_id,
            balance_after=member.points_balance,
            expires_at=datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1),
        )
        db.add(tx)
        await db.commit()

        return {
            "status": "earned",
            "points_earned": points_to_earn,
            "cashback_earned": cashback_amount,
            "new_balance": member.points_balance,
            "tier": member.tier,
        }


@app.post("/api/v1/loyalty/redeem")
async def redeem_reward(payload: dict, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    reward_id = payload.get("reward_id")
    if not reward_id:
        return JSONResponse(status_code=400, content={"error": "reward_id required"})

    async with AsyncSessionLocal() as db:
        # Get reward
        result = await db.execute(select(Reward).where(Reward.id == UUID(reward_id), Reward.is_active == True))
        reward = result.scalar_one_or_none()
        if not reward:
            return JSONResponse(status_code=404, content={"error": "reward_not_found"})

        # Get member
        result = await db.execute(select(Member).where(Member.user_id == user_uuid))
        member = result.scalar_one_or_none()
        if not member or member.points_balance < reward.points_cost:
            return JSONResponse(status_code=400, content={"error": "insufficient_points"})

        # Check tier
        if tier_rank(member.tier) < tier_rank(reward.min_tier):
            return JSONResponse(status_code=403, content={"error": "tier_too_low", "required": reward.min_tier})

        # Check stock
        if reward.stock is not None and reward.stock <= 0:
            return JSONResponse(status_code=400, content={"error": "out_of_stock"})

        # Deduct points
        member.points_balance -= reward.points_cost

        # Generate voucher code
        voucher_code = f"RWD{uuid4().hex[:8].upper()}"
        redemption = RewardRedemption(
            id=uuid4(),
            user_id=user_uuid,
            reward_id=reward.id,
            points_spent=reward.points_cost,
            voucher_code=voucher_code,
        )
        db.add(redemption)

        # Record point transaction
        tx = PointTransaction(
            id=uuid4(),
            user_id=user_uuid,
            type="REDEEM",
            points=-reward.points_cost,
            reason=f"Redeemed reward: {reward.name}",
            reference_id=str(reward.id),
            balance_after=member.points_balance,
        )
        db.add(tx)

        # Update reward stock
        if reward.stock is not None:
            reward.stock -= 1

        await db.commit()

        return {
            "status": "redeemed",
            "voucher_code": voucher_code,
            "reward": {
                "name": reward.name,
                "type": reward.type,
                "value": reward.value,
            },
            "points_spent": reward.points_cost,
            "remaining_balance": member.points_balance,
        }


@app.get("/api/v1/loyalty/rewards")
async def list_rewards(request: Request):
    uid = get_user_id(request)
    if not uid:
        # Public: return all
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Reward).where(Reward.is_active == True).order_by(Reward.points_cost)
            )
            rewards = result.scalars().all()
            return {"data": [_reward_to_dict(r) for r in rewards]}

    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        # Get user tier
        member_result = await db.execute(select(Member).where(Member.user_id == user_uuid))
        member = member_result.scalar_one_or_none()
        user_tier = member.tier if member else "SILVER"

        result = await db.execute(
            select(Reward).where(Reward.is_active == True).order_by(Reward.points_cost)
        )
        rewards = result.scalars().all()

        data = []
        for r in rewards:
            d = _reward_to_dict(r)
            d["can_redeem"] = tier_rank(user_tier) >= tier_rank(r.min_tier) and (member is None or member.points_balance >= r.points_cost)
            data.append(d)
        return {"data": data, "user_tier": user_tier}


@app.get("/api/v1/loyalty/transactions")
async def list_transactions(request: Request, page: int = 0, size: int = 20):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    user_uuid = UUID(uid)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PointTransaction).where(PointTransaction.user_id == user_uuid)
            .order_by(desc(PointTransaction.created_at)).offset(page * size).limit(size)
        )
        txs = result.scalars().all()
        count_result = await db.execute(
            select(func.count(PointTransaction.id)).where(PointTransaction.user_id == user_uuid)
        )
        total = count_result.scalar() or 0
        return {
            "data": [
                {
                    "id": str(t.id),
                    "type": t.type,
                    "points": t.points,
                    "reason": t.reason,
                    "reference_id": t.reference_id,
                    "balance_after": t.balance_after,
                    "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                    "created_at": t.created_at.isoformat(),
                }
                for t in txs
            ],
            "total": total, "page": page, "size": size,
        }


def _reward_to_dict(r: Reward) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "type": r.type,
        "points_cost": r.points_cost,
        "value": r.value,
        "min_tier": r.min_tier,
        "stock": r.stock,
    }
