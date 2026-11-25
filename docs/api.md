# SwipeVault REST API Contract (Phase 0–1)

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

## Health (no auth)

- `GET /health/live` → `{status: "ok"}`
- `GET /health/ready` → `{status: "ok"|"degraded", database: "ok"|"error", redis: "ok"|"error"}` (503 when degraded)

## Overview

`GET /stats/overview` → `{offers_total, swipes_total, pending_reviews, needs_changes, approved, assets_total, failed_jobs, active_jobs, last_ingested_at|null}`

## Networks

`GET /networks` → `Network[]`, `Network = {id, slug, name, enabled}` (seeded: `clickbank`, plus disabled `digistore24`, `buygoods`).

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

`Approval = {id, state, notes|null, user_email|null, created_at}`

### CSV import

CSV columns (header required): `network,external_offer_id,title,niche,vendor_name,offer_url,affiliate_resources_url,notes`.

- `POST /offers/import/preview` (multipart `file`) →
  ```
  {rows: [{row_number, data: {network, external_offer_id, title, niche, vendor_name, offer_url, affiliate_resources_url, notes},
           status: "valid"|"invalid"|"duplicate_existing"|"duplicate_in_file", errors: string[], existing_offer_id|null}],
   summary: {total, valid, invalid, duplicates}}
  ```
- `POST /offers/import/commit` `{rows: [{row_number, data}]}` → `{created: [{row_number, offer_id}], skipped: [{row_number, reason}]}`. The server re-validates; only valid, non-duplicate rows are created.

## Sources (manual URLs; scanning arrives in Phase 2)

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

URL rules: http(s) only, no userinfo, host must not be an IP literal in loopback/private/link-local/reserved ranges, no `localhost`.

## Assets (authorized uploads)

```
Asset = {id, asset_source_id, sha256, filename, media_type, size_bytes,
         extraction_state: "pending"|"processing"|"extracted"|"needs_review"|"failed"|"unsupported",
         extraction_error|null, parent_asset_id|null, origin: "upload"|"scan"|"archive_entry",
         version_label|null, retrieved_at, swipe_count}
```

| Method | Path | Notes |
|---|---|---|
| POST | `/offers/{id}/assets` | multipart: `file`, `confirm_authorized=true` (required), `source_id?`, `notes?` → `202 {job: Job, asset: Asset, duplicate_asset: bool}`; `400 authorization_required`; `413 file_too_large`; `415 unsupported_file_type` |
| GET | `/offers/{id}/assets` | `Asset[]` (newest first, archive entries included with `parent_asset_id`) |
| GET | `/assets/{id}/download` | original bytes as attachment |

Supported: `.txt`, `.html/.htm`, `.pdf` (embedded text), `.docx`, `.zip` (containing those; no nested archives). Limits: 25 MB per file, 100 MB expanded ZIP, 200 entries.

## Jobs

```
Job = {id, offer_id|null, source_id|null, type: "ingest_asset", state: "queued"|"running"|"completed"|"partial"|"failed"|"cancel_requested"|"cancelled",
       progress: {assets_found, assets_processed, swipes_extracted, swipes_new, versions_new, duplicates, warnings},
       attempts, error_summary|null, created_at, started_at|null, finished_at|null, elapsed_seconds|null,
       offer_title|null}
JobEvent = {id, level: "info"|"warning"|"error", event_type, message, created_at}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/jobs` | `?state=&offer_id=&page=&page_size=` → paginated `Job` (newest first) |
| GET | `/jobs/{id}` | `Job & {events: JobEvent[]}` |
| POST | `/jobs/{id}/cancel` | → `Job` (`cancel_requested` or `cancelled`); `409` if already finished |
| POST | `/jobs/{id}/retry` | → `202 Job` (new job) for `failed`/`partial`/`cancelled` jobs |

## Swipes

```
SwipeSummary = {id, offer: {id, title, vendor_name, niche, network_slug}, title|null, review_state,
                current_version: {id, version_number, primary_subject|null, subject_count, preheader|null,
                                  body_excerpt, confidence, flags: string[]},
                version_count, tags: string[], created_at, updated_at}

SwipeVersion = {id, version_number, subjects: [{id, subject, position}], preheader|null, body_text,
                body_html_sanitized|null, ctas: [{text, url|null, placeholder|null}], normalized_hash,
                parser_version, confidence, flags: string[], section_label|null, created_at,
                provenance: [{id, asset_id, asset_filename, origin, retrieval_url|null, retrieved_at, page_number|null, section_label|null}],
                review_events: [{id, decision, notes|null, user_email|null, created_at}]}

SwipeDetail = SwipeSummary-fields (minus current_version) & {notes|null, current_version_id, versions: SwipeVersion[] (newest first),
               duplicates: {exact_other_offers: [{swipe_id, offer_id, offer_title}], near: [{swipe_id, offer_title, title, similarity}]}}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/swipes` | `?q=&network=&niche=&review_state=&offer_id=&tag=&created_from=&created_to=&sort=relevance|newest|confidence&page=&page_size=` |
| GET | `/swipes/{id}` | `SwipeDetail` |
| PATCH | `/swipes/{id}` | `{title?, notes?}` → `SwipeDetail` |
| POST | `/swipes/{id}/review` | `{version_id, decision: "pending"|"needs_changes"|"approved"|"rejected"|"archived", notes?}` → `SwipeDetail`; `409 stale_version` if not current |
| POST | `/swipes/{id}/tags` | `{tags: string[]}` (replaces set) → `SwipeDetail` |
| POST | `/swipes/bulk` | `{swipe_ids: string[], action: "add_tags"|"archive", tags?: string[]}` → `{updated}` |
| GET | `/tags` | `[{id, slug, label, swipe_count}]` |

Review queue = `GET /swipes?review_state=pending&sort=confidence` (lowest confidence first).

Flags emitted by extraction: `missing_subject`, `missing_body`, `no_boundary_marker`, `short_body`, `missing_cta`, `health_claim`, `guarantee_claim`, `income_claim`, `testimonial`, `placeholder_link`. Flags are review hints, not compliance determinations.

Angle convention: use tags prefixed `angle:` (e.g. `angle:weight-loss`).
