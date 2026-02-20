"""
Shared value objects and enumerations across the domain.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    OCR_COMPLETE = "OCR_COMPLETE"
    SEGMENTED = "SEGMENTED"
    EVALUATING = "EVALUATING"
    EVALUATED = "EVALUATED"
    FAILED = "FAILED"
    FLAGGED = "FLAGGED"


class VirusScanStatus(str, Enum):
    PENDING = "PENDING"
    CLEAN = "CLEAN"
    QUARANTINED = "QUARANTINED"


class ScriptStatus(str, Enum):
    PENDING = "PENDING"
    EVALUATING = "EVALUATING"
    COMPLETE = "COMPLETE"
    FLAGGED = "FLAGGED"


class ScriptSource(str, Enum):
    TYPED = "TYPED"
    OCR = "OCR"


class EvaluationStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    OVERRIDDEN = "OVERRIDDEN"
    FAILED = "FAILED"


class ReviewRecommendation(str, Enum):
    AUTO_APPROVED = "AUTO_APPROVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MUST_REVIEW = "MUST_REVIEW"


class ConsistencyAssessment(str, Enum):
    CONSISTENT = "CONSISTENT"
    MINOR_ISSUES = "MINOR_ISSUES"
    SIGNIFICANT_ISSUES = "SIGNIFICANT_ISSUES"


class QualityFlag(str, Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SKEWED = "SKEWED"
    BLURRY = "BLURRY"


class UserRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    INSTITUTION_ADMIN = "INSTITUTION_ADMIN"
    EXAMINER = "EXAMINER"
    REVIEWER = "REVIEWER"
    STUDENT = "STUDENT"


class StudentMeta(BaseModel):
    name: str
    roll_no: str = Field(alias="rollNo")
    email: str | None = None

    model_config = {"populate_by_name": True}


class TokenUsage(BaseModel):
    prompt: int
    completion: int
    total: int
