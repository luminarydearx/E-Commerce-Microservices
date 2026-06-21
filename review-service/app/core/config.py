"""Review Service configuration."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8007

    DATABASE_URL: str
    REDIS_URL: str

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    OTEL_ENDPOINT: str = "localhost:4317"

    REVIEW_MAX_IMAGES: int = 5
    REVIEW_MAX_LENGTH: int = 5000
    REVIEW_MODERATION_ENABLED: bool = True
    REVIEW_AUTO_APPROVE: bool = True
    REVIEW_EDIT_WINDOW_HOURS: int = 24
    REVIEW_DELETE_WINDOW_HOURS: int = 168  # 7 days

    # Profanity filter
    PROFANITY_ENABLED: bool = True
    PROFANITY_WORDS: List[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore


settings = get_settings()
