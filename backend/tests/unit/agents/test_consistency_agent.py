"""
Unit tests for the ConsistencyAgent.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents.consistency import ConsistencyAgent
from app.domain.models.common import ConsistencyAssessment
from app.domain.models.evaluation import (
    ConsistencyAudit,
    FinalCriterionScore,
    ScoreAdjustment,
)
from app.domain.ports.llm import LLMResponse


@pytest.fixture
def mock_gateway():
    with patch("app.agents.base.get_llm_gateway") as mock:
        gw = MagicMock()
        mock.return_value = gw
        yield gw


class TestConsistencyAgent:
    def test_system_prompt_is_senior_examiner(self):
        agent = ConsistencyAgent.__new__(ConsistencyAgent)
        prompt = agent.get_system_prompt()
        assert "senior examiner" in prompt.lower()
        assert "inconsistencies" in prompt.lower()

    def test_build_user_prompt_has_all_context(self):
        agent = ConsistencyAgent.__new__(ConsistencyAgent)
        prompt = agent.build_user_prompt(
            answer_text="Test answer",
            rubric={"totalMarks": 5.0, "criteria": []},
            criterion_scores=[{"criterionId": "c1", "marksAwarded": 3.0}],
            question_text="What is OOP?",
        )
        assert "Test answer" in prompt
        assert "What is OOP?" in prompt
        assert "c1" in prompt

    def test_execute_returns_consistency_audit(self, mock_gateway):
        audit = ConsistencyAudit(
            overallAssessment=ConsistencyAssessment.CONSISTENT,
            adjustments=[],
            finalScores=[
                FinalCriterionScore(criterionId="c1", finalScore=3.0),
                FinalCriterionScore(criterionId="c2", finalScore=2.0),
            ],
            totalScore=5.0,
            auditNotes="All scores consistent",
        )
        llm_resp = LLMResponse(
            content="", prompt_tokens=300, completion_tokens=150,
            total_tokens=450, model="gpt-4o", latency_ms=1800,
        )
        mock_gateway.complete_structured.return_value = (audit, llm_resp)

        agent = ConsistencyAgent()
        result, meta = agent.execute(
            trace_id="test",
            answer_text="Test answer",
            rubric={"totalMarks": 5.0, "criteria": []},
            criterion_scores=[],
            question_text="What is OOP?",
        )

        assert isinstance(result, ConsistencyAudit)
        assert result.total_score == 5.0
        assert result.overall_assessment == ConsistencyAssessment.CONSISTENT
        assert len(result.final_scores) == 2

    def test_execute_with_adjustments(self, mock_gateway):
        audit = ConsistencyAudit(
            overallAssessment=ConsistencyAssessment.MINOR_ISSUES,
            adjustments=[
                ScoreAdjustment(
                    criterionId="c1",
                    originalScore=4.0,
                    recommendedScore=3.0,
                    reason="Too generous given lack of examples",
                ),
            ],
            finalScores=[
                FinalCriterionScore(criterionId="c1", finalScore=3.0),
            ],
            totalScore=3.0,
            auditNotes="Adjusted c1 down",
        )
        llm_resp = LLMResponse(
            content="", prompt_tokens=300, completion_tokens=200,
            total_tokens=500, model="gpt-4o", latency_ms=2000,
        )
        mock_gateway.complete_structured.return_value = (audit, llm_resp)

        agent = ConsistencyAgent()
        result, _ = agent.execute(
            trace_id="test",
            answer_text="Test",
            rubric={},
            criterion_scores=[],
            question_text="Q",
        )

        assert len(result.adjustments) == 1
        assert result.adjustments[0].original_score == 4.0
        assert result.adjustments[0].recommended_score == 3.0
