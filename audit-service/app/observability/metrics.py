"""Metrics for audit-service."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

AUDIT_EVENTS_INGESTED = Counter(
    "audit_events_ingested_total",
    "Audit events ingested",
    ["producer", "action"],
)

ERRORS_INGESTED = Counter(
    "audit_errors_ingested_total",
    "Errors ingested",
    ["service", "level"],
)

ANOMALIES_DETECTED = Counter(
    "audit_anomalies_detected_total",
    "Anomalies detected",
    ["rule_name", "severity"],
)

AUDIT_CHAIN_VERIFICATIONS = Counter(
    "audit_chain_verifications_total",
    "Audit chain verification runs",
    ["result"],
)

INGEST_LATENCY = Histogram(
    "audit_ingest_duration_seconds",
    "Time to ingest an event",
)


def register_metrics() -> None:
    _ = [AUDIT_EVENTS_INGESTED, ERRORS_INGESTED, ANOMALIES_DETECTED, AUDIT_CHAIN_VERIFICATIONS, INGEST_LATENCY]
