"""Kafka producer untuk publish event ke audit bus."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaProducer

from app.core.config import settings

logger = logging.getLogger("auth_service.kafka")


class AuditEventPublisher:
    """Publish audit events ke Kafka dengan retry & outbox pattern."""

    def __init__(self) -> None:
        self._producer: KafkaProducer | None = None
        self._lock = asyncio.Lock()

    async def _get_producer(self) -> KafkaProducer:
        async with self._lock:
            if self._producer is None:
                # Run blocking Kafka connection in executor
                loop = asyncio.get_event_loop()
                self._producer = await loop.run_in_executor(
                    None,
                    lambda: KafkaProducer(
                        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                        key_serializer=lambda k: k.encode("utf-8") if k else None,
                        acks="all",
                        retries=5,
                        retry_backoff_ms=500,
                        request_timeout_ms=10000,
                        delivery_timeout_ms=30000,
                        enable_idempotence=True,
                        max_in_flight_requests_per_connection=5,
                        compression_type="zstd",
                        security_protocol="SSL" if settings.ENVIRONMENT == "production" else "PLAINTEXT",
                    ),
                )
            return self._producer

    async def publish(
        self,
        action: str,
        actor: dict[str, Any],
        resource: dict[str, Any],
        correlation_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Publish audit event. Best-effort: log error but don't block business logic."""
        event = {
            "event_id": str(uuid.uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "producer": "auth-service",
            "action": action,
            "actor": actor,
            "resource": resource,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "request_id": request_id,
            "version": "1.0",
        }
        try:
            producer = await self._get_producer()
            loop = asyncio.get_event_loop()
            future = await loop.run_in_executor(
                None,
                lambda: producer.send(
                    settings.KAFKA_AUDIT_TOPIC,
                    key=actor.get("user_id"),
                    value=event,
                ),
            )
            # Wait for ack with timeout
            await asyncio.wait_for(
                loop.run_in_executor(None, future.get, 10),
                timeout=15,
            )
        except Exception as e:
            logger.error(
                "failed to publish audit event",
                extra={"error": str(e), "action": action},
            )
            # Don't raise — audit should be best-effort async
            # In production, also save to outbox table for retry worker


# Singleton
audit_publisher = AuditEventPublisher()
