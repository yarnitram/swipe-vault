# SwipeVault — Testing Guide

All automated tests use synthetic local fixtures (`fixtures/` and in-memory PDF/DOCX/ZIP generators) with zero dependency on live vendor sites, ClickBank APIs, or paid AI services.

## Backend Tests (`pytest` + `ruff`)

Run against the containerized PostgreSQL 16 + Python 3.12 environment:

```powershell
docker compose exec api ruff check app tests alembic
docker compose exec api pytest -v
```

### What Backend Tests Cover

- **`tests/test_security_and_extraction.py`:**
  - SSRF/URL validation across 15 disallowed targets (loopback, RFC1918, link-local metadata `169.254.169.254`, IPv6 loopback, decimal IP `2130706433`, `.local`, userinfo, non-HTTP schemes, non-standard ports).
  - File signature verification rejecting executables (`MZ`), legacy macro-capable OLE `.doc`, and spoofed extensions.
  - Archive safety rejecting `../` path traversal, symbolic links, and expanded size ceiling breaches.
  - HTML sanitization (`nh3`) stripping `<script>`, `onclick`/`onmouseover`, `javascript:` URLs, `<iframe>`, and remote tracking `<img>` tags.
  - Deterministic extraction and swipe parsing across `.txt`, `.html`, `.pdf`, and `.docx`, plus low-confidence flagging without fabricating missing subjects (`AC-03`, `AC-09`).
- **`tests/test_api_workflow.py`:**
  - Health probes (`/api/v1/health/live`, `/api/v1/health/ready`), Argon2id login, session cookie auth, and double-submit `X-CSRF-Token` enforcement (`AC-01`).
  - CSV import preview and commit with valid rows, invalid networks, SSRF URL rejection, in-file duplicates, and existing-offer duplicate detection (`AC-02`).
  - Authorized ZIP upload containing TXT/HTML/PDF/DOCX, SHA-256 deduplication on re-upload (`AC-04`), swipe versioning preserving prior version review events (`AC-05`), `TSVECTOR` + `pg_trgm` search and filters (`AC-08`), tag management, provenance tracking, original asset download, and interrupted worker job recovery (`AC-14`).

## Frontend Tests (`vitest` + `tsc` + `vite build`)

```powershell
cd frontend
npm run typecheck
npm test
npm run build
```
