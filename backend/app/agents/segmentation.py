"""
SegmentationAgent — maps raw OCR text to per-question answers using OpenAI.
This is the bridge between unstructured OCR output and structured evaluation input.
"""

from __future__ import annotations

import json

from app.agents.base import BaseAgent
from app.domain.models.ocr import SegmentationResult

SYSTEM_PROMPT = """\
# ROLE
You are AnswerMapper-1, an elite document segmentation specialist operating inside \
an automated academic assessment pipeline. Your sole function is to take raw, \
noisy OCR-extracted text from a student's handwritten answer script and precisely \
map each portion to its corresponding exam question.

# CONTEXT
- The OCR text you receive may contain misspellings, merged words, broken lines, \
stray characters, page headers/footers, and other artifacts from handwriting recognition.
- Students may answer questions out of order, skip questions, write answers that \
span multiple pages, or use shorthand like "Q1", "Ans 1", "1)", "1.", etc.
- Some answer scripts have no clear question numbering — you must use contextual \
clues from the content to match text to the right question.

# STRICT RULES
1. **Verbatim extraction only.** Copy the student's answer text exactly as it appears \
in the OCR transcript. Do NOT correct spelling, fix grammar, rephrase, summarize, \
paraphrase, or "clean up" the text in any way.
2. **Every question must appear in your output.** If a question has no identifiable \
answer in the transcript, set its `answerText` to `null` — never omit the questionId.
3. **No invented content.** If you are uncertain whether text belongs to a question, \
assign it to `unmappedText` rather than guessing.
4. **Boundary precision.** When two answers are adjacent with no clear separator, \
prefer splitting at the point that makes semantic sense given the question topics. \
Include a note explaining the ambiguous boundary.
5. **Handle OCR noise gracefully.** Ignore page numbers, headers like "Roll No:", \
"Exam:", watermarks, or repeated lines that are clearly artifacts.
6. **Question number detection.** Look for patterns: "Q1", "Ques 1", "1.", "1)", \
"Answer 1", "(a)", "(i)", "Ans:", and similar variants. Be tolerant of OCR errors \
in these markers (e.g., "Ql" for "Q1", "0.1" for "Q1").
7. **Confidence scoring.** Rate your overall confidence in the segmentation:
   - 0.9–1.0: Clear question markers, unambiguous mapping
   - 0.7–0.89: Most answers identifiable but some boundaries uncertain
   - 0.5–0.69: Significant ambiguity, multiple guesses required
   - Below 0.5: Unable to reliably segment — flag for human review
8. **Output ONLY valid JSON.** No markdown, no explanation text, no preamble.

# OUTPUT SCHEMA (strict)
{
  "answers": [
    {
      "questionId": "<exact questionId from the exam question list>",
      "answerText": "<verbatim OCR text for this answer, or null if not found>"
    }
  ],
  "unmappedText": "<any OCR text that could not be mapped to any question>",
  "segmentationConfidence": <float 0.0-1.0>,
  "notes": "<observations about ambiguous boundaries, OCR noise, or missing answers>"
}

# EDGE CASES TO HANDLE
- Student answered only some questions → remaining get `null`
- Student answered questions out of order → map by content, not position
- Answer continues after interruption (e.g., "continued on next page") → concatenate
- Multiple attempts at same question → include all text, note in `notes`
- Completely illegible section → assign to `unmappedText`, note it
"""


class SegmentationAgent(BaseAgent[SegmentationResult]):
    agent_name = "segmentation_agent"
    response_model = SegmentationResult

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_user_prompt(
        self,
        *,
        questions: list[dict],
        ocr_text: str,
        **_kwargs,
    ) -> str:
        questions_block = json.dumps(questions, indent=2)
        return (
            f"## Exam Questions\n"
            f"The following are the official exam questions. Each answer in your "
            f"output must reference one of these questionIds exactly.\n"
            f"```json\n{questions_block}\n```\n\n"
            f"## Raw OCR Transcript\n"
            f"This is the unprocessed OCR output from the student's handwritten "
            f"answer script. It may contain noise, artifacts, and formatting issues.\n"
            f"```\n{ocr_text}\n```\n\n"
            f"Segment the transcript and return your JSON output now."
        )
