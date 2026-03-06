"""
ScoringAgent — scores a student's answer against rubric criteria.
Supports single-criterion (legacy) and batched scoring (one LLM call for all criteria).
"""

from __future__ import annotations

import json
import time

from app.agents.base import BaseAgent
from app.common.observability import evaluation_duration, structured_log
from app.domain.models.evaluation import BatchCriterionScores, CriterionScore

SYSTEM_PROMPT = """\
# ROLE
You are Examiner-1, an impartial and rigorous academic examiner with 20 years of \
experience in fair, evidence-based assessment. You evaluate a student's answer \
against exactly ONE rubric criterion at a time. You are part of an automated \
assessment pipeline where accuracy and fairness are paramount.

# YOUR MANDATE
Award marks strictly and only based on evidence present in the student's answer. \
You must be fair — neither generous nor harsh. Think of yourself as a careful \
human examiner who must justify every mark to an auditor.

# STRICT RULES
1. **One criterion at a time.** You are evaluating against a single, specific \
criterion. Ignore all other aspects of the answer that are not relevant to THIS criterion.
1b. **OR questions.** If the question has "(a) ... OR (b) ...", identify which option the student answered and score only that option; ignore the other.
2. **Evidence-based scoring only.** Every mark you award must be backed by a \
specific quote from the student's answer. If you cannot point to evidence, the \
mark is 0 for that aspect.
3. **Exact quoting.** The `justificationQuote` must be a verbatim substring from \
the student's answer — not a paraphrase, not a summary. Copy it exactly, including \
any spelling errors or OCR artifacts.
4. **Partial credit is required.** Do not round to whole numbers. If a student \
demonstrates partial understanding, award proportional marks (e.g., 1.5 out of 3, \
0.75 out of 2). Use 0.25 granularity at minimum.
5. **Zero means zero.** If the answer contains absolutely no relevant content for \
this criterion, award 0. Do not award sympathy marks.
6. **Never exceed maximum.** `marksAwarded` must be ≤ `maxMarks`. This is a hard constraint.
7. **OCR tolerance.** The answer may contain OCR errors. Do not penalize the student \
for spelling mistakes that are clearly OCR artifacts (e.g., "polynorphism" for \
"polymorphism"). However, DO penalize genuine conceptual errors.
8. **Scoring calibration:**
   - Full marks: All evidence points for this criterion are present and correct
   - 75%+ marks: Most evidence present with minor gaps or imprecision
   - 50% marks: Core concept present but missing significant detail
   - 25% marks: Tangentially related content with major gaps
   - 0 marks: No relevant content whatsoever
9. **Confidence scoring:**
   - 0.9–1.0: Clear evidence (or clear absence), high certainty in score
   - 0.7–0.89: Some interpretation required, but confident
   - 0.5–0.69: Ambiguous answer, multiple valid scores possible
   - Below 0.5: Very uncertain — answer is unclear or criterion is vague
10. **Output ONLY valid JSON.** No markdown, no commentary, no preamble.
11. **DETERMINISM.** For the same answer text and same criterion, you MUST award the same marksAwarded, same justificationQuote, and same confidenceScore every time. Identical input → identical score output. Do not vary on re-runs.

# OUTPUT SCHEMA (strict)
{
  "criterionId": "<exact criterionId from input>",
  "marksAwarded": <float — 0 to maxMarks, 0.25 granularity minimum>,
  "maxMarks": <float — echo the input maxMarks>,
  "justificationQuote": "<exact verbatim quote from the student's answer>",
  "justificationReason": "<1-3 sentence explanation of why this score was awarded>",
  "confidenceScore": <float 0.0-1.0>
}

# ANTI-PATTERNS TO AVOID
- DO NOT award marks for "attempting" the question without demonstrating knowledge
- DO NOT award marks because the answer is long — length ≠ quality
- DO NOT penalize for not answering other parts of the question (that's another criterion)
- DO NOT let one criterion's evaluation influence another — you see only ONE criterion
- DO NOT use justificationQuote to quote the rubric — quote the STUDENT'S answer
"""

SYSTEM_PROMPT_BATCH = """\
# ROLE
You are Examiner-1, an impartial academic examiner. You evaluate a student's answer against \
MULTIPLE rubric criteria in one pass. Return one score object per criterion.

# RULES
1. **Evidence-based.** Every mark must be backed by a verbatim quote from the student's answer.
2. **Exact quoting.** justificationQuote must be a verbatim substring from the answer.
3. **Partial credit.** Use 0.25 granularity; marksAwarded ≤ maxMarks per criterion.
4. **One entry per criterion.** Output a "scores" array with exactly one object per criterion in the order given.
5. **OCR tolerance.** Do not penalize obvious OCR artifacts.
6. **OR / choice questions.** If the question presents alternatives (e.g. "(a) ... OR (b) ..."), determine which option (a or b) the student actually answered from the content of their answer, and score ONLY that option. Ignore content that refers to the other option. The question text includes both options for context; your job is to identify which one was attempted and evaluate accordingly.
7. **DETERMINISM.** Same answer and same criteria list MUST produce the same "scores" array (same marks and justifications per criterionId). Identical input → identical JSON output.
8. **Output ONLY valid JSON** with a single key "scores" whose value is an array of score objects.

# OUTPUT SCHEMA
{
  "scores": [
    {
      "criterionId": "<exact from input>",
      "marksAwarded": <float 0 to maxMarks>,
      "maxMarks": <float>,
      "justificationQuote": "<verbatim from student answer>",
      "justificationReason": "<1-3 sentences>",
      "confidenceScore": <float 0.0-1.0>
    }
  ]
}
"""


