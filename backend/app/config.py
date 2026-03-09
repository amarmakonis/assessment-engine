"""
Pydantic-based application configuration.
All secrets and tunables sourced exclusively from environment variables (12-Factor).
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root .env (backend/app/config.py -> backend/ -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
_BACKEND_ENV = Path(__file__).resolve().parent.parent / ".env"


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(_PROJECT_ROOT / ".env"), str(_BACKEND_ENV), ".env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # When False, run OCR and evaluation synchronously (no Celery/Redis).
    USE_CELERY_REDIS: bool = Field(default=False, description="Use Celery/Redis for async tasks. Set False for sync-only.")
    # When True (default), use merged agents: scoring+consistency, feedback+explainability (3 LLM calls per question).
    USE_MERGED_AGENTS: bool = Field(default=True, description="Use merged agents to reduce LLM calls from 5 to 3 per question.")

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
    # Optional: use with MongoDB Atlas to reduce timeouts in Celery workers (e.g. 60000 ms).
    MONGO_SERVER_SELECTION_TIMEOUT_MS: int | None = None
    MONGO_SOCKET_TIMEOUT_MS: int | None = None

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
    CELERY_WORKER_CONCURRENCY: int = Field(
        default=4,
        description="Number of parallel tasks per Celery worker. Increase for higher throughput.",
    )

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
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key (required)", min_length=20)
    OPENAI_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Model for evaluation/agents. Use gpt-4o for higher accuracy; gpt-4o-mini is faster and cheaper.",
    )
    OPENAI_MODEL_VISION: str = Field(
        default="gpt-4o",
        description="Model for Vision OCR (handwritten text). gpt-4o is recommended for best accuracy.",
    )
    OPENAI_TEMPERATURE: float = Field(
        default=0.0,
        description="LLM temperature. Use 0.0 for deterministic scoring (same answer → same score).",
    )
    OPENAI_MAX_TOKENS: int = 4096
    OPENAI_TIMEOUT_SECONDS: int = Field(default=120, description="Per-request timeout. Lower (e.g. 60–90) for faster fail.")
    OPENAI_MAX_RETRIES: int = 3
    OPENAI_ORGANIZATION: str = ""

    # Model for exam extraction (question + rubric from upload). Default gpt-4o-mini for speed.
    OPENAI_MODEL_EXAM_EXTRACTION: str = Field(default="gpt-4o-mini", description="Model for exam extraction from uploads. gpt-4o-mini is faster; use gpt-4o for harder documents.")
    # Model for rubric generation when no rubric file. Empty = use OPENAI_MODEL. Set to gpt-4o for more specific, less vague rubrics.
    OPENAI_MODEL_RUBRIC_BUILDER: str | None = Field(default=None, description="Model for rubric builder. None = use OPENAI_MODEL. Set to gpt-4o for higher-quality, more specific rubrics.")
    # Default for exam upload when client does not send generateRubrics. True = generate detailed rubrics when no rubric file; False = use generic only.
    USE_AUTO_RUBRIC_GENERATION: bool = Field(default=True, description="Default when user does not choose: True = generate detailed rubrics when no rubric file; False = generic only. User can override per upload.")
    # Model for segmentation. Default gpt-4o-mini for speed; set to OPENAI_MODEL or empty to use main model.
    OPENAI_MODEL_SEGMENTATION: str | None = Field(default="gpt-4o-mini", description="Model for segmentation. Default gpt-4o-mini for speed. Set empty/None to use OPENAI_MODEL.")
    # Max tokens for segmentation response. Must be high enough for full answerText per question (long essays).
    OPENAI_SEGMENTATION_MAX_TOKENS: int = Field(default=16384, description="Max completion tokens for segmentation. Use 16384+ so long answers are not truncated; lower = faster but risk cut-off.")
    # Cap OCR text length sent to segmentation (chars). 0 = full script so every answer can be captured.
    SEGMENTATION_MAX_OCR_CHARS: int = Field(default=0, description="Max OCR chars sent to segmentation. 0 = full text (recommended for full answers); set e.g. 120000 only if you accept truncating the tail.")
    # Max chars of each question's text in the segmentation prompt (reduces tokens and latency).
    SEGMENTATION_MAX_QUESTION_TEXT_CHARS: int = Field(default=300, description="Truncate each question text to this many chars in segmentation prompt (reduces latency). 0 = no truncation.")
    SEGMENTATION_SOFT_TIME_LIMIT: int = Field(default=600, description="Celery soft time limit (seconds) for segment_answers. Increase for long scripts (e.g. 33+ pages).")
    SEGMENTATION_TIME_LIMIT: int = Field(default=660, description="Celery hard time limit (seconds) for segment_answers.")
    # Max tokens for evaluation sub-agents (rubric, consistency, feedback, explainability). Lower = faster.
    OPENAI_EVALUATION_MAX_TOKENS: int = Field(default=1024, description="Max completion tokens per evaluation agent call. Increase to 2048 if feedback is truncated.")
    # How many questions to evaluate in parallel (sync pipeline). Higher = faster but more OpenAI concurrent requests; 5 is a good default.
    EVALUATION_MAX_WORKERS: int = Field(default=5, description="Max parallel evaluation tasks per script (sync mode). Set 3–8; reduce if you hit 429 rate limits.")

    # ── Upload Limits ──────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_PAGES_PER_SCRIPT: int = 40

    # ── OCR (answer papers: PDF → images → Vision per page) ─
    OCR_TEST_MAX_CONCURRENT: int = Field(
        default=2,
        description="Max parallel OCR pages (ingest & test). 2–3 for faster pipeline; use 1 if you hit 429 rate limits.",
    )
    OCR_TEST_DELAY_SECONDS: float = Field(
        default=2.0,
        description="Seconds between submitting each OCR page (throttle). Use 1–2 for speed; increase to 5+ for free-tier OpenAI.",
    )
    OCR_DPI: int = Field(
        default=120,
        description="DPI for PDF→image conversion for answer papers. Lower = faster; increase to 150 for denser scripts.",
    )
    OCR_PAGE_SOFT_TIME_LIMIT: int = Field(
        default=300,
        description="Celery soft time limit (seconds) per OCR page. One slow page can exceed this; increase for large/dense scripts.",
    )
    OCR_PAGE_TIME_LIMIT: int = Field(
        default=330,
        description="Celery hard time limit (seconds) per OCR page. Must be > OCR_PAGE_SOFT_TIME_LIMIT.",
    )
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

    @field_validator("OPENAI_API_KEY", mode="before")
    @classmethod
    def strip_openai_key(cls, v: str) -> str:
        """Strip whitespace so accidental trailing spaces don't cause 401."""
        return (v or "").strip()

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
