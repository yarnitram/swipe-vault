# SwipeVault — Milestone Tracker

**Last updated:** 2026-11-25  
**Repository:** `C:\Users\Samjie\ProjectCenter\SwipeVault` (`git@github.com:yarnitram/swipe-vault.git`)  
**Target deployment:** Self-hosted Proxmox + Docker Compose (`127.0.0.1:2100`)

## Phase Summary

| Phase | Milestone | Status | Exit Criteria |
|---|---|---|---|
| **Phase 0** | Project foundation | **Completed** | Reproducible local Docker Compose deployment, Alembic migrations, Argon2id auth + CSRF, health checks, docs, threat model, and green foundation tests. |
| **Phase 1** | Manual swipe library (first usable MVP) | **Completed** | Offer catalog, CSV preview/import, manual source URLs with SSRF validation, authorized file uploads (TXT/HTML/PDF/DOCX/ZIP), deterministic swipe extraction, SHA-256 + normalized hash deduplication, versioning, provenance, search (`TSVECTOR` + `pg_trgm`), and Review Queue UI. |
| **Phase 2** | Permission-aware collection | **Completed** | Domain-scoped HTTP worker scans (`POST /sources/{id}/scan`), DNS-rebinding & SSRF checks on every redirect hop, `robots.txt` + `401`/`403`/`429` + login/CAPTCHA gate handling without bypass, per-offer/per-source job locking, cooperative cancellation, and progress UI. |
| **Phase 3** | Draft workflow and Listmonk | **Completed** | Brand profiles (seeded **MyFitterU** + CRUD), draft creation from approved swipes (`POST /drafts`), targeted CTA placeholder & selected URL replacement (preserving unsubscribe/legal links), version-specific draft approval (`POST /drafts/{id}/approve`) invalidated by material edits, local HTML/text download fallback, and idempotent unsent Listmonk draft export (`POST /drafts/{id}/export/listmonk`). |
| **Phase 4** | Controlled expansion | Ready for Pilot | 10-offer operator pilot evaluation before 50–100 health & fitness offers, optional provider/AI adapters. |

## Acceptance Criteria Tracker (PRD §9)

| ID | Criterion | Phase | Status | Verification |
|---|---|---|---|---|
| **AC-01** | Fresh Docker Compose deployment starts and passes health checks; no public DB/Redis ports | Phase 0 | **Verified** | `compose.yaml` exposes only `127.0.0.1:2100:8080` on `frontend`; `postgres`, `redis`, `api`, `worker`, `frontend` health checks pass. |
| **AC-02** | CSV preview identifies invalid rows and duplicates; committing valid rows creates expected offers | Phase 1 | **Verified** | `test_csv_import_preview_and_commit` + `ImportPreviewTable` test |
| **AC-03** | Permitted fixture with HTML/PDF/DOCX/ZIP resources yields expected swipes and provenance | Phase 1/2 | **Verified** | `test_extract_and_parse_across_txt_html_pdf_and_docx`, `test_zip_ingestion_provenance_dedup_versioning_search_and_review`, `test_phase2_permission_aware_crawler_and_idempotency` |
| **AC-04** | Re-scanning/re-uploading an unchanged fixture adds no duplicate assets or exact swipes | Phase 1/2 | **Verified** | `test_zip_ingestion_provenance_dedup_versioning_search_and_review` + `test_phase2_permission_aware_crawler_and_idempotency` (`swipes_new == 0`, `duplicates >= 2`) |
| **AC-05** | Changed document creates versioned content while preserving prior original and review history | Phase 1 | **Verified** | `test_zip_ingestion_provenance_dedup_versioning_search_and_review` (`v1` approved history preserved when `v2` is created) |
| **AC-06** | Login-gated, forbidden or rate-limited resources handled without bypassing controls | Phase 2 | **Verified** | `test_phase2_handles_login_gates_robots_and_rate_limits_without_bypass` (`access_state` updated to `approval_required`/`restricted`, `409 source_not_scannable`) |
| **AC-07** | Private IPs, malicious redirects, unsafe archives and active HTML blocked in security tests | Phase 0–2 | **Verified** | `test_ssrf_url_validation_blocks_unsafe_targets`, redirect to `127.0.0.1` blocked in `test_phase2_permission_aware_crawler_and_idempotency`, `test_zip_safety_rejects_traversal_symlinks_and_oversized_archives`, `test_html_sanitizer_strips_scripts_event_handlers_and_tracking_pixels` |
| **AC-08** | Search returns expected subjects/body results and respects network, niche and state filters | Phase 1 | **Verified** | `test_zip_ingestion_provenance_dedup_versioning_search_and_review` |
| **AC-09** | Low-confidence extraction stays pending review; no missing body/subject is fabricated | Phase 1 | **Verified** | `test_extract_and_parse_across_txt_html_pdf_and_docx` (`missing_subject`, confidence `< 0.5`) |
| **AC-10** | Approved swipe can create a brand-specific draft without altering source content | Phase 3 | **Verified** | `test_phase3_draft_workflow_and_listmonk_export` (source swipe body & placeholders remain unchanged) |
| **AC-11** | Material draft edits invalidate approval; unapproved drafts cannot be exported | Phase 3 | **Verified** | `test_phase3_draft_workflow_and_listmonk_export` (`v1` approved → edit increments to `v2` & resets `status='editing'`, `409 draft_not_approved`) |
| **AC-12** | Test Listmonk instance receives one unsent draft; retries do not duplicate; no sending endpoint called | Phase 3 | **Verified** | `test_phase3_draft_workflow_and_listmonk_export` (`POST /api/campaigns` called once, retry returns same `Export`, zero send/schedule calls) |
| **AC-13** | Cancelling a scan/job stops further retrieval at safe boundaries and reports committed results | Phase 1/2 | **Verified** | `POST /api/v1/jobs/{id}/cancel` + cooperative boundary checks in `execute_ingest_job` and `execute_scan_source_job` |
| **AC-14** | Failed/partial jobs provide actionable logs, and worker restart does not corrupt or duplicate records | Phase 1/2 | **Verified** | `test_job_cancellation_and_worker_crash_recovery` (`recover_interrupted_jobs`) |
| **AC-15** | Backup/restore restores a fixture offer, source asset, swipe, version and draft | Phase 0–3 | **Documented & scripted** | `scripts/backup.ps1` and `scripts/restore.ps1` (`docs/deployment.md`) |
