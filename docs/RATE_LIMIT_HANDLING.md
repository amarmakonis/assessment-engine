# Rate Limit Handling — Full Description

This document describes everything implemented in the Assessment Engine to **avoid** and **handle** OpenAI API rate limit errors (HTTP 429 / "rate limit exceeded"). The strategies fall into two categories: **prevention** (throttling, concurrency limits, delays) and **recovery** (automatic retries with backoff).

---

## 1. Automatic Retries at the LLM Layer (Tenacity)

**Where:** `backend/app/infrastructure/llm/gateway.py`  
**Library:** `tenacity` (see `backend/requirements.txt`: `tenacity==9.0.0`)

All direct OpenAI calls go through a single **LLM gateway**. Two methods are decorated with Tenacity retry logic so that **429 (RateLimitError)** and **timeouts (APITimeoutError)** are retried instead of failing immediately.

### 1.1 Chat completions — `complete()`

- **Used by:** Exam extraction, rubric builder, segmentation, evaluation agents (rubric grounding, scoring, feedback, explainability).
- **Retry behaviour:**
  - **Retry on:** `APITimeoutError`, `OpenAIRateLimitError` (429).
  - **Wait between attempts:** `wait_random_exponential(multiplier=1, min=2, max=60)` seconds. So the delay is random and grows (e.g. ~2s, ~4s, ~8s, …), capped at 60 seconds. This spreads load and respects “Retry-After” style backoff.
  - **Stop after:** 5 attempts total. After that, the exception is re-raised (and can be handled by Celery task retry or returned to the client).
- **Code (conceptually):**
  ```python
  @retry(
      retry=retry_if_exception_type((APITimeoutError, OpenAIRateLimitError)),
      wait=wait_random_exponential(multiplier=1, min=2, max=60),
      stop=stop_after_attempt(5),
      reraise=True,
  )
  def complete(self, ...):
      response = self._client.chat.completions.create(...)
  ```

So every chat completion (exam creation, evaluation, segmentation, etc.) **automatically retries on 429** with exponential backoff.

### 1.2 Vision API — `vision_extract_text()`

- **Used by:** OCR (one Vision call per page when the PDF is scanned/handwritten and fast text extraction is insufficient).
- **Retry behaviour:** Same as `complete()` — retry on 429 and timeout, same exponential wait, stop after 5 attempts.

So every Vision request (e.g. per-page OCR) also **retries on rate limit** without the caller having to implement backoff.

---

## 2. Configurable Concurrency and Delays (Prevention)

**Where:** `backend/app/config.py` (and `.env`)

These settings **reduce** how often we hit rate limits by limiting parallelism and adding gaps between requests.

### 2.1 OCR (Vision) — answer script / test OCR

| Config | Default | Purpose |
|--------|--------|--------|
| **`OCR_TEST_MAX_CONCURRENT`** | `2` | Maximum number of Vision requests running at once when processing multiple pages (e.g. PDF → N images). Lower = fewer concurrent calls; set to **1** if you hit 429 often. |
| **`OCR_TEST_DELAY_SECONDS`** | `2.0` | Delay **in seconds between starting each** page request. So with 10 pages and delay 2s, requests are spread over ~18+ seconds instead of all at once. Increase to **5+** for strict free-tier or low RPM limits. |

Comments in config explicitly say: *"use 1 if you hit 429 rate limits"* and *"increase to 5+ for free-tier OpenAI"*.

### 2.2 Evaluation (sync pipeline)

| Config | Default | Purpose |
|--------|--------|--------|
| **`EVALUATION_MAX_WORKERS`** | `5` | In **sync** mode (no Celery), how many questions are evaluated in parallel. Fewer workers = fewer simultaneous chat completion calls. Config description: *"reduce if you hit 429 rate limits"* (e.g. set to 3). |

With Celery, parallelism is controlled by worker concurrency and number of workers; reducing `EVALUATION_MAX_WORKERS` only affects the sync path.

### 2.3 OpenAI client (reference)

| Config | Purpose |
|--------|--------|
| **`OPENAI_MAX_RETRIES`** | Used in the gateway for internal retry logic; Tenacity is configured with a fixed 5 attempts for 429/timeout. |
| **`OPENAI_TIMEOUT_SECONDS`** | Shorter timeouts help fail fast and retry sooner instead of long waits that still end in 429. |

---

## 3. OCR Pipeline Throttling (Prevention)

**Where:**  
- `backend/app/api/v1/ocr.py` (e.g. OCR test endpoint that processes multiple pages)  
- `backend/app/services/sync_pipeline.py` (sync ingest when not using Celery)

