"""Security utilities: password hashing, JWT, MFA."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from passlib.context import CryptContext
from pyotp import TOTP, random_base32

from app.core.config import settings
from app.core.exceptions import AuthenticationError, SecurityError

# Argon2id untuk password hashing (memory-hard, GPU-resistant)
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__memory_cost=65536,  # 64 MB
    argon2__time_cost=3,
    argon2__parallelism=4,
)


def _load_private_key() -> RSAPrivateKey:
    path = Path(settings.JWT_PRIVATE_KEY_PATH)
    if not path.exists():
        raise SecurityError(f"private key not found: {path}")
    data = path.read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise SecurityError("private key must be RSA")
    return key


def _load_public_key() -> RSAPublicKey:
    path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if not path.exists():
        raise SecurityError(f"public key not found: {path}")
    data = path.read_bytes()
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, RSAPublicKey):
        raise SecurityError("public key must be RSA")
    return key


_private_key = None
_public_key = None


def get_private_key() -> RSAPrivateKey:
    global _private_key
    if _private_key is None:
        _private_key = _load_private_key()
    return _private_key


def get_public_key() -> RSAPublicKey:
    global _public_key
    if _public_key is None:
        _public_key = _load_public_key()
    return _public_key


def hash_password(plain: str) -> str:
    """Hash password dengan Argon2id."""
    if len(plain) < settings.PASSWORD_MIN_LENGTH:
        raise SecurityError(f"password must be at least {settings.PASSWORD_MIN_LENGTH} chars")
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify password terhadap hash."""
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def is_password_strong(password: str) -> tuple[bool, list[str]]:
    """Check password strength, return (ok, list of issues)."""
    issues: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        issues.append(f"must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if settings.PASSWORD_REQUIRE_UPPER and not any(c.isupper() for c in password):
        issues.append("must contain uppercase letter")
    if settings.PASSWORD_REQUIRE_LOWER and not any(c.islower() for c in password):
        issues.append("must contain lowercase letter")
    if settings.PASSWORD_REQUIRE_DIGIT and not any(c.isdigit() for c in password):
        issues.append("must contain digit")
    if settings.PASSWORD_REQUIRE_SYMBOL and not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?/" for c in password):
        issues.append("must contain special character")
    # Common password check
    common = {"password", "123456", "qwerty", "abc123", "letmein", "admin"}
    if password.lower() in common:
        issues.append("password is too common")
    return (len(issues) == 0, issues)


def create_access_token(
    user_id: str,
    roles: list[str],
    permissions: list[str],
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Create JWT access token. Returns (token, jti)."""
    jti = str(uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iss": settings.JWT_ISSUER,
        "aud": ["api-gateway", "order-service", "payment-service", "catalog-service"],
        "roles": roles,
        "permissions": permissions,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "jti": jti,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(
        payload,
        get_private_key(),
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, jti


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """Create refresh token. Returns (token, jti)."""
    jti = str(uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iss": settings.JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)).timestamp()),
        "jti": jti,
        "type": "refresh",
    }
    token = jwt.encode(
        payload,
        get_private_key(),
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, jti


def decode_token(token: str) -> dict[str, Any]:
    """Decode & verify JWT token."""
    try:
        payload = jwt.decode(
            token,
            get_public_key(),
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        raise AuthenticationError("token expired") from e
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"invalid token: {e}") from e


def generate_mfa_secret() -> str:
    """Generate MFA secret untuk TOTP."""
    return random_base32()


def verify_mfa(secret: str, code: str) -> bool:
    """Verify TOTP code."""
    if not code or not code.isdigit() or len(code) != 6:
        return False
    totp = TOTP(secret, issuer=settings.MFA_ISSUER)
    return totp.verify(code, valid_window=1)


def generate_mfa_uri(secret: str, email: str) -> str:
    """Generate otpauth URI untuk QR code."""
    totp = TOTP(secret, issuer=settings.MFA_ISSUER)
    return totp.provisioning_uri(name=email, issuer_name=settings.MFA_ISSUER)


def generate_token(length: int = 32) -> str:
    """Generate secure random token."""
    return secrets.token_urlsafe(length)


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison (anti timing attack)."""
    return secrets.compare_digest(a, b)
