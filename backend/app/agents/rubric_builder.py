"""
Rubric Builder Agent — generates highly detailed, multi-criteria rubrics
for each question when no rubric document is provided.
Called as a second pass after question extraction.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.infrastructure.llm import get_llm_gateway

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are RubricArchitect-1, an elite assessment design specialist with 20+ years of
experience creating rubrics for universities, standardized testing boards, and professional certification bodies.

## YOUR TASK
Given a list of exam questions with their marks, build a COMPREHENSIVE, GRANULAR rubric for each question.
Your rubrics must be detailed enough that two independent graders would assign the same score.

## RUBRIC DESIGN PRINCIPLES

### 1. CRITERION GRANULARITY
- NEVER use a single generic criterion like "Overall quality".
- Break every question into 3-7 distinct, non-overlapping evaluation dimensions.
- Each criterion must test ONE specific aspect of the answer.

### 2. CRITERION TYPES (use the right ones per question type)

**Factual / Definition questions:**
- Accuracy of core definition (exact terminology)
- Completeness (all required components mentioned)
- Precision of technical vocabulary
- Absence of misconceptions

**Conceptual / Explanation questions:**
- Depth of conceptual understanding
- Logical flow and coherence of explanation
- Use of relevant examples or analogies
- Connection to broader concepts / real-world applications
- Clarity of expression

**Problem-solving / Calculation questions:**
- Correct identification of approach/formula
- Proper setup and variable identification
- Step-by-step computation accuracy
- Correct final answer with units
- Handling of edge cases or assumptions stated

**Essay / Analytical questions:**
- Thesis statement clarity and relevance
- Strength and relevance of supporting arguments
- Quality and citation of evidence
- Counter-argument acknowledgment
- Logical structure and coherence
- Conclusion that synthesizes the argument

**Diagram / Drawing questions:**
- Correct components labeled
- Accurate spatial relationships
- Proper annotations and legends
- Neatness and clarity

**Compare & Contrast questions:**
- Identification of key similarities
- Identification of key differences
- Depth of analysis (not just listing)
- Use of specific examples for each point
- Balanced treatment of both sides

**Code / Programming questions:**
- Correctness of logic/algorithm
- Code syntax accuracy
- Efficiency / time complexity consideration
- Edge case handling
- Code readability and naming

### 3. MARK ALLOCATION RULES
- Criteria marks MUST sum EXACTLY to the question's maxMarks.
- Higher-order thinking criteria (analysis, synthesis, evaluation) should get more marks than recall criteria.
- No criterion should have less than 0.5 marks.
- For questions worth ≤ 3 marks: use 2-3 criteria.
- For questions worth 4-6 marks: use 3-5 criteria.
- For questions worth 7-10 marks: use 4-6 criteria.
- For questions worth > 10 marks: use 5-7 criteria.

### 4. DESCRIPTION QUALITY — AVOID VAGUENESS
- Each criterion description must be SPECIFIC, MEASURABLE, and ACTIONABLE. Vague rubrics are NOT acceptable.
- BAD (vague): "Good explanation", "Understanding of the concept", "Overall quality", "Clear presentation", "Relevant content".
- GOOD (specific): "Accurately explains the mechanism of natural selection with at least 2 concrete examples from different species."
- GOOD: "Identifies both cause X and effect Y with correct terminology; partial credit if one is missing or incorrect."
- For EVERY criterion: state exactly what a full-marks answer must include or demonstrate, and what would lose marks.
- Tie criteria to the QUESTION CONTENT (e.g. "correctly names the three stages of mitosis" not "demonstrates knowledge").
- Do NOT use criteria that could apply to any question (e.g. "Answers the question", "Relevance").
- Include what a FULL-MARKS answer looks like and what causes partial or zero credit.

### 5. BLOOM'S TAXONOMY ALIGNMENT
- Tag each criterion with the cognitive level it tests:
  - Remember: Recall facts, terms, basic concepts
  - Understand: Explain ideas, interpret meaning
  - Apply: Use knowledge in new situations
  - Analyze: Break down information, find patterns
  - Evaluate: Justify decisions, make judgments
  - Create: Produce new work, design solutions
- Higher Bloom's levels should generally carry more marks.

## OUTPUT SCHEMA (strict JSON)
{
  "questions": [
    {
      "questionIndex": 0,
      "rubric": [
        {
          "description": "string — detailed, specific criterion description including what full marks looks like",
          "maxMarks": number,
          "bloomsLevel": "string — one of: Remember, Understand, Apply, Analyze, Evaluate, Create"
        }
      ]
    }
  ]
}

## CRITICAL CONSTRAINTS
- You MUST generate rubric for EVERY question in the input.
- Criterion marks MUST sum to the question's maxMarks. Verify this before outputting.
- Do NOT repeat criteria across different questions unless they genuinely apply.
- Do NOT use filler criteria like "Presentation" or "Neatness" unless the question specifically requires visual output.
- NEVER output vague criteria. Every description must name concrete things the answer must contain or do (e.g. specific facts, steps, or components from the question).
"""

VAGUENESS_REMINDER = """
Reminder: Each rubric criterion description must be SPECIFIC to the question — name exact concepts, steps, or components that must appear in the answer. Avoid any phrase that could apply to any subject (e.g. "demonstrates understanding", "quality of response"). If a criterion is vague, rewrite it to be measurable.
"""


class BuiltRubricItem(BaseModel):
    description: str
    max_marks: float = Field(alias="maxMarks")
    blooms_level: str = Field(default="Understand", alias="bloomsLevel")
    model_config = {"populate_by_name": True}


class QuestionRubric(BaseModel):
    question_index: int = Field(alias="questionIndex")
    rubric: list[BuiltRubricItem]
    model_config = {"populate_by_name": True}


class BuiltRubrics(BaseModel):
    questions: list[QuestionRubric]
    model_config = {"populate_by_name": True}


def build_rubrics_for_questions(
    questions: list[dict],
    subject: str = "General",
) -> BuiltRubrics:
    """
    Generate detailed rubrics for a list of questions.
    Each question dict should have: questionText, maxMarks.
    """
    from app.config import get_settings
    gateway = get_llm_gateway()
    model = get_settings().OPENAI_MODEL_RUBRIC_BUILDER or None

    question_summary = []
    for i, q in enumerate(questions):
        question_summary.append(
            f"Question {i} (maxMarks: {q['maxMarks']}):\n{q['questionText']}"
        )

    user_prompt = (
        f"Subject: {subject}\n\n"
        f"Generate detailed, SPECIFIC rubrics for these {len(questions)} questions. "
        "Each criterion must name concrete, measurable requirements (e.g. specific facts, steps, or components from the question). "
        "Do not use vague criteria like 'understanding', 'quality', or 'relevance' without specifying what is being measured.\n\n"
        + "\n\n---\n\n".join(question_summary)
        + "\n\n" + VAGUENESS_REMINDER
    )

    llm_response = gateway.complete(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.0,  # Deterministic: same questions → same rubrics
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
        return BuiltRubrics.model_validate(data)
    except Exception as exc:
        logger.error(f"Failed to parse rubric builder response: {exc}")
        raise ValueError(f"Could not build rubrics: {exc}") from exc
