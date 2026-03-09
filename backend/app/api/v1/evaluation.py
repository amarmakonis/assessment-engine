"""
Evaluation endpoints — results, reviewer overrides, export.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from flask import request, Response
from flask.views import MethodView
from flask_smorest import Blueprint

from app.api.middleware.auth import (
    can_see_all_institution_data,
    get_current_institution_id,
    get_current_user_id,
    jwt_required,
)
from app.api.v1._serializers import _fmt_dt
from app.common.exceptions import NotFoundError, ValidationError
from app.domain.models.common import EvaluationStatus
from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ExamRepository,
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
        if not can_see_all_institution_data() and script.get("createdBy") != get_current_user_id():
            raise NotFoundError("Script", script_id)

        evals = EvaluationResultRepository().find_by_script(script_id)

        def _question_sort_key(e):
            qid = e.get("questionId", "") or ""
            if qid.startswith("q") and qid[1:].isdigit():
                return int(qid[1:])
            return 0

        evals_sorted = sorted(evals, key=_question_sort_key)

        total_score = sum(e.get("totalScore", 0) for e in evals)
        max_score = sum(e.get("maxPossibleScore", 0) for e in evals)

        answers = script.get("answers") or []
        exam_id = script.get("examId")
        questions = []
        exam_total_marks = 0
        if exam_id:
            exam = ExamRepository().find_by_id(exam_id, institution_id)
            if exam:
                questions = [
                    {"questionId": q.get("questionId"), "questionText": q.get("questionText"), "maxMarks": q.get("maxMarks")}
                    for q in exam.get("questions", [])
                ]
                exam_total_marks = exam.get("totalMarks") or max_score

        return {
            "scriptId": script_id,
            "studentMeta": script.get("studentMeta"),
            "status": script.get("status"),
            "totalScore": total_score,
            "maxPossibleScore": max_score,
            "examTotalMarks": exam_total_marks,
            "percentageScore": round(total_score / max_score * 100, 2) if max_score else 0,
            "questionCount": len(answers),
            "evaluatedCount": len(evals),
            "answers": answers,
            "questions": questions,
            "evaluations": [_serialize_eval(e) for e in evals_sorted],
        }

    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def delete(self, script_id: str):
        """Delete a script and its evaluations."""
        institution_id = get_current_institution_id()
        script = ScriptRepository().find_by_id(script_id, institution_id)
        if not script:
            raise NotFoundError("Script", script_id)
        if not can_see_all_institution_data() and script.get("createdBy") != get_current_user_id():
            raise NotFoundError("Script", script_id)
        evals = EvaluationResultRepository().find_by_script(script_id)
        for e in evals:
            inst_id = e.get("institutionId")
            if inst_id is None:
                inst_id = script.get("institutionId")
            EvaluationResultRepository().delete_one(str(e["_id"]), inst_id)
        ScriptRepository().delete_one(script_id, institution_id)
        return {"message": "Script deleted", "scriptId": script_id}


def _eval_belongs_to_institution(doc: dict, institution_id: str) -> bool:
    """Check if evaluation belongs to institution (handles legacy records without institutionId)."""
    if doc.get("institutionId") == institution_id:
        return True
    if doc.get("institutionId") is not None:
        return False
    script = ScriptRepository().find_by_id(doc.get("scriptId", ""))
    return script and script.get("institutionId") == institution_id


def _user_can_access_eval(doc: dict, institution_id: str) -> bool:
    """Check if current user can access this evaluation (institution + professor isolation)."""
    if not _eval_belongs_to_institution(doc, institution_id):
        return False
    if can_see_all_institution_data():
        return True
    created_by = doc.get("createdBy")
    if created_by is None:
        script = ScriptRepository().find_by_id(doc.get("scriptId", ""))
        created_by = script.get("createdBy") if script else None
    return created_by == get_current_user_id()


@evaluation_bp.route("/results/<result_id>")
class EvaluationResultDetailView(MethodView):
    @jwt_required
    def get(self, result_id: str):
        """Get a single evaluation result with full detail."""
        institution_id = get_current_institution_id()
        doc = EvaluationResultRepository().find_by_id(result_id)
        if not doc:
            raise NotFoundError("EvaluationResult", result_id)
        if not _user_can_access_eval(doc, institution_id):
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

        institution_id = get_current_institution_id()
        doc = EvaluationResultRepository().find_by_id(result_id)
        if not doc:
            raise NotFoundError("EvaluationResult", result_id)
        if not _user_can_access_eval(doc, institution_id):
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

    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "REVIEWER", "EXAMINER"])
    def delete(self, result_id: str):
        """Delete an evaluation result."""
        institution_id = get_current_institution_id()
        doc = EvaluationResultRepository().find_by_id(result_id)
        if not doc:
            raise NotFoundError("EvaluationResult", result_id)
        if not _user_can_access_eval(doc, institution_id):
            raise NotFoundError("EvaluationResult", result_id)
        inst_id = doc.get("institutionId")
        if inst_id is None:
            script = ScriptRepository().find_by_id(doc.get("scriptId", ""))
            inst_id = script.get("institutionId") if script else None
        EvaluationResultRepository().delete_one(result_id, inst_id)
        return {"message": "Evaluation deleted", "resultId": result_id}


@evaluation_bp.route("/list")
class EvaluationListView(MethodView):
    @jwt_required
    def get(self):
        """List all evaluated scripts with summary scores. Professors see only their own."""
        institution_id = get_current_institution_id()
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("perPage", 20)), 100)
        filter_status = request.args.get("status")

        query: dict = {"institutionId": institution_id}
        if filter_status:
            query["status"] = filter_status
        if not can_see_all_institution_data():
            query["createdBy"] = get_current_user_id()

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


@evaluation_bp.route("/export")
class EvaluationExportView(MethodView):
    @jwt_required
    def get(self):
        """Export evaluation list (script summaries) as CSV."""
        institution_id = get_current_institution_id()
        query = {"institutionId": institution_id}
        if not can_see_all_institution_data():
            query["createdBy"] = get_current_user_id()
        filter_status = request.args.get("status")
        if filter_status:
            query["status"] = filter_status

        script_repo = ScriptRepository()
        eval_repo = EvaluationResultRepository()
        scripts = script_repo.find_many(
            query,
            sort=[("createdAt", -1)],
            limit=2000,
        )
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([
            "scriptId", "examId", "studentName", "rollNo", "status", "totalScore",
            "maxPossibleScore", "percentageScore", "questionCount", "evaluatedCount",
            "needsReview", "createdAt",
        ])
        for s in scripts:
            sid = str(s["_id"])
            evals = eval_repo.find_by_script(sid)
            total_score = sum(e.get("totalScore", 0) for e in evals)
            max_score = sum(e.get("maxPossibleScore", 0) for e in evals)
            pct = round(total_score / max_score * 100, 1) if max_score else 0
            recommendations = [e.get("reviewRecommendation", "") for e in evals]
            needs_review = any(r in ("NEEDS_REVIEW", "MUST_REVIEW") for r in recommendations)
            meta = s.get("studentMeta") or {}
            w.writerow([
                sid,
                s.get("examId", ""),
                meta.get("name", ""),
                meta.get("rollNo", ""),
                s.get("status", ""),
                total_score,
                max_score,
                pct,
                len(s.get("answers", [])),
                len(evals),
                needs_review,
                _fmt_dt(s.get("createdAt")),
            ])
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=evaluations.csv"},
        )


@evaluation_bp.route("/scripts/<script_id>/stop")
class StopEvaluationView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self, script_id: str):
        """Stop/cancel in-progress evaluation for a script."""
        from app.domain.models.common import ScriptStatus

        institution_id = get_current_institution_id()
        script = ScriptRepository().find_by_id(script_id, institution_id)
        if not script:
            raise NotFoundError("Script", script_id)
        if not can_see_all_institution_data() and script.get("createdBy") != get_current_user_id():
            raise NotFoundError("Script", script_id)
        if script.get("status") != ScriptStatus.EVALUATING.value:
            raise ValidationError(
                f"Cannot stop: script is not evaluating (status={script.get('status')})"
            )
        ScriptRepository().update_one(
            script_id, {"$set": {"status": ScriptStatus.CANCELLED.value}}, institution_id
        )
        return {"message": "Evaluation stopped", "scriptId": script_id}


@evaluation_bp.route("/scripts/<script_id>/answers/<question_id>")
class ScriptAnswerView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def put(self, script_id: str, question_id: str):
        """Add or correct a missed answer for one question. Updates script, removes old evaluation for that question, and triggers re-evaluation for it."""
        import uuid

        from app.config import get_settings
        from app.domain.models.common import ScriptStatus

        institution_id = get_current_institution_id()
        script = ScriptRepository().find_by_id(script_id, institution_id)
        if not script:
            raise NotFoundError("Script", script_id)
        if not can_see_all_institution_data() and script.get("createdBy") != get_current_user_id():
            raise NotFoundError("Script", script_id)

        data = request.get_json() or {}
        answer_text = (data.get("answerText") or "").strip()
        if not answer_text:
            raise ValidationError("answerText is required and cannot be empty")

        answers = list(script.get("answers") or [])
        found = False
        for a in answers:
            if a.get("questionId") == question_id:
                a["text"] = answer_text
                a["isFlagged"] = False
                found = True
                break
        if not found:
            answers.append({"questionId": question_id, "text": answer_text, "isFlagged": False})

        ScriptRepository().update_one(
            script_id, {"$set": {"answers": answers, "status": ScriptStatus.EVALUATING.value}}, institution_id
        )

        # Remove existing evaluation for this script+question so the new one replaces it
        evals = EvaluationResultRepository().find_by_script(script_id)
        for e in evals:
            if e.get("questionId") == question_id:
                inst_id = e.get("institutionId") or script.get("institutionId")
                EvaluationResultRepository().delete_one(str(e["_id"]), inst_id)
                break

        run_id = uuid.uuid4().hex
        trace_id = uuid.uuid4().hex[:16]
        if get_settings().USE_CELERY_REDIS:
            from app.tasks.evaluation import evaluate_question
            evaluate_question.delay(script_id, question_id, run_id, trace_id)
        else:
            from app.services.sync_pipeline import run_evaluate_question
            run_evaluate_question(script_id, question_id, run_id, trace_id)

        return {
            "message": "Answer added and re-evaluation triggered",
            "scriptId": script_id,
            "questionId": question_id,
            "runId": run_id,
        }


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
        if not can_see_all_institution_data() and script.get("createdBy") != get_current_user_id():
            raise NotFoundError("Script", script_id)

        run_id = uuid.uuid4().hex
        trace_id = uuid.uuid4().hex[:16]
        question_ids = [
            a["questionId"]
            for a in script.get("answers", [])
            if not a.get("isFlagged") and a.get("text", "").strip()
        ]

        ScriptRepository().update_one(script_id, {"$set": {"status": "EVALUATING"}})

        from app.config import get_settings
        if get_settings().USE_CELERY_REDIS:
            from app.tasks.evaluation import evaluate_question
            for qid in question_ids:
                evaluate_question.delay(script_id, qid, run_id, trace_id)
        else:
            from app.services.sync_pipeline import run_evaluate_question
            for qid in question_ids:
                run_evaluate_question(script_id, qid, run_id, trace_id)

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
