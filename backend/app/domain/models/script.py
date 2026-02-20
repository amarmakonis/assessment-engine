"""
Script domain model — the canonical representation of a student's answer script
after OCR + segmentation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.models.common import (
    QualityFlag,
    ScriptSource,
    ScriptStatus,
    StudentMeta,
    utcnow,
)


class ScriptAnswer(BaseModel):
    question_id: str = Field(alias="questionId")
    text: str
    is_flagged: bool = Field(default=False, alias="isFlagged")

    model_config = {"populate_by_name": True}


class Script(BaseModel):
    id: str = Field(default="", alias="_id")
    institution_id: str = Field(alias="institutionId")
    exam_id: str = Field(alias="examId")
    uploaded_script_id: str = Field(alias="uploadedScriptId")
    student_meta: StudentMeta = Field(alias="studentMeta")
    answers: list[ScriptAnswer] = Field(default_factory=list)
    source: ScriptSource
    ocr_confidence_average: float | None = Field(default=None, alias="ocrConfidenceAverage")
    ocr_quality_flags: list[QualityFlag] = Field(default_factory=list, alias="ocrQualityFlags")
    segmentation_confidence: float | None = Field(default=None, alias="segmentationConfidence")
    status: ScriptStatus = ScriptStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow, alias="createdAt")
    updated_at: datetime = Field(default_factory=utcnow, alias="updatedAt")

    model_config = {"populate_by_name": True}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = self.id
        return data
