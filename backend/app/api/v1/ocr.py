"""
OCR review endpoints — page results, text editing, segmentation re-run.
"""

from __future__ import annotations

import logging

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint

from app.api.middleware.auth import get_current_institution_id, jwt_required
from app.common.exceptions import NotFoundError
from app.infrastructure.db.repositories import (
    OCRPageResultRepository,
    UploadedScriptRepository,
)
from app.infrastructure.storage import get_storage_provider

logger = logging.getLogger(__name__)
ocr_bp = Blueprint("ocr", __name__, url_prefix="/ocr", description="OCR Review")


@ocr_bp.route("/scripts/<script_id>/pages")
class OCRPagesView(MethodView):
    @jwt_required
    def get(self, script_id: str):
        """List all OCR page results for an uploaded script."""
        institution_id = get_current_institution_id()
        upload = UploadedScriptRepository().find_by_id(script_id, institution_id)
        if not upload:
            raise NotFoundError("UploadedScript", script_id)

        pages = OCRPageResultRepository().find_by_script(script_id)

        return {
            "scriptId": script_id,
            "pageCount": len(pages),
            "pages": [_serialize_page(p) for p in pages],
        }


@ocr_bp.route("/scripts/<script_id>/pages/<int:page_number>")
class OCRPageDetailView(MethodView):
    @jwt_required
    def get(self, script_id: str, page_number: int):
        """Get a single OCR page result."""
        page = OCRPageResultRepository().find_one({
            "uploadedScriptId": script_id,
            "pageNumber": page_number,
        })
        if not page:
            raise NotFoundError("OCRPageResult", f"{script_id}/page/{page_number}")
        return _serialize_page(page)

    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER", "REVIEWER"])
    def put(self, script_id: str, page_number: int):
        """Update extracted text for a page (manual correction)."""
        data = request.get_json()
        corrected_text = data.get("extractedText")
        if corrected_text is None:
            from app.common.exceptions import ValidationError
            raise ValidationError("extractedText is required")

        page = OCRPageResultRepository().find_one({
            "uploadedScriptId": script_id,
            "pageNumber": page_number,
        })
        if not page:
            raise NotFoundError("OCRPageResult", f"{script_id}/page/{page_number}")

        OCRPageResultRepository().update_one(
            str(page["_id"]),
            {"$set": {"extractedText": corrected_text}},
        )

        return {"message": "Page text updated", "pageNumber": page_number}


@ocr_bp.route("/scripts/<script_id>/signed-url")
class SignedURLView(MethodView):
    @jwt_required
    def get(self, script_id: str):
        """Generate a signed URL for the original uploaded file."""
        institution_id = get_current_institution_id()
        upload = UploadedScriptRepository().find_by_id(script_id, institution_id)
        if not upload:
            raise NotFoundError("UploadedScript", script_id)

        storage = get_storage_provider()
        url = storage.generate_signed_url(upload["fileKey"])
        return {"signedUrl": url, "expiresIn": 900}


@ocr_bp.route("/scripts/<script_id>/re-segment")
class ReSegmentView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER", "REVIEWER"])
    def post(self, script_id: str):
        """Re-run LLM segmentation on the aggregated OCR text."""
        institution_id = get_current_institution_id()
        upload = UploadedScriptRepository().find_by_id(script_id, institution_id)
        if not upload:
            raise NotFoundError("UploadedScript", script_id)

        pages = OCRPageResultRepository().find_by_script(script_id)
        if not pages:
            from app.common.exceptions import ValidationError
            raise ValidationError("No OCR pages found — run OCR first")

        full_text = "\n\n".join(
            p["extractedText"] for p in sorted(pages, key=lambda x: x["pageNumber"])
        )
        avg_conf = sum(p["confidenceScore"] for p in pages) / len(pages)
        all_flags = list({f for p in pages for f in p.get("qualityFlags", [])})

        from app.tasks.ocr import segment_answers
        import uuid

        segment_answers.delay(
            script_id, full_text, avg_conf, all_flags, uuid.uuid4().hex[:16]
        )

        return {"message": "Re-segmentation triggered", "scriptId": script_id}


def _serialize_page(p: dict) -> dict:
    return {
        "id": str(p["_id"]),
        "uploadedScriptId": p.get("uploadedScriptId"),
        "pageNumber": p.get("pageNumber"),
        "extractedText": p.get("extractedText"),
        "confidenceScore": p.get("confidenceScore"),
        "qualityFlags": p.get("qualityFlags", []),
        "provider": p.get("provider"),
        "processingMs": p.get("processingMs"),
    }
