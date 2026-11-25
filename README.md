# SwipeVault

Private, self-hosted affiliate creative library for discovering offers, collecting vendor-authorized email swipes (manual upload or permission-aware source scanning across TXT, HTML, PDF, DOCX, ZIP), preserving original assets and source provenance, deduplicating and versioning email copy, reviewing swipes editorially, and preparing brand-specific campaign drafts with optional unsent Listmonk draft export.

- **Status:** Phases 0, 1, 2, and 3 complete and verified
- **Remote:** `git@github.com:yarnitram/swipe-vault.git`
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

## Features Implemented (Phases 0–3)

1. **Offer Catalog & CSV Import (`FR-01`, `AC-02`):** CRUD, explicit vendor approval history (`offer_approvals`), search/filters, and 2-step CSV preview/commit import with row-level duplicate and SSRF validation.
2. **Permission-Aware Source Discovery & Retrieval (`FR-02`, `FR-09`, `AC-06`, `AC-07`, `AC-13`):** Manual source registration with allowed-host scoping, operator-confirmed `POST /api/v1/sources/{id}/scan`, `robots.txt` check, `401`/`403`/`429` + login/CAPTCHA gate handling without bypass, DNS-rebinding & SSRF redirect guards, per-offer/per-source job locking, and cooperative cancellation.
3. **File Ingestion & Deterministic Swipe Extraction (`FR-03`..`FR-05`, `AC-03`..`AC-05`, `AC-09`):** Magic-byte + extension verification, traversal/symlink/zip-bomb defense, content-addressed SHA-256 private asset storage, deterministic parser for TXT/HTML/PDF/DOCX/ZIP, exact deduplication, near-duplicate trigram suggestions, and lineage-aware versioning preserving prior review decisions.
4. **Search & Editorial Review Queue (`FR-06`, `AC-08`):** Hybrid `TSVECTOR` + `pg_trgm` search, bulk tagging/archiving, `<iframe sandbox="">` isolated HTML preview with strict inline CSP, and side-by-side Review Queue with keyboard navigation (`j/k/a/r/n`).
5. **Brand Profiles, Campaign Drafts & Listmonk Draft Export (`FR-07`, `FR-08`, `AC-10`..`AC-12`):** Seeded **MyFitterU** brand profile + CRUD, draft creation from approved swipes (leaving source copy immutable), targeted CTA placeholder & selected URL replacement (preserving unsubscribe/legal links), version-specific draft approval invalidated by material edits, local HTML/text download fallback, and idempotent unsent Listmonk draft export (`POST /api/campaigns` only; zero send/schedule/import endpoints).

## Running Tests & Linters

```powershell
# Backend linter & integration test suite (runs inside the api container against PostgreSQL 16)
docker compose run --rm api ruff check app tests alembic
docker compose run --rm api pytest -v

# Frontend typecheck, unit tests, and production bundle
cd frontend
npm run typecheck
npm test
npm run build
```

## Documentation

- [Milestone Tracker](MILESTONES.md)
- [REST API Contract](docs/api.md)
- [Architecture Overview](docs/architecture.md)
- [Threat Model & Security Controls](docs/threat-model.md)
- [Deployment, Backup & Restore](docs/deployment.md)
- [Testing Guide](docs/testing.md)
- [ADR 0001 — Foundation & Manual Swipe Library](docs/adr/0001-foundation-and-mvp.md)
