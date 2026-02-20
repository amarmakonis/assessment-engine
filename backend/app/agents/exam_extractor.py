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
1. Extract EVERY question from the document. Do not skip any.
2. Preserve the EXACT question text as written in the document.
3. If marks are specified next to a question (e.g., "[5 marks]", "(10)", "Marks: 5"), extract them accurately.
4. If no marks are specified for a question, estimate reasonable marks based on context or set to 10.
5. For rubrics: if a separate rubric document is provided, map each criterion to its corresponding question.
6. If no rubric is provided, generate sensible default rubric criteria based on the question content:
   - For definition questions: "Accuracy of definition", "Key terms used"
   - For explanation questions: "Conceptual understanding", "Clarity of explanation", "Examples provided"
   - For problem-solving: "Correct approach", "Computation accuracy", "Final answer"
   - For essay questions: "Thesis clarity", "Supporting arguments", "Evidence quality", "Conclusion"
7. Each rubric criterion MUST have marks that sum up to the question's total marks.
8. Extract the exam title and subject if mentioned in the document.
9. If the document has sections (Section A, B, etc.), still extract individual questions.
10. Handle sub-questions (a, b, c) as separate questions if they have separate marks, otherwise combine them.

## OUTPUT SCHEMA (strict JSON)
{
  "title": "string — exam title if found, otherwise 'Untitled Exam'",
  "subject": "string — subject if found, otherwise 'General'",
  "questions": [
    {
      "questionText": "string — the full question text",
      "maxMarks": number,
      "rubric": [
        {
          "description": "string — what to evaluate",
          "maxMarks": number
        }
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
    gateway = get_llm_gateway()

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
    except Exception as exc:
        logger.error(f"Failed to parse exam extraction response: {exc}")
        raise ValueError(f"Could not parse exam from document: {exc}") from exc


def extract_text_from_pdf_via_vision(pdf_path: str) -> str:
    """Convert PDF pages to images and extract text using OpenAI Vision."""
    import os
    import tempfile
    from pdf2image import convert_from_path

    images = convert_from_path(pdf_path, dpi=200)
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
