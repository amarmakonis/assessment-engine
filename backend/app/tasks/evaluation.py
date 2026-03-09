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

from app.agents.mcq import score_mcq_deterministic
from app.common.observability import structured_log, tasks_total
from app.config import get_settings
from app.domain.models.common import (
    ConsistencyAssessment,
    EvaluationStatus,
    ReviewRecommendation,
    ScriptSource,
    ScriptStatus,
)
from app.domain.models.evaluation import (
    ConsistencyAudit,
    CriterionScore,
    FinalCriterionScore,
    GroundedRubric,
    RubricCriterion,
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
    """Create the Script document from segmentation results and fan out evaluation tasks.
    Ensures one script answer per exam question (full paper). Unattempted questions get
    zero-score evaluation results so the run total is out of full paper marks.
    """
    try:
        upload_doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
        if not upload_doc:
            logger.error(f"UploadedScript {uploaded_script_id} not found")
            return

        exam_id = upload_doc["examId"]
        exam_doc = ExamRepository().find_by_id(exam_id)
        if not exam_doc:
            logger.error(f"Exam {exam_id} not found")
            return

        exam_questions = exam_doc.get("questions", [])
        seg_by_q = {a["questionId"]: a for a in segmentation_result.get("answers", [])}

        answers = []
        for q in exam_questions:
            qid = q.get("questionId", "")
            seg = seg_by_q.get(qid)
            has_text = seg and seg.get("answerText") and str(seg.get("answerText", "")).strip()
            is_flagged = not has_text
            answers.append({
                "questionId": qid,
                "text": (seg.get("answerText") or "").strip() if seg else "",
                "isFlagged": is_flagged,
            })

        script_doc = {
            "institutionId": upload_doc["institutionId"],
            "createdBy": upload_doc.get("createdBy"),
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

        qid_to_max_marks = {q.get("questionId"): float(q.get("maxMarks", 0)) for q in exam_questions}

        # Insert zero-score evaluation results for unattempted (no-answer) questions
        # so the run total is out of full paper marks.
        eval_repo = EvaluationResultRepository()
        for a in answers:
            if a["isFlagged"] or not a.get("text", "").strip():
                qid = a["questionId"]
                max_marks = qid_to_max_marks.get(qid, 0)
                idempotency_key = f"{run_id}:{script_id}:{qid}:{EVALUATION_VERSION}"
                if eval_repo.find_by_idempotency_key(idempotency_key):
                    continue
                no_attempt_doc = {
                    "runId": run_id,
                    "scriptId": script_id,
                    "institutionId": script_doc.get("institutionId"),
                    "createdBy": script_doc.get("createdBy"),
                    "questionId": qid,
                    "evaluationVersion": EVALUATION_VERSION,
                    "idempotencyKey": idempotency_key,
                    "groundedRubric": None,
                    "criterionScores": [],
                    "consistencyAudit": None,
                    "feedback": None,
                    "explainability": None,
                    "totalScore": 0.0,
                    "maxPossibleScore": max_marks,
                    "percentageScore": 0.0,
                    "reviewRecommendation": ReviewRecommendation.AUTO_APPROVED.value,
                    "reviewerOverride": None,
                    "status": EvaluationStatus.COMPLETE.value,
                    "latencyMs": 0,
                    "tokensUsed": {"prompt": 0, "completion": 0, "total": 0},
                    "createdAt": datetime.now(timezone.utc),
                }
                eval_repo.insert_one(no_attempt_doc)
                logger.info("Inserted no-attempt result for question %s (script %s)", qid, script_id)

        non_flagged = [a for a in answers if not a["isFlagged"] and a.get("text", "").strip()]
        if non_flagged:
            task_group = group(
                evaluate_question.s(script_id, a["questionId"], run_id, trace_id)
                for a in non_flagged
            )
            task_group.apply_async()
        else:
            # All questions unattempted; we already inserted no-attempt results — mark script complete
            _check_script_completion(script_id)

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
    max_retries=2,
    soft_time_limit=180,
    time_limit=210,
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
        FeedbackExplainabilityAgent,
        RubricGroundingAgent,
        ScoringAgent,
        ScoringConsistencyAgent,
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
        if script_doc.get("status") == ScriptStatus.CANCELLED.value:
            logger.info(f"Script {script_id} cancelled, skipping evaluation")
            return

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
        raw_rubric = question_def.get("rubric", [])
        # Fixed order by criterionId so same exam always gives same prompt → deterministic grounding
        rubric_criteria = sorted(
            [
                {
                    "criterionId": c["criterionId"],
                    "description": c["description"],
                    "maxMarks": c["maxMarks"],
                }
                for c in raw_rubric
            ],
            key=lambda x: x["criterionId"],
        )
        question_max_marks = float(question_def.get("maxMarks", 0))

        # ── MCQ: deterministic scoring (no essay logic, no LLM for scoring) ─
        mcq_result = score_mcq_deterministic(
            question_text, answer_text, rubric_criteria, question_max_marks
        )
        if mcq_result is not None:
            criterion_id, marks_awarded, max_marks_mcq, reason = mcq_result
            grounded_rubric = GroundedRubric(
                totalMarks=max_marks_mcq,
                criteria=[
                    RubricCriterion(
                        criterionId=criterion_id,
                        description="Correct option selected",
                        maxMarks=max_marks_mcq,
                        requiredEvidencePoints=["Student selected the correct option"],
                        isAmbiguous=False,
                        ambiguityNote=None,
                    )
                ],
                groundingConfidence=1.0,
            )
            criterion_scores = [
                CriterionScore(
                    criterionId=criterion_id,
                    marksAwarded=marks_awarded,
                    maxMarks=max_marks_mcq,
                    justificationQuote=answer_text.strip() or "(no answer)",
                    justificationReason=reason,
                    confidenceScore=1.0,
                )
            ]
            consistency_audit = ConsistencyAudit(
                overallAssessment=ConsistencyAssessment.CONSISTENT,
                adjustments=[],
                finalScores=[
                    FinalCriterionScore(criterionId=criterion_id, finalScore=marks_awarded)
                ],
                totalScore=marks_awarded,
                auditNotes="MCQ: deterministic scoring; correct option = full marks, wrong = 0.",
            )
            total_score = marks_awarded
            max_score = max_marks_mcq
            fe_agent = FeedbackExplainabilityAgent()
            fe_result, fe_meta = fe_agent.execute(
                trace_id=trace_id,
                question_text=question_text,
                answer_text=answer_text,
                grounded_rubric=grounded_rubric.model_dump(by_alias=True),
                criterion_scores=[s.model_dump(by_alias=True) for s in criterion_scores],
                consistency_audit=consistency_audit.model_dump(by_alias=True),
                total_score=total_score,
                max_score=max_score,
                max_tokens=getattr(get_settings(), "OPENAI_EVALUATION_MAX_TOKENS", 2048),
            )
            feedback = fe_agent.to_feedback(fe_result)
            explainability = fe_agent.to_explainability(fe_result)
            elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
            percentage = (total_score / max_score * 100) if max_score > 0 else 0
            eval_doc = {
                "runId": run_id,
                "scriptId": script_id,
                "institutionId": script_doc.get("institutionId"),
                "createdBy": script_doc.get("createdBy"),
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
                    "prompt": fe_meta.get("prompt_tokens", 0),
                    "completion": fe_meta.get("completion_tokens", 0),
                    "total": fe_meta.get("prompt_tokens", 0) + fe_meta.get("completion_tokens", 0),
                },
                "createdAt": datetime.now(timezone.utc),
            }
            EvaluationResultRepository().insert_one(eval_doc)
            _check_script_completion(script_id)
            structured_log(
                "info",
                f"Evaluation complete (MCQ) for script={script_id} question={question_id}",
                trace_id=trace_id,
                script_id=script_id,
                agent_name="evaluate_question",
                duration_ms=elapsed_ms,
            )
            tasks_total.labels(queue="evaluation", status="success").inc()
            return

        settings = get_settings()
        eval_max_tokens = getattr(settings, "OPENAI_EVALUATION_MAX_TOKENS", 2048)

        # ── Agent 1: Rubric Grounding ─────────────────────
        rubric_agent = RubricGroundingAgent()
        grounded_rubric, rubric_meta = rubric_agent.execute(
            trace_id=trace_id,
            question_text=question_text,
            rubric_criteria=rubric_criteria,
            max_tokens=eval_max_tokens,
        )
        total_prompt_tokens += rubric_meta["prompt_tokens"]
        total_completion_tokens += rubric_meta["completion_tokens"]

        # Normalize grounded rubric so total_marks matches the question's maxMarks.
        # LLM can produce criteria that sum to e.g. 10.5 instead of 10 due to rounding.
        question_max_marks = float(question_def.get("maxMarks", 0))
        if question_max_marks > 0 and abs(grounded_rubric.total_marks - question_max_marks) > 0.01:
            scale = question_max_marks / grounded_rubric.total_marks
            for c in grounded_rubric.criteria:
                c.max_marks = round(c.max_marks * scale, 2)
            grounded_rubric.total_marks = question_max_marks

        max_score = grounded_rubric.total_marks
        use_merged = getattr(get_settings(), "USE_MERGED_AGENTS", True)

        if use_merged:
            # Merged flow: 3 LLM calls (rubric + scoring+consistency + feedback+explainability)
            sorted_criteria = sorted(
                grounded_rubric.criteria, key=lambda c: c.criterion_id
            )
            sc_agent = ScoringConsistencyAgent()
            sc_result, sc_meta = sc_agent.execute(
                trace_id=trace_id,
                answer_text=answer_text,
                rubric=grounded_rubric.model_dump(by_alias=True),
                grounded_criteria=[c.model_dump(by_alias=True) for c in sorted_criteria],
                question_text=question_text,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += sc_meta["prompt_tokens"]
            total_completion_tokens += sc_meta["completion_tokens"]

            criterion_scores = sorted(sc_result.scores, key=lambda s: s.criterion_id)
            consistency_audit = sc_agent.to_consistency_audit(sc_result)
            total_score = round(
                sum(fs.final_score for fs in consistency_audit.final_scores), 4
            )
            consistency_audit.total_score = total_score

            final_score_map = {
                fs.criterion_id: fs.final_score
                for fs in consistency_audit.final_scores
            }
            for cs in criterion_scores:
                if cs.criterion_id in final_score_map:
                    cs.marks_awarded = final_score_map[cs.criterion_id]

            fe_agent = FeedbackExplainabilityAgent()
            fe_result, fe_meta = fe_agent.execute(
                trace_id=trace_id,
                question_text=question_text,
                answer_text=answer_text,
                grounded_rubric=grounded_rubric.model_dump(by_alias=True),
                criterion_scores=[s.model_dump(by_alias=True) for s in criterion_scores],
                consistency_audit=consistency_audit.model_dump(by_alias=True),
                total_score=total_score,
                max_score=max_score,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += fe_meta["prompt_tokens"]
            total_completion_tokens += fe_meta["completion_tokens"]
            feedback = fe_agent.to_feedback(fe_result)
            explainability = fe_agent.to_explainability(fe_result)
        else:
            # Legacy flow: 5 LLM calls
            sorted_criteria = sorted(
                grounded_rubric.criteria, key=lambda c: c.criterion_id
            )
            scoring_agent = ScoringAgent()
            criterion_scores, scoring_metas = scoring_agent.score_all_criteria(
                trace_id=trace_id,
                answer_text=answer_text,
                grounded_criteria=[c.model_dump(by_alias=True) for c in sorted_criteria],
                question_text=question_text,
            )
            for m in scoring_metas:
                total_prompt_tokens += m["prompt_tokens"]
                total_completion_tokens += m["completion_tokens"]

            sorted_scores = sorted(criterion_scores, key=lambda s: s.criterion_id)
            consistency_agent = ConsistencyAgent()
            consistency_audit, consistency_meta = consistency_agent.execute(
                trace_id=trace_id,
                answer_text=answer_text,
                rubric=grounded_rubric.model_dump(by_alias=True),
                criterion_scores=[s.model_dump(by_alias=True) for s in sorted_scores],
                question_text=question_text,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += consistency_meta["prompt_tokens"]
            total_completion_tokens += consistency_meta["completion_tokens"]

            final_score_map = {
                fs.criterion_id: fs.final_score
                for fs in consistency_audit.final_scores
            }
            for cs in criterion_scores:
                if cs.criterion_id in final_score_map:
                    cs.marks_awarded = final_score_map[cs.criterion_id]

            total_score = round(
                sum(fs.final_score for fs in consistency_audit.final_scores), 4
            )
            consistency_audit.total_score = total_score

            sorted_final = sorted(
                consistency_audit.final_scores, key=lambda fs: fs.criterion_id
            )
            feedback_agent = FeedbackAgent()
            feedback, feedback_meta = feedback_agent.execute(
                trace_id=trace_id,
                question_text=question_text,
                answer_text=answer_text,
                final_scores=[fs.model_dump(by_alias=True) for fs in sorted_final],
                total_score=total_score,
                max_score=max_score,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += feedback_meta["prompt_tokens"]
            total_completion_tokens += feedback_meta["completion_tokens"]

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
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += explain_meta["prompt_tokens"]
            total_completion_tokens += explain_meta["completion_tokens"]

        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        percentage = (total_score / max_score * 100) if max_score > 0 else 0

        eval_doc = {
            "runId": run_id,
            "scriptId": script_id,
            "institutionId": script_doc.get("institutionId"),
            "createdBy": script_doc.get("createdBy"),
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
    """Mark script COMPLETE when every question has an evaluation result (full paper)."""
    script_doc = ScriptRepository().find_by_id(script_id)
    if not script_doc:
        return

    answer_ids = {a["questionId"] for a in script_doc.get("answers", [])}
    eval_repo = EvaluationResultRepository()
    completed_evals = eval_repo.find_by_script(script_id)
    completed_ids = {e["questionId"] for e in completed_evals if e["status"] == "COMPLETE"}

    if answer_ids and answer_ids <= completed_ids:
        has_flagged = any(a.get("isFlagged") for a in script_doc["answers"])
        # FLAGGED is reserved for pipeline failures (e.g. segmentation). Use IN_REVIEW when evaluation completed but some answers need human review.
        status = ScriptStatus.IN_REVIEW if has_flagged else ScriptStatus.COMPLETE
        ScriptRepository().update_one(script_id, {"$set": {"status": status.value}})

        uploaded_script_id = script_doc.get("uploadedScriptId")
        if uploaded_script_id:
            from app.domain.models.common import UploadStatus
            final_upload_status = UploadStatus.IN_REVIEW if has_flagged else UploadStatus.EVALUATED
            UploadedScriptRepository().update_one(
                uploaded_script_id, {"$set": {"uploadStatus": final_upload_status.value}}
            )