class ScoringAgent(BaseAgent[CriterionScore]):
    agent_name = "scoring_agent"
    response_model = CriterionScore

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_user_prompt(
        self,
        *,
        answer_text: str,
        criterion: dict,
        question_text: str,
        **_kwargs,
    ) -> str:
        criterion_block = json.dumps(criterion, indent=2)
        return (
            f"## Question\n{question_text}\n\n"
            f"## Student's Answer\n"
            f"(This is the OCR-extracted text — may contain minor artifacts)\n"
            f"```\n{answer_text}\n```\n\n"
            f"## Rubric Criterion to Evaluate\n"
            f"Score the answer against THIS criterion only.\n"
            f"```json\n{criterion_block}\n```\n\n"
            f"Evaluate and return your JSON score now."
        )

    def score_all_criteria(
        self,
        *,
        answer_text: str,
        grounded_criteria: list[dict],
        question_text: str,
        trace_id: str = "",
    ) -> tuple[list[CriterionScore], list[dict]]:
        """Score all criteria in one LLM call when possible; fallback to per-criterion on batch failure."""
        if len(grounded_criteria) == 0:
            return [], []
        if len(grounded_criteria) == 1:
            return self._score_one_by_one(
                answer_text=answer_text,
                grounded_criteria=grounded_criteria,
                question_text=question_text,
                trace_id=trace_id,
            )
        try:
            return self.score_all_criteria_batched(
                answer_text=answer_text,
                grounded_criteria=grounded_criteria,
                question_text=question_text,
                trace_id=trace_id,
            )
        except Exception:
            return self._score_one_by_one(
                answer_text=answer_text,
                grounded_criteria=grounded_criteria,
                question_text=question_text,
                trace_id=trace_id,
            )

    def score_all_criteria_batched(
        self,
        *,
        answer_text: str,
        grounded_criteria: list[dict],
        question_text: str,
        trace_id: str = "",
    ) -> tuple[list[CriterionScore], list[dict]]:
        """One LLM call for all criteria — significantly faster than N separate calls."""
        start = time.perf_counter_ns()
        criteria_block = json.dumps(grounded_criteria, indent=2)
        user_prompt = (
            f"## Question\n{question_text}\n\n"
            f"## Student's Answer\n```\n{answer_text}\n```\n\n"
            f"## Rubric Criteria (score each in order; return one score object per criterion)\n"
            f"```json\n{criteria_block}\n```\n\n"
            "Return JSON with a \"scores\" array containing one object per criterion, in the same order."
        )
        structured_log("info", "scoring_agent batch starting", trace_id=trace_id, agent_name="scoring_agent")
        parsed, llm_response = self._llm.complete_structured(
            system_prompt=SYSTEM_PROMPT_BATCH,
            user_prompt=user_prompt,
            response_model=BatchCriterionScores,
            agent_name=self.agent_name,
            temperature=0.0,
        )
        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        evaluation_duration.labels(agent_name=self.agent_name, status="success").observe(elapsed_ms / 1000)
        meta = {
            "agent_name": self.agent_name,
            "latency_ms": elapsed_ms,
            "prompt_tokens": llm_response.prompt_tokens,
            "completion_tokens": llm_response.completion_tokens,
        }
        scores = parsed.scores
        if len(scores) != len(grounded_criteria):
            raise ValueError(
                f"Batch returned {len(scores)} scores but {len(grounded_criteria)} criteria expected"
            )
        criterion_ids = {c.get("criterionId") for c in grounded_criteria}
        for s in scores:
            if s.criterion_id not in criterion_ids:
                raise ValueError(f"Unexpected criterionId in batch: {s.criterion_id}")
        return scores, [meta]

    def _score_one_by_one(
        self,
        *,
        answer_text: str,
        grounded_criteria: list[dict],
        question_text: str,
        trace_id: str = "",
    ) -> tuple[list[CriterionScore], list[dict]]:
        """Score each criterion in a separate LLM call (fallback)."""
        scores: list[CriterionScore] = []
        all_meta: list[dict] = []
        for criterion in grounded_criteria:
            score, meta = self.execute(
                trace_id=trace_id,
                answer_text=answer_text,
                criterion=criterion,
                question_text=question_text,
            )
            scores.append(score)
            all_meta.append(meta)
        return scores, all_meta
