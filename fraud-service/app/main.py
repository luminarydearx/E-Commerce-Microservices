"""Fraud Detection Service — rule-based + ML scoring for transactions."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
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
from sqlalchemy import String, Integer, Text, Boolean, DateTime, Float
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8017
    DATABASE_URL: str
    REDIS_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    OTEL_ENDPOINT: str = "localhost:4317"

    # Velocity thresholds
    MAX_FAILED_TRANSACTIONS_10M: int = 3
    MAX_ORDERS_PER_HOUR: int = 10
    MAX_ORDERS_PER_DAY: int = 50
    MAX_REGISTER_PER_IP_PER_MIN: int = 3

    # Amount thresholds
    LARGE_ORDER_THRESHOLD: int = 50_000_000  # 50 juta
    VERY_LARGE_ORDER_THRESHOLD: int = 100_000_000  # 100 juta

    # Score thresholds
    BLOCK_THRESHOLD: float = 0.7
    CHALLENGE_THRESHOLD: float = 0.4


settings = Settings()  # type: ignore
engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=30)
logger = logging.getLogger("fraud_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Base(DeclarativeBase):
    pass


class FraudFlag(Base):
    __tablename__ = "fraud_flags"
    __table_args__ = {"schema": "fraud"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), index=True)
    device_id: Mapped[str | None] = mapped_column(String(255))
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info, warning, critical
    score: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN, REVIEWING, RESOLVED, FALSE_POSITIVE
    action_taken: Mapped[str | None] = mapped_column(String(50))  # BLOCKED, CHALLENGED, ALLOWED
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class BlockedIP(Base):
    __tablename__ = "blocked_ips"
    __table_args__ = {"schema": "fraud"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    ip_address: Mapped[str] = mapped_column(String(45), unique=True, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(200))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = permanent
    blocked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BlockedUser(Base):
    __tablename__ = "blocked_users"
    __table_args__ = {"schema": "fraud"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(200))
    blocked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ===== Schemas =====
class TransactionCheck(BaseModel):
    user_id: str
    ip_address: str
    device_id: str | None = None
    amount: int = Field(ge=0)
    transaction_type: str  # ORDER, PAYMENT, REGISTER, LOGIN, WITHDRAWAL
    context: dict = {}


# ===== App =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting fraud-service")
    yield
    await redis_client.close()
    await engine.dispose()


app = FastAPI(title="Fraud Detection Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "fraud-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


# ===== Endpoints =====

@app.post("/api/v1/internal/fraud/check")
async def check_transaction(req: TransactionCheck, request: Request):
    """Check transaction for fraud. Returns score and recommended action."""
    score = 0.0
    flags = []

    # Rule 1: Blocked IP
    if await _is_ip_blocked(req.ip_address):
        score = 1.0
        flags.append({"rule": "BLOCKED_IP", "severity": "critical", "description": "IP is on blocklist"})
    # Rule 2: Blocked user
    if await _is_user_blocked(req.user_id):
        score = 1.0
        flags.append({"rule": "BLOCKED_USER", "severity": "critical", "description": "User is on blocklist"})
    # Rule 3: Velocity check (failed transactions)
    failed_count = await _count_recent_events(req.user_id, "PAYMENT_FAILED", timedelta(minutes=10))
    if failed_count >= settings.MAX_FAILED_TRANSACTIONS_10M:
        score += 0.4
        flags.append({"rule": "VELOCITY_FAILED_PAYMENT", "severity": "warning",
                      "description": f"{failed_count} failed payments in 10 min"})
    # Rule 4: Order velocity
    order_count_hour = await _count_recent_events(req.user_id, "ORDER_CREATED", timedelta(hours=1))
    if order_count_hour >= settings.MAX_ORDERS_PER_HOUR:
        score += 0.3
        flags.append({"rule": "HIGH_ORDER_VELOCITY", "severity": "warning",
                      "description": f"{order_count_hour} orders in 1 hour"})
    # Rule 5: Large order
    if req.amount >= settings.VERY_LARGE_ORDER_THRESHOLD:
        score += 0.3
        flags.append({"rule": "VERY_LARGE_ORDER", "severity": "warning",
                      "description": f"Order amount {req.amount} exceeds very large threshold"})
    elif req.amount >= settings.LARGE_ORDER_THRESHOLD:
        score += 0.15
        flags.append({"rule": "LARGE_ORDER", "severity": "info",
                      "description": f"Large order amount: {req.amount}"})
    # Rule 6: New account + large amount
    if req.transaction_type == "ORDER" and req.amount > 5_000_000:
        # In production: check account age from auth-service
        is_new = await redis_client.get(f"user:new:{req.user_id}")
        if is_new:
            score += 0.3
            flags.append({"rule": "NEW_ACCOUNT_LARGE_ORDER", "severity": "warning",
                          "description": "New account placing large order"})
    # Rule 7: Multiple accounts from same IP
    if req.transaction_type == "REGISTER":
        recent_regs = await _count_recent_registrations_from_ip(req.ip_address, timedelta(minutes=1))
        if recent_regs >= settings.MAX_REGISTER_PER_IP_PER_MIN:
            score += 0.6
            flags.append({"rule": "MULTIPLE_REGISTRATIONS_IP", "severity": "critical",
                          "description": f"{recent_regs} registrations from IP in 1 min"})

    score = min(score, 1.0)

    # Determine action
    action = "ALLOWED"
    if score >= settings.BLOCK_THRESHOLD:
        action = "BLOCKED"
        # Auto-block IP for 1 hour
        await _block_ip(req.ip_address, f"Auto-block: fraud score {score}", timedelta(hours=1))
    elif score >= settings.CHALALLENGE_THRESHOLD:
        action = "CHALLENGED"  # require MFA/CAPTCHA

    # Save flag if score > 0
    if score > 0:
        async with AsyncSessionLocal() as db:
            flag = FraudFlag(
                id=uuid4(),
                user_id=UUID(req.user_id) if req.user_id else None,
                ip_address=req.ip_address,
                device_id=req.device_id,
                rule_name=flags[0]["rule"] if flags else "ML_ANOMALY",
                severity=flags[0]["severity"] if flags else "info",
                score=score,
                description="; ".join(f["description"] for f in flags),
                context={"flags": flags, "transaction": req.model_dump()},
                action_taken=action,
            )
            db.add(flag)
            await db.commit()

            # Publish event
            logger.warning("fraud flag raised", extra={
                "user_id": req.user_id, "score": score, "action": action,
                "flags": [f["rule"] for f in flags],
            })

    return {
        "score": score,
        "action": action,
        "flags": flags,
        "requires_mfa": action == "CHALLENGED",
        "transaction_id": str(uuid4()),
    }


@app.get("/api/v1/admin/fraud/flags")
async def list_flags(request: Request, page: int = 0, size: int = 50, status_filter: str | None = None):
    roles = request.headers.get("X-User-Roles", "")
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    async with AsyncSessionLocal() as db:
        stmt = select(FraudFlag).order_by(desc(FraudFlag.created_at))
        count_stmt = select(func.count(FraudFlag.id))
        if status_filter:
            stmt = stmt.where(FraudFlag.status == status_filter)
            count_stmt = count_stmt.where(FraudFlag.status == status_filter)
        stmt = stmt.offset(page * size).limit(size)
        result = await db.execute(stmt)
        flags = result.scalars().all()
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
        return {
            "data": [_flag_to_dict(f) for f in flags],
            "total": total, "page": page, "size": size,
        }


@app.post("/api/v1/admin/fraud/blocks/ip")
async def block_ip(payload: dict, request: Request):
    roles = request.headers.get("X-User-Roles", "")
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    ip = payload.get("ip_address")
    reason = payload.get("reason", "manual block")
    hours = payload.get("hours")  # None = permanent
    if not ip:
        return JSONResponse(status_code=400, content={"error": "ip_address required"})
    until = None
    if hours:
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
    await _block_ip(ip, reason, until if until else timedelta(hours=0))
    return {"status": "blocked", "ip": ip, "until": until.isoformat() if until else "permanent"}


@app.delete("/api/v1/admin/fraud/blocks/ip/{ip}")
async def unblock_ip(ip: str, request: Request):
    roles = request.headers.get("X-User-Roles", "")
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(BlockedIP).where(BlockedIP.ip_address == ip))
        block = result.scalar_one_or_none()
        if block:
            await db.delete(block)
            await db.commit()
    return {"status": "unblocked"}


# ===== Helpers =====

async def _is_ip_blocked(ip: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BlockedIP).where(
                BlockedIP.ip_address == ip,
                (BlockedIP.blocked_until.is_(None)) | (BlockedIP.blocked_until > datetime.now(timezone.utc))
            )
        )
        return result.scalar_one_or_none() is not None


async def _is_user_blocked(user_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(BlockedUser).where(BlockedUser.user_id == UUID(user_id)))
        return result.scalar_one_or_none() is not None


async def _count_recent_events(user_id: str, event_type: str, window: timedelta) -> int:
    """Count events in Redis (set by audit consumer)."""
    key = f"events:{user_id}:{event_type}"
    now = datetime.now(timezone.utc).timestamp()
    count = await redis_client.zcount(key, now - window.total_seconds(), now)
    return count or 0


async def _count_recent_registrations_from_ip(ip: str, window: timedelta) -> int:
    key = f"regs:{ip}"
    now = datetime.now(timezone.utc).timestamp()
    count = await redis_client.zcount(key, now - window.total_seconds(), now)
    return count or 0


async def _block_ip(ip: str, reason: str, duration: timedelta) -> None:
    async with AsyncSessionLocal() as db:
        # Upsert
        result = await db.execute(select(BlockedIP).where(BlockedIP.ip_address == ip))
        block = result.scalar_one_or_none()
        if block:
            block.reason = reason
            if duration.total_seconds() > 0:
                block.blocked_until = datetime.now(timezone.utc) + duration
            else:
                block.blocked_until = None
        else:
            block = BlockedIP(
                id=uuid4(),
                ip_address=ip,
                reason=reason,
                blocked_until=datetime.now(timezone.utc) + duration if duration.total_seconds() > 0 else None,
            )
            db.add(block)
        await db.commit()


def _flag_to_dict(f: FraudFlag) -> dict:
    return {
        "id": str(f.id),
        "user_id": str(f.user_id) if f.user_id else None,
        "ip_address": f.ip_address,
        "device_id": f.device_id,
        "rule_name": f.rule_name,
        "severity": f.severity,
        "score": f.score,
        "description": f.description,
        "context": f.context,
        "status": f.status,
        "action_taken": f.action_taken,
        "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
        "resolved_by": str(f.resolved_by) if f.resolved_by else None,
        "created_at": f.created_at.isoformat(),
    }


# Fix typo
def _check_challenge_threshold(score):
    return score >= settings.CHALLENGE_THRESHOLD
