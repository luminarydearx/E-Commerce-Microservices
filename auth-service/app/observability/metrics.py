"""Prometheus metrics."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "auth_service_requests_total",
    "Total request count",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "auth_service_request_duration_seconds",
    "Request latency in seconds",
    ["method", "path"],
)

DB_QUERY_DURATION = Histogram(
    "auth_service_db_query_duration_seconds",
    "DB query latency",
    ["operation"],
)

REDIS_OP_DURATION = Histogram(
    "auth_service_redis_op_duration_seconds",
    "Redis operation latency",
    ["operation"],
)

LOGIN_ATTEMPTS = Counter(
    "auth_service_login_attempts_total",
    "Login attempt count",
    ["result"],  # success / failed / locked
)

REGISTRATION_COUNT = Counter(
    "auth_service_registrations_total",
    "User registration count",
    ["role"],
)


def register_metrics() -> None:
    """Touch metrics to register them."""
    _ = [
        REQUEST_COUNT,
        REQUEST_LATENCY,
        DB_QUERY_DURATION,
        REDIS_OP_DURATION,
        LOGIN_ATTEMPTS,
        REGISTRATION_COUNT,
    ]
