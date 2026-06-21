"""Config for notification-service."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8005

    DATABASE_URL: str
    REDIS_URL: str

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_GROUP_ID: str = "notification-service"
    KAFKA_TOPICS: List[str] = [
        "ecommerce.user.events",
        "ecommerce.order.events",
        "ecommerce.payment.events",
    ]

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@ecommerce.local"

    OTEL_ENDPOINT: str = "localhost:4317"

    @lru_cache
    def validate(self):
        if self.ENVIRONMENT not in ("development", "staging", "production"):
            raise ValueError("invalid ENVIRONMENT")
        return True


@lru_cache
def get_settings() -> Settings:
    s = Settings()  # type: ignore
    return s


settings = get_settings()
