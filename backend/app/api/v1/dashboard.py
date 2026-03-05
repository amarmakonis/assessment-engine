"""
Dashboard & analytics endpoints — KPIs, queue depth, activity feed.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId
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
from app.common.exceptions import ValidationError
from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ScriptRepository,
    UploadedScriptRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard", description="Dashboard")


@dashboard_bp.route("/kpis")
class KPIView(MethodView):
    @jwt_required
    def get(self):
        """Top-level KPI cards for the dashboard. Professors see only their own data."""
        institution_id = get_current_institution_id()
        user_id = get_current_user_id()
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        base_query = {"institutionId": institution_id}
        if not can_see_all_institution_data():
            base_query["createdBy"] = user_id

        upload_repo = UploadedScriptRepository()
        script_repo = ScriptRepository()
        eval_repo = EvaluationResultRepository()

        upload_query = {**base_query, "createdAt": {"$gte": today_start}}
        total_uploads_today = upload_repo.count(upload_query)

        total_scripts = script_repo.count(base_query)

        ocr_docs = upload_repo.find_many(
            {**base_query, "uploadStatus": {"$in": ["OCR_COMPLETE", "SEGMENTED"]}},
            limit=1000,
        )
        avg_ocr_confidence = 0.0
        if ocr_docs:
            confs = [d.get("pageCount", 0) for d in ocr_docs if d.get("pageCount")]

        scripts_with_evals = script_repo.find_many(
            {**base_query, "status": "COMPLETE"},
            limit=1000,
        )
        eval_query = {**base_query, "status": "COMPLETE"}
        completed_evals = eval_repo.find_many(eval_query, limit=5000)
        if completed_evals:
            scores = [e.get("percentageScore", 0) for e in completed_evals]
            avg_score = sum(scores) / len(scores)
        else:
            avg_score = 0

        review_queue = eval_repo.count({
            **base_query,
            "reviewRecommendation": {"$in": ["NEEDS_REVIEW", "MUST_REVIEW"]},
            "status": "COMPLETE",
        })

        failed_count = upload_repo.count({
            **base_query,
            "uploadStatus": "FAILED",
        })

        processing_count = upload_repo.count({
            **base_query,
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


def _dismissal_key(typ: str, id_: str) -> str:
    return f"{typ}:{id_}"


@dashboard_bp.route("/recent-activity")
class RecentActivityView(MethodView):
    @jwt_required
    def get(self):
        """Recent evaluation and upload activity feed. Professors see only their own. Excludes dismissed items."""
        institution_id = get_current_institution_id()
        user_id = get_current_user_id()
        base_query = {"institutionId": institution_id}
        if not can_see_all_institution_data():
            base_query["createdBy"] = user_id

        user_doc = UserRepository().find_by_id(user_id)
        dismissed = set((user_doc or {}).get("dismissedActivityIds") or [])
        cleared_at = (user_doc or {}).get("activityClearedAt")

        recent_evals = EvaluationResultRepository().find_many(
            base_query,
            sort=[("createdAt", -1)],
            limit=20,
        )

        recent_uploads = UploadedScriptRepository().find_many(
            base_query,
            sort=[("createdAt", -1)],
            limit=20,
        )

        activity = []
        for e in recent_evals:
            key = _dismissal_key("evaluation", str(e["_id"]))
            if key in dismissed:
                continue
            created_at = e.get("createdAt")
            if cleared_at and created_at and created_at <= cleared_at:
                continue
            activity.append({
                "type": "evaluation",
                "id": str(e["_id"]),
                "scriptId": e.get("scriptId"),
                "questionId": e.get("questionId"),
                "status": e.get("status"),
                "totalScore": e.get("totalScore"),
                "maxScore": e.get("maxPossibleScore"),
                "createdAt": _fmt_dt(created_at),
            })

        for u in recent_uploads:
            key = _dismissal_key("upload", str(u["_id"]))
            if key in dismissed:
                continue
            created_at = u.get("createdAt")
            if cleared_at and created_at and created_at <= cleared_at:
                continue
            activity.append({
                "type": "upload",
                "id": str(u["_id"]),
                "filename": u.get("originalFilename"),
                "status": u.get("uploadStatus"),
                "createdAt": _fmt_dt(created_at),
            })

        activity.sort(key=lambda x: x["createdAt"], reverse=True)
        return {"activity": activity[:30]}

    @jwt_required
    def post(self):
        """Dismiss one item from recent activity (data is not deleted). Body: { "type": "upload"|"evaluation", "id": "..." }."""
        user_id = get_current_user_id()
        data = request.get_json() or {}
        typ = data.get("type")
        id_ = data.get("id")
        if typ not in ("upload", "evaluation") or not id_:
            raise ValidationError("Body must include type (upload|evaluation) and id")
        key = _dismissal_key(typ, id_)
        UserRepository().collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$addToSet": {"dismissedActivityIds": key},
                "$set": {"updatedAt": datetime.now(timezone.utc)},
            },
        )
        return {"message": "Removed from recent activity", "type": typ, "id": id_}


@dashboard_bp.route("/recent-activity/clear")
class RecentActivityClearView(MethodView):
    @jwt_required
    def post(self):
        """Dismiss all current recent activity from the feed (data is not deleted)."""
        user_id = get_current_user_id()
        UserRepository().collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "activityClearedAt": datetime.now(timezone.utc),
                    "updatedAt": datetime.now(timezone.utc),
                },
            },
        )
        return {"message": "Recent activity cleared"}


@dashboard_bp.route("/review-queue")
class ReviewQueueView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "REVIEWER"])
    def get(self):
        """List evaluations pending human review. REVIEWER sees only their own."""
        institution_id = get_current_institution_id()
        query = {
            "institutionId": institution_id,
            "reviewRecommendation": {"$in": ["NEEDS_REVIEW", "MUST_REVIEW"]},
            "status": "COMPLETE",
        }
        if not can_see_all_institution_data():
            query["createdBy"] = get_current_user_id()
        evals = EvaluationResultRepository().find_many(
            query,
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


@dashboard_bp.route("/review-queue/export")
class ReviewQueueExportView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "REVIEWER"])
    def get(self):
        """Export review queue as CSV."""
        institution_id = get_current_institution_id()
        query = {
            "institutionId": institution_id,
            "reviewRecommendation": {"$in": ["NEEDS_REVIEW", "MUST_REVIEW"]},
            "status": "COMPLETE",
        }
        if not can_see_all_institution_data():
            query["createdBy"] = get_current_user_id()
        evals = EvaluationResultRepository().find_many(
            query,
            sort=[("createdAt", -1)],
            limit=2000,
        )
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([
            "id", "scriptId", "questionId", "totalScore", "maxScore",
            "reviewRecommendation", "reviewReason", "createdAt",
        ])
        for e in evals:
            w.writerow([
                str(e["_id"]),
                e.get("scriptId", ""),
                e.get("questionId", ""),
                e.get("totalScore", ""),
                e.get("maxPossibleScore", ""),
                e.get("reviewRecommendation", ""),
                (e.get("explainability") or {}).get("reviewReason", ""),
                _fmt_dt(e.get("createdAt")),
            ])
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=review-queue.csv"},
        )
