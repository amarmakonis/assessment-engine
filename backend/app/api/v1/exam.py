"""
Exam management endpoints — create exams manually or by uploading
question papers / rubric documents (PDF, DOCX, images).
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint
from pydantic import BaseModel, Field

from app.api.middleware.auth import get_current_institution_id, get_current_user_id, jwt_required
from app.api.v1._serializers import _fmt_dt
from app.common.exceptions import NotFoundError, ValidationError
from app.infrastructure.db.repositories import ExamRepository

logger = logging.getLogger(__name__)
exam_bp = Blueprint("exam", __name__, url_prefix="/exams", description="Exam Management")

ALLOWED_DOC_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}


class RubricCriterionInput(BaseModel):
    description: str
    max_marks: float = Field(alias="maxMarks", gt=0)
    model_config = {"populate_by_name": True}


class QuestionInput(BaseModel):
    question_text: str = Field(alias="questionText", min_length=1)
    max_marks: float = Field(alias="maxMarks", gt=0)
    rubric: list[RubricCriterionInput] = Field(default_factory=list)
    model_config = {"populate_by_name": True}


class CreateExamRequest(BaseModel):
    title: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    questions: list[QuestionInput] = Field(min_length=1)
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
        """List all exams for the institution."""
        institution_id = get_current_institution_id()
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("perPage", 50)), 100)

        repo = ExamRepository()
        query = {"institutionId": institution_id}
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
        Supports PDF, DOCX, JPEG, PNG.
        Extracts questions and rubrics using OpenAI.
        """
        from app.agents.exam_extractor import (
            extract_exam_from_text,
            extract_text_from_docx,
            extract_text_from_image_via_vision,
            extract_text_from_pdf_via_vision,
        )

        question_file = request.files.get("questionPaper")
        rubric_file = request.files.get("rubricDocument")

        if not question_file:
            raise ValidationError("questionPaper file is required")

        question_text = _extract_text_from_upload(
            question_file,
            extract_text_from_pdf_via_vision,
            extract_text_from_docx,
            extract_text_from_image_via_vision,
        )

        rubric_text = None
        if rubric_file:
            rubric_text = _extract_text_from_upload(
                rubric_file,
                extract_text_from_pdf_via_vision,
                extract_text_from_docx,
                extract_text_from_image_via_vision,
            )

        extracted = extract_exam_from_text(question_text, rubric_text)

        title_override = request.form.get("title")
        subject_override = request.form.get("subject")
        if title_override:
            extracted.title = title_override
        if subject_override:
            extracted.subject = subject_override

        if not rubric_file:
            from app.agents.rubric_builder import build_rubrics_for_questions

            q_dicts = [
                {"questionText": q.question_text, "maxMarks": q.max_marks}
                for q in extracted.questions
            ]
            built = build_rubrics_for_questions(q_dicts, subject=extracted.subject)

            from app.agents.exam_extractor import RubricItem

            rubric_map: dict[int, list] = {}
            for qr in built.questions:
                rubric_map[qr.question_index] = qr.rubric

            for i, q in enumerate(extracted.questions):
                if i in rubric_map:
                    q.rubric = [
                        RubricItem(description=r.description, maxMarks=r.max_marks)
                        for r in rubric_map[i]
                    ]

        questions_data = []
        for q in extracted.questions:
            questions_data.append(QuestionInput(
                questionText=q.question_text,
                maxMarks=q.max_marks,
                rubric=[
                    RubricCriterionInput(description=r.description, maxMarks=r.max_marks)
                    for r in q.rubric
                ],
            ))

        create_req = CreateExamRequest(
            title=extracted.title,
            subject=extracted.subject,
            questions=questions_data,
        )

        return _create_exam_from_data(create_req)


@exam_bp.route("/<exam_id>")
class ExamDetailView(MethodView):
    @jwt_required
    def get(self, exam_id: str):
        """Get exam details with all questions and rubrics."""
        institution_id = get_current_institution_id()
        doc = ExamRepository().find_by_id(exam_id, institution_id)
        if not doc:
            raise NotFoundError("Exam", exam_id)
        return _serialize_exam(doc)


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


def _create_exam_from_data(data: CreateExamRequest) -> tuple[dict, int]:
    institution_id = get_current_institution_id()
    user_id = get_current_user_id()
    total_marks = sum(q.max_marks for q in data.questions)

    needs_rubric_gen = any(
        not q.rubric or all(not c.description.strip() for c in q.rubric)
        for q in data.questions
    )
    built_rubric_map: dict[int, list] = {}
    if needs_rubric_gen:
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
        q_id = f"q{i}"
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


def _serialize_exam(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", ""),
        "subject": doc.get("subject", ""),
        "questions": doc.get("questions", []),
        "totalMarks": doc.get("totalMarks", 0),
        "createdAt": _fmt_dt(doc.get("createdAt")),
    }
