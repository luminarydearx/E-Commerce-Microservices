"""Kafka consumer for notification events."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from kafka import KafkaConsumer

from app.core.config import settings
from app.services.notification_service import NotificationService

logger = logging.getLogger("notification_service.consumer")


class NotificationConsumer:
    """Consume events from Kafka and dispatch to notification channels."""

    def __init__(self) -> None:
        self._consumer: KafkaConsumer | None = None
        self._running = False
        self._svc = NotificationService()

    def start(self) -> None:
        self._running = True
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._run())

    async def _run(self) -> None:
        # Run blocking Kafka consumer in executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._consume_sync)

    def _consume_sync(self) -> None:
        try:
            self._consumer = KafkaConsumer(
                *settings.KAFKA_TOPICS,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=settings.KAFKA_GROUP_ID,
                auto_offset_reset="latest",
                enable_auto_commit=False,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                key_deserializer=lambda k: k.decode("utf-8") if k else None,
                consumer_timeout_ms=1000,
            )
            logger.info("kafka consumer started", extra={"topics": settings.KAFKA_TOPICS})
        except Exception as e:
            logger.error("failed to start kafka consumer", exc_info=True, extra={"error": str(e)})
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
                continue

        try:
            self._consumer.close()
        except Exception:
            pass
        logger.info("kafka consumer stopped")

    def _process(self, event: dict[str, Any]) -> None:
        action = event.get("action", "")
        logger.info("processing event", extra={"action": action, "event_id": event.get("event_id")})

        try:
            if action == "user.register":
                asyncio.run(self._svc.on_user_registered(event))
            elif action == "order.created":
                asyncio.run(self._svc.on_order_created(event))
            elif action == "payment.succeeded":
                asyncio.run(self._svc.on_payment_succeeded(event))
            elif action == "payment.failed":
                asyncio.run(self._svc.on_payment_failed(event))
            else:
                logger.debug("no handler for action", extra={"action": action})
        except Exception as e:
            logger.error("event processing failed", exc_info=True,
                         extra={"action": action, "error": str(e)})

    def stop(self) -> None:
        self._running = False
