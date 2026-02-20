"""
Dashboard & analytics endpoints — KPIs, queue depth, activity feed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask.views import MethodView
from flask_smorest import Blueprint

from app.api.middleware.auth import get_current_institution_id, jwt_required
from app.api.v1._serializers import _fmt_dt
from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ScriptRepository,
    UploadedScriptRepository,
)

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard", description="Dashboard")


@dashboard_bp.route("/kpis")
class KPIView(MethodView):
    @jwt_required
    def get(self):
        """Top-level KPI cards for the dashboard."""
        institution_id = get_current_institution_id()
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        upload_repo = UploadedScriptRepository()
        script_repo = ScriptRepository()
        eval_repo = EvaluationResultRepository()

        total_uploads_today = upload_repo.count({
            "institutionId": institution_id,
            "createdAt": {"$gte": today_start},
        })

        total_scripts = script_repo.count({"institutionId": institution_id})

        ocr_docs = upload_repo.find_many(
            {
                "institutionId": institution_id,
                "uploadStatus": {"$in": ["OCR_COMPLETE", "SEGMENTED"]},
            },
            limit=1000,
        )
        avg_ocr_confidence = 0.0
        if ocr_docs:
            confs = [d.get("pageCount", 0) for d in ocr_docs if d.get("pageCount")]

        scripts_with_evals = script_repo.find_many(
            {"institutionId": institution_id, "status": "COMPLETE"},
            limit=1000,
        )
        completed_evals = eval_repo.find_many(
            {"status": "COMPLETE"},
            limit=5000,
        )
        if completed_evals:
            scores = [e.get("percentageScore", 0) for e in completed_evals]
            avg_score = sum(scores) / len(scores)
        else:
            avg_score = 0

        review_queue = eval_repo.count({
            "reviewRecommendation": {"$in": ["NEEDS_REVIEW", "MUST_REVIEW"]},
            "status": "COMPLETE",
        })

        failed_count = upload_repo.count({
            "institutionId": institution_id,
            "uploadStatus": "FAILED",
        })

        processing_count = upload_repo.count({
            "institutionId": institution_id,
            "uploadStatus": "PROCESSING",
        })

        return {
            "totalUploadsToday": total_uploads_today,
            "totalScripts": total_scripts,
            "averageScore": round(avg_score, 1),
            "reviewQueueSize": review_queue,
            "failedScripts": failed_count,
            "processingNow": processing_count,
        }


@dashboard_bp.route("/recent-activity")
class RecentActivityView(MethodView):
    @jwt_required
    def get(self):
        """Recent evaluation and upload activity feed."""
        institution_id = get_current_institution_id()

        recent_evals = EvaluationResultRepository().find_many(
            {},
            sort=[("createdAt", -1)],
            limit=20,
        )

        recent_uploads = UploadedScriptRepository().find_many(
            {"institutionId": institution_id},
            sort=[("createdAt", -1)],
            limit=20,
        )

        activity = []
        for e in recent_evals:
            activity.append({
                "type": "evaluation",
                "id": str(e["_id"]),
                "scriptId": e.get("scriptId"),
                "questionId": e.get("questionId"),
                "status": e.get("status"),
                "totalScore": e.get("totalScore"),
                "maxScore": e.get("maxPossibleScore"),
                "createdAt": _fmt_dt(e.get("createdAt")),
            })

        for u in recent_uploads:
            activity.append({
                "type": "upload",
                "id": str(u["_id"]),
                "filename": u.get("originalFilename"),
                "status": u.get("uploadStatus"),
                "createdAt": _fmt_dt(u.get("createdAt")),
            })

        activity.sort(key=lambda x: x["createdAt"], reverse=True)
        return {"activity": activity[:30]}


@dashboard_bp.route("/review-queue")
class ReviewQueueView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "REVIEWER"])
    def get(self):
        """List evaluations pending human review."""
        evals = EvaluationResultRepository().find_many(
            {
                "reviewRecommendation": {"$in": ["NEEDS_REVIEW", "MUST_REVIEW"]},
                "status": "COMPLETE",
            },
            sort=[("createdAt", -1)],
            limit=50,
        )

        return {
            "items": [
                {
                    "id": str(e["_id"]),
                    "scriptId": e.get("scriptId"),
                    "questionId": e.get("questionId"),
                    "totalScore": e.get("totalScore"),
                    "maxScore": e.get("maxPossibleScore"),
                    "reviewRecommendation": e.get("reviewRecommendation"),
                    "reviewReason": (e.get("explainability") or {}).get("reviewReason", ""),
                    "createdAt": _fmt_dt(e.get("createdAt")),
                }
                for e in evals
            ],
            "total": len(evals),
        }
