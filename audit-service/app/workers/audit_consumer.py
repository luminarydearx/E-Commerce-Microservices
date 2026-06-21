"""Kafka consumer for audit events."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaConsumer

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.audit import AnomalyAlert
from app.services.audit_ingest import ingest_audit_event, check_anomaly_rules

logger = logging.getLogger("audit_service.audit_consumer")


class AuditConsumer:
    def __init__(self) -> None:
        self._consumer: KafkaConsumer | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._consume_sync)

    def _consume_sync(self) -> None:
        try:
            self._consumer = KafkaConsumer(
                settings.KAFKA_AUDIT_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=settings.KAFKA_GROUP_ID,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                consumer_timeout_ms=1000,
            )
            logger.info("audit consumer started")
        except Exception as e:
            logger.error("failed to start audit consumer", exc_info=True, extra={"error": str(e)})
            return

        while self._running:
            try:
                records = self._consumer.poll(timeout_ms=500, max_records=100)
                if not records:
                    continue
                for tp, messages in records.items():
                    for msg in messages:
                        self._process(msg.value)
                    self._consumer.commit()
            except Exception as e:
                logger.error("consume error", exc_info=True, extra={"error": str(e)})

        try:
            self._consumer.close()
        except Exception:
            pass
        logger.info("audit consumer stopped")

    def _process(self, event: dict[str, Any]) -> None:
        asyncio.run(self._process_async(event))

    async def _process_async(self, event: dict[str, Any]) -> None:
        try:
            async with AsyncSessionLocal() as db:
                entry = await ingest_audit_event(db, event)
                # Check anomaly rules
                if settings.ANOMALY_RULES_ENABLED:
                    alert = await check_anomaly_rules(db, event)
                    if alert:
                        db.add(alert)
                        logger.warning(
                            "anomaly detected",
                            extra={"rule": alert.rule_name, "description": alert.description},
                        )
                await db.commit()
        except Exception as e:
            logger.error("failed to process audit event", exc_info=True,
                         extra={"error": str(e), "event_id": event.get("event_id")})

    def stop(self) -> None:
        self._running = False
