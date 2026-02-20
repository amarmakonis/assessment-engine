"""
Unit tests for the OpenAI LLM gateway.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from app.infrastructure.llm.gateway import OpenAIGateway


class SampleResponse(BaseModel):
    name: str
    score: float


class TestOpenAIGateway:
    @patch("app.infrastructure.llm.gateway.OpenAI")
    def test_extract_json_block_strips_markdown(self, _mock_openai):
        content = '```json\n{"name": "test", "score": 0.8}\n```'
        result = OpenAIGateway._extract_json_block(content)
        parsed = json.loads(result)
        assert parsed["name"] == "test"

    @patch("app.infrastructure.llm.gateway.OpenAI")
    def test_extract_json_block_plain_json(self, _mock_openai):
        content = '{"name": "plain", "score": 1.0}'
        result = OpenAIGateway._extract_json_block(content)
        parsed = json.loads(result)
        assert parsed["name"] == "plain"

    @patch("app.infrastructure.llm.gateway.OpenAI")
    def test_try_parse_valid(self, _mock_openai):
        valid_json = '{"name": "valid", "score": 0.95}'
        result = OpenAIGateway._try_parse(valid_json, SampleResponse)
        assert result is not None
        assert result.name == "valid"

    @patch("app.infrastructure.llm.gateway.OpenAI")
    def test_try_parse_invalid_json(self, _mock_openai):
        result = OpenAIGateway._try_parse("not json", SampleResponse)
        assert result is None

    @patch("app.infrastructure.llm.gateway.OpenAI")
    def test_try_parse_schema_mismatch(self, _mock_openai):
        result = OpenAIGateway._try_parse('{"wrong_field": true}', SampleResponse)
        assert result is None
