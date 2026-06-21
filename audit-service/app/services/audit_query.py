"""Query audit log & error log."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.audit import AuditLog, ErrorLog

logger = logging.getLogger("audit_service.query")


class AuditQueryService:
    """Read audit log & error log."""

    async def list_audit(
        self,
        action: str | None = None,
        actor_user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: int = 0,
        size: int = 50,
    ) -> dict:
        async with AsyncSessionLocal() as db:
            stmt = select(AuditLog).order_by(desc(AuditLog.timestamp))
            count_stmt = select(func.count(AuditLog.audit_id))
            conditions = []
            if action:
                conditions.append(AuditLog.action == action)
            if actor_user_id:
                conditions.append(AuditLog.actor_user_id == actor_user_id)
            if resource_type:
                conditions.append(AuditLog.resource_type == resource_type)
            if resource_id:
                conditions.append(AuditLog.resource_id == resource_id)
            if start:
                conditions.append(AuditLog.timestamp >= datetime.fromisoformat(start))
            if end:
                conditions.append(AuditLog.timestamp <= datetime.fromisoformat(end))

            if conditions:
                stmt = stmt.where(and_(*conditions))
                count_stmt = count_stmt.where(and_(*conditions))

            stmt = stmt.offset(page * size).limit(size)
            result = await db.execute(stmt)
            entries = result.scalars().all()
            count_result = await db.execute(count_stmt)
            total = count_result.scalar() or 0

            return {
                "data": [_audit_to_dict(e) for e in entries],
                "total": total,
                "page": page,
                "size": size,
            }

    async def list_errors(
        self,
        service: str | None = None,
        level: str | None = None,
        fingerprint: str | None = None,
        page: int = 0,
        size: int = 50,
    ) -> dict:
        async with AsyncSessionLocal() as db:
            stmt = select(ErrorLog).order_by(desc(ErrorLog.timestamp))
            count_stmt = select(func.count(ErrorLog.error_id))
            conditions = []
            if service:
                conditions.append(ErrorLog.service == service)
            if level:
                conditions.append(ErrorLog.level == level)
            if fingerprint:
                conditions.append(ErrorLog.fingerprint == fingerprint)
            if conditions:
                stmt = stmt.where(and_(*conditions))
                count_stmt = count_stmt.where(and_(*conditions))
            stmt = stmt.offset(page * size).limit(size)
            result = await db.execute(stmt)
            entries = result.scalars().all()
            count_result = await db.execute(count_stmt)
            total = count_result.scalar() or 0
            return {
                "data": [_error_to_dict(e) for e in entries],
                "total": total,
                "page": page,
                "size": size,
            }

    async def verify_chain(self, start: str, end: str) -> dict:
        """Verify hash chain integrity."""
        async with AsyncSessionLocal() as db:
            stmt = select(AuditLog).order_by(AuditLog.timestamp).where(
                and_(
                    AuditLog.timestamp >= datetime.fromisoformat(start),
                    AuditLog.timestamp <= datetime.fromisoformat(end),
                )
            )
            result = await db.execute(stmt)
            entries = list(result.scalars().all())

            total = len(entries)
            broken = 0
            prev_hash = None
            for entry in entries:
                if entry.prev_hash != prev_hash:
                    broken += 1
                    logger.warning(
                        "audit chain broken",
                        extra={"audit_id": str(entry.audit_id), "expected": prev_hash, "got": entry.prev_hash},
                    )
                prev_hash = entry.row_hash

            return {
                "total_entries": total,
                "broken_links": broken,
                "verified": broken == 0,
                "period": {"start": start, "end": end},
            }


def _audit_to_dict(e: AuditLog) -> dict:
    return {
        "audit_id": str(e.audit_id),
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "producer": e.producer,
        "action": e.action,
        "actor_user_id": e.actor_user_id,
        "actor_role": e.actor_role,
        "actor_ip": e.actor_ip,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "before": e.before,
        "after": e.after,
        "correlation_id": e.correlation_id,
        "request_id": e.request_id,
        "event_id": e.event_id,
        "row_hash": e.row_hash,
    }


def _error_to_dict(e: ErrorLog) -> dict:
    return {
        "error_id": str(e.error_id),
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "service": e.service,
        "environment": e.environment,
        "level": e.level,
        "error_type": e.error_type,
        "message": e.message,
        "stack_trace": e.stack_trace,
        "context": e.context,
        "request_id": e.request_id,
        "correlation_id": e.correlation_id,
        "user_id": e.user_id,
        "fingerprint": e.fingerprint,
        "pii_redacted": e.pii_redacted,
    }
