# SwipeVault — Testing Guide

All automated tests use synthetic local fixtures (`fixtures/`, `httpx.MockTransport`, and in-memory PDF/DOCX/ZIP generators) with zero dependency on live vendor sites, ClickBank APIs, production Listmonk instances, or paid AI services.

## Backend Tests (`pytest` + `ruff`)

Run against the containerized PostgreSQL 16 + Python 3.12 environment:

```powershell
docker compose run --rm api ruff check app tests alembic
docker compose run --rm api pytest -v
```

### What Backend Tests Cover (`28 passed`)

- **`tests/test_security_and_extraction.py` (`21 tests`):**
  - SSRF/URL validation across 15 disallowed targets (loopback, RFC1918, link-local metadata `169.254.169.254`, IPv6 loopback, decimal IP `2130706433`, `.local`, userinfo, non-HTTP schemes, non-standard ports).
  - File signature verification rejecting executables (`MZ`), legacy macro-capable OLE `.doc`, and spoofed extensions.
  - Archive safety rejecting `../` path traversal, symbolic links, and expanded size ceiling breaches.
  - HTML sanitization (`nh3`) stripping `<script>`, `onclick`/`onmouseover`, `javascript:` URLs, `<iframe>`, and remote tracking `<img>` tags.
  - Deterministic extraction and swipe parsing across `.txt`, `.html`, `.pdf`, and `.docx`, plus low-confidence flagging without fabricating missing subjects (`AC-03`, `AC-09`).
- **`tests/test_api_workflow.py` (`4 tests`):**
  - Health probes (`/api/v1/health/live`, `/api/v1/health/ready`), Argon2id login, session cookie auth, and double-submit `X-CSRF-Token` enforcement (`AC-01`).
  - CSV import preview and commit with valid rows, invalid networks, SSRF URL rejection, in-file duplicates, and existing-offer duplicate detection (`AC-02`).
  - Authorized ZIP upload containing TXT/HTML/PDF/DOCX, SHA-256 deduplication on re-upload (`AC-04`), swipe versioning preserving prior version review events (`AC-05`), `TSVECTOR` + `pg_trgm` search and filters (`AC-08`), tag management, provenance tracking, original asset download, and interrupted worker job recovery (`AC-14`).
- **`tests/test_phase2_and_phase3.py` (`3 tests`):**
  - Permission-aware HTTP crawler (`execute_scan_source_job`) discovering linked swipe pages and downloadable assets within allowed hosts, skipping `/checkout` and off-domain links, blocking `302` redirects to `127.0.0.1` (`AC-07`), and deduplicating on re-scan (`AC-03`, `AC-04`).
  - Handling of login/CAPTCHA gates without bypassing controls (`access_state = "approval_required"`, `409 source_not_scannable` on subsequent scan attempt — `AC-06`).
  - Brand profile (`MyFitterU`), campaign draft creation from approved swipes (keeping source copy immutable — `AC-10`), targeted CTA placeholder and selected vendor link replacement while preserving unsubscribe links (`FR-07`), version-specific approval and edit invalidation (`AC-11`), local HTML/text download, and idempotent Listmonk draft export via `POST /api/campaigns` with zero send/schedule calls (`AC-12`).

## Frontend Tests (`vitest` + `tsc` + `vite build`)

```powershell
cd frontend
npm run typecheck
npm test
npm run build
```
