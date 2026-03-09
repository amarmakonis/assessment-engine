"""
Exam management endpoints — create exams manually or by uploading
question papers / rubric documents (PDF, DOCX, images).
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint
from pydantic import BaseModel, Field

from app.api.middleware.auth import (
    can_see_all_institution_data,
    get_current_institution_id,
    get_current_user_id,
    jwt_required,
)
from app.api.v1._serializers import _fmt_dt
from app.common.exceptions import NotFoundError, ValidationError
from app.config import get_settings
from app.infrastructure.db.repositories import ExamJobRepository, ExamRepository

logger = logging.getLogger(__name__)
exam_bp = Blueprint("exam", __name__, url_prefix="/exams", description="Exam Management")

ALLOWED_DOC_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}


def _detect_stated_maximum_marks(raw_text: str) -> int | None:
    """Detect stated maximum marks from document text (e.g. 'Maximum Marks : 80')."""
    if not raw_text or not raw_text.strip():
        return None
    # Common patterns: "Maximum Marks : 80", "Max. Marks: 80", "Total: 80", "Total Marks 80"
    patterns = [
        r"(?:Maximum|Max\.?)\s*Marks?\s*[:\s]+\s*(\d+)",
        r"Total\s*(?:Marks?)?\s*[:\s]+\s*(\d+)",
        r"(?:Full\s+)?Marks?\s*[:\s]+\s*(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                continue
    return None


class RubricCriterionInput(BaseModel):
    description: str
    max_marks: float = Field(alias="maxMarks", gt=0)
    model_config = {"populate_by_name": True}


class QuestionInput(BaseModel):
    question_number: int | None = Field(default=None, alias="questionNumber")
    question_text: str = Field(alias="questionText", min_length=1)
    max_marks: float = Field(alias="maxMarks", gt=0)
    rubric: list[RubricCriterionInput] = Field(default_factory=list)
    model_config = {"populate_by_name": True}


class CreateExamRequest(BaseModel):
    title: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    questions: list[QuestionInput] = Field(min_length=1)
    model_config = {"populate_by_name": True}


class AddQuestionInput(BaseModel):
    """Payload for adding a single question to an existing exam (e.g. missed 34.2)."""
    question_label: str | None = Field(default=None, alias="questionLabel")
    question_text: str = Field(alias="questionText", min_length=1)
    max_marks: float = Field(alias="maxMarks", gt=0)
    rubric: list[RubricCriterionInput] = Field(default_factory=list)
    model_config = {"populate_by_name": True}


class UpdateQuestionInput(BaseModel):
    """Payload for updating question text, marks, or rubric."""
    question_text: str | None = Field(default=None, alias="questionText")
    max_marks: float | None = Field(default=None, alias="maxMarks", gt=0)
    rubric: list[RubricCriterionInput] | None = None
    model_config = {"populate_by_name": True}


@exam_bp.route("/")
class ExamListView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self):
        """Create a new exam with questions and rubrics (manual JSON input)."""
        data = CreateExamRequest.model_validate(request.get_json())
        return _create_exam_from_data(data)

    @jwt_required
    def get(self):
        """List all exams for the institution. Professors see only their own exams."""
        institution_id = get_current_institution_id()
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("perPage", 50)), 100)

        repo = ExamRepository()
        query = {"institutionId": institution_id}
        if not can_see_all_institution_data():
            query["createdBy"] = get_current_user_id()
        total = repo.count(query)
        docs = repo.find_many(query, sort=[("createdAt", -1)], skip=(page - 1) * per_page, limit=per_page)

        return {
            "items": [_serialize_exam(d) for d in docs],
            "total": total,
            "page": page,
            "perPage": per_page,
        }


@exam_bp.route("/upload")
class ExamUploadView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self):
        """
        Create an exam by uploading question paper and/or rubric documents.
        When Celery is enabled, returns 202 and processes in background; poll GET /exams/jobs/<jobId>.
        Otherwise runs synchronously and returns 201 with examId.
        """
        import shutil
        import uuid
        question_file = request.files.get("questionPaper")
        rubric_file = request.files.get("rubricDocument")
        if not question_file:
            raise ValidationError("questionPaper file is required")

        settings = get_settings()
        institution_id = get_current_institution_id()
        user_id = get_current_user_id()
        job_base = _exam_jobs_base_path()
        job_dir = os.path.join(job_base, uuid.uuid4().hex)
        os.makedirs(job_dir, exist_ok=True)

        try:
            question_path, question_mime = _save_upload_to_job_dir(job_dir, question_file, "question")
        except Exception as e:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

        rubric_path = rubric_mime = None
        if rubric_file and rubric_file.filename:
            try:
                rubric_path, rubric_mime = _save_upload_to_job_dir(job_dir, rubric_file, "rubric")
            except Exception as e:
                logger.warning("Rubric file save failed, continuing without rubric: %s", e)

        title_override = request.form.get("title") or None
        subject_override = request.form.get("subject") or None
        generate_rubrics_val = request.form.get("generateRubrics", "true").lower()
        use_auto_rubric_generation = generate_rubrics_val not in ("false", "0", "no")

        job_doc = {
            "institutionId": institution_id,
            "createdBy": user_id,
            "status": "CREATING",
            "questionFilePath": question_path,
            "questionMime": question_mime,
            "useAutoRubricGeneration": use_auto_rubric_generation,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }
        if rubric_path:
            job_doc["rubricFilePath"] = rubric_path
            job_doc["rubricMime"] = rubric_mime
        if title_override:
            job_doc["titleOverride"] = title_override
        if subject_override:
            job_doc["subjectOverride"] = subject_override

        job_id = ExamJobRepository().insert_one(job_doc)

        if settings.USE_CELERY_REDIS:
            from app.tasks.exam import create_exam_from_upload_task
            create_exam_from_upload_task.delay(job_id)
            return {
                "message": "Exam creation started. Poll GET /exams/jobs/{jobId} for status.",
                "jobId": job_id,
                "status": "CREATING",
            }, 202

        from app.tasks.exam import _run_exam_creation
        _run_exam_creation(job_id)
        job = ExamJobRepository().find_by_id(job_id, institution_id)
        if job.get("status") == "COMPLETE":
            return {
                "message": "Exam created",
                "examId": job.get("examId"),
                "totalMarks": job.get("totalMarks"),
            }, 201
        raise ValidationError(job.get("error", "Exam creation failed"))


@exam_bp.route("/jobs/<job_id>")
class ExamJobStatusView(MethodView):
    @jwt_required
    def get(self, job_id: str):
        """Poll exam creation job status. Returns status (CREATING|COMPLETE|FAILED), examId when complete, error when failed."""
        institution_id = get_current_institution_id()
        job = ExamJobRepository().find_by_id(job_id, institution_id)
        if not job:
            raise NotFoundError("ExamJob", job_id)
        if not can_see_all_institution_data() and job.get("createdBy") != get_current_user_id():
            raise NotFoundError("ExamJob", job_id)
        out = {"jobId": job_id, "status": job.get("status", "CREATING")}
        if job.get("examId"):
            out["examId"] = job["examId"]
        if job.get("error"):
            out["error"] = job["error"]
        return out


@exam_bp.route("/jobs/<job_id>/cancel")
class ExamJobCancelView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self, job_id: str):
        """Cancel an in-progress exam creation job. Task will skip creating the exam if it sees CANCELLED."""
        institution_id = get_current_institution_id()
        job = ExamJobRepository().find_by_id(job_id, institution_id)
        if not job:
            raise NotFoundError("ExamJob", job_id)
        if not can_see_all_institution_data() and job.get("createdBy") != get_current_user_id():
            raise NotFoundError("ExamJob", job_id)
        status = job.get("status", "CREATING")
        if status not in (None, "CREATING"):
            return {"message": f"Job already {status}", "jobId": job_id, "status": status}
        ExamJobRepository().update_one(
            job_id,
            {"$set": {"status": "CANCELLED", "updatedAt": datetime.now(timezone.utc)}},
            institution_id,
        )
        return {"message": "Exam creation cancelled", "jobId": job_id, "status": "CANCELLED"}


def _exam_jobs_base_path() -> str:
    """Return a writable base path for exam_jobs. Uses LOCAL_STORAGE_PATH if writable, else temp dir (works locally and on AWS)."""
    settings = get_settings()
    base = os.path.join(settings.LOCAL_STORAGE_PATH, "exam_jobs")
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except (PermissionError, OSError):
        fallback = os.path.join(tempfile.gettempdir(), "aae_exam_jobs")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _save_upload_to_job_dir(job_dir: str, file_obj, prefix: str) -> tuple[str, str]:
    """Save uploaded file to job dir. Returns (absolute_path, mime)."""
    import magic as pymagic
    file_bytes = file_obj.read()
    file_obj.seek(0)
    mime = pymagic.from_buffer(file_bytes, mime=True)
    if mime not in ALLOWED_DOC_MIMES:
        raise ValidationError(f"Unsupported file type: {mime}. Use PDF, DOCX, JPEG, or PNG.")
    ext = _mime_to_ext(mime)
    path = os.path.join(job_dir, f"{prefix}{ext}")
    with open(path, "wb") as f:
        f.write(file_bytes)
    return os.path.abspath(path), mime


@exam_bp.route("/<exam_id>")
class ExamDetailView(MethodView):
    @jwt_required
    def get(self, exam_id: str):
        """Get exam details with all questions and rubrics."""
        institution_id = get_current_institution_id()
        doc = ExamRepository().find_by_id(exam_id, institution_id)
        if not doc:
            raise NotFoundError("Exam", exam_id)
        if not can_see_all_institution_data() and doc.get("createdBy") != get_current_user_id():
            raise NotFoundError("Exam", exam_id)
        return _serialize_exam(doc)

    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def delete(self, exam_id: str):
        """Delete an exam."""
        institution_id = get_current_institution_id()
        doc = ExamRepository().find_by_id(exam_id, institution_id)
        if not doc:
            raise NotFoundError("Exam", exam_id)
        if not can_see_all_institution_data() and doc.get("createdBy") != get_current_user_id():
            raise NotFoundError("Exam", exam_id)
        ExamRepository().delete_one(exam_id, institution_id)
        return {"message": "Exam deleted", "examId": exam_id}


@exam_bp.route("/<exam_id>/questions")
class ExamQuestionsView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def post(self, exam_id: str):
        """Add a missing question to an existing exam (e.g. 34.2 that was not detected)."""
        institution_id = get_current_institution_id()
        doc = ExamRepository().find_by_id(exam_id, institution_id)
        if not doc:
            raise NotFoundError("Exam", exam_id)
        if not can_see_all_institution_data() and doc.get("createdBy") != get_current_user_id():
            raise NotFoundError("Exam", exam_id)

        data = AddQuestionInput.model_validate(request.get_json())
        questions = list(doc.get("questions") or [])
        next_idx = len(questions) + 1
        if data.question_label and str(data.question_label).strip():
            raw = str(data.question_label).strip().lower()
            q_id = f"q{raw}" if not raw.startswith("q") else raw
        else:
            q_id = f"q{next_idx}"

        rubric_criteria = []
        if data.rubric and any(c.description.strip() for c in data.rubric):
            for j, c in enumerate(data.rubric, start=1):
                rubric_criteria.append({
                    "criterionId": f"{q_id}_c{j}",
                    "description": c.description.strip(),
                    "maxMarks": c.max_marks,
                })
        if not rubric_criteria:
            rubric_criteria.append({
                "criterionId": f"{q_id}_c1",
                "description": "Overall answer quality",
                "maxMarks": data.max_marks,
            })

        new_question = {
            "questionId": q_id,
            "questionText": data.question_text.strip(),
            "maxMarks": data.max_marks,
            "rubric": rubric_criteria,
        }
        questions.append(new_question)
        total_marks = (doc.get("totalMarks") or 0) + data.max_marks
        ExamRepository().update_one(
            exam_id,
            {"$set": {"questions": questions, "totalMarks": total_marks}},
            institution_id,
        )
        return {
            "message": "Question added",
            "examId": exam_id,
            "questionId": q_id,
            "question": new_question,
        }, 201


@exam_bp.route("/<exam_id>/questions/<question_id>")
class ExamQuestionDetailView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER"])
    def patch(self, exam_id: str, question_id: str):
        """Update an existing question's text, max marks, or rubric."""
        institution_id = get_current_institution_id()
        doc = ExamRepository().find_by_id(exam_id, institution_id)
        if not doc:
            raise NotFoundError("Exam", exam_id)
        if not can_see_all_institution_data() and doc.get("createdBy") != get_current_user_id():
            raise NotFoundError("Exam", exam_id)

        data = UpdateQuestionInput.model_validate(request.get_json())
        questions = list(doc.get("questions") or [])
        found_idx = None
        for i, q in enumerate(questions):
            if (q.get("questionId") or "").lower() == question_id.lower():
                found_idx = i
                break
        if found_idx is None:
            raise NotFoundError("Question", question_id)

        q = questions[found_idx]
        if data.question_text is not None:
            q["questionText"] = data.question_text.strip()
        if data.max_marks is not None:
            q["maxMarks"] = data.max_marks
        if data.rubric is not None and len(data.rubric) > 0:
            q_id = q.get("questionId", f"q{found_idx + 1}")
            q["rubric"] = [
                {
                    "criterionId": f"{q_id}_c{j}",
                    "description": c.description.strip(),
                    "maxMarks": c.max_marks,
                }
                for j, c in enumerate(data.rubric, start=1)
            ]
        questions[found_idx] = q
        total_marks = sum(qu.get("maxMarks", 0) for qu in questions)
        ExamRepository().update_one(
            exam_id,
            {"$set": {"questions": questions, "totalMarks": total_marks}},
            institution_id,
        )
        return {"message": "Question updated", "examId": exam_id, "questionId": question_id}


