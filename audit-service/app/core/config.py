"""Config for audit-service."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8006

    DATABASE_URL: str
    REDIS_URL: str

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_AUDIT_TOPIC: str = "ecommerce.audit.events"
    KAFKA_ERROR_TOPIC: str = "ecommerce.errors"
    KAFKA_GROUP_ID: str = "audit-service"

    OTEL_ENDPOINT: str = "localhost:4317"

    ANOMALY_RULES_ENABLED: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore


settings = get_settings()
