"""
Unit tests for domain Pydantic models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.models.common import StudentMeta, TokenUsage, UploadStatus
from app.domain.models.evaluation import (
    CriterionScore,
    EvaluationResult,
    GroundedRubric,
    RubricCriterion,
)
from app.domain.models.ocr import SegmentationResult, SegmentedAnswer
from app.domain.models.upload import UploadedScript


class TestStudentMeta:
    def test_valid_creation(self):
        sm = StudentMeta(name="Alice", rollNo="2024CS001", email="alice@uni.edu")
        assert sm.name == "Alice"
        assert sm.roll_no == "2024CS001"

    def test_alias_population(self):
        sm = StudentMeta.model_validate({"name": "Bob", "rollNo": "123"})
        assert sm.roll_no == "123"


class TestCriterionScore:
    def test_valid_score(self):
        cs = CriterionScore(
            criterionId="c1",
            marksAwarded=1.5,
            maxMarks=2.0,
            justificationQuote="relevant quote",
            justificationReason="explanation",
            confidenceScore=0.9,
        )
        assert cs.marks_awarded == 1.5

    def test_serialization_with_alias(self):
        cs = CriterionScore(
            criterionId="c1",
            marksAwarded=2.0,
            maxMarks=2.0,
            justificationQuote="q",
            justificationReason="r",
            confidenceScore=1.0,
        )
        data = cs.model_dump(by_alias=True)
        assert "criterionId" in data
        assert "marksAwarded" in data


class TestGroundedRubric:
    def test_valid_rubric(self):
        gr = GroundedRubric(
            totalMarks=10.0,
            criteria=[
                RubricCriterion(
                    criterionId="c1",
                    description="Test",
                    maxMarks=5.0,
                    requiredEvidencePoints=["point 1"],
                    isAmbiguous=False,
                    ambiguityNote=None,
                )
            ],
            groundingConfidence=0.95,
        )
        assert gr.total_marks == 10.0
        assert len(gr.criteria) == 1


class TestSegmentationResult:
    def test_valid_segmentation(self):
        sr = SegmentationResult(
            answers=[
                SegmentedAnswer(questionId="q1", answerText="Some answer text"),
                SegmentedAnswer(questionId="q2", answerText=None),
            ],
            unmappedText="Extra text",
            segmentationConfidence=0.88,
            notes="Some notes",
        )
        assert len(sr.answers) == 2
        assert sr.answers[1].answer_text is None


class TestTokenUsage:
    def test_valid_usage(self):
        tu = TokenUsage(prompt=100, completion=50, total=150)
        assert tu.total == 150
