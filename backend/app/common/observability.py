"""
Prometheus metrics and structured logging helpers.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any, Generator

from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# ── Prometheus Metrics ────────────────────────────────────

ocr_processing_duration = Histogram(
    "aae_ocr_processing_duration_seconds",
    "OCR processing duration",
    ["provider", "status"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120),
)

ocr_confidence_score = Histogram(
    "aae_ocr_confidence_score",
    "OCR confidence score distribution",
    ["institution_id"],
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

evaluation_duration = Histogram(
    "aae_evaluation_duration_seconds",
    "Evaluation agent duration",
    ["agent_name", "status"],
    buckets=(1, 2, 5, 10, 30, 60, 120),
)

llm_tokens_total = Counter(
    "aae_llm_tokens_used_total",
    "Total LLM tokens consumed",
    ["agent_name", "model"],
)

llm_latency = Histogram(
    "aae_llm_latency_seconds",
    "LLM call latency",
    ["agent_name"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60),
)

tasks_total = Counter(
    "aae_tasks_total",
    "Total Celery tasks processed",
    ["queue", "status"],
)


# ── Trace Context ─────────────────────────────────────────

def generate_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def structured_log(
    level: str,
    message: str,
    *,
    trace_id: str = "",
    institution_id: str = "",
    script_id: str = "",
    agent_name: str = "",
    duration_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "traceId": trace_id,
        "institutionId": institution_id,
        "scriptId": script_id,
        "agentName": agent_name,
    }
    if duration_ms is not None:
        payload["durationMs"] = duration_ms
    if extra:
        payload.update(extra)

    getattr(logger, level.lower(), logger.info)(message, extra=payload)


@contextmanager
def timed_block(metric: Histogram, labels: dict) -> Generator[None, None, None]:
    start = time.perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.perf_counter() - start
        metric.labels(**{**labels, "status": status}).observe(elapsed)


def track_llm_usage(agent_name: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    total = prompt_tokens + completion_tokens
    llm_tokens_total.labels(agent_name=agent_name, model=model).inc(total)
