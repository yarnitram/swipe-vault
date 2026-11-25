# SwipeVault REST API Contract (Phases 0–3)

Prefix: `/api/v1`. OpenAPI is served at `/api/v1/openapi.json` and `/api/v1/docs` (development only).

## Conventions

- JSON request/response bodies unless noted (`multipart/form-data` for uploads/CSV).
- **Session:** `sv_session` cookie (HttpOnly, SameSite=Lax, `Secure` in production).
- **CSRF:** double-submit. Login sets a readable `sv_csrf` cookie. Every `POST`/`PATCH`/`PUT`/`DELETE` except `/auth/login` must send header `X-CSRF-Token: <sv_csrf value>`; otherwise `403 csrf_failed`.
- **Errors:** `{"error": {"code": "snake_case_code", "message": "Human readable", "details": <any|null>}}`. Validation errors use `422 validation_error` with `details` = list of field errors.
- **Pagination:** `?page=1&page_size=25` (max 100) → `{"items": [...], "total": 123, "page": 1, "page_size": 25}`.
- Timestamps are ISO-8601 UTC strings. IDs are UUID strings.
- Unknown data is `null`; the API never fabricates metrics.

## Auth

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/login` | `{email, password}` | `200 {user: User}` + cookies; `401 invalid_credentials`; `429 rate_limited` |
| POST | `/auth/logout` | – | `204` |
| GET | `/auth/me` | – | `200 User`; `401 not_authenticated` |

`User = {id, email, role: "admin"}`

## Health & Settings (no secrets exposed)

- `GET /health/live` → `{status: "ok"}`
- `GET /health/ready` → `{status: "ok"|"degraded", database: "ok"|"error", redis: "ok"|"error"}` (503 when degraded)
- `GET /settings/runtime` →
  ```
  {crawl_delay_seconds, crawl_max_pages, crawl_max_depth, crawl_timeout_seconds,
   download_max_bytes, near_duplicate_threshold,
   listmonk_enabled: bool, listmonk_configured: bool, listmonk_base_url: string|null,
   ai_provider: string}
  ```

## Overview

`GET /stats/overview` → `{offers_total, swipes_total, pending_reviews, needs_changes, approved, assets_total, drafts_total, failed_jobs, active_jobs, last_ingested_at|null}`

## Networks

`GET /networks` → `Network[]`, `Network = {id, slug, name, enabled}`.

## Offers

```
Offer = {
  id, network: {id, slug, name}, external_offer_id|null, title, niche|null, vendor_name|null,
  offer_url|null, affiliate_resources_url|null,
  approval_state: "unknown"|"requested"|"approved"|"denied"|"revoked",
  metrics_json|null, metrics_source|null, metrics_as_of|null, notes|null,
  last_verified_at|null, created_at, updated_at, swipe_count, asset_count, source_count
}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/offers` | `?q=&network=<slug>&niche=&approval_state=&page=&page_size=` → paginated `Offer` |
| POST | `/offers` | `{network_slug, title, external_offer_id?, niche?, vendor_name?, offer_url?, affiliate_resources_url?, notes?}` → `201 Offer`; `409 duplicate_offer` |
| GET | `/offers/niches` | `string[]` distinct niches |
| GET | `/offers/{id}` | `Offer` |
| PATCH | `/offers/{id}` | partial of POST fields + `metrics_json`, `metrics_source`, `metrics_as_of`, `last_verified_at` |
| GET | `/offers/{id}/approvals` | `Approval[]` newest first |
| POST | `/offers/{id}/approvals` | `{state, notes?}` → `201 Approval` and updates `offer.approval_state` |
| POST | `/offers/import/preview` | multipart `file` → `{rows, summary}` |
| POST | `/offers/import/commit` | `{rows: [{row_number, data}]}` → `{created, skipped}` |

## Sources & Permission-Aware Scanning (Phase 2)

```
Source = {id, offer_id, url, normalized_url, source_type: "affiliate_page"|"offer_page"|"asset_url"|"other",
          access_state: "unverified"|"authorized"|"restricted"|"approval_required"|"forbidden",
          permission_notes|null, allowed_hosts: string[], last_checked_at|null, created_at}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/offers/{id}/sources` | `Source[]` |
| POST | `/offers/{id}/sources` | `{url, source_type, access_state?, permission_notes?, allowed_hosts?}` → `201`; `422 unsafe_url`; `409 duplicate_source` |
| PATCH | `/sources/{id}` | `{access_state?, permission_notes?, allowed_hosts?, source_type?}` |
| POST | `/sources/{id}/scan` | `{confirm_authorized: true}` → `202 Job` (`type: "scan_source"`); `400 authorization_required`; `409 source_not_scannable` (when `restricted`/`approval_required`/`forbidden`); `409 scan_already_running` |

## Assets (authorized uploads & scanned assets)

```
Asset = {id, asset_source_id, sha256, filename, media_type, size_bytes,
         extraction_state: "pending"|"processing"|"extracted"|"needs_review"|"failed"|"unsupported",
         extraction_error|null, parent_asset_id|null, origin: "upload"|"scan"|"archive_entry",
         retrieval_url|null, version_label|null, retrieved_at, swipe_count}
```

| Method | Path | Notes |
|---|---|---|
| POST | `/offers/{id}/assets` | multipart: `file`, `confirm_authorized=true`, `source_id?`, `notes?` → `202 {job: Job, asset: Asset, duplicate_asset: bool}` |
| GET | `/offers/{id}/assets` | `Asset[]` |
| GET | `/assets/{id}/download` | original bytes as attachment |

## Jobs

```
Job = {id, offer_id|null, source_id|null, type: "ingest_asset"|"scan_source",
       state: "queued"|"running"|"completed"|"partial"|"failed"|"cancel_requested"|"cancelled",
       progress: {pages_checked, assets_found, assets_processed, swipes_extracted, swipes_new, versions_new, duplicates, warnings},
       attempts, error_summary|null, created_at, started_at|null, finished_at|null, elapsed_seconds|null,
       offer_title|null}
