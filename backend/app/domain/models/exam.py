"""
Exam and Question domain models.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.models.common import utcnow


class RubricCriterionDef(BaseModel):
    criterion_id: str = Field(alias="criterionId")
    description: str
    max_marks: float = Field(alias="maxMarks")

    model_config = {"populate_by_name": True}


class ExamQuestion(BaseModel):
    question_id: str = Field(alias="questionId")
    question_text: str = Field(alias="questionText")
    max_marks: float = Field(alias="maxMarks")
    rubric: list[RubricCriterionDef] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class Exam(BaseModel):
    id: str = Field(default="", alias="_id")
    institution_id: str = Field(alias="institutionId")
    title: str
    subject: str
    questions: list[ExamQuestion] = Field(default_factory=list)
    total_marks: float = Field(alias="totalMarks")
    created_by: str = Field(alias="createdBy")
    created_at: datetime = Field(default_factory=utcnow, alias="createdAt")
    updated_at: datetime = Field(default_factory=utcnow, alias="updatedAt")

    model_config = {"populate_by_name": True}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = self.id
        return data
