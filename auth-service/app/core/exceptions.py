"""Custom exception hierarchy."""
from __future__ import annotations


class AppError(Exception):
    """Base application error."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str = "", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(AppError):
    status_code = 401
    error_code = "unauthorized"


class AuthorizationError(AppError):
    status_code = 403
    error_code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"


class ValidationError(AppError):
    status_code = 422
    error_code = "validation_error"


class ConflictError(AppError):
    status_code = 409
    error_code = "conflict"


class RateLimitError(AppError):
    status_code = 429
    error_code = "rate_limit_exceeded"


class SecurityError(AppError):
    status_code = 400
    error_code = "security_violation"


class AccountLockedError(AppError):
    status_code = 423
    error_code = "account_locked"


class MFARequiredError(AppError):
    status_code = 403
    error_code = "mfa_required"
