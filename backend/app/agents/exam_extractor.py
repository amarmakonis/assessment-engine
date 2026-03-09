"""
Exam Extraction Agent — extracts questions and rubrics from uploaded
question papers and rubric documents using OpenAI.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.infrastructure.llm import get_llm_gateway

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ExamExtractor-1, a precision document parser for educational assessments.

## YOUR TASK
Given the raw text extracted from a question paper and/or rubric document, produce a structured JSON output containing all questions, their marks, and grading rubric criteria.

## STRICT RULES
1. **English only — ignore Hindi.** If the document is bilingual (Hindi and English), extract ONLY the English version of each question. Ignore all Hindi text. Do not create duplicate questions for the Hindi version. If the same question appears in both languages, include only the English questionText.
2. **Question number = number as printed.** For each question, set `questionNumber` to the exact number shown on the paper (e.g. "24." or "Q. 24" → questionNumber 24). This ensures question 23 is stored as 23 and question 24 as 24; do not rely on list position alone. If the document has no explicit number, use the 1-based position in the sequence.
3. **OR questions = one question, one mark total.** When the paper has "(a) ... OR (b) ..." (student answers either (a) or (b)), output ONE question: include the full text of both options in questionText, and set maxMarks to the marks for ONE option only (e.g. if (a) has 3 and (b) has 3, use maxMarks 3 so the total is not 6). The sum of all questions' maxMarks must match the document total (e.g. 80).
4. **Extract exact marks per question.** Use the marks exactly as printed (e.g. "[5 marks]", "(2)", "Marks: 4"). Do not scale or redistribute. The sum of all maxMarks must equal the stated maximum (e.g. Maximum Marks : 80).
5. Extract EVERY question from the document (English only). Do not skip any.
6. Preserve the EXACT question text as written (English only). For OR questions, keep both (a) and (b) in questionText so the evaluator can tell which option the student answered.
7. For rubrics: if a separate rubric document is provided, map each criterion to its corresponding question. Keep or refine descriptions to be SPECIFIC and measurable (what exactly gets full vs partial marks).
8. If no rubric is provided, generate specific default rubric criteria — not vague ones like "overall quality". Each criterion must name concrete requirements (e.g. key terms, steps, or components the answer must include). Each criterion's maxMarks must sum to the question's maxMarks.
9. Extract the exam title and subject if mentioned.
10. If the document has sections (Section A, B, etc.), still extract individual questions (English only). Use the printed question number for each.
11. Sub-questions (a), (b), (c) that are all to be answered (no OR) may be separate questions if they have separate marks; if they share one mark block, combine. For "(a) ... OR (b) ..." always one question with maxMarks = one option's marks.

## OUTPUT SCHEMA (strict JSON)
{
  "title": "string — exam title if found, otherwise 'Untitled Exam'",
  "subject": "string — subject if found, otherwise 'General'",
  "questions": [
    {
      "questionNumber": <number, as printed on the document e.g. 1, 2, 24 — required for correct numbering>,
      "questionText": "string — the full question text (for OR questions, include both (a) and (b) options)",
      "maxMarks": number — exact marks for this question (for OR questions, the marks for one option only, e.g. 3 not 6),
      "rubric": [
        { "description": "string", "maxMarks": number }
      ]
    }
  ]
}
"""


class RubricItem(BaseModel):
    description: str
    max_marks: float = Field(alias="maxMarks")
    model_config = {"populate_by_name": True}


class ExtractedQuestion(BaseModel):
    question_number: int | None = Field(default=None, alias="questionNumber")
    question_text: str = Field(alias="questionText")
    max_marks: float = Field(alias="maxMarks")
    rubric: list[RubricItem] = Field(default_factory=list)
    model_config = {"populate_by_name": True}


class ExtractedExam(BaseModel):
    title: str = "Untitled Exam"
    subject: str = "General"
    questions: list[ExtractedQuestion] = Field(default_factory=list)
    model_config = {"populate_by_name": True}


def extract_exam_from_text(
    question_paper_text: str,
    rubric_text: str | None = None,
) -> ExtractedExam:
    """
    Use OpenAI to parse raw document text into structured exam data.
    """
    from app.config import get_settings
    gateway = get_llm_gateway()
    model = get_settings().OPENAI_MODEL_EXAM_EXTRACTION or None

    user_prompt_parts = ["## QUESTION PAPER TEXT\n", question_paper_text]
    if rubric_text:
        user_prompt_parts.append("\n\n## RUBRIC / MARKING SCHEME TEXT\n")
        user_prompt_parts.append(rubric_text)

    user_prompt = "".join(user_prompt_parts)

    llm_response = gateway.complete(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=8192,
        model=model,
    )

    content = llm_response.content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        data = json.loads(content)
        return ExtractedExam.model_validate(data)
    except json.JSONDecodeError as exc:
        preview = (content[:500] + "…") if len(content) > 500 else content
        logger.error(
            "Exam extraction: invalid JSON from LLM (msg=%s, preview=%s)",
            exc,
            preview,
        )
        raise ValueError(f"Invalid JSON from document extraction: {exc}") from exc
    except Exception as exc:
        preview = (content[:500] + "…") if len(content) > 500 else content
        logger.error(
            "Exam extraction: parse/validation failed (exc=%s, preview=%s)",
            exc,
            preview,
        )
        raise ValueError(f"Could not parse exam from document: {exc}") from exc


# Minimum characters from fast extraction to skip Vision (avoids N API calls for typed PDFs).
_PDF_FAST_EXTRACT_MIN_CHARS = 80


def extract_text_from_pdf_fast(pdf_path: str) -> str:
    """Extract text from PDF using pypdf — no API calls, instant for typed question papers."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        parts = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                parts.append(f"--- Page {i + 1} ---\n{text.strip()}")
        return "\n\n".join(parts) if parts else ""
    except Exception as e:
        logger.warning("Fast PDF extraction failed, will use Vision: %s", e)
        return ""


def extract_text_from_pdf_via_vision(pdf_path: str) -> str:
    """
    Extract text from PDF: try fast path (pypdf, no API) first.
    Only use OpenAI Vision (one call per page) for scanned/handwritten PDFs where fast path returns little text.
    """
    fast_text = extract_text_from_pdf_fast(pdf_path)
    if len(fast_text.strip()) >= _PDF_FAST_EXTRACT_MIN_CHARS:
        logger.info("Using fast PDF text extraction (no Vision API calls)")
        return fast_text

    logger.info("Fast extraction yielded little text; using Vision API per page")
    import os
    import tempfile
    from pdf2image import convert_from_path

    images = convert_from_path(pdf_path, dpi=150)
    gateway = get_llm_gateway()
    all_text = []

    tmpdir = tempfile.mkdtemp()
    for i, img in enumerate(images, start=1):
        page_path = os.path.join(tmpdir, f"page_{i}.png")
        img.save(page_path, "PNG")

        response = gateway.vision_extract_text(page_path, detail="high")
        all_text.append(f"--- Page {i} ---\n{response.content.strip()}")

    return "\n\n".join(all_text)


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file."""
    from io import BytesIO
    from docx import Document

    doc = Document(BytesIO(file_bytes))
    paragraphs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                paragraphs.append(" | ".join(cells))

    return "\n".join(paragraphs)


def extract_text_from_image_via_vision(image_path: str) -> str:
    """Extract text from a single image using OpenAI Vision."""
    gateway = get_llm_gateway()
    response = gateway.vision_extract_text(image_path, detail="high")
    return response.content.strip()
