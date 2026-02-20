"""
OCR via OpenAI Vision — GPT-4o extracts text from page images.
No Tesseract, no external OCR services needed.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.common.exceptions import OCRError
from app.domain.ports.ocr import OCRResult
from app.infrastructure.llm import get_llm_gateway

logger = logging.getLogger(__name__)


def extract_page_text(image_path: str | Path, page_number: int = 1) -> OCRResult:
    """
    Extract text from a single page image using OpenAI GPT-4o Vision.
    Returns an OCRResult with extracted text and confidence estimate.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise OCRError(f"Image file not found: {image_path}")

    gateway = get_llm_gateway()
    start = time.perf_counter_ns()

    try:
        llm_response = gateway.vision_extract_text(image_path, detail="high")
    except Exception as exc:
        raise OCRError(f"OpenAI Vision OCR failed: {exc}") from exc

    elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
    text = llm_response.content.strip()

    illegible_count = text.lower().count("[illegible]")
    word_count = len(text.split()) if text else 0
    if word_count == 0:
        confidence = 0.0
    elif illegible_count == 0:
        confidence = 0.95
    else:
        confidence = max(0.0, 1.0 - (illegible_count / max(word_count, 1)) * 2)

    return OCRResult(
        text=text,
        confidence=round(confidence, 3),
        word_level_data=None,
        page_number=page_number,
        processing_ms=elapsed_ms,
        provider="openai_vision",
    )
