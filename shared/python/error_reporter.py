"""Shared error reporter — services use this to push errors to audit-service."""
from __future__ import annotations

import logging
import os
import socket
import traceback
from typing import Any

import httpx

logger = logging.getLogger("error_reporter")


class ErrorReporter:
    """Report errors to centralized audit-service.

    Usage:
        from shared.observability.error_reporter import report_error

        try:
            risky_op()
        except Exception as e:
            report_error(e, context={"user_id": user_id}, request=request)
            raise  # re-raise after reporting
    """

    def __init__(self, endpoint: str | None = None, service_name: str | None = None,
                 environment: str | None = None) -> None:
        self.endpoint = endpoint or os.getenv("AUDIT_SERVICE_URL", "http://audit-service:8006")
        self.service_name = service_name or os.getenv("SERVICE_NAME", "unknown")
        self.environment = environment or os.getenv("ENVIRONMENT", "development")
        self.hostname = socket.gethostname()

    def report(
        self,
        error: Exception,
        context: dict[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        level: str = "error",
    ) -> None:
        """Report an error. Best-effort, never raises."""
        try:
            payload = {
                "service": self.service_name,
                "environment": self.environment,
                "level": level,
                "error_type": type(error).__name__,
                "message": str(error),
                "stack_trace": traceback.format_exc(),
                "context": {
                    "hostname": self.hostname,
                    **(context or {}),
                },
                "request_id": request_id,
                "correlation_id": correlation_id,
                "user_id": user_id,
            }
            # Send to audit-service (fire-and-forget)
            with httpx.Client(timeout=2.0) as client:
                resp = client.post(
                    f"{self.endpoint}/api/v1/internal/errors",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "failed to report error to audit-service",
                        extra={"status": resp.status_code, "body": resp.text[:200]},
                    )
        except Exception as e:
            # Never let error reporting cause another error
            logger.warning("error reporter failed", exc_info=True, extra={"error": str(e)})


# Singleton
_reporter = ErrorReporter()


def report_error(
    error: Exception,
    context: dict[str, Any] | None = None,
    request=None,
    level: str = "error",
) -> None:
    """Convenience function to report error."""
    request_id = None
    correlation_id = None
    user_id = None
    if request is not None:
        request_id = getattr(request, "headers", {}).get("X-Request-Id")
        correlation_id = getattr(request, "headers", {}).get("X-Correlation-Id")
        # Try to extract user_id from request state if available
        if hasattr(request, "state"):
            user_id = getattr(request.state, "user_id", None)
    _reporter.report(error, context, request_id, correlation_id, user_id, level)
