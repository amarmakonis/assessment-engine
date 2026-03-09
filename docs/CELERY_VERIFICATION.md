# How to Verify Celery and Async Features Are Working

This guide helps you confirm that Redis, Celery workers, and the async flows (exam creation, OCR, evaluation) are running and working.

---

## 1. Prerequisites

- **Redis** must be running (Celery uses it as broker and result backend).
- **`.env`** (project root or `backend/`) must have:
  - `USE_CELERY_REDIS=true`
  - `REDIS_URL=redis://localhost:6379/0`
  - `CELERY_BROKER_URL=redis://localhost:6379/1`
  - `CELERY_RESULT_BACKEND=redis://localhost:6379/2`

---

## 2. Start Redis (if not already running)

**Linux / macOS (system Redis):**
```bash
# Ubuntu/Debian
sudo systemctl start redis-server

# macOS (Homebrew)
brew services start redis

# Or run in foreground to see logs
redis-server
```

**Docker:**
```bash
docker run -d -p 6379:6379 --name redis redis:alpine
```

**Check Redis is up:**
```bash
redis-cli ping
# Should reply: PONG
```

---

## 3. Start the App with Celery

From the **project root**:

```bash
# Ensure .env has USE_CELERY_REDIS=true, then:
./run.sh
```

This will:
- Start Flask on port 5000
- Start **two Celery workers**: one for `ocr,default` (exam creation + OCR), one for `evaluation`
- Start the frontend on port 3000

If Redis is not running, `run.sh` will exit with an error when `USE_CELERY_REDIS=true`.

**Or start manually (same effect):**
```bash
cd backend
source venv/bin/activate   # or venv\Scripts\activate on Windows

# Terminal 1: Flask
python -m flask run --host=0.0.0.0 --port=5000

# Terminal 2: Celery (OCR + exam creation)
celery -A celery_app worker -Q ocr,default -l info --concurrency=4

# Terminal 3: Celery (evaluation)
celery -A celery_app worker -Q evaluation -l info --concurrency=4

# Terminal 4: Frontend
cd frontend && npm run dev
```

---

## 4. Verify Async Exam Creation

1. Open the app: **http://localhost:3000**
2. Log in and go to **Exams** → **New Exam** → **Upload Documents**.
3. Upload a **question paper** (PDF/DOCX). Optionally choose “Generate detailed rubrics with AI” or “Use generic rubrics only”.
4. Click **Extract & Create Exam**.

**If Celery is working:**
- You see a toast: **“Creating exam… This may take 1–2 minutes.”**
- The request returns immediately (no long wait).
- After 30–90 seconds the exam appears in the list and the toast updates to success.

**If Celery is NOT used** (`USE_CELERY_REDIS=false`):
- The browser waits for the full extraction (1–3 min) then shows success.

**Check Celery logs (worker that has `default` queue):**
You should see something like:
```
[tasks]
  . app.tasks.exam.create_exam_from_upload
  . app.tasks.ocr.ingest_file
  ...
Received task: app.tasks.exam.create_exam_from_upload[xxx]
Task app.tasks.exam.create_exam_from_upload[xxx] succeeded in X.Xs
```

---

## 5. Verify OCR + Evaluation (Answer Scripts)

1. Create an exam (or use an existing one).
2. Go to **Upload** and upload an **answer script** (PDF/images) for that exam.

**If Celery is working:**
- Upload accepts quickly.
- Script status moves through: Uploaded → OCR / Segmented → Evaluating → Evaluated (or In Review).
- In the Celery **ocr** worker logs you see `ingest_file`, `aggregate_pages`, `segment_answers`, etc.
- In the **evaluation** worker logs you see `evaluate_question` tasks.

**If Celery is NOT used:**
- The upload request runs OCR and evaluation in-process and can take several minutes or time out.

---

## 6. Quick Checklist

| Check | How |
|-------|-----|
| Redis running | `redis-cli ping` → `PONG` |
| USE_CELERY_REDIS | `true` in `.env` |
| Celery workers up | Two processes: `-Q ocr,default` and `-Q evaluation`; no errors in terminal |
| Exam creation async | Upload question paper → toast “Creating exam…” → exam appears after 1–2 min |
| Exam creation task | In worker logs: `create_exam_from_upload` received and `succeeded` |
| Answer script pipeline | Upload script → status progresses; OCR and evaluation tasks in worker logs |

---

## 7. Troubleshooting

- **“Redis not running on 6379”**  
  Start Redis (see step 2) and ensure nothing else is using port 6379.

- **Exam creation never completes (stuck “Creating exam…”)**  
  - Ensure a worker is consuming the **default** queue:  
    `celery -A celery_app worker -Q ocr,default -l info`
  - Check that worker’s logs for errors (e.g. missing env, MongoDB, or OpenAI key).

- **Tasks not picked up**  
  - Restart workers after changing `.env` or code.  
  - Confirm `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` match in `.env` and that Redis is the same instance.

- **USE_CELERY_REDIS is true but request still slow**  
  - Confirm the **backend** (Flask) process was started **after** setting `USE_CELERY_REDIS=true` in `.env` (or restart Flask so it reloads env).