def _extract_text_from_upload(file_obj, pdf_extractor, docx_extractor, image_extractor) -> str:
    """Route file to the correct extractor based on content type."""
    import magic as pymagic

    file_bytes = file_obj.read()
    mime = pymagic.from_buffer(file_bytes, mime=True)

    if mime not in ALLOWED_DOC_MIMES:
        raise ValidationError(f"Unsupported file type: {mime}. Use PDF, DOCX, JPEG, or PNG.")

    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return docx_extractor(file_bytes)

    with tempfile.NamedTemporaryFile(delete=False, suffix=_mime_to_ext(mime)) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        if mime == "application/pdf":
            return pdf_extractor(tmp_path)
        else:
            return image_extractor(tmp_path)
    finally:
        os.unlink(tmp_path)


def _mime_to_ext(mime: str) -> str:
    return {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }.get(mime, ".bin")


def _create_exam_from_data_sync(
    data: CreateExamRequest,
    institution_id: str,
    user_id: str,
) -> tuple[dict, int]:
    """Create exam in DB. Used by API (with current user) and by Celery task (with job's institution/user)."""
    total_marks = sum(q.max_marks for q in data.questions)

    settings = get_settings()
    needs_rubric_gen = any(
        not q.rubric or all(not c.description.strip() for c in q.rubric)
        for q in data.questions
    )
    built_rubric_map: dict[int, list] = {}
    if needs_rubric_gen and settings.USE_AUTO_RUBRIC_GENERATION:
        try:
            from app.agents.rubric_builder import build_rubrics_for_questions
            q_dicts = [
                {"questionText": q.question_text, "maxMarks": q.max_marks}
                for q in data.questions
            ]
            built = build_rubrics_for_questions(q_dicts, subject=data.subject)
            for qr in built.questions:
                built_rubric_map[qr.question_index] = qr.rubric
        except Exception:
            logger.warning("RubricBuilder failed; falling back to generic rubrics", exc_info=True)

    questions = []
    for i, q in enumerate(data.questions, start=1):
        # Use printed question number when present so Q23 stays q23 and Q24 stays q24
        q_id = f"q{q.question_number}" if q.question_number is not None else f"q{i}"
        rubric_criteria = []

        has_real_descriptions = q.rubric and any(c.description.strip() for c in q.rubric)

        if has_real_descriptions:
            for j, c in enumerate(q.rubric, start=1):
                rubric_criteria.append({
                    "criterionId": f"{q_id}_c{j}",
                    "description": c.description,
                    "maxMarks": c.max_marks,
                })
        elif (i - 1) in built_rubric_map:
            for j, r in enumerate(built_rubric_map[i - 1], start=1):
                rubric_criteria.append({
                    "criterionId": f"{q_id}_c{j}",
                    "description": r.description,
                    "maxMarks": r.max_marks,
                })

        if not rubric_criteria:
            rubric_criteria.append({
                "criterionId": f"{q_id}_c1",
                "description": "Overall answer quality",
                "maxMarks": q.max_marks,
            })

        questions.append({
            "questionId": q_id,
            "questionText": q.question_text,
            "maxMarks": q.max_marks,
            "rubric": rubric_criteria,
        })

    doc = {
        "institutionId": institution_id,
        "title": data.title,
        "subject": data.subject,
        "questions": questions,
        "totalMarks": total_marks,
        "createdBy": user_id,
        "createdAt": datetime.now(timezone.utc),
        "updatedAt": datetime.now(timezone.utc),
    }

    exam_id = ExamRepository().insert_one(doc)
    return {"message": "Exam created", "examId": exam_id, "totalMarks": total_marks}, 201


def _create_exam_from_data(data: CreateExamRequest) -> tuple[dict, int]:
    """Create exam using current request's institution and user."""
    return _create_exam_from_data_sync(
        data,
        get_current_institution_id(),
        get_current_user_id(),
    )


def _serialize_exam(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", ""),
        "subject": doc.get("subject", ""),
        "questions": doc.get("questions", []),
        "totalMarks": doc.get("totalMarks", 0),
        "createdAt": _fmt_dt(doc.get("createdAt")),
    }
