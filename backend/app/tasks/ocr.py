"""
OCR pipeline Celery tasks — file ingestion, PDF splitting, per-page OpenAI Vision OCR,
aggregation, and LLM-based segmentation.

All tasks: bind=True, acks_late=True, reject_on_worker_lost=True.
Exponential backoff on retry: countdown = 2 ** retries * 10
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid

from celery import group

from app.common.exceptions import OCRError, SegmentationError
from app.common.observability import (
    ocr_confidence_score,
    ocr_processing_duration,
    structured_log,
    tasks_total,
)
from app.config import get_settings
from app.domain.models.common import QualityFlag, UploadStatus
from app.infrastructure.db.repositories import (
    ExamRepository,
    OCRPageResultRepository,
    UploadedScriptRepository,
)
from app.infrastructure.storage import get_storage_provider
from celery_app import celery

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 0.65


@celery.task(
    bind=True,
    name="app.tasks.ocr.ingest_file",
    queue="ocr",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def ingest_file(self, uploaded_script_id: str):
    """Stage 1 entry: download file and dispatch OCR pipeline."""
    trace_id = uuid.uuid4().hex[:16]
    repo = UploadedScriptRepository()

    try:
        doc = repo.find_by_id(uploaded_script_id)
        if not doc:
            logger.error(f"UploadedScript {uploaded_script_id} not found")
            return

        repo.update_one(uploaded_script_id, {"$set": {"uploadStatus": UploadStatus.PROCESSING.value}})

        storage = get_storage_provider()
        mime_type = doc["mimeType"]
        file_key = doc["fileKey"]

        tmpdir = tempfile.mkdtemp()
        local_path = os.path.join(tmpdir, "input_file")
        storage.download(file_key, local_path)

        if mime_type == "application/pdf":
            convert_pdf_to_images.delay(uploaded_script_id, local_path, trace_id)
        else:
            process_page.apply_async(
                args=[uploaded_script_id, local_path, 1, trace_id],
                link=aggregate_pages.si(uploaded_script_id, trace_id),
            )

        tasks_total.labels(queue="ocr", status="success").inc()

    except Exception as exc:
        tasks_total.labels(queue="ocr", status="error").inc()
        repo.update_one(uploaded_script_id, {
            "$set": {"uploadStatus": UploadStatus.FAILED.value, "failureReason": str(exc)}
        })
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)


@celery.task(
    bind=True,
    name="app.tasks.ocr.convert_pdf_to_images",
    queue="ocr",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=2,
)
def convert_pdf_to_images(self, uploaded_script_id: str, pdf_path: str, trace_id: str):
    """Split PDF into per-page images, fan out OpenAI Vision OCR tasks."""
    try:
        from pdf2image import convert_from_path

        settings = get_settings()
        dpi = getattr(settings, "OCR_DPI", 150)
        images = convert_from_path(pdf_path, dpi=dpi)
        page_count = len(images)

        if page_count > settings.MAX_PAGES_PER_SCRIPT:
            UploadedScriptRepository().update_one(uploaded_script_id, {
                "$set": {
                    "uploadStatus": UploadStatus.FAILED.value,
                    "failureReason": f"Page count {page_count} exceeds max {settings.MAX_PAGES_PER_SCRIPT}",
                }
            })
            return

        UploadedScriptRepository().update_one(
            uploaded_script_id, {"$set": {"pageCount": page_count}}
        )

        tmpdir = tempfile.mkdtemp()
        page_tasks = []
        for i, img in enumerate(images, start=1):
            page_path = os.path.join(tmpdir, f"page_{i}.png")
            img.save(page_path, "PNG")
            page_tasks.append(
                process_page.s(uploaded_script_id, page_path, i, trace_id)
            )

        # Dispatch all OCR page tasks; no chord (chord callback often never runs with
        # many tasks + Redis). Schedule aggregate_pages to run after a delay and retry
        # until all pages are in the DB.
        group(page_tasks).apply_async()
        aggregate_pages.apply_async(
            args=[uploaded_script_id, trace_id],
            kwargs={"expected_page_count": page_count},
            countdown=45,
        )

    except Exception as exc:
        UploadedScriptRepository().update_one(uploaded_script_id, {
            "$set": {"uploadStatus": UploadStatus.FAILED.value, "failureReason": str(exc)}
        })
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)


def _process_page_limits():
    s = get_settings()
    return {
        "soft_time_limit": getattr(s, "OCR_PAGE_SOFT_TIME_LIMIT", 300),
        "time_limit": getattr(s, "OCR_PAGE_TIME_LIMIT", 330),
    }


@celery.task(
    bind=True,
    name="app.tasks.ocr.process_page",
    queue="ocr",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=2,
    **_process_page_limits(),
)
def process_page(self, uploaded_script_id: str, image_path: str, page_number: int, trace_id: str):
    """Send a single page image to OpenAI Vision for text extraction."""
    try:
        from app.infrastructure.ocr import extract_page_text

        result = extract_page_text(image_path, page_number=page_number)

        quality_flags = []
        if result.confidence < LOW_CONFIDENCE_THRESHOLD:
            quality_flags.append(QualityFlag.LOW_CONFIDENCE.value)

        page_doc = {
            "uploadedScriptId": uploaded_script_id,
            "pageNumber": result.page_number,
            "extractedText": result.text,
            "confidenceScore": result.confidence,
            "wordLevelData": None,
            "qualityFlags": quality_flags,
            "provider": result.provider,
            "processingMs": result.processing_ms,
        }

        OCRPageResultRepository().insert_one(page_doc)

        ocr_processing_duration.labels(
            provider="openai_vision", status="success"
        ).observe(result.processing_ms / 1000)

        structured_log(
            "info",
            f"OCR page {page_number} extracted via OpenAI Vision",
            trace_id=trace_id,
            script_id=uploaded_script_id,
            agent_name="openai_vision_ocr",
            duration_ms=result.processing_ms,
        )

    except Exception as exc:
        ocr_processing_duration.labels(
            provider="openai_vision", status="error"
        ).observe(0)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)


@celery.task(
    bind=True,
    name="app.tasks.ocr.aggregate_pages",
    queue="ocr",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=15,
)
def aggregate_pages(
    self,
    uploaded_script_id: str,
    trace_id: str,
    *,
    expected_page_count: int | None = None,
):
    """Aggregate all OCR page results into full text and trigger segmentation.
    Scheduled with countdown after fan-out; retries until all pages are ready.
    """
    logger.info(
        "aggregate_pages started for script %s",
        uploaded_script_id,
    )
    try:
        ocr_repo = OCRPageResultRepository()
        pages = ocr_repo.find_by_script(uploaded_script_id)

        if not pages:
            raise self.retry(countdown=10)

        expected = expected_page_count
        if expected is None:
            doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
            expected = doc.get("pageCount") if doc else None

        if expected is not None and len(pages) < expected:
            logger.info(
                "aggregate_pages: script %s has %s/%s pages, retrying in 10s",
                uploaded_script_id,
                len(pages),
                expected,
            )
            raise self.retry(countdown=10)

        pages_sorted = sorted(pages, key=lambda p: p["pageNumber"])
        full_text = "\n\n".join(p["extractedText"] for p in pages_sorted)
        confidences = [p["confidenceScore"] for p in pages_sorted]
        avg_confidence = sum(confidences) / len(confidences)

        all_flags = set()
        for p in pages_sorted:
            all_flags.update(p.get("qualityFlags", []))

        UploadedScriptRepository().update_one(uploaded_script_id, {
            "$set": {
                "uploadStatus": UploadStatus.OCR_COMPLETE.value,
                "pageCount": len(pages_sorted),
            }
        })
        logger.info(
            "aggregate_pages: set uploadStatus=OCR_COMPLETE for %s (%s pages), dispatching segment_answers",
            uploaded_script_id,
            len(pages_sorted),
        )

        doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
        if doc:
            ocr_confidence_score.labels(
                institution_id=doc.get("institutionId", "unknown")
            ).observe(avg_confidence)

        segment_answers.delay(
            uploaded_script_id, full_text, avg_confidence,
            list(all_flags), trace_id,
        )

    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)


def _segment_answers_limits():
    """Time limits for segment_answers (configurable via env)."""
    s = get_settings()
    return {
        "soft_time_limit": s.SEGMENTATION_SOFT_TIME_LIMIT,
        "time_limit": s.SEGMENTATION_TIME_LIMIT,
    }


# Regex to find question-number markers in unmapped text (e.g. "Q23", "Question 23", "23.", "Ans 23").
# Captures the number; used to recover answers the LLM left in unmappedText.
_QUESTION_MARKER_RE = re.compile(
    r"(?:(?:^|\n)\s*)(?:Q\.?\s*|Question\s+|Ques\.?\s*|Ans(?:wer)?\s*)?(\d+)[\.\)\:\s]",
    re.IGNORECASE,
)


def _recover_answers_from_unmapped(seg_result: dict, question_ids: list[str]) -> dict:
    """
    Post-process segmentation: assign substantial blocks in unmappedText to questions
    that currently have no answer when the block clearly follows a question-number marker.
    Reduces missed answers when the LLM leaves content in unmappedText.
    """
    unmapped = (seg_result.get("unmappedText") or "").strip()
    if not unmapped or len(unmapped) < 20:
        return seg_result

    answers_list = list(seg_result.get("answers") or [])
    by_q = {a.get("questionId") or "": a for a in answers_list}
    # Normalize: ensure we have entries for all exam questions
    for qid in question_ids:
        if qid not in by_q:
            by_q[qid] = {"questionId": qid, "answerText": None}
            answers_list.append(by_q[qid])

    # Find all (start_index, number) for question markers in unmapped
    matches = list(_QUESTION_MARKER_RE.finditer(unmapped))
    if not matches:
        return seg_result

    recovered = 0
    for i, m in enumerate(matches):
        num_str = m.group(1)
        try:
            num = int(num_str)
        except ValueError:
            continue
        qid = f"q{num}"
        if qid not in by_q:
            continue
        entry = by_q[qid]
        current = (entry.get("answerText") or "").strip()
        if current:
            continue  # already has an answer
        # Text for this answer: from end of this marker to start of next marker or end
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(unmapped)
        block = unmapped[start:end].strip()
        if len(block) < 15:
            continue
        entry["answerText"] = block
        recovered += 1
        logger.info("Recovered answer for %s from unmappedText (%d chars)", qid, len(block))

    if recovered:
        seg_result["answers"] = [by_q[qid] for qid in question_ids]
    return seg_result


@celery.task(
    bind=True,
    name="app.tasks.ocr.segment_answers",
    queue="ocr",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=2,
    **_segment_answers_limits(),
)
def segment_answers(
    self,
    uploaded_script_id: str,
    full_text: str,
    avg_confidence: float,
    quality_flags: list[str],
    trace_id: str,
):
    """Use the SegmentationAgent to map OCR text to per-question answers."""
    from app.agents.segmentation import SegmentationAgent
    from app.tasks.evaluation import prepare_script

    logger.info("segment_answers started for script %s", uploaded_script_id)
    try:
        settings = get_settings()
        max_chars = getattr(settings, "SEGMENTATION_MAX_OCR_CHARS", 0) or 0
        if max_chars > 0 and len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n\n[... OCR text truncated for length ...]"
            logger.info("segment_answers: truncated OCR to %s chars", max_chars)

        doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
        if not doc:
            raise SegmentationError(f"Script {uploaded_script_id} not found")

        exam = ExamRepository().find_by_id(doc["examId"])
        if not exam:
            raise SegmentationError(f"Exam {doc['examId']} not found")

        questions = [
            {"questionId": q["questionId"], "questionText": q["questionText"]}
            for q in exam.get("questions", [])
        ]

        seg_model = getattr(settings, "OPENAI_MODEL_SEGMENTATION", None)
        seg_max_tokens = getattr(settings, "OPENAI_SEGMENTATION_MAX_TOKENS", 8192)

        agent = SegmentationAgent()
        result, meta = agent.execute(
            trace_id=trace_id,
            questions=questions,
            ocr_text=full_text,
            model=seg_model if seg_model else None,
            max_tokens=seg_max_tokens,
        )

        seg_dict = result.model_dump(by_alias=True)
        question_ids = [q.get("questionId", "") for q in exam.get("questions", []) if q.get("questionId")]
        seg_dict = _recover_answers_from_unmapped(seg_dict, question_ids)

        UploadedScriptRepository().update_one(uploaded_script_id, {
            "$set": {"uploadStatus": UploadStatus.SEGMENTED.value}
        })
        logger.info("segment_answers: set uploadStatus=SEGMENTED for %s, dispatching prepare_script", uploaded_script_id)

        prepare_script.delay(
            uploaded_script_id,
            seg_dict,
            avg_confidence,
            quality_flags,
            trace_id,
        )

    except Exception as exc:
        UploadedScriptRepository().update_one(uploaded_script_id, {
            "$set": {
                "uploadStatus": UploadStatus.FLAGGED.value,
                "failureReason": f"Segmentation failed: {exc}",
            }
        })
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)
