"""
OpenAI LLM gateway — text completions, vision OCR, structured output parsing,
retry logic, and telemetry. Single gateway for ALL OpenAI interactions.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Type, TypeVar

from openai import OpenAI
from openai import APIError, APITimeoutError, RateLimitError as OpenAIRateLimitError
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.common.exceptions import LLMError
from app.common.observability import llm_latency, structured_log, track_llm_usage
from app.config import get_settings
from app.domain.ports.llm import LLMResponse

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_REPAIR_PROMPT = (
    "The previous response was not valid JSON. "
    "Fix it and return ONLY valid JSON matching the required schema. "
    "Do NOT wrap it in markdown code fences. "
    "Previous invalid output:\n{bad_json}"
)


class OpenAIGateway:
    """Production OpenAI gateway with structured output parsing, retries, and observability."""

    def __init__(self):
        settings = get_settings()
        client_kwargs: dict = {
            "api_key": settings.OPENAI_API_KEY,
            "timeout": settings.OPENAI_TIMEOUT_SECONDS,
            "max_retries": 0,
        }
        if settings.OPENAI_ORGANIZATION:
            client_kwargs["organization"] = settings.OPENAI_ORGANIZATION

        self._client = OpenAI(**client_kwargs)
        self._model = settings.OPENAI_MODEL
        self._temperature = settings.OPENAI_TEMPERATURE
        self._max_tokens = settings.OPENAI_MAX_TOKENS
        self._max_retries = settings.OPENAI_MAX_RETRIES

    @retry(
        retry=retry_if_exception_type((APITimeoutError, OpenAIRateLimitError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        start = time.perf_counter_ns()
        try:
            response = self._client.chat.completions.create(
                model=model or self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature if temperature is not None else self._temperature,
                max_tokens=max_tokens or self._max_tokens,
                response_format={"type": "json_object"},
            )
        except (APITimeoutError, OpenAIRateLimitError):
            raise
        except APIError as exc:
            raise LLMError(f"OpenAI API error: {exc}") from exc

        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        usage = response.usage

        return LLMResponse(
            content=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            model=response.model,
            latency_ms=elapsed_ms,
        )

    def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_retries: int = 2,
        agent_name: str = "unknown",
    ) -> tuple[T, LLMResponse]:
        """
        Call OpenAI and parse the response into a Pydantic model.
        Uses response_format=json_object for reliable JSON.
        On parse failure, issues a repair prompt up to max_retries times.
        """
        llm_response = self.complete(
            system_prompt, user_prompt,
            temperature=temperature, max_tokens=max_tokens,
        )

        llm_latency.labels(agent_name=agent_name).observe(llm_response.latency_ms / 1000)
        track_llm_usage(
            agent_name, llm_response.model,
            llm_response.prompt_tokens, llm_response.completion_tokens,
        )

        content = self._extract_json_block(llm_response.content)
        parsed = self._try_parse(content, response_model)
        if parsed is not None:
            return parsed, llm_response

        total_prompt_tokens = llm_response.prompt_tokens
        total_completion_tokens = llm_response.completion_tokens

        for attempt in range(max_retries):
            structured_log(
                "warning",
                f"JSON parse failed for {agent_name}, repair attempt {attempt + 1}",
                agent_name=agent_name,
            )
            repair_response = self.complete(
                system_prompt,
                _REPAIR_PROMPT.format(bad_json=content),
                temperature=0.0,
                max_tokens=max_tokens,
            )
            total_prompt_tokens += repair_response.prompt_tokens
            total_completion_tokens += repair_response.completion_tokens

            content = self._extract_json_block(repair_response.content)
            parsed = self._try_parse(content, response_model)
            if parsed is not None:
                aggregated = LLMResponse(
                    content=repair_response.content,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                    model=repair_response.model,
                    latency_ms=llm_response.latency_ms + repair_response.latency_ms,
                )
                return parsed, aggregated

        raise LLMError(
            f"Failed to parse structured response for {agent_name} "
            f"after {max_retries} repair attempts"
        )

    @retry(
        retry=retry_if_exception_type((APITimeoutError, OpenAIRateLimitError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def vision_extract_text(
        self,
        image_path: str | Path,
        *,
        system_prompt: str | None = None,
        detail: str = "high",
    ) -> LLMResponse:
        """
        Send an image to GPT-4o vision and extract handwritten/printed text.
        Returns the raw OCR text in LLMResponse.content.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise LLMError(f"Image not found: {image_path}")

        with open(image_path, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode("utf-8")

        suffix = image_path.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        mime_type = mime_map.get(suffix, "image/png")

        ocr_system = system_prompt or (
            "You are a precise OCR engine. Extract ALL text from this handwritten "
            "or printed document image. Preserve the original layout, line breaks, "
            "and paragraph structure as closely as possible. Output ONLY the "
            "extracted text — no commentary, no descriptions of the image, no "
            "markdown formatting. If you cannot read a word, write [illegible]. "
            "Preserve the student's original spelling, grammar, and punctuation "
            "exactly as written."
        )

        start = time.perf_counter_ns()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": ocr_system},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{b64_image}",
                                    "detail": detail,
                                },
                            },
                            {
                                "type": "text",
                                "text": "Extract all handwritten and printed text from this image.",
                            },
                        ],
                    },
                ],
                temperature=0.0,
                max_tokens=self._max_tokens,
            )
        except (APITimeoutError, OpenAIRateLimitError):
            raise
        except APIError as exc:
            raise LLMError(f"OpenAI Vision API error: {exc}") from exc

        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        usage = response.usage

        return LLMResponse(
            content=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            model=response.model,
            latency_ms=elapsed_ms,
        )

    def health_check(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:
            return False

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """Strip markdown code fences if present."""
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        return stripped

    @staticmethod
    def _try_parse(content: str, model: Type[T]) -> T | None:
        try:
            data = json.loads(content)
            return model.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None
