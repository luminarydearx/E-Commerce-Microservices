"""Dispute & Refund Service — buyer can dispute orders, upload evidence, mediate."""
from __future__ import annotations

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
from sqlalchemy import String, Integer, Text, Boolean, DateTime
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ENVIRONMENT: str = "development"
    PORT: int = 8013
    DATABASE_URL: str
    REDIS_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    OTEL_ENDPOINT: str = "localhost:4317"
    DISPUTE_WINDOW_DAYS: int = 7  # buyer can dispute within 7 days after delivery
    SELLER_RESPONSE_HOURS: int = 48
    MAX_EVIDENCE_FILES: int = 5


settings = Settings()  # type: ignore
engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=20)
logger = logging.getLogger("dispute_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Base(DeclarativeBase):
    pass


class Dispute(Base):
    __tablename__ = "disputes"
    __table_args__ = {"schema": "dispute"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    order_item_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    buyer_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    seller_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    reason: Mapped[str] = mapped_column(String(50), nullable=False)  # ITEM_NOT_AS_DESCRIBED, DAMAGED, NOT_RECEIVED, WRONG_ITEM, OTHER
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_files: Mapped[list[str] | None] = mapped_column(JSONB)  # list of URLs

    requested_refund_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_refund_amount: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)  # OPEN, SELLER_RESPONDED, ESCALATED, RESOLVED, REJECTED, CANCELLED
    resolution: Mapped[str | None] = mapped_column(String(20))  # FULL_REFUND, PARTIAL_REFUND, REPLACE, REJECT
    resolution_note: Mapped[str | None] = mapped_column(Text)

    seller_response: Mapped[str | None] = mapped_column(Text)
    seller_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    buyer_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resolved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    seller_response_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class DisputeMessage(Base):
    __tablename__ = "dispute_messages"
    __table_args__ = {"schema": "dispute"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dispute_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sender_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20))  # buyer, seller, admin
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# Schemas
class DisputeCreate(BaseModel):
    order_id: str
    order_item_id: str | None = None
    reason: str
    description: str = Field(max_length=2000)
    evidence_files: list[str] = Field(default=[], max_length=5)
    requested_refund_amount: int = Field(ge=0)


class SellerResponse(BaseModel):
    message: str = Field(max_length=2000)
    proposed_resolution: str  # ACCEPT_REFUND, REJECT, OFFER_PARTIAL, OFFER_REPLACE
    proposed_amount: int | None = None


class EscalateRequest(BaseModel):
    reason: str = Field(max_length=500)


