# SwipeVault

Private, self-hosted affiliate creative library for discovering offers, ingesting vendor-authorized email swipes (TXT, HTML, PDF, DOCX, ZIP), preserving original assets and source provenance, deduplicating and versioning email copy, and reviewing swipes for internal newsletter campaigns.

- **Status:** Phase 0 (Foundation) & Phase 1 (Manual Swipe Library MVP) complete
- **Stack:** Python 3.12 · FastAPI · PostgreSQL 16 (`pg_trgm` + `TSVECTOR`) · SQLAlchemy 2.0 · Alembic · Redis 7 · RQ · React 18 · TypeScript · Vite · Tailwind CSS · Docker Compose
- **Default local port:** `http://127.0.0.1:2100` (single-origin Nginx reverse proxy; PostgreSQL and Redis are not exposed to the host)

## Quick Start (Docker Compose)

```powershell
# 1. Start the full stack (PostgreSQL, Redis, API + Alembic migrations, Worker, Frontend)
docker compose up --build -d --wait

# 2. Verify health checks
curl http://127.0.0.1:2100/api/v1/health/live
curl http://127.0.0.1:2100/api/v1/health/ready
```

Open `http://127.0.0.1:2100` and sign in with the development bootstrap credentials (override in `.env` before any shared/LAN use):
- **Email:** `admin@swipevault.local`
- **Password:** `ChangeMe-SwipeVault-2026!`

## Running Tests & Linters

```powershell
# Backend linter & integration test suite (runs inside the api container against PostgreSQL 16)
docker compose exec api ruff check app tests alembic
docker compose exec api pytest -v

# Frontend typecheck, unit tests, and production bundle
cd frontend
npm run typecheck
npm test
npm run build
```

## Repository Structure

```text
SwipeVault/
  PRD.md                  # Full product requirements & acceptance criteria (AC-01..AC-15)
  MILESTONES.md           # Phase & acceptance criteria tracker
  README.md               # Quick start & commands
  AGENTS.md               # Agent guardrails & architectural invariants
  .env.example            # Environment variable template (no production secrets)
  compose.yaml            # Docker Compose deployment (private DB/Redis)
  backend/                # FastAPI REST API, Alembic migrations, RQ worker, extraction adapters
  frontend/               # React + TypeScript + Vite + Tailwind dashboard + Nginx config
  fixtures/               # Synthetic CSV, TXT, and HTML fixtures for testing
  docs/                   # Architecture, REST API contract, threat model, deployment, testing, ADRs
  scripts/                # Backup and restore scripts for PostgreSQL + private assets
```

## Documentation

- [Milestone Tracker](MILESTONES.md)
- [REST API Contract](docs/api.md)
- [Architecture Overview](docs/architecture.md)
- [Threat Model & Security Controls](docs/threat-model.md)
- [Deployment, Backup & Restore](docs/deployment.md)
- [Testing Guide](docs/testing.md)
- [ADR 0001 — Foundation & Manual Swipe Library](docs/adr/0001-foundation-and-mvp.md)
