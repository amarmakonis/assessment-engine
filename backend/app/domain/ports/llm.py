"""
LLM gateway port — all LLM provider implementations conform to this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Type, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    latency_ms: int


@runtime_checkable
class LLMGateway(Protocol):
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return raw response."""
        ...

    def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_retries: int = 2,
    ) -> tuple[T, LLMResponse]:
        """
        Send a chat completion request and parse into a Pydantic model.
        Retries with a repair prompt on JSON parse failure.
        """
        ...

    def health_check(self) -> bool:
        """Verify the LLM backend is reachable."""
        ...
