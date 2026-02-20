"""
Evaluation pipeline Celery tasks — rubric grounding, scoring, consistency,
feedback, explainability, and finalization.

All tasks: bind=True, acks_late=True, reject_on_worker_lost=True.
Idempotent by composite key: runId:scriptId:questionId:version.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from celery import group

from app.common.observability import structured_log, tasks_total
from app.config import get_settings
from app.domain.models.common import (
    EvaluationStatus,
    ScriptSource,
    ScriptStatus,
)
from app.infrastructure.cache.redis_cache import RedisCache
from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ExamRepository,
    ScriptRepository,
    UploadedScriptRepository,
)
from celery_app import celery

logger = logging.getLogger(__name__)
EVALUATION_VERSION = "1.0.0"


@celery.task(
    bind=True,
    name="app.tasks.evaluation.prepare_script",
    queue="evaluation",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=2,
)
def prepare_script(
    self,
    uploaded_script_id: str,
    segmentation_result: dict,
    avg_confidence: float,
    quality_flags: list[str],
    trace_id: str,
):
    """Create the Script document from segmentation results and fan out evaluation tasks."""
    try:
        upload_doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
        if not upload_doc:
            logger.error(f"UploadedScript {uploaded_script_id} not found")
            return

        answers = []
        flagged_questions = []
        for ans in segmentation_result.get("answers", []):
            is_flagged = ans.get("answerText") is None
            if is_flagged:
                flagged_questions.append(ans["questionId"])
            answers.append({
                "questionId": ans["questionId"],
                "text": ans.get("answerText") or "",
                "isFlagged": is_flagged,
            })

        script_doc = {
            "institutionId": upload_doc["institutionId"],
            "examId": upload_doc["examId"],
            "uploadedScriptId": uploaded_script_id,
            "studentMeta": upload_doc["studentMeta"],
            "answers": answers,
            "source": ScriptSource.OCR.value,
            "ocrConfidenceAverage": avg_confidence,
            "ocrQualityFlags": quality_flags,
            "segmentationConfidence": segmentation_result.get("segmentationConfidence"),
            "status": ScriptStatus.EVALUATING.value,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }

        script_id = ScriptRepository().insert_one(script_doc)
        run_id = uuid.uuid4().hex

        from app.domain.models.common import UploadStatus
        UploadedScriptRepository().update_one(
            uploaded_script_id, {"$set": {"uploadStatus": UploadStatus.EVALUATING.value}}
        )

        non_flagged = [a for a in answers if not a["isFlagged"] and a["text"].strip()]
        if non_flagged:
            task_group = group(
                evaluate_question.s(script_id, a["questionId"], run_id, trace_id)
                for a in non_flagged
            )
            task_group.apply_async()

        tasks_total.labels(queue="evaluation", status="success").inc()

    except Exception as exc:
        tasks_total.labels(queue="evaluation", status="error").inc()
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)


@celery.task(
    bind=True,
    name="app.tasks.evaluation.evaluate_question",
    queue="evaluation",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
    soft_time_limit=300,
    time_limit=360,
)
def evaluate_question(
    self,
    script_id: str,
    question_id: str,
    run_id: str,
    trace_id: str,
):
    """
    Full evaluation pipeline for a single (scriptId × questionId).
    Idempotent by composite key.
    """
    from app.agents import (
        ConsistencyAgent,
        ExplainabilityAgent,
        FeedbackAgent,
        RubricGroundingAgent,
        ScoringAgent,
    )

    idempotency_key = f"{run_id}:{script_id}:{question_id}:{EVALUATION_VERSION}"

    cache = RedisCache()
    if not cache.set_with_nx(f"eval_lock:{idempotency_key}", "1", ttl=600):
        existing = EvaluationResultRepository().find_by_idempotency_key(idempotency_key)
        if existing:
            logger.info(f"Idempotent skip: {idempotency_key}")
            return
        cache.delete(f"eval_lock:{idempotency_key}")

    start = time.perf_counter_ns()
    total_prompt_tokens = 0
    total_completion_tokens = 0

    try:
        script_doc = ScriptRepository().find_by_id(script_id)
        if not script_doc:
            raise ValueError(f"Script {script_id} not found")

        exam_doc = ExamRepository().find_by_id(script_doc["examId"])
        if not exam_doc:
            raise ValueError(f"Exam {script_doc['examId']} not found")

        answer_entry = next(
            (a for a in script_doc["answers"] if a["questionId"] == question_id),
            None,
        )
        if not answer_entry:
            raise ValueError(f"Answer for question {question_id} not found in script")

        question_def = next(
            (q for q in exam_doc["questions"] if q["questionId"] == question_id),
            None,
        )
        if not question_def:
            raise ValueError(f"Question {question_id} not found in exam")

        answer_text = answer_entry["text"]
        question_text = question_def["questionText"]
        rubric_criteria = [
            {
                "criterionId": c["criterionId"],
                "description": c["description"],
                "maxMarks": c["maxMarks"],
            }
            for c in question_def.get("rubric", [])
        ]

        # ── Agent 1: Rubric Grounding ─────────────────────
        rubric_agent = RubricGroundingAgent()
        grounded_rubric, rubric_meta = rubric_agent.execute(
            trace_id=trace_id,
            question_text=question_text,
            rubric_criteria=rubric_criteria,
        )
        total_prompt_tokens += rubric_meta["prompt_tokens"]
        total_completion_tokens += rubric_meta["completion_tokens"]

        # ── Agent 2: Scoring (per criterion) ───────────────
        scoring_agent = ScoringAgent()
        criterion_scores, scoring_metas = scoring_agent.score_all_criteria(
            trace_id=trace_id,
            answer_text=answer_text,
            grounded_criteria=[
                c.model_dump(by_alias=True) for c in grounded_rubric.criteria
            ],
            question_text=question_text,
        )
        for m in scoring_metas:
            total_prompt_tokens += m["prompt_tokens"]
            total_completion_tokens += m["completion_tokens"]

        # ── Agent 3: Consistency Check ─────────────────────
        consistency_agent = ConsistencyAgent()
        consistency_audit, consistency_meta = consistency_agent.execute(
            trace_id=trace_id,
            answer_text=answer_text,
            rubric=grounded_rubric.model_dump(by_alias=True),
            criterion_scores=[s.model_dump(by_alias=True) for s in criterion_scores],
            question_text=question_text,
        )
        total_prompt_tokens += consistency_meta["prompt_tokens"]
        total_completion_tokens += consistency_meta["completion_tokens"]

        max_score = grounded_rubric.total_marks

        # Build a lookup from the consistency audit's final scores
        final_score_map = {
            fs.criterion_id: fs.final_score
            for fs in consistency_audit.final_scores
        }

        # Merge consistency-adjusted scores back into criterion_scores
        for cs in criterion_scores:
            if cs.criterion_id in final_score_map:
                cs.marks_awarded = final_score_map[cs.criterion_id]

        # Never trust LLM arithmetic — compute total from the actual values
        total_score = round(
            sum(fs.final_score for fs in consistency_audit.final_scores), 4
        )
        consistency_audit.total_score = total_score

        # ── Agent 4: Feedback ──────────────────────────────
        feedback_agent = FeedbackAgent()
        feedback, feedback_meta = feedback_agent.execute(
            trace_id=trace_id,
            question_text=question_text,
            answer_text=answer_text,
            final_scores=[fs.model_dump(by_alias=True) for fs in consistency_audit.final_scores],
            total_score=total_score,
            max_score=max_score,
        )
        total_prompt_tokens += feedback_meta["prompt_tokens"]
        total_completion_tokens += feedback_meta["completion_tokens"]

        # ── Agent 5: Explainability ────────────────────────
        explain_agent = ExplainabilityAgent()
        explainability, explain_meta = explain_agent.execute(
            trace_id=trace_id,
            question_text=question_text,
            answer_text=answer_text,
            grounded_rubric=grounded_rubric.model_dump(by_alias=True),
            criterion_scores=[s.model_dump(by_alias=True) for s in criterion_scores],
            consistency_audit=consistency_audit.model_dump(by_alias=True),
            feedback=feedback.model_dump(by_alias=True),
            total_score=total_score,
            max_score=max_score,
        )
        total_prompt_tokens += explain_meta["prompt_tokens"]
        total_completion_tokens += explain_meta["completion_tokens"]

        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        percentage = (total_score / max_score * 100) if max_score > 0 else 0

        eval_doc = {
            "runId": run_id,
            "scriptId": script_id,
            "questionId": question_id,
            "evaluationVersion": EVALUATION_VERSION,
            "idempotencyKey": idempotency_key,
            "groundedRubric": grounded_rubric.model_dump(by_alias=True),
            "criterionScores": [s.model_dump(by_alias=True) for s in criterion_scores],
            "consistencyAudit": consistency_audit.model_dump(by_alias=True),
            "feedback": feedback.model_dump(by_alias=True),
            "explainability": explainability.model_dump(by_alias=True),
            "totalScore": total_score,
            "maxPossibleScore": max_score,
            "percentageScore": round(percentage, 2),
            "reviewRecommendation": explainability.review_recommendation.value,
            "reviewerOverride": None,
            "status": EvaluationStatus.COMPLETE.value,
            "latencyMs": elapsed_ms,
            "tokensUsed": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_prompt_tokens + total_completion_tokens,
            },
            "createdAt": datetime.now(timezone.utc),
        }

        EvaluationResultRepository().insert_one(eval_doc)

        _check_script_completion(script_id)

        structured_log(
            "info",
            f"Evaluation complete for script={script_id} question={question_id}",
            trace_id=trace_id,
            script_id=script_id,
            agent_name="evaluate_question",
            duration_ms=elapsed_ms,
        )

        tasks_total.labels(queue="evaluation", status="success").inc()

    except Exception as exc:
        tasks_total.labels(queue="evaluation", status="error").inc()
        structured_log(
            "error",
            f"Evaluation failed: {exc}",
            trace_id=trace_id,
            script_id=script_id,
        )
        cache.delete(f"eval_lock:{idempotency_key}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)


def _check_script_completion(script_id: str) -> None:
    """Mark script COMPLETE if all non-flagged questions have evaluation results."""
    script_doc = ScriptRepository().find_by_id(script_id)
    if not script_doc:
        return

    non_flagged_ids = {
        a["questionId"]
        for a in script_doc["answers"]
        if not a.get("isFlagged") and a.get("text", "").strip()
    }

    eval_repo = EvaluationResultRepository()
    completed_evals = eval_repo.find_by_script(script_id)
    completed_ids = {e["questionId"] for e in completed_evals if e["status"] == "COMPLETE"}

    if non_flagged_ids <= completed_ids:
        has_flagged = any(a.get("isFlagged") for a in script_doc["answers"])
        status = ScriptStatus.FLAGGED if has_flagged else ScriptStatus.COMPLETE
        ScriptRepository().update_one(script_id, {"$set": {"status": status.value}})

        uploaded_script_id = script_doc.get("uploadedScriptId")
        if uploaded_script_id:
            from app.domain.models.common import UploadStatus
            final_upload_status = UploadStatus.FLAGGED if has_flagged else UploadStatus.EVALUATED
            UploadedScriptRepository().update_one(
                uploaded_script_id, {"$set": {"uploadStatus": final_upload_status.value}}
            )