class AdminResolve(BaseModel):
    resolution: str  # FULL_REFUND, PARTIAL_REFUND, REPLACE, REJECT
    refund_amount: int | None = None
    note: str = Field(default="", max_length=1000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting dispute-service")
    yield
    await redis_client.close()
    await engine.dispose()


app = FastAPI(title="Dispute Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "dispute-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    return request.headers.get("X-User-Id", "")


def get_user_roles(request: Request) -> list[str]:
    roles = request.headers.get("X-User-Roles", "")
    return [r.strip() for r in roles.split(",") if r.strip()]


# ===== Routes =====

@app.post("/api/v1/disputes")
async def create_dispute(req: DisputeCreate, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    if req.reason not in ("ITEM_NOT_AS_DESCRIBED", "DAMAGED", "NOT_RECEIVED", "WRONG_ITEM", "OTHER"):
        return JSONResponse(status_code=400, content={"error": "invalid_reason"})

    if len(req.evidence_files) > settings.MAX_EVIDENCE_FILES:
        return JSONResponse(status_code=400, content={"error": "too_many_evidence_files"})

    async with AsyncSessionLocal() as db:
        # Check: no existing OPEN dispute for same order
        existing = await db.execute(
            select(Dispute).where(
                Dispute.order_id == UUID(req.order_id),
                Dispute.buyer_id == UUID(uid),
                Dispute.status.in_(["OPEN", "SELLER_RESPONDED", "ESCALATED"]),
            )
        )
        if existing.scalar_one_or_none():
            return JSONResponse(status_code=409, content={"error": "dispute_already_open"})

        # TODO: verify buyer actually purchased this order & it's delivered
        # In production: call order-service via gRPC

        dispute = Dispute(
            id=uuid4(),
            order_id=UUID(req.order_id),
            order_item_id=UUID(req.order_item_id) if req.order_item_id else None,
            buyer_id=UUID(uid),
            seller_id=UUID("00000000-0000-0000-0000-000000000000"),  # TODO: from order
            reason=req.reason,
            description=req.description,
            evidence_files=req.evidence_files,
            requested_refund_amount=req.requested_refund_amount,
            seller_response_deadline=datetime.now(timezone.utc) + timedelta(hours=settings.SELLER_RESPONSE_HOURS),
        )
        db.add(dispute)
        await db.commit()
        await db.refresh(dispute)

        # Publish event (notification to seller)
        logger.info("dispute opened", extra={"dispute_id": str(dispute.id), "order_id": req.order_id})

        return _dispute_to_dict(dispute)


@app.get("/api/v1/disputes")
async def list_disputes(request: Request, page: int = 0, size: int = 20, status_filter: str | None = None):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    async with AsyncSessionLocal() as db:
        stmt = select(Dispute)
        count_stmt = select(func.count(Dispute.id))

        # Filter by role
        roles = get_user_roles(request)
        if "admin" in roles or "superadmin" in roles:
            pass  # see all
        elif "seller" in roles:
            stmt = stmt.where(Dispute.seller_id == UUID(uid))
            count_stmt = count_stmt.where(Dispute.seller_id == UUID(uid))
        else:  # buyer
            stmt = stmt.where(Dispute.buyer_id == UUID(uid))
            count_stmt = count_stmt.where(Dispute.buyer_id == UUID(uid))

        if status_filter:
            stmt = stmt.where(Dispute.status == status_filter)
            count_stmt = count_stmt.where(Dispute.status == status_filter)

        stmt = stmt.order_by(desc(Dispute.created_at)).offset(page * size).limit(size)
        result = await db.execute(stmt)
        disputes = result.scalars().all()
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        return {"data": [_dispute_to_dict(d) for d in disputes], "total": total, "page": page, "size": size}


@app.get("/api/v1/disputes/{dispute_id}")
async def get_dispute(dispute_id: str, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Dispute).where(Dispute.id == UUID(dispute_id)))
        dispute = result.scalar_one_or_none()
        if not dispute:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        # Authorization
        roles = get_user_roles(request)
        if "admin" not in roles and "superadmin" not in roles:
            if dispute.buyer_id != UUID(uid) and dispute.seller_id != UUID(uid):
                return JSONResponse(status_code=403, content={"error": "forbidden"})

        # Include messages
        msgs_result = await db.execute(
            select(DisputeMessage).where(DisputeMessage.dispute_id == dispute.id).order_by(DisputeMessage.created_at)
        )
        messages = msgs_result.scalars().all()

        d = _dispute_to_dict(dispute)
        d["messages"] = [_msg_to_dict(m) for m in messages]
        return d


@app.post("/api/v1/disputes/{dispute_id}/seller-response")
async def seller_response(dispute_id: str, req: SellerResponse, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Dispute).where(Dispute.id == UUID(dispute_id)))
        dispute = result.scalar_one_or_none()
        if not dispute:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        if dispute.seller_id != UUID(uid):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        if dispute.status not in ("OPEN",):
            return JSONResponse(status_code=400, content={"error": "cannot_respond"})

        dispute.seller_response = req.message
        dispute.seller_response_at = datetime.now(timezone.utc)
        dispute.status = "SELLER_RESPONDED"

        # Add message
        msg = DisputeMessage(
            id=uuid4(),
            dispute_id=dispute.id,
            sender_id=UUID(uid),
            sender_role="seller",
            message=req.message,
        )
        db.add(msg)

        # If seller accepts, mark as resolved
        if req.proposed_resolution == "ACCEPT_REFUND":
            dispute.status = "RESOLVED"
            dispute.resolution = "FULL_REFUND"
            dispute.approved_refund_amount = dispute.requested_refund_amount
            dispute.resolved_at = datetime.now(timezone.utc)
            # TODO: trigger refund via payment-service

        await db.commit()
        return _dispute_to_dict(dispute)


@app.post("/api/v1/disputes/{dispute_id}/escalate")
async def escalate(dispute_id: str, req: EscalateRequest, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Dispute).where(Dispute.id == UUID(dispute_id)))
        dispute = result.scalar_one_or_none()
        if not dispute:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        if dispute.buyer_id != UUID(uid):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        if dispute.status not in ("SELLER_RESPONDED",):
            return JSONResponse(status_code=400, content={"error": "cannot_escalate"})

        dispute.buyer_escalated = True
        dispute.escalated_at = datetime.now(timezone.utc)
        dispute.status = "ESCALATED"

        msg = DisputeMessage(
            id=uuid4(),
            dispute_id=dispute.id,
            sender_id=UUID(uid),
            sender_role="buyer",
            message=f"Escalated to admin: {req.reason}",
        )
        db.add(msg)
        await db.commit()
        return _dispute_to_dict(dispute)


