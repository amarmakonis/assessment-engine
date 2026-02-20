"""
Evaluation endpoints — results, reviewer overrides, export.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint

from app.api.middleware.auth import get_current_institution_id, get_current_user_id, jwt_required
from app.api.v1._serializers import _fmt_dt
from app.common.exceptions import NotFoundError, ValidationError
from app.domain.models.common import EvaluationStatus
from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ScriptRepository,
)

logger = logging.getLogger(__name__)
evaluation_bp = Blueprint(
    "evaluation", __name__, url_prefix="/evaluation", description="Evaluation Results"
)


@evaluation_bp.route("/scripts/<script_id>")
class ScriptEvaluationView(MethodView):
    @jwt_required
    def get(self, script_id: str):
        """Get all evaluation results for a script."""
        institution_id = get_current_institution_id()
        script = ScriptRepository().find_by_id(script_id, institution_id)
        if not script:
            raise NotFoundError("Script", script_id)

        evals = EvaluationResultRepository().find_by_script(script_id)

        total_score = sum(e.get("totalScore", 0) for e in evals)
        max_score = sum(e.get("maxPossibleScore", 0) for e in evals)

        return {
            "scriptId": script_id,
            "studentMeta": script.get("studentMeta"),
            "status": script.get("status"),
            "totalScore": total_score,
            "maxPossibleScore": max_score,
            "percentageScore": round(total_score / max_score * 100, 2) if max_score else 0,
            "questionCount": len(script.get("answers", [])),
            "evaluatedCount": len(evals),
            "evaluations": [_serialize_eval(e) for e in evals],
        }


@evaluation_bp.route("/results/<result_id>")
class EvaluationResultDetailView(MethodView):
    @jwt_required
    def get(self, result_id: str):
        """Get a single evaluation result with full detail."""
        doc = EvaluationResultRepository().find_by_id(result_id)
        if not doc:
            raise NotFoundError("EvaluationResult", result_id)
        return _serialize_eval(doc)


@evaluation_bp.route("/results/<result_id>/override")
class ReviewerOverrideView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "REVIEWER"])
    def post(self, result_id: str):
        """Apply a reviewer score override."""
        data = request.get_json()
        override_score = data.get("overrideScore")
        note = data.get("note", "")

        if override_score is None:
            raise ValidationError("overrideScore is required")

        doc = EvaluationResultRepository().find_by_id(result_id)
        if not doc:
            raise NotFoundError("EvaluationResult", result_id)

        if override_score < 0 or override_score > doc.get("maxPossibleScore", 0):
            raise ValidationError(
                f"Override score must be between 0 and {doc.get('maxPossibleScore')}"
            )

        reviewer_id = get_current_user_id()
        override_data = {
            "reviewerId": reviewer_id,
            "overrideScore": float(override_score),
            "note": note,
            "at": datetime.now(timezone.utc),
        }

        EvaluationResultRepository().update_one(result_id, {
            "$set": {
                "reviewerOverride": override_data,
                "status": EvaluationStatus.OVERRIDDEN.value,
                "totalScore": float(override_score),
                "percentageScore": round(
                    float(override_score) / doc.get("maxPossibleScore", 1) * 100, 2
                ),
            }
        })

        return {"message": "Override applied", "resultId": result_id}


@evaluation_bp.route("/list")
class EvaluationListView(MethodView):
    @jwt_required
    def get(self):
        """List all evaluated scripts with summary scores."""
        institution_id = get_current_institution_id()
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("perPage", 20)), 100)
        filter_status = request.args.get("status")

        query: dict = {"institutionId": institution_id}
        if filter_status:
            query["status"] = filter_status

        script_repo = ScriptRepository()
        eval_repo = EvaluationResultRepository()

        total = script_repo.count(query)
        scripts = script_repo.find_many(
            query,
            sort=[("createdAt", -1)],
            skip=(page - 1) * per_page,
            limit=per_page,
        )

        items = []
        for s in scripts:
            sid = str(s["_id"])
            evals = eval_repo.find_by_script(sid)
            total_score = sum(e.get("totalScore", 0) for e in evals)
            max_score = sum(e.get("maxPossibleScore", 0) for e in evals)
            pct = round(total_score / max_score * 100, 1) if max_score else 0

            recommendations = [e.get("reviewRecommendation", "") for e in evals]
            needs_review = any(r in ("NEEDS_REVIEW", "MUST_REVIEW") for r in recommendations)

            items.append({
                "scriptId": sid,
                "examId": s.get("examId"),
                "studentMeta": s.get("studentMeta"),
                "status": s.get("status"),
                "totalScore": total_score,
                "maxPossibleScore": max_score,
                "percentageScore": pct,
                "questionCount": len(s.get("answers", [])),
                "evaluatedCount": len(evals),
                "needsReview": needs_review,
                "createdAt": _fmt_dt(s.get("createdAt")),
            })

        return {"items": items, "total": total, "page": page, "perPage": per_page}


@evaluation_bp.route("/scripts/<script_id>/re-evaluate")
class ReEvaluateView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self, script_id: str):
        """Trigger re-evaluation for all questions in a script."""
        import uuid

        from app.tasks.evaluation import evaluate_question

        institution_id = get_current_institution_id()
        script = ScriptRepository().find_by_id(script_id, institution_id)
        if not script:
            raise NotFoundError("Script", script_id)

        run_id = uuid.uuid4().hex
        trace_id = uuid.uuid4().hex[:16]
        question_ids = [
            a["questionId"]
            for a in script.get("answers", [])
            if not a.get("isFlagged") and a.get("text", "").strip()
        ]

        ScriptRepository().update_one(script_id, {"$set": {"status": "EVALUATING"}})

        for qid in question_ids:
            evaluate_question.delay(script_id, qid, run_id, trace_id)

        return {
            "message": "Re-evaluation triggered",
            "scriptId": script_id,
            "questionCount": len(question_ids),
            "runId": run_id,
        }


def _serialize_eval(e: dict) -> dict:
    return {
        "id": str(e["_id"]),
        "runId": e.get("runId"),
        "scriptId": e.get("scriptId"),
        "questionId": e.get("questionId"),
        "evaluationVersion": e.get("evaluationVersion"),
        "groundedRubric": e.get("groundedRubric"),
        "criterionScores": e.get("criterionScores"),
        "consistencyAudit": e.get("consistencyAudit"),
        "feedback": e.get("feedback"),
        "explainability": e.get("explainability"),
        "totalScore": e.get("totalScore"),
        "maxPossibleScore": e.get("maxPossibleScore"),
        "percentageScore": e.get("percentageScore"),
        "reviewRecommendation": e.get("reviewRecommendation"),
        "reviewerOverride": e.get("reviewerOverride"),
        "status": e.get("status"),
        "latencyMs": e.get("latencyMs"),
        "tokensUsed": e.get("tokensUsed"),
        "createdAt": _fmt_dt(e.get("createdAt")),
    }
