"""
Unit tests for the ScoringAgent.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.scoring import ScoringAgent
from app.domain.models.evaluation import CriterionScore
from app.domain.ports.llm import LLMResponse


@pytest.fixture
def mock_gateway():
    with patch("app.agents.base.get_llm_gateway") as mock:
        gw = MagicMock()
        mock.return_value = gw
        yield gw


class TestScoringAgent:
    def test_system_prompt_contains_required_instructions(self):
        agent = ScoringAgent.__new__(ScoringAgent)
        prompt = agent.get_system_prompt()
        assert "impartial" in prompt.lower()
        assert "ONE specific rubric criterion" in prompt
        assert "justificationQuote" in prompt

    def test_build_user_prompt_includes_all_fields(self):
        agent = ScoringAgent.__new__(ScoringAgent)
        prompt = agent.build_user_prompt(
            answer_text="Polymorphism allows objects to take many forms.",
            criterion={"criterionId": "c1", "description": "Definition", "maxMarks": 2.0},
            question_text="Explain polymorphism.",
        )
        assert "Polymorphism allows" in prompt
        assert "c1" in prompt
        assert "Explain polymorphism" in prompt

    def test_execute_returns_criterion_score(self, mock_gateway):
        score_json = json.dumps({
            "criterionId": "c1",
            "marksAwarded": 1.5,
            "maxMarks": 2.0,
            "justificationQuote": "objects to take many forms",
            "justificationReason": "Partially correct definition",
            "confidenceScore": 0.85,
        })

        llm_response = LLMResponse(
            content=score_json,
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            model="gpt-4o",
            latency_ms=1500,
        )

        parsed_score = CriterionScore(
            criterionId="c1",
            marksAwarded=1.5,
            maxMarks=2.0,
            justificationQuote="objects to take many forms",
            justificationReason="Partially correct definition",
            confidenceScore=0.85,
        )

        mock_gateway.complete_structured.return_value = (parsed_score, llm_response)

        agent = ScoringAgent()
        result, meta = agent.execute(
            trace_id="test-trace",
            answer_text="Polymorphism allows objects to take many forms.",
            criterion={"criterionId": "c1", "description": "Definition", "maxMarks": 2.0},
            question_text="Explain polymorphism.",
        )

        assert isinstance(result, CriterionScore)
        assert result.marks_awarded == 1.5
        assert result.criterion_id == "c1"
        assert meta["agent_name"] == "scoring_agent"

    def test_score_all_criteria(self, mock_gateway):
        for cid, marks in [("c1", 1.5), ("c2", 2.5)]:
            score = CriterionScore(
                criterionId=cid,
                marksAwarded=marks,
                maxMarks=3.0,
                justificationQuote="test quote",
                justificationReason="test reason",
                confidenceScore=0.9,
            )
            llm_resp = LLMResponse(
                content="", prompt_tokens=100, completion_tokens=50,
                total_tokens=150, model="gpt-4o", latency_ms=1000,
            )
            mock_gateway.complete_structured.return_value = (score, llm_resp)

        agent = ScoringAgent()
        scores, metas = agent.score_all_criteria(
            trace_id="test",
            answer_text="Test answer",
            grounded_criteria=[
                {"criterionId": "c1", "description": "A", "maxMarks": 3.0},
                {"criterionId": "c2", "description": "B", "maxMarks": 3.0},
            ],
            question_text="Test question",
        )

        assert len(scores) == 2
        assert len(metas) == 2