@app.post("/api/v1/disputes/{dispute_id}/messages")
async def add_message(dispute_id: str, payload: dict, request: Request):
    uid = get_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    message = payload.get("message", "")
    if not message or len(message) > 2000:
        return JSONResponse(status_code=400, content={"error": "invalid_message"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Dispute).where(Dispute.id == UUID(dispute_id)))
        dispute = result.scalar_one_or_none()
        if not dispute:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        roles = get_user_roles(request)
        sender_role = "admin" if "admin" in roles else ("seller" if "seller" in roles else "buyer")

        if sender_role == "buyer" and dispute.buyer_id != UUID(uid):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        if sender_role == "seller" and dispute.seller_id != UUID(uid):
            return JSONResponse(status_code=403, content={"error": "forbidden"})

        msg = DisputeMessage(
            id=uuid4(),
            dispute_id=dispute.id,
            sender_id=UUID(uid),
            sender_role=sender_role,
            message=message,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return _msg_to_dict(msg)


@app.post("/api/v1/admin/disputes/{dispute_id}/resolve")
async def admin_resolve(dispute_id: str, req: AdminResolve, request: Request):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        return JSONResponse(status_code=403, content={"error": "admin_required"})
    uid = get_user_id(request)

    if req.resolution not in ("FULL_REFUND", "PARTIAL_REFUND", "REPLACE", "REJECT"):
        return JSONResponse(status_code=400, content={"error": "invalid_resolution"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Dispute).where(Dispute.id == UUID(dispute_id)))
        dispute = result.scalar_one_or_none()
        if not dispute:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        dispute.status = "RESOLVED" if req.resolution != "REJECT" else "REJECTED"
        dispute.resolution = req.resolution
        dispute.resolution_note = req.note
        dispute.approved_refund_amount = req.refund_amount
        dispute.resolved_by = UUID(uid)
        dispute.resolved_at = datetime.now(timezone.utc)

        await db.commit()
        return _dispute_to_dict(dispute)


def _dispute_to_dict(d: Dispute) -> dict:
    return {
        "id": str(d.id),
        "order_id": str(d.order_id),
        "order_item_id": str(d.order_item_id) if d.order_item_id else None,
        "buyer_id": str(d.buyer_id),
        "seller_id": str(d.seller_id),
        "reason": d.reason,
        "description": d.description,
        "evidence_files": d.evidence_files or [],
        "requested_refund_amount": d.requested_refund_amount,
        "approved_refund_amount": d.approved_refund_amount,
        "status": d.status,
        "resolution": d.resolution,
        "resolution_note": d.resolution_note,
        "seller_response": d.seller_response,
        "seller_response_at": d.seller_response_at.isoformat() if d.seller_response_at else None,
        "buyer_escalated": d.buyer_escalated,
        "escalated_at": d.escalated_at.isoformat() if d.escalated_at else None,
        "resolved_by": str(d.resolved_by) if d.resolved_by else None,
        "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
        "seller_response_deadline": d.seller_response_deadline.isoformat(),
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


def _msg_to_dict(m: DisputeMessage) -> dict:
    return {
        "id": str(m.id),
        "dispute_id": str(m.dispute_id),
        "sender_id": str(m.sender_id),
        "sender_role": m.sender_role,
        "message": m.message,
        "attachments": m.attachments or [],
        "created_at": m.created_at.isoformat(),
    }
