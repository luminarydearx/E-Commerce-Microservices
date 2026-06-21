"""Audit event ingestion with hash chain."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog, ErrorLog, AnomalyAlert

logger = logging.getLogger("audit_service.ingest")


def compute_row_hash(timestamp: str, producer: str, action: str,
                     actor_user_id: str | None, resource_type: str,
                     resource_id: str | None, before: str, after: str,
                     prev_hash: str | None) -> str:
    """Compute SHA256 hash of row contents for tamper-evidence."""
    payload = f"{timestamp}|{producer}|{action}|{actor_user_id}|{resource_type}|{resource_id}|{before}|{after}|{prev_hash or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def get_last_hash(db: AsyncSession) -> str | None:
    """Get the row_hash of the latest audit entry."""
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(1)
    )
    last = result.scalar_one_or_none()
    return last.row_hash if last else None


async def ingest_audit_event(db: AsyncSession, event: dict[str, Any]) -> AuditLog:
    """Insert audit event with hash chain."""
    actor = event.get("actor", {}) or {}
    resource = event.get("resource", {}) or {}

    # Serialize before/after
    before = resource.get("before")
    after = resource.get("after")
    before_json = json.dumps(before, default=str, sort_keys=True) if before is not None else ""
    after_json = json.dumps(after, default=str, sort_keys=True) if after is not None else ""

    timestamp_str = event.get("occurred_at") or datetime.now(timezone.utc).isoformat()
    prev_hash = await get_last_hash(db)
    row_hash = compute_row_hash(
        timestamp_str,
        event.get("producer", ""),
        event.get("action", ""),
        str(actor.get("user_id", "")) if actor.get("user_id") else None,
        resource.get("type", ""),
        str(resource.get("id", "")) if resource.get("id") else None,
        before_json,
        after_json,
        prev_hash,
    )

    entry = AuditLog(
        event_id=event.get("event_id"),
        timestamp=datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if isinstance(timestamp_str, str) else timestamp_str,
        producer=event.get("producer", "unknown"),
        action=event.get("action", ""),
        actor_user_id=str(actor.get("user_id")) if actor.get("user_id") else None,
        actor_role=actor.get("role"),
        actor_ip=actor.get("ip"),
        actor_user_agent=actor.get("user_agent"),
        resource_type=resource.get("type", ""),
        resource_id=str(resource.get("id")) if resource.get("id") else None,
        before=before,
        after=after,
        correlation_id=event.get("correlation_id"),
        request_id=event.get("request_id"),
        prev_hash=prev_hash,
        row_hash=row_hash,
    )
    db.add(entry)
    await db.flush()
    return entry


# PII patterns for redaction in error logs
PII_PATTERNS = [
    # Email
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[REDACTED_EMAIL]"),
    # Phone (Indonesian)
    (r"\+62\d{8,12}", "[REDACTED_PHONE]"),
    # Credit card (16 digits)
    (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "[REDACTED_CARD]"),
    # UUID (could be user_id, but keep for trace)
    # IP address (keep for security)
]


def redact_pii(text: str) -> tuple[str, bool]:
    """Redact PII from text. Returns (redacted_text, was_redacted)."""
    import re
    if not text:
        return text, False
    redacted = text
    changed = False
    for pattern, replacement in PII_PATTERNS:
        new_text = re.sub(pattern, replacement, redacted)
        if new_text != redacted:
            changed = True
            redacted = new_text
    return redacted, changed


def compute_error_fingerprint(service: str, error_type: str | None, stack_trace: str | None) -> str:
    """Compute fingerprint for error grouping."""
    import hashlib
    # Sanitize stack trace: remove file paths and line numbers for grouping
    import re
    sanitized = ""
    if stack_trace:
        # Extract just function names and exception types
        lines = stack_trace.split("\n")[:10]
        for line in lines:
            # Remove file paths and line numbers
            cleaned = re.sub(r'File ".*?", line \d+', 'File "..."', line)
            sanitized += cleaned + "\n"
    payload = f"{service}|{error_type or ''}|{sanitized}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


async def ingest_error(db: AsyncSession, payload: dict) -> ErrorLog:
    """Insert error log entry."""
    message = payload.get("message", "")
    stack_trace = payload.get("stack_trace", "")
    redacted_msg, _ = redact_pii(message)
    redacted_stack, pii_redacted = redact_pii(stack_trace)

    fingerprint = compute_error_fingerprint(
        payload.get("service", "unknown"),
        payload.get("error_type"),
        stack_trace,
    )

    entry = ErrorLog(
        service=payload.get("service", "unknown"),
        environment=payload.get("environment", "development"),
        level=payload.get("level", "error"),
        error_type=payload.get("error_type"),
        message=redacted_msg,
        stack_trace=redacted_stack,
        context=payload.get("context"),
        request_id=payload.get("request_id"),
        correlation_id=payload.get("correlation_id"),
        user_id=payload.get("user_id"),
        fingerprint=fingerprint,
        pii_redacted=pii_redacted,
    )
    db.add(entry)
    await db.flush()
    return entry


# ===== Anomaly Detection Rules =====

async def check_anomaly_rules(db: AsyncSession, event: dict) -> AnomalyAlert | None:
    """Apply rule-based anomaly detection to audit event."""
    action = event.get("action", "")
    actor = event.get("actor", {}) or {}
    ip = actor.get("ip")
    user_id = str(actor.get("user_id", "")) if actor.get("user_id") else None

    # Rule 1: Multiple failed logins from same IP
    if action == "user.login" and event.get("resource", {}).get("after", {}).get("result") == "failed":
        # Check recent failures from same IP
        from sqlalchemy import func
        result = await db.execute(
            select(func.count(AuditLog.audit_id)).where(
                AuditLog.actor_ip == ip,
                AuditLog.action == "user.login",
                AuditLog.timestamp >= datetime.now(timezone.utc).replace(second=0)
            )
        )
        count = result.scalar() or 0
        if count >= 10:
            return AnomalyAlert(
                rule_name="multiple_failed_logins",
                severity="warning",
                description=f"10+ failed login attempts from IP {ip} in 5 min",
                actor_user_id=user_id,
                actor_ip=ip,
                evidence={"count": count, "window_minutes": 5},
            )

    # Rule 2: Large order value
    if action == "order.created":
        total = event.get("resource", {}).get("after", {}).get("total")
        if total and float(total) > 50_000_000:  # > 50 juta
            return AnomalyAlert(
                rule_name="large_order_value",
                severity="warning",
                description=f"Order > Rp 50 juta by user {user_id}",
                actor_user_id=user_id,
                actor_ip=ip,
                evidence={"total": total},
            )

    # Rule 3: Multiple registration from same IP
    if action == "user.register":
        from sqlalchemy import func
        result = await db.execute(
            select(func.count(AuditLog.audit_id)).where(
                AuditLog.actor_ip == ip,
                AuditLog.action == "user.register",
                AuditLog.timestamp >= datetime.now(timezone.utc).replace(minute=datetime.now().minute - 1)
            )
        )
        count = result.scalar() or 0
        if count >= 5:
            return AnomalyAlert(
                rule_name="multiple_registrations",
                severity="critical",
                description=f"5+ registrations from IP {ip} in 1 min — possible bot",
                actor_user_id=user_id,
                actor_ip=ip,
                evidence={"count": count},
            )

    # Rule 4: Payment refund spike
    if action == "payment.refunded":
        from sqlalchemy import func
        result = await db.execute(
            select(func.count(AuditLog.audit_id)).where(
                AuditLog.action == "payment.refunded",
                AuditLog.timestamp >= datetime.now(timezone.utc).replace(hour=datetime.now().hour - 1)
            )
        )
        count = result.scalar() or 0
        if count >= 5:
            return AnomalyAlert(
                rule_name="refund_spike",
                severity="critical",
                description=f"5+ refunds in 1 hour — possible abuse",
                evidence={"count": count},
            )

    return None
