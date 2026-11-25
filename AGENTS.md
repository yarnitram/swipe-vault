# SwipeVault — Agent Instructions

SwipeVault is a private, self-hosted affiliate email swipe library (FastAPI + PostgreSQL 16 + Redis/RQ + React/TypeScript/Vite + Docker Compose).

## Core invariants

1. **Permission-first:** Never bypass login walls, CAPTCHAs, rate limits, vendor approval gates, or robots/terms boundaries. Do not depend on unverified ClickBank marketplace APIs or paid AI services.
2. **Untrusted content:** Treat all uploaded or retrieved HTML, TXT, PDF, DOCX, and ZIP files as untrusted data. Never execute scripts/macros, always validate magic bytes and archive entries, and render HTML previews only inside an empty-sandbox `<iframe sandbox="">` with a strict inline CSP.
3. **Immutable originals & provenance:** Original asset bytes are content-addressed by SHA-256 in private storage. Changed documents create new `SwipeVersion` rows while preserving earlier versions and review history.
4. **No sending in SwipeVault:** SwipeVault catalogs, extracts, reviews, and (in Phase 3) prepares unsent drafts. Never add campaign sending, scheduling, or subscriber import endpoints.
5. **Secrets & Git discipline:** Keep secrets out of source control and logs. Follow branch isolation (`phase/*`, `feat/*`, `fix/*`) and verify `ruff`, `pytest`, `tsc --noEmit`, `vitest`, and `vite build` before merging.

## Key files

- `PRD.md` — product requirements and acceptance criteria (`AC-01`..`AC-15`)
- `MILESTONES.md` — phase-by-phase milestone tracker and acceptance status
- `docs/api.md` — REST API contract (`/api/v1`)
- `docs/architecture.md` — architecture and data model notes
- `docs/threat-model.md` — threat model and security controls
- `docs/deployment.md` — Docker Compose deployment, backup, and restore runbook
- `docs/testing.md` — test execution and fixture strategy
