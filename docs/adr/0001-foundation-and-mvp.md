# ADR 0001 — Phase 0 & Phase 1 Foundation and Manual Swipe Library Architecture

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

SwipeVault requires a self-hosted, permission-aware affiliate email swipe library that operates on Proxmox via Docker Compose without relying on a universal ClickBank swipe API or paid external AI services.

## Decisions

1. **Single-Origin Reverse Proxy (`frontend` -> `api`):**
   - Expose only the Nginx `frontend` container on `127.0.0.1:2100` (container port `8080`), proxying `/api/` to `http://api:8000`. Keep PostgreSQL 16 and Redis 7 on the private Docker network with no host ports (`AC-01`).
2. **Argon2id + Server-Side Sessions + Double-Submit CSRF:**
   - Store HMAC-SHA256 hashes of session tokens in PostgreSQL (`sessions`) and send the raw token in an `HttpOnly; SameSite=Lax` cookie (`sv_session`) alongside a readable `sv_csrf` cookie verified via `X-CSRF-Token` on all mutating routes.
3. **Content-Addressed Private Asset Storage + Lineage Keys:**
   - Store original asset bytes immutable by SHA-256 under `/data/assets/<sha[:2]>/<sha256>`. Track per-offer references in `asset_sources` with a `lineage_key` (`file:<name>` or `file:<zip>::<entry>`) so unchanged re-uploads deduplicate (`AC-04`) while edited re-uploads create new `SwipeVersion` rows and preserve earlier review decisions (`AC-05`).
4. **Defense-in-Depth HTML Sanitization:**
   - Sanitize HTML on ingestion using `nh3` (dropping scripts, event handlers, unsafe schemes, and remote `<img>` tracking pixels) and render HTML previews in the React UI exclusively inside `<iframe sandbox="" srcdoc="...">` with an inline CSP (`default-src 'none'; style-src 'unsafe-inline'; img-src data:`).
5. **PostgreSQL Hybrid Full-Text + Trigram Search:**
   - Combine a generated `TSVECTOR` column (`swipes.search_tsv`) with `pg_trgm` GIN indexes so both natural-language queries and partial/substring matches perform well without an external search cluster.
