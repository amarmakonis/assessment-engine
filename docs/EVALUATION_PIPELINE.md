# Full Evaluation Pipeline – Flow and File Reference

This document explains the **entire pipeline** from answer-script upload to evaluation results: where each step runs, what it does, and which files implement it. The terminal logs (e.g. `segment_answers`, `prepare_script`, `evaluate_question`, agent names) map directly to this flow.

---

## 1. Pipeline overview (end-to-end)

```
[User uploads answer PDF]
        ↓
  convert_pdf_to_images (OCR queue)
        ↓
  process_page × N pages (OCR queue)
        ↓
  aggregate_pages (OCR queue, after countdown)
        ↓
  segment_answers (OCR queue)
        ↓
  prepare_script (evaluation queue)
        ↓
  evaluate_question × M questions (evaluation queue)
        ↓
  [Script COMPLETE / IN_REVIEW; Upload EVALUATED / IN_REVIEW]
```

- **OCR queue** (`ocr`): PDF → images → per-page OCR → aggregation → segmentation.
- **Evaluation queue** (`evaluation`): one Script document → per-question evaluation (5 agents) → completion check.

---

## 2. Step-by-step flow with files and logs

### 2.1 Upload and OCR (before the segment_answers log)

| Step | What happens | File | Log / trigger |
|------|----------------|------|----------------|
| **Upload API** | User uploads PDF; API creates `UploadedScript`, stores file, calls **convert_pdf_to_images** | `backend/app/api/v1/upload.py` (or files API) | HTTP POST upload |
| **convert_pdf_to_images** | Convert PDF to images (pdf2image at `OCR_DPI`), fan-out **process_page** per page, schedule **aggregate_pages** with countdown=28s | `backend/app/tasks/ocr.py` | `group(page_tasks).apply_async()` + `aggregate_pages.apply_async(..., countdown=28)` |
| **process_page** | One page: OpenAI Vision OCR via `extract_page_text`, save to `OCRPageResultRepository` | `backend/app/tasks/ocr.py` | One task per page; "OCR page N extracted via OpenAI Vision" |
| **aggregate_pages** | Redis lock per script; wait until all pages in DB (retries every 10s); concatenate text; set `uploadStatus=OCR_COMPLETE`; call **segment_answers** | `backend/app/tasks/ocr.py` | "aggregate_pages: set uploadStatus=OCR_COMPLETE for … dispatching segment_answers" |

- **OCR extraction**: `backend/app/infrastructure/ocr.py` (e.g. `extract_page_text` used by `process_page`).
- **Repositories**: `backend/app/infrastructure/db/repositories.py` — `UploadedScriptRepository`, `OCRPageResultRepository`, etc.

---

### 2.2 Segmentation (OCR → question-level answers)

| Step | What happens | File | Log you see |
|------|----------------|------|--------------|
| **segment_answers** | Load script + exam; optionally cap/truncate OCR text and question text from config; call **SegmentationAgent**; persist segmentation; set `uploadStatus=SEGMENTED`; call **prepare_script** with `(uploaded_script_id, seg_dict, avg_confidence, quality_flags, trace_id)` | `backend/app/tasks/ocr.py` | `segmentation_agent completed` → `segment_answers: set uploadStatus=SEGMENTED for … dispatching prepare_script` → `Task … segment_answers … succeeded in …s` |
| **SegmentationAgent** | Builds prompt (exam questions + full OCR text); calls OpenAI; parses JSON mapping `questionId` → `answerText` (and unmappedText, notes) | `backend/app/agents/segmentation.py` | `segmentation_agent completed` (from base agent logging) |

- **segment_answers** uses **SegmentationAgent** from `backend/app/agents/segmentation.py`.
- **prepare_script** is invoked from `backend/app/tasks/ocr.py`:  
  `prepare_script.delay(uploaded_script_id, seg_dict, avg_confidence, quality_flags, trace_id)`.

---

### 2.3 Prepare script and fan-out evaluation

| Step | What happens | File | Log you see |
|------|----------------|------|--------------|
| **prepare_script** | Load `UploadedScript` + Exam; build one answer per exam question from segmentation (`answerText` or empty); create **Script** doc (status EVALUATING); set upload status to EVALUATING; insert **no-attempt** evaluation results (0 score) for questions with no answer text; fan-out **evaluate_question** for each question that has answer text | `backend/app/tasks/evaluation.py` | `Task … prepare_script … received` → `Inserted no-attempt result for question q23 (script …)` (etc.) → `Task … prepare_script … succeeded` |
| **evaluate_question** (× M) | One task per (script, question) that has answer text. Runs the 5 agents in sequence; inserts one **EvaluationResult**; calls **_check_script_completion** | `backend/app/tasks/evaluation.py` | `Task … evaluate_question … received` (many) → agent logs (below) → `Evaluation complete for script=… question=qX` → `Task … evaluate_question … succeeded` |

- **prepare_script** creates the Script in MongoDB via `ScriptRepository` and inserts no-attempt rows via `EvaluationResultRepository` (see `backend/app/tasks/evaluation.py`). The "Inserted no-attempt result for question q23 (script …)" lines in your log come from here (q23, q31, q32, q33 had no answer text).
- **evaluate_question** is applied as a Celery `group`: one task per answered question, all on the **evaluation** queue.

