"""Metrics for notification-service."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

NOTIFICATIONS_SENT = Counter(
    "notification_sent_total",
    "Notifications sent",
    ["channel", "status"],
)

NOTIFICATION_LATENCY = Histogram(
    "notification_duration_seconds",
    "Time to send notification",
    ["channel"],
)

EVENTS_CONSUMED = Counter(
    "notification_events_consumed_total",
    "Events consumed from Kafka",
    ["action"],
)


def register_metrics() -> None:
    _ = [NOTIFICATIONS_SENT, NOTIFICATION_LATENCY, EVENTS_CONSUMED]
