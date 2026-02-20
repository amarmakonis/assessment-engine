"""
Unit tests for the SegmentationAgent.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.segmentation import SegmentationAgent
from app.domain.models.ocr import SegmentationResult, SegmentedAnswer
from app.domain.ports.llm import LLMResponse


@pytest.fixture
def mock_gateway():
    with patch("app.agents.base.get_llm_gateway") as mock:
        gw = MagicMock()
        mock.return_value = gw
        yield gw


class TestSegmentationAgent:
    def test_system_prompt_contains_key_instructions(self):
        agent = SegmentationAgent.__new__(SegmentationAgent)
        prompt = agent.get_system_prompt()
        assert "segmentation" in prompt.lower()
        assert "Do NOT paraphrase" in prompt
        assert "questionId" in prompt

    def test_build_user_prompt_includes_questions_and_text(self):
        agent = SegmentationAgent.__new__(SegmentationAgent)
        prompt = agent.build_user_prompt(
            questions=[
                {"questionId": "q1", "questionText": "What is AI?"},
                {"questionId": "q2", "questionText": "Explain ML."},
            ],
            ocr_text="Answer 1: AI is... Answer 2: ML stands for...",
        )
        assert "q1" in prompt
        assert "What is AI?" in prompt
        assert "AI is..." in prompt

    def test_execute_returns_segmentation_result(self, mock_gateway):
        seg_result = SegmentationResult(
            answers=[
                SegmentedAnswer(questionId="q1", answerText="AI is artificial intelligence"),
                SegmentedAnswer(questionId="q2", answerText=None),
            ],
            unmappedText="Some leftover text",
            segmentationConfidence=0.85,
            notes="q2 had no identifiable answer",
        )
        llm_resp = LLMResponse(
            content="",
            prompt_tokens=500,
            completion_tokens=200,
            total_tokens=700,
            model="gpt-4o",
            latency_ms=2000,
        )
        mock_gateway.complete_structured.return_value = (seg_result, llm_resp)

        agent = SegmentationAgent()
        result, meta = agent.execute(
            trace_id="test-trace",
            questions=[
                {"questionId": "q1", "questionText": "What is AI?"},
                {"questionId": "q2", "questionText": "Explain ML."},
            ],
            ocr_text="Answer 1: AI is artificial intelligence",
        )

        assert isinstance(result, SegmentationResult)
        assert len(result.answers) == 2
        assert result.answers[0].answer_text == "AI is artificial intelligence"
        assert result.answers[1].answer_text is None
        assert result.segmentation_confidence == 0.85
        assert meta["agent_name"] == "segmentation_agent"
