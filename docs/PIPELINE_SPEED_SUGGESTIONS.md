# Full pipeline speed – suggestions to reduce 5–6 minutes

The full pipeline for a multi-page script is roughly:

1. **PDF → images** (in-process)
2. **OCR** – N × Vision API calls (one per page), run in parallel
3. **Aggregate** – wait for all pages, then one task
4. **Segmentation** – one LLM call on full OCR text
5. **Prepare script** – DB + fan-out
6. **Evaluation** – M × `evaluate_question` in parallel; each question does **3 sequential LLM calls** when `USE_MERGED_AGENTS=true` (default): rubric → scoring+consistency → feedback+explainability. Set `USE_MERGED_AGENTS=false` for legacy 5-agent flow.

Below are **concrete suggestions** to reduce end-to-end time, in order of impact vs effort.

---

## 0. Merged agents (implemented)

- **Effect:** Evaluation uses **3 LLM calls per question** (default) instead of 5: rubric → scoring+consistency → feedback+explainability.
- **Config:** `USE_MERGED_AGENTS=true` (default). Set to `false` for legacy 5-agent flow.

---

## 1. Run more Celery workers / higher concurrency (high impact)

- **Current:** One worker process with default concurrency (often = CPU count), serving both `ocr` and `evaluation` queues.
- **Effect:** Each worker evaluates different questions in parallel. Same per-question time, but higher throughput. Set `CELERY_WORKER_CONCURRENCY=8` (default 4) in `.env`.
- **Options:**
  - **A. run_celery.sh (recommended)**  
    ```bash
    CELERY_WORKER_CONCURRENCY=8 ./run_celery.sh
    ```
  - **B. Single worker, higher concurrency**  
    ```bash
    celery -A celery_app.celery worker -Q ocr,evaluation,default -l info --concurrency=12
    ```
    (Use a number that fits your machine and API rate limits.)
  - **C. Separate workers per queue**  
    Run two workers so OCR and evaluation don’t compete:
    ```bash
    celery -A celery_app.celery worker -Q ocr -l info --concurrency=8 &
    celery -A celery_app.celery worker -Q evaluation -l info --concurrency=8 &
    ```
  - **D. Multiple machines:** Run more workers on more machines, all pointing at the same broker/backend.

---

## 2. Use a faster model for evaluation (high impact)

- **Current:** Evaluation uses `OPENAI_MODEL` (default `gpt-4o`), which is accurate but slower.
- **Change:** Use a faster model for evaluation only (segmentation already uses `gpt-4o-mini`):
  ```bash
  OPENAI_MODEL=gpt-4o-mini
  ```
  In `.env` (or export before starting the app).
- **Trade-off:** Slightly lower quality possible on complex rubrics; latency and cost drop noticeably.

---

## 3. Lower OCR DPI (medium impact, for many pages)

- **Current:** `OCR_DPI=150` (configurable in config / env).
- **Change:** Reduce to 120 for answer scripts where handwriting is readable:
  ```bash
  OCR_DPI=120
  ```
- **Effect:** Smaller images → faster PDF→image conversion and faster Vision API per page. Slight risk for very faint handwriting.

---

## 4. Segmentation prompt size (medium impact)

- **OCR:** Full OCR text is sent by default (`SEGMENTATION_MAX_OCR_CHARS=0`). Do not set a cap if you need all answers from the full script; truncation can drop answers that appear later in the script.
- **Question text in prompt:** Each question’s text is truncated to **500 characters** in the segmentation prompt (`SEGMENTATION_MAX_QUESTION_TEXT_CHARS`, default 500). This only shortens the question description sent to the model; it does not remove any OCR/content. Set to `0` to send full question text.
- **Max response tokens:** `OPENAI_SEGMENTATION_MAX_TOKENS` defaults to **8192** so the full mapping is not truncated.

---

## 5. Reduce max tokens for evaluation agents (medium impact)

- **Current:** `OPENAI_EVALUATION_MAX_TOKENS=2048` per agent (feedback, explainability, etc.).
- **Change:** Shorten responses so each call finishes sooner:
  ```bash
  OPENAI_EVALUATION_MAX_TOKENS=1024
  ```
  Or 1536. May truncate very long feedback; usually still enough for useful output.

---

## 6. Segmentation max tokens

- **Default:** `OPENAI_SEGMENTATION_MAX_TOKENS=8192` so the full answer mapping is returned. Lower only if you accept possible truncation.

---

## 7. Shorter aggregate countdown (small impact)

- **Current:** `aggregate_pages` is scheduled with `countdown=45` after dispatching OCR tasks.
- **Effect:** If OCR finishes in e.g. 60 s, aggregation still waits 45 s before the first check. For fast OCR, a smaller countdown (e.g. 20–30) can save a few seconds. Implemented in `backend/app/tasks/ocr.py` in `convert_pdf_to_images`; reduce the `countdown` value passed to `aggregate_pages.apply_async(..., countdown=...)`.

---

## 8. Optional: Skip or shorten explainability (config-driven, future)

- **Current:** Every question runs 5 agents: rubric → scoring → consistency → feedback → explainability.
- **Idea:** Add a config flag to skip explainability (or run it async / in background) for “fast mode”. Would require a small code change and a setting (e.g. `EVALUATION_SKIP_EXPLAINABILITY=true`). Explainability is useful for review but not required for a score.

---

## 9. Ensure MongoDB/Redis are local or low-latency

- If MongoDB or Redis are remote (e.g. Atlas in another region), every task pays network latency. Prefer same region / same VPC or local instances for workers to cut DB/Redis round-trips.

---

## Quick checklist (minimal config + process changes)

| Action | Where | Effect |
|--------|--------|--------|
| `OPENAI_MODEL=gpt-4o-mini` | `.env` | Faster evaluation (main gain). |
| `OPENAI_EVALUATION_MAX_TOKENS=1024` | `.env` | Shorter agent replies. |
| `SEGMENTATION_MAX_OCR_CHARS=80000` | `.env` | Faster segmentation on long scripts. |
| `OCR_DPI=120` | `.env` | Faster OCR for multi-page PDFs. |
| Separate Celery workers for `ocr` vs `evaluation,default` | `run.sh` or process manager | Better parallelism, less queueing. |
| `--concurrency=8` (or higher) per worker | Celery CLI | More parallel tasks per process. |

Start with **more concurrency / separate workers** and **OPENAI_MODEL=gpt-4o-mini**; then tune DPI, token caps, and segmentation length based on your typical scripts and quality requirements.
