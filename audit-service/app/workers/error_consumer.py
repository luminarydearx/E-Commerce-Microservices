"""Kafka consumer for error events from all services."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from kafka import KafkaConsumer

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.audit_ingest import ingest_error

logger = logging.getLogger("audit_service.error_consumer")


class ErrorConsumer:
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
                settings.KAFKA_ERROR_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=settings.KAFKA_GROUP_ID,
                auto_offset_reset="latest",
                enable_auto_commit=False,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                consumer_timeout_ms=1000,
            )
            logger.info("error consumer started")
        except Exception as e:
            logger.error("failed to start error consumer", exc_info=True, extra={"error": str(e)})
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
        logger.info("error consumer stopped")

    def _process(self, payload: dict[str, Any]) -> None:
        asyncio.run(self._process_async(payload))

    async def _process_async(self, payload: dict[str, Any]) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await ingest_error(db, payload)
                await db.commit()
        except Exception as e:
            logger.error("failed to ingest error from kafka", exc_info=True, extra={"error": str(e)})

    def stop(self) -> None:
        self._running = False
