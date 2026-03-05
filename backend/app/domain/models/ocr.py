"""
OCR pipeline domain models.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.models.common import QualityFlag, utcnow


class WordLevelEntry(BaseModel):
    word: str
    bbox: tuple[int, int, int, int]
    confidence: float


class OCRPageResult(BaseModel):
    id: str = Field(default="", alias="_id")
    uploaded_script_id: str = Field(alias="uploadedScriptId")
    page_number: int = Field(alias="pageNumber")
    extracted_text: str = Field(alias="extractedText")
    confidence_score: float = Field(alias="confidenceScore")
    word_level_data: list[WordLevelEntry] | None = Field(default=None, alias="wordLevelData")
    quality_flags: list[QualityFlag] = Field(default_factory=list, alias="qualityFlags")
    provider: str
    processing_ms: int = Field(alias="processingMs")
    created_at: datetime = Field(default_factory=utcnow, alias="createdAt")

    model_config = {"populate_by_name": True}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = self.id
        return data


class SegmentedAnswer(BaseModel):
    question_id: str = Field(alias="questionId")
    answer_text: str | None = Field(alias="answerText")

    model_config = {"populate_by_name": True}

    @field_validator("question_id", mode="before")
    @classmethod
    def coerce_question_id(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("answer_text", mode="before")
    @classmethod
    def coerce_answer_text(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        return str(v)


class SegmentationResult(BaseModel):
    answers: list[SegmentedAnswer]
    unmapped_text: str = Field(default="", alias="unmappedText")
    segmentation_confidence: float = Field(default=0.0, alias="segmentationConfidence")
    notes: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("answers", mode="before")
    @classmethod
    def coerce_answers_list(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            return [v]
        return []

    @field_validator("unmapped_text", mode="before")
    @classmethod
    def coerce_unmapped_text(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("segmentation_confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v: object) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @field_validator("notes", mode="before")
    @classmethod
    def coerce_notes(cls, v: object) -> str | None:
        if v is None:
            return None
        return str(v)
