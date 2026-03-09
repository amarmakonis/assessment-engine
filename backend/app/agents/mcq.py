"""
MCQ detection and deterministic scoring.

MCQs are scored by option match only: correct option = full marks, wrong = 0.
No LLM-based evidence or partial marks. This logic is fixed and must not be
overridden by essay-style scoring.
"""

from __future__ import annotations

import re
from typing import Optional

# Option letters we treat as MCQ choices
OPTION_LETTERS = frozenset("ABCD")
OPTION_PATTERN = re.compile(r"\(([A-Da-d])\)|^\s*([A-Da-d])\s*$|option\s*([A-Da-d])|answer\s*[:\s]+\s*([A-Da-d])", re.IGNORECASE | re.MULTILINE)
# Pattern to find "correct answer is B" or "Answer: (B)" in rubric text
CORRECT_PATTERN = re.compile(
    r"(?:correct|right|answer)\s*(?:is|:|=)\s*[\(\s]*([A-Da-d])[\)\s]*|"
    r"\(([A-Da-d])\)\s*(?:is\s+correct|correct)|"
    r"answer\s*[:\s]+\s*([A-Da-d])",
    re.IGNORECASE,
)


def is_mcq_question(question_text: str) -> bool:
    """True if question text clearly presents options (A), (B), (C), (D)."""
    if not (question_text or question_text.strip()):
        return False
    text = question_text.upper()
    # Must have at least (A) and (B) or similar
    has_a = "(A)" in text or " A)" in text or " A " in text
    has_b = "(B)" in text or " B)" in text or " B " in text
    has_c = "(C)" in text or " C)" in text or " C " in text
    has_d = "(D)" in text or " D)" in text or " D " in text
    return (has_a and has_b) and (has_c or has_d)


def extract_correct_option(rubric_criteria: list[dict]) -> Optional[str]:
    """Extract the correct option letter (A/B/C/D) from rubric text. Returns None if unclear."""
    for c in rubric_criteria:
        desc = (c.get("description") or "").strip()
        if not desc:
            continue
        m = CORRECT_PATTERN.search(desc)
        if m:
            for g in m.groups():
                if g:
                    return g.upper()
    return None


def normalize_student_option(answer_text: str) -> Optional[str]:
    """Extract a single option letter A–D from the student's answer. Returns None if ambiguous."""
    if not (answer_text or answer_text.strip()):
        return None
    stripped = answer_text.strip()
    # Single letter
    if len(stripped) == 1 and stripped.upper() in OPTION_LETTERS:
        return stripped.upper()
    # (B) or (b)
    m = re.match(r"^\s*\(\s*([A-Da-d])\s*\)\s*", stripped)
    if m:
        return m.group(1).upper()
    # "B." or "B)"
    m = re.match(r"^\s*([A-Da-d])[\s.\)].*", stripped)
    if m:
        return m.group(1).upper()
    # "option B" at start
    m = re.search(r"option\s*([A-Da-d])\b", stripped, re.IGNORECASE)
    if m and len(stripped) < 30:
        return m.group(1).upper()
    return None


def score_mcq_deterministic(
    question_text: str,
    answer_text: str,
    rubric_criteria: list[dict],
    question_max_marks: float,
) -> Optional[tuple[str, float, float, str]]:
    """
    If this is an MCQ and we can determine correct/student option, return
    (criterion_id, marks_awarded, max_marks, reason). Otherwise return None.
    Logic: correct option = full marks, wrong = 0. No partial marks.
    """
    if not is_mcq_question(question_text) or not rubric_criteria:
        return None
    correct = extract_correct_option(rubric_criteria)
    student = normalize_student_option(answer_text)
    if correct is None or student is None:
        return None
    criterion_id = rubric_criteria[0].get("criterionId") or "c1"
    max_marks = float(rubric_criteria[0].get("maxMarks", question_max_marks))
    if max_marks <= 0:
        max_marks = question_max_marks
    if correct == student:
        return (criterion_id, max_marks, max_marks, "Correct option selected.")
    return (criterion_id, 0.0, max_marks, "Incorrect option.")
