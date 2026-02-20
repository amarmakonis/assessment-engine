"""
Typed domain events dispatched through the Celery task graph.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileUploadedEvent(BaseModel):
    uploaded_script_id: str = Field(alias="uploadedScriptId")
    institution_id: str = Field(alias="institutionId")
    exam_id: str = Field(alias="examId")
    file_key: str = Field(alias="fileKey")
    mime_type: str = Field(alias="mimeType")

    model_config = {"populate_by_name": True}


class OCRCompletedEvent(BaseModel):
    uploaded_script_id: str = Field(alias="uploadedScriptId")
    page_count: int = Field(alias="pageCount")
    average_confidence: float = Field(alias="averageConfidence")

    model_config = {"populate_by_name": True}


class SegmentationCompletedEvent(BaseModel):
    uploaded_script_id: str = Field(alias="uploadedScriptId")
    script_id: str = Field(alias="scriptId")
    question_count: int = Field(alias="questionCount")

    model_config = {"populate_by_name": True}


class EvaluationCompletedEvent(BaseModel):
    script_id: str = Field(alias="scriptId")
    question_id: str = Field(alias="questionId")
    evaluation_result_id: str = Field(alias="evaluationResultId")
    total_score: float = Field(alias="totalScore")
    review_recommendation: str = Field(alias="reviewRecommendation")

    model_config = {"populate_by_name": True}
