"""
Pydantic-based application configuration.
All secrets and tunables sourced exclusively from environment variables (12-Factor).
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Core ───────────────────────────────────────────────
    APP_NAME: str = "Agentic Assessment Engine"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = False
    SECRET_KEY: str = Field(..., min_length=32)
    API_VERSION: str = "v1"
    LOG_LEVEL: str = "INFO"

    # ── Flask ──────────────────────────────────────────────
    FLASK_HOST: str = "0.0.0.0"
    FLASK_PORT: int = 5000

    # ── MongoDB ────────────────────────────────────────────
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "aae_db"
    MONGO_MAX_POOL_SIZE: int = 50
    MONGO_MIN_POOL_SIZE: int = 10

    # ── Redis ──────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600

    # ── Celery ─────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: list[str] = ["json"]
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 600
    CELERY_TASK_SOFT_TIME_LIMIT: int = 540

    # ── Object Storage ─────────────────────────────────────
    STORAGE_PROVIDER: Literal["local", "s3"] = "local"
    LOCAL_STORAGE_PATH: str = "/data/uploads"
    S3_BUCKET_NAME: str = ""
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION: str = "us-east-1"
    SIGNED_URL_EXPIRY_SECONDS: int = 900

    # ── OpenAI (powers OCR + evaluation + all agents) ─────
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key (required)")
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TEMPERATURE: float = 0.1
    OPENAI_MAX_TOKENS: int = 4096
    OPENAI_TIMEOUT_SECONDS: int = 120
    OPENAI_MAX_RETRIES: int = 3
    OPENAI_ORGANIZATION: str = ""

    # ── Upload Limits ──────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_PAGES_PER_SCRIPT: int = 40
    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "image/jpeg",
        "image/png",
    ]
    UPLOAD_RATE_LIMIT: str = "10/minute"

    # ── JWT / Auth ─────────────────────────────────────────
    JWT_SECRET_KEY: str = ""
    JWT_ACCESS_TOKEN_EXPIRES_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRES_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"

    # ── Observability ──────────────────────────────────────
    OTEL_EXPORTER_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "aae-backend"
    PROMETHEUS_METRICS_PORT: int = 9090

    @field_validator("JWT_SECRET_KEY", mode="before")
    @classmethod
    def default_jwt_secret(cls, v: str, info) -> str:
        if not v:
            return info.data.get("SECRET_KEY", "")
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
