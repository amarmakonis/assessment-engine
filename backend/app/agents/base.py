"""
Base agent contract and shared utilities.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Generic, Type, TypeVar

from pydantic import BaseModel

from app.common.observability import evaluation_duration, structured_log
from app.infrastructure.llm import get_llm_gateway

T = TypeVar("T", bound=BaseModel)


class BaseAgent(ABC, Generic[T]):
    """
    Every evaluation agent inherits from this base.
    Enforces structured output, telemetry, and a standard call interface.
    """

    agent_name: str = "base_agent"
    response_model: Type[T]

    def __init__(self):
        self._llm = get_llm_gateway()
        self._logger = logging.getLogger(f"agent.{self.agent_name}")

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        ...

    @abstractmethod
    def build_user_prompt(self, **kwargs) -> str:
        """Build the user prompt from the given context."""
        ...

    def execute(self, *, trace_id: str = "", **kwargs) -> tuple[T, dict]:
        """
        Run the agent: build prompts → call LLM → parse → return structured result.
        Returns (parsed_result, metadata_dict).
        """
        start = time.perf_counter_ns()
        system_prompt = self.get_system_prompt()
        user_prompt = self.build_user_prompt(**kwargs)

        structured_log(
            "info",
            f"{self.agent_name} starting execution",
            trace_id=trace_id,
            agent_name=self.agent_name,
        )

        parsed, llm_response = self._llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=self.response_model,
            agent_name=self.agent_name,
        )

        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        evaluation_duration.labels(
            agent_name=self.agent_name, status="success"
        ).observe(elapsed_ms / 1000)

        metadata = {
            "agent_name": self.agent_name,
            "latency_ms": elapsed_ms,
            "prompt_tokens": llm_response.prompt_tokens,
            "completion_tokens": llm_response.completion_tokens,
            "total_tokens": llm_response.total_tokens,
            "model": llm_response.model,
        }

        structured_log(
            "info",
            f"{self.agent_name} completed",
            trace_id=trace_id,
            agent_name=self.agent_name,
            duration_ms=elapsed_ms,
        )

        return parsed, metadata
