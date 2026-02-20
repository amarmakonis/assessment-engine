"""
OCR pipeline domain models.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

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


class SegmentationResult(BaseModel):
    answers: list[SegmentedAnswer]
    unmapped_text: str = Field(default="", alias="unmappedText")
    segmentation_confidence: float = Field(alias="segmentationConfidence")
    notes: str | None = None