JobEvent = {id, level: "info"|"warning"|"error", event_type, message, created_at}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/jobs` | `?state=&offer_id=&type=&page=&page_size=` → paginated `Job` |
| GET | `/jobs/{id}` | `Job & {events: JobEvent[]}` |
| POST | `/jobs/{id}/cancel` | → `Job` (`cancel_requested` or `cancelled`) |
| POST | `/jobs/{id}/retry` | → `202 Job` |

## Swipes

| Method | Path | Notes |
|---|---|---|
| GET | `/swipes` | `?q=&network=&niche=&review_state=&offer_id=&tag=&created_from=&created_to=&sort=relevance|newest|confidence&page=&page_size=` |
| GET | `/swipes/{id}` | `SwipeDetail` |
| PATCH | `/swipes/{id}` | `{title?, notes?}` → `SwipeDetail` |
| POST | `/swipes/{id}/review` | `{version_id, decision, notes?}` → `SwipeDetail`; `409 stale_version` |
| POST | `/swipes/{id}/tags` | `{tags: string[]}` → `SwipeDetail` |
| POST | `/swipes/bulk` | `{swipe_ids: string[], action: "add_tags"|"archive", tags?: string[]}` → `{updated}` |
| GET | `/tags` | `[{id, slug, label, swipe_count}]` |

## Brand Profiles (Phase 3 — FR-07)

```
BrandProfile = {
  id, name, slug, sender_identity_ref|null,
  affiliate_settings_json: {default_tracking_param?: string|null, allowed_affiliate_hosts?: string[]},
  disclosure_text, footer_template, integration_ref|null,
  created_at, updated_at
}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/brands` | `BrandProfile[]` (seeded with `MyFitterU`) |
| POST | `/brands` | `{name, sender_identity_ref?, affiliate_settings_json?, disclosure_text?, footer_template?, integration_ref?}` → `201 BrandProfile` |
| PATCH | `/brands/{id}` | partial update of POST fields → `BrandProfile` |

## Campaign Drafts (Phase 3 — FR-07)

```
DraftReviewChecks = {
  has_affiliate_url: bool,
  affiliate_url_valid: bool,
  has_disclosure: bool,
  has_sender_footer: bool,
  unresolved_placeholders: string[],
  unexpected_hosts: string[],
  claim_flags: string[],
  warnings: string[],
  ready_for_approval: bool
}

Draft = {
  id, swipe_id, swipe_version_id, swipe_version_number,
  offer: {id, title, vendor_name, network_slug},
  brand: {id, name, slug},
  title, subject, preheader|null, affiliate_url|null,
  body_html, body_text,
  status: "editing"|"approved"|"exported"|"archived",
  version: int,
  approved_version: int|null,
  approved_at: string|null,
  review_checks: DraftReviewChecks,
  sequence_position: int|null,
  suggested_day_offset: int|null,
  created_at, updated_at
}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/drafts` | `?brand_id=&offer_id=&status=&page=&page_size=` → paginated `Draft` |
| POST | `/drafts` | `{swipe_id, brand_id, subject_position?: int, affiliate_url?: string, replace_urls?: string[], sequence_position?: int, suggested_day_offset?: int}` → `201 Draft`; requires swipe `review_state == "approved"` (`409 swipe_not_approved`) |
| GET | `/drafts/{id}` | `Draft & {available_subjects: string[], source_ctas: [{text, url|null, placeholder|null}], exports: Export[]}` |
| PATCH | `/drafts/{id}` | `{title?, subject?, preheader?, body_text?, body_html?, affiliate_url?, replace_placeholders?: bool, replace_urls?: string[], append_brand_footer?: bool, sequence_position?, suggested_day_offset?, status?: "editing"|"archived"}` → material edits increment `version`, clear `approved_version`/`approved_at`, reset `status = "editing"`, and recompute `review_checks` (`AC-11`) |
| POST | `/drafts/{id}/approve` | `{version: int}` → approves exact version (`status = "approved"`, `approved_version = version`); `409 stale_draft_version` if version mismatches; `422 draft_checks_failed` if unresolved placeholders or invalid affiliate URL remain |
| GET | `/drafts/{id}/download` | `?format=html|txt` → attachment download of approved draft (`409 draft_not_approved` if not approved) |

## Listmonk Draft Integration (Phase 3 — FR-08)

```
Export = {
  id, draft_id, draft_version, target: "listmonk"|"local_download",
  idempotency_key, remote_id: string|null, remote_url: string|null,
  status: "pending"|"completed"|"failed"|"needs_reconciliation",
  error_summary: string|null, created_at, updated_at
}
```

| Method | Path | Notes |
|---|---|---|
| POST | `/integrations/listmonk/test` | `{}` → `{enabled: bool, configured: bool, reachable: bool, lists: [{id: int, name: string, type: string}], message: string}` |
| POST | `/drafts/{id}/export/listmonk` | `{list_ids: int[], confirm_unsent_draft: true}` → `200 Export`; requires approved draft (`409 draft_not_approved`), `confirm_unsent_draft=true` (`400 confirmation_required`), non-empty `list_ids` (`422 list_selection_required`); idempotent on `(draft_id, draft_version, sorted(list_ids))`; never calls any send/schedule/start endpoint (`AC-12`) |
| GET | `/exports/{id}` | `Export` |
