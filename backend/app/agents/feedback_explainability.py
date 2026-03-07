"""
FeedbackExplainabilityAgent — merged agent: generates student feedback AND
explainability audit trail in a single LLM call. Reduces per-question calls from 2 to 1.
"""

from __future__ import annotations

import json

from app.agents.base import BaseAgent
from app.domain.models.evaluation import (
    ExplainabilityResult,
    FeedbackExplainabilityResult,
    StudentFeedback,
)

SYSTEM_PROMPT = """\
# ROLE
You are Coach+Auditor, a combined role that produces BOTH (1) pedagogically sound \
student feedback and (2) a complete audit trail for institutional review. Perform \
both in one pass.

# PART 1: STUDENT FEEDBACK
- Generate strengths (evidence-based), improvements (specific gaps + suggestions), \
  study recommendations, encouragement note
- Match tone to performance; never condescend
- Strengths must be real (correspond to marks earned)
- Summary 2-3 sentences; encouragement genuine and specific

# PART 2: EXPLAINABILITY AUDIT
- chainOfReasoning: 3-6 paragraphs covering rubric interpretation, each criterion \
  scored, consistency adjustments, final score computation
- uncertaintyAreas: list specific areas where assessment may be unreliable
- reviewRecommendation: AUTO_APPROVED | NEEDS_REVIEW | MUST_REVIEW (apply threshold \
  rules strictly; do not default to NEEDS_REVIEW out of caution)
- reviewReason: specific trigger for the recommendation
- agentAgreementScore: 0.0–1.0 (how well pipeline agents agreed)

# REVIEW RECOMMENDATION THRESHOLDS
- AUTO_APPROVED: All confidence ≥ 0.85, consistency CONSISTENT, no ambiguous criteria, \
  score 30%-90%, no adjustments
- NEEDS_REVIEW: Any confidence 0.6-0.85, MINOR_ISSUES, 1-2 adjustments, extreme score, \
  one ambiguous criterion. Exception: score ≥85% with only MINOR_ISSUES → AUTO_APPROVED
- MUST_REVIEW: Any confidence < 0.6, SIGNIFICANT_ISSUES, 3+ adjustments, multiple \
  ambiguous, low OCR quality

# STRICT RULES
1. Output ONLY valid JSON. No markdown, no commentary, no preamble.
2. DETERMINISM: same input → same conclusions (wording may vary slightly).

# OUTPUT SCHEMA (strict)
{
  "summary": "<2-3 sentence overall summary>",
  "strengths": ["<specific strength 1>", "<specific strength 2>"],
  "improvements": [
    {"criterionId": "<id>", "gap": "<what was missing>", "suggestion": "<actionable advice>"}
  ],
  "studyRecommendations": ["<specific topic or resource>"],
  "encouragementNote": "<1 genuine, specific closing sentence>",
  "chainOfReasoning": "<multi-paragraph structured narrative>",
  "uncertaintyAreas": ["<area 1>", "<area 2>"],
  "reviewRecommendation": "AUTO_APPROVED" | "NEEDS_REVIEW" | "MUST_REVIEW",
  "reviewReason": "<specific reason for recommendation>",
  "agentAgreementScore": <float 0.0-1.0>
}
"""


class FeedbackExplainabilityAgent(BaseAgent[FeedbackExplainabilityResult]):
    agent_name = "feedback_explainability_agent"
    response_model = FeedbackExplainabilityResult

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_user_prompt(
        self,
        *,
        question_text: str,
        answer_text: str,
        grounded_rubric: dict,
        criterion_scores: list[dict],
        consistency_audit: dict,
        total_score: float,
        max_score: float,
        **_kwargs,
    ) -> str:
        pct = round(total_score / max_score * 100, 1) if max_score > 0 else 0
        return (
            f"## Question\n{question_text}\n\n"
            f"## Student's Answer\n```\n{answer_text}\n```\n\n"
            f"## Grounded Rubric\n```json\n{json.dumps(grounded_rubric, indent=2)}\n```\n\n"
            f"## Criterion Scores (post-consistency)\n"
            f"```json\n{json.dumps(criterion_scores, indent=2)}\n```\n\n"
            f"## Consistency Audit\n```json\n{json.dumps(consistency_audit, indent=2)}\n```\n\n"
            f"## Final Score: {total_score}/{max_score} ({pct}%)\n\n"
            "Generate pedagogically sound feedback AND the complete audit trail. Return your JSON output now."
        )

    def to_feedback(self, result: FeedbackExplainabilityResult) -> StudentFeedback:
        """Extract StudentFeedback for downstream compatibility."""
        return StudentFeedback(
            summary=result.summary,
            strengths=result.strengths,
            improvements=result.improvements,
            studyRecommendations=result.study_recommendations,
            encouragementNote=result.encouragement_note,
        )

    def to_explainability(self, result: FeedbackExplainabilityResult) -> ExplainabilityResult:
        """Extract ExplainabilityResult for downstream compatibility."""
        return ExplainabilityResult(
            chainOfReasoning=result.chain_of_reasoning,
            uncertaintyAreas=result.uncertainty_areas,
            reviewRecommendation=result.review_recommendation,
            reviewReason=result.review_reason,
            agentAgreementScore=result.agent_agreement_score,
        )
