"""
OCR review endpoints — page results, text editing, segmentation re-run.
"""

from __future__ import annotations

import logging

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint

from app.api.middleware.auth import (
    can_see_all_institution_data,
    get_current_institution_id,
    get_current_user_id,
    jwt_required,
)
from app.common.exceptions import NotFoundError, ValidationError
from app.infrastructure.db.repositories import (
    OCRPageResultRepository,
    UploadedScriptRepository,
)
from app.infrastructure.storage import get_storage_provider

logger = logging.getLogger(__name__)
ocr_bp = Blueprint("ocr", __name__, url_prefix="/ocr", description="OCR Review")


def _check_upload_access(upload: dict | None, script_id: str) -> None:
    """Raise NotFoundError if user cannot access this upload (professor isolation)."""
    if not upload:
        raise NotFoundError("UploadedScript", script_id)
    if not can_see_all_institution_data() and upload.get("createdBy") != get_current_user_id():
        raise NotFoundError("UploadedScript", script_id)


@ocr_bp.route("/scripts/<script_id>/pages")
class OCRPagesView(MethodView):
    @jwt_required
    def get(self, script_id: str):
        """List all OCR page results for an uploaded script."""
        institution_id = get_current_institution_id()
        upload = UploadedScriptRepository().find_by_id(script_id, institution_id)
        _check_upload_access(upload, script_id)

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
        institution_id = get_current_institution_id()
        upload = UploadedScriptRepository().find_by_id(script_id, institution_id)
        _check_upload_access(upload, script_id)
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
        institution_id = get_current_institution_id()
        upload = UploadedScriptRepository().find_by_id(script_id, institution_id)
        _check_upload_access(upload, script_id)
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
        _check_upload_access(upload, script_id)

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
        _check_upload_access(upload, script_id)

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


@ocr_bp.route("/test")
class OCRTestView(MethodView):
    @jwt_required(roles=["SUPER_ADMIN", "INSTITUTION_ADMIN", "EXAMINER", "REVIEWER"])
    def post(self):
        """Test OCR with a single file (answer booklet). Returns the extracted text."""
        import os
        import shutil
        import tempfile
        from concurrent.futures import ThreadPoolExecutor

        import magic
        from werkzeug.utils import secure_filename

        from app.infrastructure.ocr import extract_page_text

        if "file" not in request.files:
            raise ValidationError("file is required")

        file = request.files["file"]
        if file.filename == "":
            raise ValidationError("No selected file")

        file_bytes = file.read()
        detected_mime = magic.from_buffer(file_bytes, mime=True)

        tmpdir = tempfile.mkdtemp()
        local_path = os.path.join(tmpdir, secure_filename(file.filename or "test_file"))

        with open(local_path, "wb") as f:
            f.write(file_bytes)

        try:
            if detected_mime == "application/pdf":
                from pdf2image import convert_from_path

                images = convert_from_path(local_path, dpi=200)
                page_tasks = []
                for i, img in enumerate(images, start=1):
                    if i > 10:
                        break
                    page_path = os.path.join(tmpdir, f"page_{i}.png")
                    img.save(page_path, "PNG")
                    page_tasks.append((page_path, i))

                results = []
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(extract_page_text, path, num)
                        for path, num in page_tasks
                    ]
                    for future in futures:
                        results.append(future.result())

                results.sort(key=lambda r: r.page_number)
                full_text = "\n\n".join(
                    f"--- Page {r.page_number} ---\n{r.text}" for r in results
                )
                return {"text": full_text}
            else:
                result = extract_page_text(local_path, 1)
                return {"text": result.text}
        except Exception as e:
            raise ValidationError(f"OCR Test Failed: {str(e)}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


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
