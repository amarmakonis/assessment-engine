"""
Synchronous pipeline for OCR and evaluation — runs without Celery/Redis.
Used when USE_CELERY_REDIS is False.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import get_settings
from app.domain.models.common import UploadStatus
from app.infrastructure.cache.memory_cache import MemoryCache
from app.infrastructure.db.repositories import (
    ExamRepository,
    OCRPageResultRepository,
    UploadedScriptRepository,
)
from app.infrastructure.storage import get_storage_provider

logger = logging.getLogger(__name__)

AGGREGATE_LOCK_TTL = 600


def run_ingest(uploaded_script_id: str, local_file_path: str | None = None) -> None:
    """Run full OCR + segmentation + prepare + evaluation pipeline synchronously.
    If local_file_path is set, use it (answer script file is not stored in storage).
    Otherwise download from storage using doc fileKey (legacy).
    """
    trace_id = uuid.uuid4().hex[:16]
    repo = UploadedScriptRepository()

    doc = repo.find_by_id(uploaded_script_id)
    if not doc:
        logger.error(f"UploadedScript {uploaded_script_id} not found")
        return

    try:
        repo.update_one(uploaded_script_id, {"$set": {"uploadStatus": UploadStatus.PROCESSING.value}})

        mime_type = doc["mimeType"]
        tmpdir = None
        if local_file_path:
            local_path = local_file_path
        else:
            file_key = doc.get("fileKey")
            if not file_key:
                raise ValueError("No file: fileKey missing and local_file_path not provided")
            storage = get_storage_provider()
            tmpdir = tempfile.mkdtemp()
            local_path = os.path.join(tmpdir, "input_file")
            storage.download(file_key, local_path)

        try:
            if mime_type == "application/pdf":
                _run_convert_pdf_and_ocr(uploaded_script_id, local_path, trace_id)
            else:
                _run_process_page(uploaded_script_id, local_path, 1, trace_id)
                _run_aggregate_and_segment(uploaded_script_id, trace_id, expected_page_count=1)
        finally:
            if tmpdir and os.path.isdir(tmpdir):
                try:
                    import shutil
                    shutil.rmtree(tmpdir, ignore_errors=True)
                except OSError:
                    pass
    except Exception as exc:
        logger.exception("Ingest failed for %s", uploaded_script_id)
        repo.update_one(uploaded_script_id, {
            "$set": {"uploadStatus": UploadStatus.FAILED.value, "failureReason": str(exc)}
        })


def re_run_ocr_from_file(uploaded_script_id: str, local_file_path: str) -> None:
    """Re-run OCR (and then segmentation) from a local file. Clears existing OCR page results first.
    Use when the file was stored (storeFile=true) and you want to re-run OCR e.g. after changing OCR params.
    """
    trace_id = uuid.uuid4().hex[:16]
    repo = UploadedScriptRepository()
    doc = repo.find_by_id(uploaded_script_id)
    if not doc:
        logger.error("re_run_ocr_from_file: UploadedScript %s not found", uploaded_script_id)
        return
    OCRPageResultRepository().delete_many_by_uploaded_script(uploaded_script_id)
    try:
        repo.update_one(uploaded_script_id, {"$set": {"uploadStatus": UploadStatus.PROCESSING.value}})
        mime_type = doc.get("mimeType", "application/pdf")
        if mime_type == "application/pdf":
            _run_convert_pdf_and_ocr(uploaded_script_id, local_file_path, trace_id)
        else:
            _run_process_page(uploaded_script_id, local_file_path, 1, trace_id)
            _run_aggregate_and_segment(uploaded_script_id, trace_id, expected_page_count=1)
    except Exception as exc:
        logger.exception("re_run_ocr_from_file failed for %s", uploaded_script_id)
        repo.update_one(uploaded_script_id, {
            "$set": {"uploadStatus": UploadStatus.FAILED.value, "failureReason": str(exc)}
        })


def _run_convert_pdf_and_ocr(uploaded_script_id: str, pdf_path: str, trace_id: str) -> None:
    """Split PDF into pages, run OCR on each, then aggregate and segment."""
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

    import time

    tmpdir = tempfile.mkdtemp()
    try:
        max_concurrent = max(1, min(getattr(settings, "OCR_TEST_MAX_CONCURRENT", 1), 5))
        delay_sec = max(0.0, getattr(settings, "OCR_TEST_DELAY_SECONDS", 2.0))
        page_tasks = []
        for i, img in enumerate(images, start=1):
            page_path = os.path.join(tmpdir, f"page_{i}.png")
            img.save(page_path, "PNG")
            page_tasks.append((page_path, i))

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = []
            for idx, (page_path, page_num) in enumerate(page_tasks):
                if delay_sec > 0 and idx > 0:
                    time.sleep(delay_sec)
                futures.append(executor.submit(_run_process_page, uploaded_script_id, page_path, page_num, trace_id))
            for f in as_completed(futures):
                f.result()

        _run_aggregate_and_segment(uploaded_script_id, trace_id, expected_page_count=page_count)
    finally:
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def _run_process_page(uploaded_script_id: str, image_path: str, page_number: int, trace_id: str) -> None:
    """Extract text from a single page via OpenAI Vision and store result."""
    from app.common.observability import ocr_processing_duration, structured_log
    from app.domain.models.common import QualityFlag
    from app.infrastructure.ocr import extract_page_text

    LOW_CONFIDENCE_THRESHOLD = 0.65

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

    ocr_processing_duration.labels(provider="openai_vision", status="success").observe(
        result.processing_ms / 1000
    )

    structured_log(
        "info",
        f"OCR page {page_number} extracted via OpenAI Vision",
        trace_id=trace_id,
        script_id=uploaded_script_id,
        agent_name="openai_vision_ocr",
        duration_ms=result.processing_ms,
    )


def _run_aggregate_and_segment(
    uploaded_script_id: str,
    trace_id: str,
    *,
    expected_page_count: int | None = None,
) -> None:
    """Aggregate OCR pages and run segmentation, then prepare script and evaluate."""
    from app.tasks.ocr import _recover_answers_from_unmapped

    cache = MemoryCache()
    lock_key = f"aggregate_lock:{uploaded_script_id}"
    acquired = cache.set_with_nx(lock_key, "1", AGGREGATE_LOCK_TTL)
    if not acquired:
        logger.info("aggregate: skip script %s (lock held)", uploaded_script_id)
        return

    try:
        doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
        if not doc:
            return
        if doc.get("uploadStatus") == UploadStatus.OCR_COMPLETE.value:
            return

        ocr_repo = OCRPageResultRepository()
        pages = ocr_repo.find_by_script(uploaded_script_id)

        if not pages:
            raise RuntimeError("No OCR pages found")

        expected = expected_page_count or doc.get("pageCount")
        if expected is not None and len(pages) < expected:
            raise RuntimeError(f"Only {len(pages)}/{expected} pages ready")

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

        run_segment_and_prepare(
            uploaded_script_id,
            full_text,
            avg_confidence,
            list(all_flags),
            trace_id,
        )
    finally:
        cache.delete(lock_key)


def run_segment_and_prepare(
    uploaded_script_id: str,
    full_text: str,
    avg_confidence: float,
    quality_flags: list[str],
    trace_id: str,
) -> None:
    """Run segmentation and prepare script, then evaluate questions synchronously."""
    from app.agents.segmentation import SegmentationAgent
    from app.tasks.ocr import _recover_answers_from_unmapped

    settings = get_settings()
    max_chars = getattr(settings, "SEGMENTATION_MAX_OCR_CHARS", 0) or 0
    if max_chars > 0 and len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n\n[... OCR text truncated for length ...]"

    doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
    if not doc:
        logger.warning("segment_answers: script %s not found", uploaded_script_id)
        return

    exam = ExamRepository().find_by_id(doc["examId"])
    if not exam:
        logger.warning("segment_answers: exam %s not found", doc.get("examId"))
        return

    max_q_chars = getattr(settings, "SEGMENTATION_MAX_QUESTION_TEXT_CHARS", 0) or 0
    questions = []
    for q in exam.get("questions", []):
        qtext = (q.get("questionText") or "").strip()
        if max_q_chars > 0 and len(qtext) > max_q_chars:
            qtext = qtext[:max_q_chars] + "..."
        questions.append({"questionId": q.get("questionId"), "questionText": qtext})
    question_ids = [q.get("questionId", "") for q in exam.get("questions", []) if q.get("questionId")]

    seg_model = getattr(settings, "OPENAI_MODEL_SEGMENTATION", None)
    seg_max_tokens = getattr(settings, "OPENAI_SEGMENTATION_MAX_TOKENS", 8192)

    agent = SegmentationAgent()
    result, _ = agent.execute(
        trace_id=trace_id,
        questions=questions,
        ocr_text=full_text,
        model=seg_model if seg_model else None,
        max_tokens=seg_max_tokens,
    )

    seg_dict = result.model_dump(by_alias=True)
    seg_dict = _recover_answers_from_unmapped(seg_dict, question_ids)

    UploadedScriptRepository().update_one(uploaded_script_id, {
        "$set": {"uploadStatus": UploadStatus.SEGMENTED.value}
    })

    run_prepare_script(
        uploaded_script_id,
        seg_dict,
        avg_confidence,
        quality_flags,
        trace_id,
    )


def run_prepare_script(
    uploaded_script_id: str,
    segmentation_result: dict,
    avg_confidence: float,
    quality_flags: list[str],
    trace_id: str,
) -> None:
    """Create Script from segmentation and evaluate all questions synchronously."""
    from datetime import datetime, timezone

    from app.domain.models.common import (
        EvaluationStatus,
        ReviewRecommendation,
        ScriptSource,
        ScriptStatus,
    )
    from app.infrastructure.db.repositories import (
        EvaluationResultRepository,
        ScriptRepository,
    )

    EVALUATION_VERSION = "1.0.0"
    from app.domain.models.common import UploadStatus

    upload_doc = UploadedScriptRepository().find_by_id(uploaded_script_id)
    if not upload_doc:
        return

    exam_id = upload_doc["examId"]
    exam_doc = ExamRepository().find_by_id(exam_id)
    if not exam_doc:
        return

    exam_questions = exam_doc.get("questions", [])
    seg_by_q = {a["questionId"]: a for a in segmentation_result.get("answers", [])}

    answers = []
    for q in exam_questions:
        qid = q.get("questionId", "")
        seg = seg_by_q.get(qid)
        has_text = seg and seg.get("answerText") and str(seg.get("answerText", "")).strip()
        is_flagged = not has_text
        answers.append({
            "questionId": qid,
            "text": (seg.get("answerText") or "").strip() if seg else "",
            "isFlagged": is_flagged,
        })

    script_doc = {
        "institutionId": upload_doc["institutionId"],
        "createdBy": upload_doc.get("createdBy"),
        "examId": upload_doc["examId"],
        "uploadedScriptId": uploaded_script_id,
        "studentMeta": upload_doc["studentMeta"],
        "answers": answers,
        "source": ScriptSource.OCR.value,
        "ocrConfidenceAverage": avg_confidence,
        "ocrQualityFlags": quality_flags,
        "segmentationConfidence": segmentation_result.get("segmentationConfidence"),
        "status": ScriptStatus.EVALUATING.value,
        "createdAt": datetime.now(timezone.utc),
        "updatedAt": datetime.now(timezone.utc),
    }

    script_id = ScriptRepository().insert_one(script_doc)
    run_id = uuid.uuid4().hex

    UploadedScriptRepository().update_one(
        uploaded_script_id, {"$set": {"uploadStatus": UploadStatus.EVALUATING.value}}
    )

    qid_to_max_marks = {q.get("questionId"): float(q.get("maxMarks", 0)) for q in exam_questions}

    eval_repo = EvaluationResultRepository()
    for a in answers:
        if a["isFlagged"] or not a.get("text", "").strip():
            qid = a["questionId"]
            max_marks = qid_to_max_marks.get(qid, 0)
            idempotency_key = f"{run_id}:{script_id}:{qid}:{EVALUATION_VERSION}"
            if eval_repo.find_by_idempotency_key(idempotency_key):
                continue
            no_attempt_doc = {
                "runId": run_id,
                "scriptId": script_id,
                "institutionId": script_doc.get("institutionId"),
                "createdBy": script_doc.get("createdBy"),
                "questionId": qid,
                "evaluationVersion": EVALUATION_VERSION,
                "idempotencyKey": idempotency_key,
                "groundedRubric": None,
                "criterionScores": [],
                "consistencyAudit": None,
                "feedback": None,
                "explainability": None,
                "totalScore": 0.0,
                "maxPossibleScore": max_marks,
                "percentageScore": 0.0,
                "reviewRecommendation": ReviewRecommendation.AUTO_APPROVED.value,
                "reviewerOverride": None,
                "status": EvaluationStatus.COMPLETE.value,
                "latencyMs": 0,
                "tokensUsed": {"prompt": 0, "completion": 0, "total": 0},
                "createdAt": datetime.now(timezone.utc),
            }
            eval_repo.insert_one(no_attempt_doc)

    non_flagged = [a for a in answers if not a["isFlagged"] and a.get("text", "").strip()]
    if not non_flagged:
        _check_script_completion(script_id)
    else:
        settings = get_settings()
        max_workers = max(1, min(getattr(settings, "EVALUATION_MAX_WORKERS", 5), 10))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(run_evaluate_question, script_id, a["questionId"], run_id, trace_id)
                for a in non_flagged
            ]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    logger.exception("Evaluation failed for one question: %s", e)
        _check_script_completion(script_id)


def run_evaluate_question(script_id: str, question_id: str, run_id: str, trace_id: str) -> None:
    """Run full evaluation for one question synchronously."""
    from datetime import datetime, timezone

    from app.agents import (
        ConsistencyAgent,
        ExplainabilityAgent,
        FeedbackAgent,
        FeedbackExplainabilityAgent,
        RubricGroundingAgent,
        ScoringAgent,
        ScoringConsistencyAgent,
    )
    from app.domain.models.common import ScriptStatus
    from app.infrastructure.cache.memory_cache import MemoryCache
    from app.infrastructure.db.repositories import (
        EvaluationResultRepository,
        ScriptRepository,
        UploadedScriptRepository,
    )

    EVALUATION_VERSION = "1.0.0"
    from app.domain.models.common import EvaluationStatus

    idempotency_key = f"{run_id}:{script_id}:{question_id}:{EVALUATION_VERSION}"

    cache = MemoryCache()
    if not cache.set_with_nx(f"eval_lock:{idempotency_key}", "1", 600):
        existing = EvaluationResultRepository().find_by_idempotency_key(idempotency_key)
        if existing:
            return
        cache.delete(f"eval_lock:{idempotency_key}")

    try:
        import time
        start = time.perf_counter_ns()
        total_prompt_tokens = 0
        total_completion_tokens = 0

        script_doc = ScriptRepository().find_by_id(script_id)
        if not script_doc:
            raise ValueError(f"Script {script_id} not found")
        if script_doc.get("status") == ScriptStatus.CANCELLED.value:
            return

        exam_doc = ExamRepository().find_by_id(script_doc["examId"])
        if not exam_doc:
            raise ValueError(f"Exam {script_doc['examId']} not found")

        answer_entry = next(
            (a for a in script_doc["answers"] if a["questionId"] == question_id),
            None,
        )
        if not answer_entry:
            raise ValueError(f"Answer for question {question_id} not found")

        question_def = next(
            (q for q in exam_doc["questions"] if q["questionId"] == question_id),
            None,
        )
        if not question_def:
            raise ValueError(f"Question {question_id} not found")

        answer_text = answer_entry["text"]
        question_text = question_def["questionText"]
        raw_rubric = question_def.get("rubric", [])
        rubric_criteria = sorted(
            [
                {"criterionId": c["criterionId"], "description": c["description"], "maxMarks": c["maxMarks"]}
                for c in raw_rubric
            ],
            key=lambda x: x["criterionId"],
        )

        settings = get_settings()
        eval_max_tokens = getattr(settings, "OPENAI_EVALUATION_MAX_TOKENS", 2048)

        rubric_agent = RubricGroundingAgent()
        grounded_rubric, rubric_meta = rubric_agent.execute(
            trace_id=trace_id,
            question_text=question_text,
            rubric_criteria=rubric_criteria,
            max_tokens=eval_max_tokens,
        )
        total_prompt_tokens += rubric_meta["prompt_tokens"]
        total_completion_tokens += rubric_meta["completion_tokens"]

        question_max_marks = float(question_def.get("maxMarks", 0))
        if question_max_marks > 0 and abs(grounded_rubric.total_marks - question_max_marks) > 0.01:
            scale = question_max_marks / grounded_rubric.total_marks
            for c in grounded_rubric.criteria:
                c.max_marks = round(c.max_marks * scale, 2)
            grounded_rubric.total_marks = question_max_marks

        max_score = grounded_rubric.total_marks
        use_merged = getattr(settings, "USE_MERGED_AGENTS", True)

        if use_merged:
            # Merged flow: 3 LLM calls (rubric + scoring+consistency + feedback+explainability)
            sorted_criteria = sorted(grounded_rubric.criteria, key=lambda c: c.criterion_id)
            scoring_consistency_agent = ScoringConsistencyAgent()
            sc_result, sc_meta = scoring_consistency_agent.execute(
                trace_id=trace_id,
                answer_text=answer_text,
                rubric=grounded_rubric.model_dump(by_alias=True),
                grounded_criteria=[c.model_dump(by_alias=True) for c in sorted_criteria],
                question_text=question_text,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += sc_meta["prompt_tokens"]
            total_completion_tokens += sc_meta["completion_tokens"]

            criterion_scores = sorted(sc_result.scores, key=lambda s: s.criterion_id)
            consistency_audit = scoring_consistency_agent.to_consistency_audit(sc_result)
            total_score = round(sum(fs.final_score for fs in consistency_audit.final_scores), 4)
            consistency_audit.total_score = total_score

            # Apply final scores to criterion_scores for downstream
            final_score_map = {fs.criterion_id: fs.final_score for fs in consistency_audit.final_scores}
            for cs in criterion_scores:
                if cs.criterion_id in final_score_map:
                    cs.marks_awarded = final_score_map[cs.criterion_id]

            sorted_final = sorted(consistency_audit.final_scores, key=lambda fs: fs.criterion_id)
            criterion_scores_dict = [s.model_dump(by_alias=True) for s in criterion_scores]
            fe_agent = FeedbackExplainabilityAgent()
            fe_result, fe_meta = fe_agent.execute(
                trace_id=trace_id,
                question_text=question_text,
                answer_text=answer_text,
                grounded_rubric=grounded_rubric.model_dump(by_alias=True),
                criterion_scores=criterion_scores_dict,
                consistency_audit=consistency_audit.model_dump(by_alias=True),
                total_score=total_score,
                max_score=max_score,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += fe_meta["prompt_tokens"]
            total_completion_tokens += fe_meta["completion_tokens"]
            feedback = fe_agent.to_feedback(fe_result)
            explainability = fe_agent.to_explainability(fe_result)
        else:
            # Legacy flow: 5 LLM calls
            sorted_criteria = sorted(grounded_rubric.criteria, key=lambda c: c.criterion_id)
            scoring_agent = ScoringAgent()
            criterion_scores, scoring_metas = scoring_agent.score_all_criteria(
                trace_id=trace_id,
                answer_text=answer_text,
                grounded_criteria=[c.model_dump(by_alias=True) for c in sorted_criteria],
                question_text=question_text,
            )
            for m in scoring_metas:
                total_prompt_tokens += m["prompt_tokens"]
                total_completion_tokens += m["completion_tokens"]

            sorted_scores = sorted(criterion_scores, key=lambda s: s.criterion_id)
            consistency_agent = ConsistencyAgent()
            consistency_audit, consistency_meta = consistency_agent.execute(
                trace_id=trace_id,
                answer_text=answer_text,
                rubric=grounded_rubric.model_dump(by_alias=True),
                criterion_scores=[s.model_dump(by_alias=True) for s in sorted_scores],
                question_text=question_text,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += consistency_meta["prompt_tokens"]
            total_completion_tokens += consistency_meta["completion_tokens"]

            final_score_map = {fs.criterion_id: fs.final_score for fs in consistency_audit.final_scores}
            for cs in criterion_scores:
                if cs.criterion_id in final_score_map:
                    cs.marks_awarded = final_score_map[cs.criterion_id]

            total_score = round(sum(fs.final_score for fs in consistency_audit.final_scores), 4)
            consistency_audit.total_score = total_score

            sorted_final = sorted(consistency_audit.final_scores, key=lambda fs: fs.criterion_id)
            feedback_agent = FeedbackAgent()
            feedback, feedback_meta = feedback_agent.execute(
                trace_id=trace_id,
                question_text=question_text,
                answer_text=answer_text,
                final_scores=[fs.model_dump(by_alias=True) for fs in sorted_final],
                total_score=total_score,
                max_score=max_score,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += feedback_meta["prompt_tokens"]
            total_completion_tokens += feedback_meta["completion_tokens"]

            explain_agent = ExplainabilityAgent()
            explainability, explain_meta = explain_agent.execute(
                trace_id=trace_id,
                question_text=question_text,
                answer_text=answer_text,
                grounded_rubric=grounded_rubric.model_dump(by_alias=True),
                criterion_scores=[s.model_dump(by_alias=True) for s in criterion_scores],
                consistency_audit=consistency_audit.model_dump(by_alias=True),
                feedback=feedback.model_dump(by_alias=True),
                total_score=total_score,
                max_score=max_score,
                max_tokens=eval_max_tokens,
            )
            total_prompt_tokens += explain_meta["prompt_tokens"]
            total_completion_tokens += explain_meta["completion_tokens"]

        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        percentage = (total_score / max_score * 100) if max_score > 0 else 0

        eval_doc = {
            "runId": run_id,
            "scriptId": script_id,
            "institutionId": script_doc.get("institutionId"),
            "createdBy": script_doc.get("createdBy"),
            "questionId": question_id,
            "evaluationVersion": EVALUATION_VERSION,
            "idempotencyKey": idempotency_key,
            "groundedRubric": grounded_rubric.model_dump(by_alias=True),
            "criterionScores": [s.model_dump(by_alias=True) for s in criterion_scores],
            "consistencyAudit": consistency_audit.model_dump(by_alias=True),
            "feedback": feedback.model_dump(by_alias=True),
            "explainability": explainability.model_dump(by_alias=True),
            "totalScore": total_score,
            "maxPossibleScore": max_score,
            "percentageScore": round(percentage, 2),
            "reviewRecommendation": explainability.review_recommendation.value,
            "reviewerOverride": None,
            "status": EvaluationStatus.COMPLETE.value,
            "latencyMs": elapsed_ms,
            "tokensUsed": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_prompt_tokens + total_completion_tokens,
            },
            "createdAt": datetime.now(timezone.utc),
        }

        EvaluationResultRepository().insert_one(eval_doc)

        _check_script_completion(script_id)
    finally:
        cache.delete(f"eval_lock:{idempotency_key}")


def _check_script_completion(script_id: str) -> None:
    """Mark script COMPLETE when every question has an evaluation result."""
    from app.domain.models.common import ScriptStatus
    from app.infrastructure.db.repositories import (
        EvaluationResultRepository,
        ScriptRepository,
        UploadedScriptRepository,
    )

    script_doc = ScriptRepository().find_by_id(script_id)
    if not script_doc:
        return

    answer_ids = {a["questionId"] for a in script_doc.get("answers", [])}
    eval_repo = EvaluationResultRepository()
    completed_evals = eval_repo.find_by_script(script_id)
    completed_ids = {e["questionId"] for e in completed_evals if e["status"] == "COMPLETE"}

    if answer_ids and answer_ids <= completed_ids:
        has_flagged = any(a.get("isFlagged") for a in script_doc["answers"])
        status = ScriptStatus.IN_REVIEW if has_flagged else ScriptStatus.COMPLETE
        ScriptRepository().update_one(script_id, {"$set": {"status": status.value}})

        uploaded_script_id = script_doc.get("uploadedScriptId")
        if uploaded_script_id:
            from app.domain.models.common import UploadStatus
            final_status = UploadStatus.IN_REVIEW if has_flagged else UploadStatus.EVALUATED
            UploadedScriptRepository().update_one(
                uploaded_script_id, {"$set": {"uploadStatus": final_status.value}}
            )
