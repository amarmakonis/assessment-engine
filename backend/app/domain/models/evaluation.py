"""
Evaluation pipeline domain models — rubric, scores, feedback, audit trail.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.domain.models.common import (
    ConsistencyAssessment,
    EvaluationStatus,
    ReviewRecommendation,
    TokenUsage,
    utcnow,
)


# ── Rubric Grounding ──────────────────────────────────────

class RubricCriterion(BaseModel):
    criterion_id: str = Field(alias="criterionId")
    description: str
    max_marks: float = Field(alias="maxMarks")
    required_evidence_points: list[str] = Field(alias="requiredEvidencePoints")
    is_ambiguous: bool = Field(default=False, alias="isAmbiguous")
    ambiguity_note: str | None = Field(default=None, alias="ambiguityNote")

    model_config = {"populate_by_name": True}


class GroundedRubric(BaseModel):
    total_marks: float = Field(alias="totalMarks")
    criteria: list[RubricCriterion]
    grounding_confidence: float = Field(alias="groundingConfidence")

    model_config = {"populate_by_name": True}


# ── Scoring ────────────────────────────────────────────────

class CriterionScore(BaseModel):
    criterion_id: str = Field(alias="criterionId")
    marks_awarded: float = Field(alias="marksAwarded")
    max_marks: float = Field(alias="maxMarks")
    justification_quote: str = Field(alias="justificationQuote")
    justification_reason: str = Field(alias="justificationReason")
    confidence_score: float = Field(alias="confidenceScore")

    model_config = {"populate_by_name": True}


# ── Consistency Audit ──────────────────────────────────────

class ScoreAdjustment(BaseModel):
    criterion_id: str = Field(alias="criterionId")
    original_score: float = Field(alias="originalScore")
    recommended_score: float = Field(alias="recommendedScore")
    reason: str

    model_config = {"populate_by_name": True}


class FinalCriterionScore(BaseModel):
    criterion_id: str = Field(alias="criterionId")
    final_score: float = Field(alias="finalScore")

    model_config = {"populate_by_name": True}


class ConsistencyAudit(BaseModel):
    overall_assessment: ConsistencyAssessment = Field(alias="overallAssessment")
    adjustments: list[ScoreAdjustment] = Field(default_factory=list)
    final_scores: list[FinalCriterionScore] = Field(alias="finalScores")
    total_score: float = Field(alias="totalScore")
    audit_notes: str = Field(default="", alias="auditNotes")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _fix_total(self) -> "ConsistencyAudit":
        """LLMs frequently miscompute sums — always recompute from final_scores."""
        computed = round(sum(fs.final_score for fs in self.final_scores), 4)
        if abs(self.total_score - computed) > 0.01:
            self.total_score = computed
        return self


# ── Feedback ───────────────────────────────────────────────

class ImprovementItem(BaseModel):
    criterion_id: str = Field(alias="criterionId")
    gap: str
    suggestion: str

    model_config = {"populate_by_name": True}


class StudentFeedback(BaseModel):
    summary: str
    strengths: list[str]
    improvements: list[ImprovementItem]
    study_recommendations: list[str] = Field(alias="studyRecommendations")
    encouragement_note: str = Field(alias="encouragementNote")

    model_config = {"populate_by_name": True}


# ── Explainability ─────────────────────────────────────────

class ExplainabilityResult(BaseModel):
    chain_of_reasoning: str = Field(alias="chainOfReasoning")
    uncertainty_areas: list[str] = Field(alias="uncertaintyAreas")
    review_recommendation: ReviewRecommendation = Field(alias="reviewRecommendation")
    review_reason: str = Field(alias="reviewReason")
    agent_agreement_score: float = Field(alias="agentAgreementScore")

    model_config = {"populate_by_name": True}


# ── Reviewer Override ──────────────────────────────────────

class ReviewerOverride(BaseModel):
    reviewer_id: str = Field(alias="reviewerId")
    override_score: float = Field(alias="overrideScore")
    note: str
    at: datetime

    model_config = {"populate_by_name": True}


# ── Top-Level Evaluation Result ────────────────────────────

class EvaluationResult(BaseModel):
    id: str = Field(default="", alias="_id")
    run_id: str = Field(alias="runId")
    script_id: str = Field(alias="scriptId")
    question_id: str = Field(alias="questionId")
    evaluation_version: str = Field(alias="evaluationVersion")
    idempotency_key: str = Field(alias="idempotencyKey")
    grounded_rubric: GroundedRubric = Field(alias="groundedRubric")
    criterion_scores: list[CriterionScore] = Field(alias="criterionScores")
    consistency_audit: ConsistencyAudit = Field(alias="consistencyAudit")
    feedback: StudentFeedback
    explainability: ExplainabilityResult
    total_score: float = Field(alias="totalScore")
    max_possible_score: float = Field(alias="maxPossibleScore")
    percentage_score: float = Field(alias="percentageScore")
    review_recommendation: ReviewRecommendation = Field(alias="reviewRecommendation")
    reviewer_override: ReviewerOverride | None = Field(default=None, alias="reviewerOverride")
    status: EvaluationStatus = EvaluationStatus.PENDING
    latency_ms: int = Field(alias="latencyMs")
    tokens_used: TokenUsage = Field(alias="tokensUsed")
    created_at: datetime = Field(default_factory=utcnow, alias="createdAt")

    model_config = {"populate_by_name": True}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = self.id
        return data
