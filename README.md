# Agentic Assessment Engine

**Production-grade autonomous descriptive-answer evaluation platform** for educational institutions and enterprises. Built with a 3-stage async pipeline powered by LLM agents, OCR, and a modern React dashboard.

Built by [Makonis.ai](https://makonis.ai)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite + TS)                      │
│  Login ─── Dashboard ─── Upload ─── OCR Review ─── Evaluation ─── Review │
└──────────────────┬───────────────────────────────────────────────────────┘
                   │  REST API (JWT Auth)
┌──────────────────▼───────────────────────────────────────────────────────┐
│                        FLASK API (Blueprints)                            │
│  /auth  ─── /uploads  ─── /ocr  ─── /evaluation  ─── /dashboard         │
└─────┬────────────┬────────────┬──────────────────────────────────────────┘
      │            │            │
      ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────────────────────────────────────────┐
│  MongoDB │ │  Redis   │ │              CELERY WORKERS                   │
│  (Motor) │ │ (Cache/  │ │                                              │
│          │ │  Broker) │ │  Queue: ocr          Queue: evaluation       │
│          │ │          │ │  ┌────────────┐      ┌────────────────────┐  │
│          │ │          │ │  │ PDF Split  │      │ RubricGrounding    │  │
│          │ │          │ │  │ OCR Pages  │      │ Scoring (per crit) │  │
│          │ │          │ │  │ Aggregate  │      │ Consistency Audit  │  │
│          │ │          │ │  │ Segment    │      │ Feedback Gen       │  │
│          │ │          │ │  │  (LLM)     │      │ Explainability     │  │
│          │ │          │ │  └────────────┘      └────────────────────┘  │
└──────────┘ └──────────┘ └──────────────────────────────────────────────┘
                                    │
                          ┌─────────▼─────────┐
                          │  Object Storage   │
                          │  (Local / MinIO / │
                          │   AWS S3)         │
                          └───────────────────┘
```

## 3-Stage Async Pipeline

| Stage | Queue | Description |
|-------|-------|-------------|
| **1. File Ingestion** | `default` | MIME validation, virus scan hook, object storage upload, `UploadedScript` creation |
| **2. OCR + Segmentation** | `ocr` | PDF→images, per-page OCR via **OpenAI GPT-4o Vision**, quality scoring, text aggregation, LLM-based answer segmentation |
| **3. Evaluation** | `evaluation` | Per-question: rubric grounding → criterion scoring → consistency audit → feedback generation → explainability audit trail |

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend API | Flask (blueprints + application factory) |
| Database | MongoDB (Motor async driver) |
| Cache / Broker | Redis |
| Task Queue | Celery 5.x |
| Object Storage | Local filesystem (dev) / S3-compatible (prod) |
| LLM + OCR | **OpenAI API (GPT-4o)** — powers OCR (Vision), segmentation, and all evaluation agents |
| Frontend | React 18 + Vite + TypeScript + TailwindCSS |
| Auth | JWT + refresh tokens + RBAC |
| Containerization | Docker + Docker Compose |
| Observability | JSON structured logging + Prometheus metrics |

---

## Project Structure

```
Assessment Engine/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py              # Pydantic Settings (all env vars)
│   │   ├── extensions.py          # Flask extension singletons
│   │   ├── factory.py             # Application factory
│   │   ├── domain/
│   │   │   ├── models/            # Pydantic domain models
│   │   │   │   ├── common.py      # Enums, value objects
│   │   │   │   ├── upload.py      # UploadedScript
│   │   │   │   ├── ocr.py         # OCRPageResult, SegmentationResult
│   │   │   │   ├── script.py      # Script (post-segmentation)
│   │   │   │   ├── evaluation.py  # Full evaluation pipeline models
│   │   │   │   ├── exam.py        # Exam, Question, Rubric definitions
│   │   │   │   └── user.py        # User model
│   │   │   ├── ports/             # Protocol interfaces
│   │   │   │   ├── storage.py     # StorageProvider protocol
│   │   │   │   ├── ocr.py         # OCRProvider protocol + OCRResult
│   │   │   │   └── llm.py         # LLMGateway protocol
│   │   │   └── events/            # Typed domain events
│   │   ├── infrastructure/
│   │   │   ├── storage/           # Local + S3 implementations
│   │   │   ├── ocr/               # OpenAI Vision OCR (GPT-4o)
│   │   │   ├── llm/               # OpenAI gateway (text + vision)
│   │   │   ├── db/                # MongoDB repositories (Motor)
│   │   │   └── cache/             # Redis cache layer
│   │   ├── agents/                # All 6 evaluation pipeline agents
│   │   │   ├── base.py            # BaseAgent (generic, telemetry)
│   │   │   ├── segmentation.py    # OCR text → Q&A mapping
│   │   │   ├── rubric_grounding.py
│   │   │   ├── scoring.py         # Per-criterion scoring
│   │   │   ├── consistency.py     # Cross-criterion audit
│   │   │   ├── feedback.py        # Student feedback generation
│   │   │   └── explainability.py  # Audit trail for reviewers
│   │   ├── tasks/                 # Celery task graph
│   │   │   ├── ocr.py             # OCR pipeline tasks
│   │   │   └── evaluation.py      # Evaluation pipeline tasks
│   │   ├── api/v1/                # Flask blueprints
│   │   │   ├── auth.py            # JWT login/register/refresh
│   │   │   ├── upload.py          # File upload endpoints
│   │   │   ├── ocr.py             # OCR review endpoints
│   │   │   ├── evaluation.py      # Evaluation results + overrides
│   │   │   └── dashboard.py       # KPIs + activity feed
│   │   ├── api/middleware/
│   │   │   ├── auth.py            # JWT + RBAC decorator
│   │   │   └── errors.py          # Centralized error handlers
│   │   └── common/
│   │       ├── exceptions.py      # Exception hierarchy
│   │       └── observability.py   # Prometheus metrics + logging
│   ├── celery_app.py              # Celery application entry
│   ├── wsgi.py                    # WSGI entry point
│   ├── requirements.txt
│   ├── Dockerfile                 # Multi-stage: api / celery-ocr / celery-eval
│   ├── pytest.ini
│   └── tests/
│       └── unit/                  # Mocked agent, API, infra tests
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ui/                # GlassCard, StatusBadge, KPICard, etc.
│   │   │   └── dashboard/         # AgentStatusCard, PipelineTracker, etc.
│   │   ├── pages/                 # Dashboard, Upload, OCR Review, Evaluation
│   │   ├── context/               # AuthContext (JWT state management)
│   │   ├── services/              # Axios API client
│   │   ├── types/                 # Full TypeScript type definitions
│   │   ├── styles/                # TailwindCSS globals + design tokens
│   │   └── tests/                 # Vitest component tests
│   ├── package.json
│   ├── vite.config.ts
│   ├── vitest.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml             # Full dev stack
├── .env.example
├── .gitignore
└── README.md
```

---

## Quick Start

### Prerequisites

- Docker & Docker Compose (or Python 3.12 + Node 20 for local dev)
- An OpenAI API key (GPT-4o — used for OCR, segmentation, and all evaluation agents)

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY and OPENAI_API_KEY at minimum
```

### 2. Start all services

```bash
docker compose up --build
```

This starts:
- **MongoDB** on port `27017`
- **Redis** on port `6379`
- **MinIO** on ports `9000` (API) / `9001` (console)
- **Flask API** on port `5000`
- **Celery OCR worker** (queue: `ocr`, `default`)
- **Celery Evaluation worker** (queue: `evaluation`)
- **Frontend (Nginx)** on port `3000`

### 3. Access the application

- **Frontend**: http://localhost:3000
- **API Swagger**: http://localhost:5000/api/docs/swagger
- **MinIO Console**: http://localhost:9001

### 4. Create a user (API)

```bash
curl -X POST http://localhost:5000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@institution.edu",
    "password": "securepassword123",
    "fullName": "Admin User",
    "institutionId": "inst_001",
    "role": "INSTITUTION_ADMIN"
  }'
```

---

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start MongoDB and Redis locally, then:
export SECRET_KEY="dev-secret-key-at-least-32-characters-long"
export OPENAI_API_KEY="sk-your-openai-key"

# API server
python wsgi.py

# Celery OCR worker
celery -A celery_app.celery worker --queues ocr,default --loglevel info

# Celery Evaluation worker
celery -A celery_app.celery worker --queues evaluation --loglevel info
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
# Backend
cd backend
pytest

# Frontend
cd frontend
npm test
```

---

## Environment Variables

All configuration is via environment variables (12-Factor). See `.env.example` for the complete list.

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Application secret (min 32 chars) | *required* |
| `ENVIRONMENT` | `development` / `staging` / `production` | `development` |
| `MONGO_URI` | MongoDB connection string | `mongodb://localhost:27017` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery broker URL | `redis://localhost:6379/1` |
| `STORAGE_PROVIDER` | `local` or `s3` | `local` |
| `OPENAI_API_KEY` | OpenAI API key (powers OCR + all agents) | *required* |
| `OPENAI_MODEL` | OpenAI model name | `gpt-4o` |
| `OPENAI_TEMPERATURE` | Sampling temperature | `0.1` |
| `MAX_UPLOAD_SIZE_MB` | Max file upload size | `50` |
| `MAX_PAGES_PER_SCRIPT` | Max pages per uploaded script | `40` |

---

## RBAC Roles

| Role | Permissions |
|---|---|
| `SUPER_ADMIN` | Full system access |
| `INSTITUTION_ADMIN` | Manage exams, users, view all scripts within institution |
| `EXAMINER` | Upload scripts, configure exams, trigger evaluations |
| `REVIEWER` | Review evaluations, apply score overrides |
| `STUDENT` | View own results (read-only) |

---

## Evaluation Agent Pipeline

Each question is evaluated by 5 specialized OpenAI-powered agents in sequence:

| Agent | Role Codename | Function |
|---|---|---|
| **RubricGroundingAgent** | `RubricAnalyst-1` | Decomposes rubric criteria into discrete, testable evidence points. Detects ambiguous criteria. Acts as the "rubric compiler" for downstream scoring. |
| **ScoringAgent** | `Examiner-1` | Scores the answer against ONE criterion at a time with exact justification quotes. Enforces 0.25 granularity, partial credit, and strict evidence-based marking. |
| **ConsistencyAgent** | `ChiefExaminer-1` | Adversarial audit of all criterion scores. Checks cross-criterion coherence, score-justification alignment, generosity/harshness bias, and double-counting. Has override authority. |
| **FeedbackAgent** | `Coach-1` | Generates pedagogically sound, growth-oriented feedback. Tone-matched to performance level. Every strength is evidence-based, every improvement is actionable. |
| **ExplainabilityAgent** | `Auditor-1` | Produces legal-grade audit trails. Chain-of-reasoning narrative, uncertainty mapping, and deterministic review recommendations (AUTO_APPROVED / NEEDS_REVIEW / MUST_REVIEW). |

All agents use OpenAI's `response_format: json_object` for reliable structured output. Failed JSON parsing triggers automatic repair prompts (max 2 retries).

---

## Observability

### Prometheus Metrics

```
aae_ocr_processing_duration_seconds{provider, status}
aae_ocr_confidence_score{institution_id}
aae_evaluation_duration_seconds{agent_name, status}
aae_llm_tokens_used_total{agent_name, model}
aae_llm_latency_seconds{agent_name}
aae_tasks_total{queue, status}
```

### Structured JSON Logging

Every log entry includes: `traceId`, `institutionId`, `scriptId`, `agentName`, `durationMs`

---

## API Endpoints

### Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login (returns JWT + refresh) |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| GET | `/api/v1/auth/me` | Current user info |

### Uploads
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/uploads/` | Upload answer scripts (multipart) |
| GET | `/api/v1/uploads/` | List uploaded scripts |
| GET | `/api/v1/uploads/:id` | Get upload details |

### OCR Review
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/ocr/scripts/:id/pages` | List OCR page results |
| GET | `/api/v1/ocr/scripts/:id/pages/:n` | Get specific page |
| PUT | `/api/v1/ocr/scripts/:id/pages/:n` | Correct extracted text |
| GET | `/api/v1/ocr/scripts/:id/signed-url` | Get signed file URL |
| POST | `/api/v1/ocr/scripts/:id/re-segment` | Re-run segmentation |

### Evaluation
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/evaluation/scripts/:id` | All results for a script |
| GET | `/api/v1/evaluation/results/:id` | Single result detail |
| POST | `/api/v1/evaluation/results/:id/override` | Reviewer score override |
| POST | `/api/v1/evaluation/scripts/:id/re-evaluate` | Trigger re-evaluation |

### Dashboard
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/dashboard/kpis` | KPI metrics |
| GET | `/api/v1/dashboard/recent-activity` | Activity feed |
| GET | `/api/v1/dashboard/review-queue` | Pending reviews |

---

## Design Principles

- **Clean Architecture**: Domain → Application → Infrastructure layers with no leakage
- **Hexagonal / Ports & Adapters**: All external services behind protocol interfaces
- **Event-Driven**: All async work flows through typed Celery tasks
- **Pydantic Everywhere**: Every LLM response, API payload, and config is typed
- **12-Factor App**: Env-based config, stateless workers, ephemeral filesystems
- **Idempotent Tasks**: Composite key deduplication for every Celery task
- **Zero Raw File URLs**: All asset access via signed, time-limited URLs
- **Multi-Tenant Isolation**: `institutionId` scoped in every DB query

---

## Security

- Server-side MIME validation via `python-magic`
- UUID file renaming (original names stored in metadata only)
- JWT access tokens (15min) + refresh tokens (7d)
- RBAC role enforcement on every endpoint
- Rate limiting with `429 + Retry-After` headers
- No PII in LLM prompts (stripped before sending)
- Audit log for all LLM calls
- Signed URLs for all file access (15min expiry)

---

## License

Proprietary — Makonis.ai. All rights reserved.
