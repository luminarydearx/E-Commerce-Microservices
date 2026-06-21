"""Custom exceptions."""
from __future__ import annotations


class AppError(Exception):
    status_code: int = 500
    error_code: str = "internal_error"
    def __init__(self, message: str = "", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"


class ConflictError(AppError):
    status_code = 409
    error_code = "conflict"


class ForbiddenError(AppError):
    status_code = 403
    error_code = "forbidden"


class ValidationError(AppError):
    status_code = 422
    error_code = "validation_error"
