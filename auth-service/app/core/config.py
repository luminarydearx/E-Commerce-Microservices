"""Application configuration loaded from environment."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    APP_NAME: str = "auth-service"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # Database
    DATABASE_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # Redis
    REDIS_URL: str

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_AUDIT_TOPIC: str = "ecommerce.audit.events"
    KAFKA_USER_EVENTS_TOPIC: str = "ecommerce.user.events"

    # JWT
    JWT_PRIVATE_KEY_PATH: str
    JWT_PUBLIC_KEY_PATH: str
    JWT_ALGORITHM: str = "RS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ISSUER: str = "auth-service"

    # Password
    PASSWORD_MIN_LENGTH: int = 12
    PASSWORD_REQUIRE_UPPER: bool = True
    PASSWORD_REQUIRE_LOWER: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SYMBOL: bool = True
    BCRYPT_ROUNDS: int = 12

    # Account lockout
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30

    # MFA
    MFA_ENABLED: bool = True
    MFA_ISSUER: str = "ECommerce"

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    # Observability
    OTEL_ENDPOINT: str = "localhost:4317"
    SENTRY_DSN: str = ""

    # Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@ecommerce.local"

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if v not in ("development", "staging", "production"):
            raise ValueError("ENVIRONMENT must be one of: development, staging, production")
        return v

    @field_validator("PASSWORD_MIN_LENGTH")
    @classmethod
    def validate_min_len(cls, v: int) -> int:
        if v < 8:
            raise ValueError("PASSWORD_MIN_LENGTH must be >= 8")
        return v

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def validate_algo(cls, v: str) -> str:
        if v not in ("RS256", "RS384", "RS512", "ES256"):
            raise ValueError("JWT_ALGORITHM must be RS256/RS384/RS512/ES256 (asymmetric)")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
