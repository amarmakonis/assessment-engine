"""
Celery task for async exam creation from uploaded documents.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.agents.exam_extractor import (
    ExtractedExam,
    RubricItem,
    extract_exam_from_text,
    extract_text_from_docx,
    extract_text_from_image_via_vision,
    extract_text_from_pdf_via_vision,
)
from app.common.exceptions import LLMError
from app.infrastructure.db.repositories import ExamJobRepository, ExamRepository
from app.config import get_settings

logger = logging.getLogger(__name__)

# Transient errors that should trigger a task retry (network/API)
def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, LLMError):
        msg = str(exc).lower()
        return "connection" in msg or "timeout" in msg or "rate" in msg or "429" in msg
    return False

ALLOWED_DOC_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}


def _extract_text_from_path(file_path: str, mime: str) -> str:
    """Extract text from a saved file (used by Celery worker)."""
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        with open(file_path, "rb") as f:
            return extract_text_from_docx(f.read())
    if mime == "application/pdf":
        return extract_text_from_pdf_via_vision(file_path)
    if mime in ("image/jpeg", "image/png"):
        return extract_text_from_image_via_vision(file_path)
    raise ValueError(f"Unsupported mime for exam extraction: {mime}")


def _run_exam_creation(job_id: str) -> None:
    """
    Run exam extraction and creation. Called from Celery task or synchronously.
    Updates job status to COMPLETE with examId or FAILED with error.
    """
    from app.api.v1.exam import (
        CreateExamRequest,
        QuestionInput,
        RubricCriterionInput,
        _create_exam_from_data_sync,
    )

    job_repo = ExamJobRepository()
    job = job_repo.find_by_id(job_id)
    if not job:
        logger.error("Exam job %s not found", job_id)
        return
    if job.get("status") not in (None, "CREATING"):
        logger.info("Exam job %s already finished with status %s", job_id, job.get("status"))
        return

    question_path = job.get("questionFilePath")
    question_mime = job.get("questionMime", "application/pdf")
    if not question_path or not os.path.isfile(question_path):
        job_repo.update_one(
            job_id,
            {"$set": {"status": "FAILED", "error": "Question file missing or not readable", "updatedAt": datetime.now(timezone.utc)}},
            job.get("institutionId"),
        )
        return

    try:
        question_text = _extract_text_from_path(question_path, question_mime)
    except LLMError as e:
        if _is_transient_error(e):
            raise  # Let task retry
        logger.exception("Exam job %s: text extraction failed", job_id)
        job_repo.update_one(
            job_id,
            {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
            job.get("institutionId"),
        )
        return
    except Exception as e:
        logger.exception("Exam job %s: text extraction failed", job_id)
        job_repo.update_one(
            job_id,
            {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
            job.get("institutionId"),
        )
        return

    rubric_text = None
    rubric_path = job.get("rubricFilePath")
    rubric_mime = job.get("rubricMime")
    if rubric_path and os.path.isfile(rubric_path) and rubric_mime:
        try:
            rubric_text = _extract_text_from_path(rubric_path, rubric_mime)
        except Exception as e:
            logger.warning("Exam job %s: rubric extraction failed, continuing without rubric: %s", job_id, e)

    try:
        extracted = extract_exam_from_text(question_text, rubric_text)
    except LLMError as e:
        if _is_transient_error(e):
            raise  # Let task retry
        logger.exception("Exam job %s: exam extraction failed", job_id)
        job_repo.update_one(
            job_id,
            {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
            job.get("institutionId"),
        )
        return
    except Exception as e:
        logger.exception("Exam job %s: exam extraction failed", job_id)
        job_repo.update_one(
            job_id,
            {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
            job.get("institutionId"),
        )
        return

    title_override = job.get("titleOverride")
    subject_override = job.get("subjectOverride")
    if title_override:
        extracted.title = title_override
    if subject_override:
        extracted.subject = subject_override

    use_auto_rubric = job.get("useAutoRubricGeneration", get_settings().USE_AUTO_RUBRIC_GENERATION)
    needs_rubric = not rubric_text and not (extracted.questions and any(
        q.rubric and any(c.description.strip() for c in q.rubric) for q in extracted.questions
    ))
    if needs_rubric and use_auto_rubric:
        try:
            from app.agents.rubric_builder import build_rubrics_for_questions
            q_dicts = [{"questionText": q.question_text, "maxMarks": q.max_marks} for q in extracted.questions]
            built = build_rubrics_for_questions(q_dicts, subject=extracted.subject)
            for qr in built.questions:
                if qr.question_index < len(extracted.questions):
                    extracted.questions[qr.question_index].rubric = [
                        RubricItem(description=r.description, maxMarks=r.max_marks) for r in qr.rubric
                    ]
        except Exception as e:
            logger.warning("Exam job %s: rubric builder failed, using generic rubrics: %s", job_id, e)
    elif needs_rubric and not use_auto_rubric:
        for q in extracted.questions:
            if not q.rubric or not any(c.description.strip() for c in q.rubric):
                q.rubric = [RubricItem(description="Overall answer quality", maxMarks=q.max_marks)]

    questions_data = [
        QuestionInput(
            questionNumber=q.question_number,
            questionText=q.question_text,
            maxMarks=q.max_marks,
            rubric=[RubricCriterionInput(description=r.description, maxMarks=r.max_marks) for r in q.rubric],
        )
        for q in extracted.questions
    ]
    create_req = CreateExamRequest(
        title=extracted.title,
        subject=extracted.subject,
        questions=questions_data,
    )

    institution_id = job.get("institutionId")
    user_id = job.get("createdBy")
    if not institution_id or not user_id:
        job_repo.update_one(
            job_id,
            {"$set": {"status": "FAILED", "error": "Job missing institutionId or createdBy", "updatedAt": datetime.now(timezone.utc)}},
            institution_id,
        )
        return

    # Re-fetch job: user may have cancelled while we were extracting/building rubrics
    job = job_repo.find_by_id(job_id)
    if job and job.get("status") == "CANCELLED":
        logger.info("Exam job %s was cancelled; skipping exam creation", job_id)
        return

    try:
        response, _ = _create_exam_from_data_sync(create_req, institution_id, user_id)
        exam_id = response.get("examId")
        total_marks = response.get("totalMarks")
        update = {"$set": {"status": "COMPLETE", "examId": exam_id, "updatedAt": datetime.now(timezone.utc)}}
        if total_marks is not None:
            update["$set"]["totalMarks"] = total_marks
        job_repo.update_one(job_id, update, institution_id)
        logger.info("Exam job %s completed, examId=%s", job_id, exam_id)
    except Exception as e:
        logger.exception("Exam job %s: create exam failed", job_id)
        job_repo.update_one(
            job_id,
            {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
            institution_id,
        )


from celery_app import celery


@celery.task(
    bind=True,
    name="app.tasks.exam.create_exam_from_upload",
    queue="default",
    acks_late=True,
    max_retries=3,
)
def create_exam_from_upload_task(self, job_id: str):
    """Create exam from uploaded files. Job doc must exist with questionFilePath and status CREATING.
    Transient connection/API errors trigger a task retry (up to 3) with backoff."""
    try:
        _run_exam_creation(job_id)
    except LLMError as e:
        if _is_transient_error(e) and self.request.retries < self.max_retries:
            countdown = (2 ** self.request.retries) * 30  # 30s, 60s, 120s
            logger.warning("Exam job %s: transient error (will retry in %ss): %s", job_id, countdown, e)
            raise self.retry(exc=e, countdown=countdown)
        # Final failure or non-transient: mark job failed
        from app.infrastructure.db.repositories import ExamJobRepository
        job_repo = ExamJobRepository()
        job = job_repo.find_by_id(job_id)
        if job and job.get("status") in (None, "CREATING"):
            job_repo.update_one(
                job_id,
                {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
                job.get("institutionId"),
            )
        raise