---

### 2.4 Per-question evaluation (5 agents inside evaluate_question)

For each **evaluate_question** task, the following agents run **in order** in the same process. All live under `backend/app/agents/` and are called from `backend/app/tasks/evaluation.py` inside `evaluate_question`.

| # | Agent | What it does | File | Log you see |
|---|--------|----------------|------|--------------|
| 1 | **RubricGroundingAgent** | Takes question text + rubric criteria; produces a "grounded" rubric (criteria with clear descriptions and marks) so total matches question’s maxMarks | `backend/app/agents/rubric_grounding.py` | `rubric_grounding_agent starting execution` → `rubric_grounding_agent completed` |
| 2 | **ScoringAgent** | For each criterion, scores the student’s answer (marks per criterion). For no-attempt/short answers it may use a batch path | `backend/app/agents/scoring.py` | `scoring_agent starting execution` or `scoring_agent batch starting` → `scoring_agent completed` |
| 3 | **ConsistencyAgent** | Checks scores across criteria for consistency and can adjust; outputs final_scores and total_score | `backend/app/agents/consistency.py` | `consistency_agent starting execution` → `consistency_agent completed` |
| 4 | **FeedbackAgent** | Generates textual feedback for the student based on question, answer, and final scores | `backend/app/agents/feedback.py` | `feedback_agent starting execution` → `feedback_agent completed` |
| 5 | **ExplainabilityAgent** | Explains scoring and sets **reviewRecommendation** (e.g. AUTO_APPROVED, IN_REVIEW) | `backend/app/agents/explainability.py` | `explainability_agent starting execution` → `explainability_agent completed` |

- After the 5 agents, `evaluate_question` builds one **EvaluationResult** document (grounded rubric, criterion scores, consistency audit, feedback, explainability, totalScore, maxPossibleScore, reviewRecommendation, status=COMPLETE) and inserts it via **EvaluationResultRepository**.
- Then it calls **_check_script_completion(script_id)**.

---

### 2.5 Script completion and upload status

| Step | What happens | File | Log you see |
|------|----------------|------|--------------|
| **_check_script_completion** | Counts evaluation results for the script; when every question has a COMPLETE result, sets Script **status** to COMPLETE or IN_REVIEW (if any answer was flagged/no-attempt); sets **UploadedScript** `uploadStatus` to EVALUATED or IN_REVIEW | `backend/app/tasks/evaluation.py` (function `_check_script_completion`) | No dedicated log line; happens after each `Evaluation complete for script=… question=qX`. When the last question completes, script and upload status are updated. |

- **FLAGGED** is reserved for pipeline failures (e.g. segmentation failed). When evaluation completes but some answers need human review (e.g. no-attempt), status is **IN_REVIEW**, not FLAGGED.

---

## 3. File reference summary

| Component | File(s) |
|-----------|---------|
| OCR pipeline tasks | `backend/app/tasks/ocr.py` — `convert_pdf_to_images`, `process_page`, `aggregate_pages`, `segment_answers` |
| Evaluation pipeline tasks | `backend/app/tasks/evaluation.py` — `prepare_script`, `evaluate_question`, `_check_script_completion` |
| Segmentation agent | `backend/app/agents/segmentation.py` |
| Rubric grounding | `backend/app/agents/rubric_grounding.py` |
| Scoring | `backend/app/agents/scoring.py` |
| Consistency | `backend/app/agents/consistency.py` |
| Feedback | `backend/app/agents/feedback.py` |
| Explainability | `backend/app/agents/explainability.py` |
| Agent base / shared behaviour | `backend/app/agents/base.py` (if present) |
| Config (models, DPI, limits) | `backend/app/config.py` |
| Repositories (DB access) | `backend/app/infrastructure/db/repositories.py` |
| OCR extraction (OpenAI Vision) | `backend/app/infrastructure/ocr.py` |
| Upload API (trigger) | `backend/app/api/v1/upload.py` (or files API that starts the pipeline) |

---

## 4. How your terminal logs map to this flow

- **GET /api/v1/uploads/** — Frontend polling the uploads list; not part of the pipeline logic.
- **segmentation_agent completed** — From `segment_answers` in `ocr.py` using `SegmentationAgent` in `segmentation.py`.
- **segment_answers: set uploadStatus=SEGMENTED for …, dispatching prepare_script** — End of `segment_answers` in `ocr.py`; next step is `prepare_script` in `evaluation.py`.
- **Task … prepare_script … received** / **succeeded** — `prepare_script` in `evaluation.py`.
- **Inserted no-attempt result for question q23 (script …)** — `prepare_script` in `evaluation.py` inserting zero-score evaluation results for unattempted questions.
- **Task … evaluate_question … received** — One task per question with answer text; logic in `evaluation.py`.
- **rubric_grounding_agent … / scoring_agent … / consistency_agent … / feedback_agent … / explainability_agent …** — The 5 agents run inside each `evaluate_question` task; implementations in `backend/app/agents/*.py`.
- **Evaluation complete for script=… question=qX** — End of one `evaluate_question` task in `evaluation.py`; after the last question, `_check_script_completion` updates script and upload status.

This is the full evaluation pipeline and where each part of the flow is implemented in the project.
