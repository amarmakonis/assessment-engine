"""
OCR via OpenAI Vision — GPT-4o extracts text from page images.
Enhanced with production-grade image preprocessing and strict system prompting.
"""

from __future__ import annotations

import logging
import time
import tempfile
import os
from pathlib import Path

from PIL import Image, ImageEnhance

from app.common.exceptions import OCRError
from app.domain.ports.ocr import OCRResult
from app.infrastructure.llm import get_llm_gateway

logger = logging.getLogger(__name__)

OCR_SYSTEM_PROMPT = """You are a highly advanced, production-grade Optical Character Recognition (OCR) engine. 
Your sole responsibility is to extract ALL handwritten and printed text from the provided image with absolute precision.

STRICT RULES:
1. PRESERVE LAYOUT: Maintain original line breaks, paragraph structure, indentations, and spatial arrangements.
2. ABSOLUTE ACCURACY: Do NOT autocorrect original spelling mistakes, grammatical errors, or peculiar phrasing. Transcribe exactly as written.
3. ILLEGIBLE TEXT: If a word is genuinely impossible to read, use the placeholder [illegible]. Do not guess blindly.
4. NO HALLUCINATION: Output ONLY the text visible in the image. Do NOT add commentary, conversational responses, metadata, or markdown text block formatting markers like ```.
5. SYMBOLS & MATH: Accurately transcribe mathematical formulas, special characters, and scientific notations if present.
6. CROSSED OUT / STRICKETHROUGH / SCRATCHED TEXT: COMPLETELY IGNORE any text that has been crossed out, struck through (strikethrough), scratched out, or marked for deletion. DO NOT transcribe it under any circumstances. If an entire paragraph or answer is crossed out, omit it entirely from your output. Only transcribe text that the student intends to submit as their final answer.

Focus heavily on accurately capturing faint handwriting and complex mixed layouts (such as exam answer booklets or resumes)."""


def preprocess_image_for_ocr(original_path: Path) -> Path:
    """
    Enhance the image to improve OCR accuracy for faint handwriting.
    Returns the path to the enhanced temporary image.
    """
    try:
        with Image.open(original_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Resize if excessively large to prevent OpenAI API timeouts
            max_size = 2048
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # Enhance Contrast heavily to make pencil/faint ink pop out
            img = ImageEnhance.Contrast(img).enhance(1.8)

            # Sharpen the image significantly to crisp up edges of letters
            img = ImageEnhance.Sharpness(img).enhance(2.0)

            # Optional: Color enhancement to reduce slight discoloration, making paper whiter
            img = ImageEnhance.Color(img).enhance(0.5)

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            temp_file.close()  # Must close on Windows before PIL saves to it
            img.save(temp_file.name, format="JPEG", quality=85, optimize=True)
            return Path(temp_file.name)
    except Exception as e:
        logger.warning(f"Image preprocessing failed for {original_path}: {e}")
        return original_path


def extract_page_text(image_path: str | Path, page_number: int = 1) -> OCRResult:
    """
    Extract text from a single page image using OpenAI GPT-4o Vision.
    Applies image preprocessing before extracting.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise OCRError(f"Image file not found: {image_path}")

    gateway = get_llm_gateway()

    # 1. Preprocess the image
    enhanced_path = preprocess_image_for_ocr(image_path)
    is_temp_file = enhanced_path != image_path

    start = time.perf_counter_ns()

    try:
        # 2. Extract using enhanced prompt and preprocessed image
        llm_response = gateway.vision_extract_text(
            enhanced_path,
            system_prompt=OCR_SYSTEM_PROMPT,
            detail="high",
        )
    except Exception as exc:
        raise OCRError(f"OpenAI Vision OCR failed: {exc}") from exc
    finally:
        # 3. Clean up the ephemeral preprocessed file to prevent disk bloat
        if is_temp_file and enhanced_path.exists():
            try:
                os.remove(enhanced_path)
            except OSError as e:
                logger.warning(f"Failed to remove temporary enhanced image {enhanced_path}: {e}")

    elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
    text = llm_response.content.strip()

    # Calculate confidence based on occurrence of the [illegible] marker
    illegible_count = text.lower().count("[illegible]")
    word_count = len(text.split()) if text else 0

    if word_count == 0:
        confidence = 0.0
    elif illegible_count == 0:
        confidence = 0.95
    else:
        # Confidence drops as ratio of illegible words increases
        confidence = max(0.0, 1.0 - (illegible_count / max(word_count, 1)) * 2)

    return OCRResult(
        text=text,
        confidence=round(confidence, 3),
        word_level_data=None,
        page_number=page_number,
        processing_ms=elapsed_ms,
        provider="openai_vision",
    )
