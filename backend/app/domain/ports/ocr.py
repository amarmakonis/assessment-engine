"""
OCR provider port — all OCR implementations conform to this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class WordBound:
    word: str
    confidence: float
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float
    word_level_data: list[WordBound] | None
    page_number: int
    processing_ms: int
    provider: str


@runtime_checkable
class OCRProvider(Protocol):
    def extract_text(self, image_path: Path) -> OCRResult:
        """Extract text from a single page image."""
        ...

    def health_check(self) -> bool:
        """Verify the OCR backend is reachable and operational."""
        ...
