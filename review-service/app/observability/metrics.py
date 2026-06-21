"""Metrics."""
from prometheus_client import Counter, Histogram

REVIEWS_CREATED = Counter("review_created_total", "Reviews created", ["rating"])
REVIEWS_VOTED = Counter("review_voted_total", "Helpful votes", ["helpful"])


def register_metrics() -> None:
    _ = [REVIEWS_CREATED, REVIEWS_VOTED]
