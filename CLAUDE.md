# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Система управления строительством** — a multi-tenant construction project management platform with Gantt scheduling, daily foreman reporting, AI-powered construction spec matching, and cost estimation workflows.

## Commands

### Backend

```bash
cd backend

# Development (with log rotation)
python scripts/run_with_weekly_logs.py

# Or directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
pytest

# Run a single test file
pytest tests/test_gantt_builder.py -v

# Run a specific test
pytest tests/test_gantt_builder.py::test_function_name -v

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1
```

### Frontend

```bash
cd frontend

npm run dev        # Development (with weekly log rotation)
npm run build      # Production build
npm run start      # Production server
npm run lint       # ESLint
```

### Docker (full stack)

```bash
docker-compose up -d
docker-compose exec backend alembic upgrade head
```

Services: frontend at `localhost:3000`, backend at `localhost:8000`, API docs at `localhost:8000/docs`.

## Architecture

### Backend (`backend/`)

FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL. Entry point: `app/main.py`.

**Key directories:**
- `app/api/routers/` — 15 route modules, all mounted under `/api` prefix
- `app/models/` — SQLAlchemy ORM models (all exported from `__init__.py`)
- `app/services/` — Business logic; routers stay thin
- `app/core/` — Config (`config.py`), permissions matrix (`permissions.py`), date utils (`date_utils.py`), auth dependencies (`deps.py`)
- `alembic/versions/` — 36 migrations (001–036)
- `tests/` — pytest-asyncio tests (23 files)

**Auth flow:** JWT tokens via PyJWT + bcrypt. `app/api/deps.py` provides `get_current_user` and `require_role()` dependencies injected per-route.

**Task durations** are always in **working days** (Mon–Fri, excluding `holidays` table). All date math goes through `app/core/date_utils.py`.

**Async Excel upload:** POST returns 202 + `job_id`. Client polls `GET /jobs/{id}`. Processing happens in `UploadService`.

**Celery beat schedule:** 22:00 UTC foreman reminders, 07:00 UTC morning escalation + dashboard, hourly escalation check for issues > 48h old.

### Frontend (`frontend/`)

Next.js 15 App Router + React 19 + TypeScript.

**Key files:**
- `lib/api.ts` — typed fetch client + all endpoint definitions
- `lib/types.ts` — domain TypeScript interfaces
- `lib/UserContext.tsx` — global auth state
- `lib/useJobPoller.ts` — polling hook for async job status
- `next.config.ts` — proxies `/api/*` → `http://localhost:8000`

**Routing:** `app/projects/[id]/` houses the main project workspace. Layouts in `app/projects/[id]/layout.tsx` gate access.

### Special Domains

**ENIR** — Russian construction standards hierarchy (collection → section → chapter → paragraph → norms). Used for estimate validation and work composition reference.

**FER** — Federal Estimate Standards. Hybrid search via FTS + vector embeddings (OpenRouter) + reranking. Matching thresholds configured via `RERANK_SCORE_THRESHOLD` and `FER_EXAMPLE_MATCH_THRESHOLD` env vars.

**KTP** (Карточка Технической Подготовки) — AI-generated work preparation cards via `ktp_service.py` using OpenRouter GPT-4o-mini.

### Data Model Conventions

- Soft deletes: `deleted_at` nullable timestamp (never hard-delete records with audit trail)
- Parent task progress is computed from leaf descendants via SQL CTE — not stored
- Role-based access is **per-project**: `project_members.role` ∈ {owner, pm, foreman, supplier, viewer}. Permission matrix: `app/core/permissions.py`
- Task dependencies are a separate M:M table (`task_dependencies`), not a text field

## Environment

Copy `backend/.env.example` to `backend/.env`. Required vars:

```
DATABASE_URL=postgresql+asyncpg://...
SECRET_KEY=<256-bit>
REDIS_URL=redis://localhost:6379/0
OPENROUTER_API_KEY=<key>     # Required for KTP generation and FER vector search
EMAIL_PROVIDER=log            # Options: log | resend | smtp
```

Frontend: `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local`.