When processing **multiple pages** (PDF converted to one image per page):

1. **Concurrency cap:** A thread pool is used with `max_workers = OCR_TEST_MAX_CONCURRENT` (capped between 1 and 3 or 5 in code). So at most that many Vision requests run at the same time.
2. **Delay between submissions:** Before submitting each page (except the first), the code does `time.sleep(delay_sec)` where `delay_sec = OCR_TEST_DELAY_SECONDS`. So requests are staggered instead of fired in one burst.

Example (10 pages, `OCR_TEST_MAX_CONCURRENT=2`, `OCR_TEST_DELAY_SECONDS=2`):  
Pages are submitted in pairs with 2-second gaps, so total time is spread over ~18+ seconds and concurrent requests stay at 2. This keeps the request rate (RPM) under typical limits and **reduces 429s** from OCR.

---

## 4. Celery Task Retries (Recovery)

**Where:**  
- `backend/app/tasks/ocr.py` (ingest_file, process_page, aggregate_pages, segment_answers, prepare_script, etc.)  
- `backend/app/tasks/evaluation.py` (evaluate_question, prepare_script)

If an OpenAI call still fails after the gateway’s Tenacity retries (e.g. 429 persists for 5 attempts), the **Celery task** that made the call can retry the whole task:

- **Mechanism:** `raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)`.
- **Effect:** The task is re-queued and run again after a delay. The delay is **exponential** in the retry number: 10s, 20s, 40s, … (exact formula may vary per task).
- **Result:** Transient 429s can be overcome by retrying later, when the rate limit window may have passed.

So we have **two layers of retry**:  
1. **Per-request** (Tenacity in the gateway): up to 5 attempts with 2–60s backoff.  
2. **Per-task** (Celery): task-level retries with countdown so the entire operation (e.g. “process this page” or “evaluate this question”) is retried later.

---

## 5. Upload Rate Limit (Application-Level Prevention)

**Where:** `backend/app/config.py`

- **Config:** `UPLOAD_RATE_LIMIT: str = "10/minute"`.
- **Intent:** Limit how often upload endpoints can be called (e.g. 10 requests per minute per user or per IP, depending on how it is applied in the app). This prevents a single user or script from triggering a large burst of downstream OpenAI calls (e.g. many exam creations or script uploads) and thus **reduces** the chance of hitting OpenAI’s rate limit.

If your app uses a rate-limiting middleware or decorator that reads this config, it would apply here; otherwise this serves as a documented recommendation for deployment (e.g. Nginx or API gateway limits).

---

## 6. Custom Rate Limit Error (API Response)

**Where:**  
- `backend/app/common/exceptions.py` — defines `RateLimitError` (HTTP 429, code `RATE_LIMITED`).  
- `backend/app/api/middleware/errors.py` — when a `RateLimitError` is raised, the response can set a **`Retry-After`** header (e.g. `retry_after` seconds) so clients know when to retry.

This is used when the **application** itself wants to signal “rate limited” (e.g. your own upload or per-user limits), as opposed to propagating OpenAI’s 429. It keeps behaviour consistent and allows setting a sensible retry-after value.

---

## 7. Summary Table

| Layer | What | How it avoids or handles rate limits |
|-------|------|-------------------------------------|
| **LLM gateway (Tenacity)** | Chat + Vision | Retry on 429 (and timeout) up to 5 times with exponential backoff (2–60s). |
| **Config: OCR** | `OCR_TEST_MAX_CONCURRENT`, `OCR_TEST_DELAY_SECONDS` | Fewer concurrent Vision calls and a delay between each page request → lower RPM. |
| **Config: Evaluation** | `EVALUATION_MAX_WORKERS` | Fewer parallel evaluation (chat) requests in sync mode → lower chance of 429. |
| **OCR pipeline** | Throttling in API + sync_pipeline | Uses the above config: cap concurrency and add delay between page submissions. |
| **Celery tasks** | `self.retry(..., countdown=...)` | Task-level retry with backoff if the gateway still fails after its retries. |
| **Upload limit** | `UPLOAD_RATE_LIMIT` | Config for app-level upload rate limiting to avoid burst traffic. |
| **Errors** | `RateLimitError` + middleware | Consistent 429 response and optional `Retry-After` header for clients. |

Together, these measures **reduce** how often we hit OpenAI rate limits (throttling, concurrency, delays, upload limits) and **recover** when we do (Tenacity retries and Celery task retries).
