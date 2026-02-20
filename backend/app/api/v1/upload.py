"""
File upload endpoints — ingestion, batch upload, status tracking.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import magic
from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint

from app.api.middleware.auth import get_current_institution_id, get_current_user_id, jwt_required
from app.api.v1._serializers import _fmt_dt
from app.common.exceptions import ValidationError
from app.config import get_settings
from app.infrastructure.db.repositories import UploadedScriptRepository
from app.infrastructure.storage import get_storage_provider
from app.tasks.ocr import ingest_file

logger = logging.getLogger(__name__)
upload_bp = Blueprint("upload", __name__, url_prefix="/uploads", description="File Uploads")


@upload_bp.route("/")
class UploadListView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self):
        """Upload one or more answer scripts for an exam."""
        settings = get_settings()
        institution_id = get_current_institution_id()
        user_id = get_current_user_id()

        exam_id = request.form.get("examId")
        if not exam_id:
            raise ValidationError("examId is required")

        files = request.files.getlist("files")
        if not files:
            raise ValidationError("At least one file is required")

        student_name = request.form.get("studentName", "")
        student_roll = request.form.get("studentRollNo", "")
        student_email = request.form.get("studentEmail")

        upload_batch_id = uuid.uuid4().hex
        results = []

        for f in files:
            file_bytes = f.read()
            detected_mime = magic.from_buffer(file_bytes, mime=True)

            if detected_mime not in settings.ALLOWED_MIME_TYPES:
                results.append({
                    "filename": f.filename,
                    "status": "REJECTED",
                    "reason": f"MIME type {detected_mime} not allowed",
                })
                continue

            if len(file_bytes) > settings.max_upload_bytes:
                results.append({
                    "filename": f.filename,
                    "status": "REJECTED",
                    "reason": f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit",
                })
                continue

            file_key = f"{institution_id}/{exam_id}/{uuid.uuid4().hex}"
            from io import BytesIO
            storage = get_storage_provider()
            storage.upload(BytesIO(file_bytes), file_key, {"originalFilename": f.filename or ""})

            doc = {
                "institutionId": institution_id,
                "examId": exam_id,
                "uploadBatchId": upload_batch_id,
                "studentMeta": {
                    "name": student_name,
                    "rollNo": student_roll,
                    "email": student_email,
                },
                "fileKey": file_key,
                "originalFilename": f.filename or "unnamed",
                "mimeType": detected_mime,
                "fileSizeBytes": len(file_bytes),
                "pageCount": None,
                "uploadStatus": "UPLOADED",
                "failureReason": None,
                "virusScanStatus": "PENDING",
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
                "createdBy": user_id,
            }

            doc_id = UploadedScriptRepository().insert_one(doc)
            ingest_file.delay(doc_id)

            results.append({
                "filename": f.filename,
                "uploadedScriptId": doc_id,
                "status": "ACCEPTED",
            })

        return {
            "batchId": upload_batch_id,
            "totalFiles": len(files),
            "results": results,
        }, 201

    @jwt_required
    def get(self):
        """List uploaded scripts for an exam."""
        institution_id = get_current_institution_id()
        exam_id = request.args.get("examId")
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("perPage", 20)), 100)

        query = {"institutionId": institution_id}
        if exam_id:
            query["examId"] = exam_id

        repo = UploadedScriptRepository()
        total = repo.count(query)
        docs = repo.find_many(
            query,
            sort=[("createdAt", -1)],
            skip=(page - 1) * per_page,
            limit=per_page,
        )

        return {
            "items": [_serialize_upload(d) for d in docs],
            "total": total,
            "page": page,
            "perPage": per_page,
        }


@upload_bp.route("/<script_id>")
class UploadDetailView(MethodView):
    @jwt_required
    def get(self, script_id: str):
        """Get upload status and details."""
        institution_id = get_current_institution_id()
        doc = UploadedScriptRepository().find_by_id(script_id, institution_id)
        if not doc:
            from app.common.exceptions import NotFoundError
            raise NotFoundError("UploadedScript", script_id)
        return _serialize_upload(doc)


def _serialize_upload(doc: dict) -> dict:
    from app.infrastructure.db.repositories import ScriptRepository
    uploaded_id = str(doc["_id"])
    script_doc = ScriptRepository().find_one({"uploadedScriptId": uploaded_id})
    script_id = str(script_doc["_id"]) if script_doc else None

    return {
        "id": uploaded_id,
        "scriptId": script_id,
        "examId": doc.get("examId"),
        "uploadBatchId": doc.get("uploadBatchId"),
        "studentMeta": doc.get("studentMeta"),
        "originalFilename": doc.get("originalFilename"),
        "mimeType": doc.get("mimeType"),
        "fileSizeBytes": doc.get("fileSizeBytes"),
        "pageCount": doc.get("pageCount"),
        "uploadStatus": doc.get("uploadStatus"),
        "failureReason": doc.get("failureReason"),
        "createdAt": _fmt_dt(doc.get("createdAt")),
    }
