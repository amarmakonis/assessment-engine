"""
File upload endpoints — ingestion, batch upload, status tracking, typed answers.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from io import BytesIO

import magic
from flask import request
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
from app.config import get_settings
from app.domain.models.common import ScriptSource, ScriptStatus
from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ExamRepository,
    OCRPageResultRepository,
    ScriptRepository,
    UploadedScriptRepository,
)
from app.infrastructure.storage import get_storage_provider

logger = logging.getLogger(__name__)


def _run_ingest(doc_id: str) -> None:
    """Run ingest via sync pipeline or Celery depending on config."""
    import threading

    from app.config import get_settings
    if get_settings().USE_CELERY_REDIS:
        from app.tasks.ocr import ingest_file
        ingest_file.delay(doc_id)
    else:
        from app.services.sync_pipeline import run_ingest

        def _bg_ingest():
            try:
                run_ingest(doc_id)
            except Exception:
                logger.exception("Background ingest failed for %s", doc_id)

        t = threading.Thread(target=_bg_ingest, daemon=True)
        t.start()


def _ingest_from_temp_in_background(doc_id: str, temp_path: str) -> None:
    """Run ingest from temp file (answer script files are not stored). Then delete temp file."""
    import threading

    from app.domain.models.common import UploadStatus
    from app.services.sync_pipeline import run_ingest

    def _bg():
        try:
            run_ingest(doc_id, local_file_path=temp_path)
        except Exception:
            logger.exception("Background ingest failed for %s", doc_id)
            UploadedScriptRepository().update_one(doc_id, {
                "$set": {"uploadStatus": UploadStatus.FAILED.value, "failureReason": "Ingest failed"}
            })
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    t = threading.Thread(target=_bg, daemon=True)
    t.start()


def _upload_to_storage_and_ingest_in_background(
    doc_id: str, temp_path: str, file_key: str, metadata: dict
) -> None:
    """Upload to storage then run ingest (used only when USE_CELERY_REDIS is True)."""
    import threading

    from app.domain.models.common import UploadStatus

    def _bg():
        try:
            with open(temp_path, "rb") as f:
                get_storage_provider().upload(BytesIO(f.read()), file_key, metadata)
            _run_ingest(doc_id)
        except Exception:
            logger.exception("Background upload/ingest failed for %s", doc_id)
            UploadedScriptRepository().update_one(doc_id, {
                "$set": {"uploadStatus": UploadStatus.FAILED.value, "failureReason": "Upload to storage or ingest failed"}
            })
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    t = threading.Thread(target=_bg, daemon=True)
    t.start()


def _store_file_and_ingest_in_background(
    doc_id: str, temp_path: str, file_key: str, metadata: dict
) -> None:
    """Store file in GridFS (for tuning / re-run OCR) and run ingest from temp. Keeps file for later."""
    import threading

    from app.domain.models.common import UploadStatus
    from app.services.sync_pipeline import run_ingest

    def _bg():
        try:
            with open(temp_path, "rb") as f:
                get_storage_provider().upload(BytesIO(f.read()), file_key, metadata)
            run_ingest(doc_id, local_file_path=temp_path)
        except Exception:
            logger.exception("Background store+ingest failed for %s", doc_id)
            UploadedScriptRepository().update_one(doc_id, {
                "$set": {"uploadStatus": UploadStatus.FAILED.value, "failureReason": "Store or ingest failed"}
            })
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    t = threading.Thread(target=_bg, daemon=True)
    t.start()


def _run_evaluate_question(script_id: str, question_id: str, run_id: str, trace_id: str) -> None:
    """Run evaluate via sync pipeline or Celery depending on config."""
    from app.config import get_settings
    if get_settings().USE_CELERY_REDIS:
        from app.tasks.evaluation import evaluate_question
        evaluate_question.delay(script_id, question_id, run_id, trace_id)
    else:
        from app.services.sync_pipeline import run_evaluate_question
        run_evaluate_question(script_id, question_id, run_id, trace_id)
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
        store_file = request.form.get("storeFile", "").lower() in ("true", "1", "yes") or request.form.get("forTuning", "").lower() in ("true", "1", "yes")

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

            # Store file in GridFS when storeFile/forTuning=true (for segmentation tuning / re-run OCR).
            # With Celery we always store so the worker can download; otherwise only when requested.
            use_celery = settings.USE_CELERY_REDIS
            store_file_for_tuning = store_file and not use_celery
            file_key = f"{institution_id}/{exam_id}/{uuid.uuid4().hex}" if (use_celery or store_file_for_tuning) else None

            fd, temp_path = tempfile.mkstemp(suffix=".upload")
            try:
                os.write(fd, file_bytes)
            finally:
                os.close(fd)

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

            try:
                doc_id = UploadedScriptRepository().insert_one(doc)
            except Exception:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                raise
            if use_celery:
                _upload_to_storage_and_ingest_in_background(
                    doc_id, temp_path, file_key, {"originalFilename": f.filename or ""}
                )
            elif store_file_for_tuning:
                _store_file_and_ingest_in_background(
                    doc_id, temp_path, file_key, {"originalFilename": f.filename or ""}
                )
            else:
                _ingest_from_temp_in_background(doc_id, temp_path)

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
        """List uploaded scripts for an exam. Professors see only their own uploads."""
        institution_id = get_current_institution_id()
        exam_id = request.args.get("examId")
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("perPage", 20)), 100)

        query = {"institutionId": institution_id}
        if exam_id:
            query["examId"] = exam_id
        if not can_see_all_institution_data():
            query["createdBy"] = get_current_user_id()

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


@upload_bp.route("/typed")
class TypedUploadView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self):
        """Submit typed/pasted answers (no file upload). Skips OCR, goes straight to evaluation."""
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required")

        institution_id = get_current_institution_id()
        user_id = get_current_user_id()
        exam_id = data.get("examId")
        student_name = data.get("studentName", "")
        student_roll = data.get("studentRollNo", "")
        answers_input = data.get("answers")

        if not exam_id:
            raise ValidationError("examId is required")
        if not answers_input or not isinstance(answers_input, list):
            raise ValidationError("answers must be a non-empty array of {questionId, answerText}")

        exam_doc = ExamRepository().find_by_id(exam_id, institution_id)
        if not exam_doc:
            raise NotFoundError("Exam", exam_id)
        if not can_see_all_institution_data() and exam_doc.get("createdBy") != user_id:
            raise NotFoundError("Exam", exam_id)

        exam_questions = {q["questionId"] for q in exam_doc.get("questions", [])}
        answers = []
        for a in answers_input:
            qid = a.get("questionId")
            text = a.get("answerText", "")
            if qid not in exam_questions:
                continue
            answers.append({
                "questionId": qid,
                "text": str(text).strip() if text else "",
                "isFlagged": not text or not str(text).strip(),
            })

        if not answers:
            raise ValidationError("No valid answers for exam questions")

        upload_batch_id = uuid.uuid4().hex
        uploaded_id = uuid.uuid4().hex
        file_key = f"typed/{institution_id}/{exam_id}/{uploaded_id}"

        upload_doc = {
            "institutionId": institution_id,
            "examId": exam_id,
            "uploadBatchId": upload_batch_id,
            "studentMeta": {"name": student_name, "rollNo": student_roll, "email": None},
            "fileKey": file_key,
            "originalFilename": "typed-answer.txt",
            "mimeType": "text/plain",
            "fileSizeBytes": 0,
            "pageCount": 0,
            "uploadStatus": "EVALUATING",
            "failureReason": None,
            "virusScanStatus": "CLEAN",
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "createdBy": user_id,
        }
        doc_id = UploadedScriptRepository().insert_one(upload_doc)

        script_doc = {
            "institutionId": institution_id,
            "createdBy": user_id,
            "examId": exam_id,
            "uploadedScriptId": doc_id,
            "studentMeta": {"name": student_name, "rollNo": student_roll, "email": None},
            "answers": answers,
            "source": ScriptSource.TYPED.value,
            "ocrConfidenceAverage": 1.0,
            "ocrQualityFlags": [],
            "segmentationConfidence": 1.0,
            "status": ScriptStatus.EVALUATING.value,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }
        script_id = ScriptRepository().insert_one(script_doc)

        run_id = uuid.uuid4().hex
        trace_id = uuid.uuid4().hex[:16]
        non_flagged = [a for a in answers if not a["isFlagged"] and a["text"].strip()]
        for a in non_flagged:
            _run_evaluate_question(script_id, a["questionId"], run_id, trace_id)

        return {
            "message": "Typed answer submitted",
            "uploadedScriptId": doc_id,
            "scriptId": script_id,
            "questionCount": len(answers),
            "evaluatingCount": len(non_flagged),
        }, 201


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
        if not can_see_all_institution_data() and doc.get("createdBy") != get_current_user_id():
            from app.common.exceptions import NotFoundError
            raise NotFoundError("UploadedScript", script_id)
        return _serialize_upload(doc)

    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def delete(self, script_id: str):
        """Delete an upload and its scripts, evaluations, and OCR results."""
        institution_id = get_current_institution_id()
        doc = UploadedScriptRepository().find_by_id(script_id, institution_id)
        if not doc:
            raise NotFoundError("UploadedScript", script_id)
        if not can_see_all_institution_data() and doc.get("createdBy") != get_current_user_id():
            raise NotFoundError("UploadedScript", script_id)
        uploaded_id = str(doc["_id"])
        scripts = list(ScriptRepository().find_many({"uploadedScriptId": uploaded_id}, limit=50))
        for s in scripts:
            sid = str(s["_id"])
            evals = EvaluationResultRepository().find_by_script(sid)
            for e in evals:
                EvaluationResultRepository().delete_one(str(e["_id"]), e.get("institutionId"))
            ScriptRepository().delete_one(sid, s.get("institutionId"))
        OCRPageResultRepository().collection.delete_many({"uploadedScriptId": uploaded_id})
        UploadedScriptRepository().delete_one(script_id, institution_id)
        return {"message": "Upload deleted", "uploadedScriptId": script_id}


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
