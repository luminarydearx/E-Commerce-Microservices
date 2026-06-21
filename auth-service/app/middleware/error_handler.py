"""Global error handlers — return structured JSON, hide internals."""
from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppError

logger = logging.getLogger("auth_service.errors")


def register_error_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request.headers.get("X-Request-Id", ""),
                "correlation_id": request.headers.get("X-Correlation-Id", ""),
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError):
        logger.warning("integrity error", extra={"error": str(exc), "path": request.url.path})
        return JSONResponse(
            status_code=409,
            content={
                "error": "conflict",
                "message": "resource conflict, please retry",
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # Log full trace, return generic message
        logger.exception(
            "unhandled exception",
            extra={
                "error": str(exc),
                "path": request.url.path,
                "method": request.method,
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        )
        # Report to audit-service (best-effort)
        # In production: also push to Sentry-like service
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "an unexpected error occurred",
                "request_id": request.headers.get("X-Request-Id", ""),
                "correlation_id": request.headers.get("X-Correlation-Id", ""),
            },
        )
