# SwipeVault — Product Requirements Document

**Version:** 1.0  
**Status:** Proposed / ready for implementation planning  
**Target deployment:** Self-hosted Proxmox + Docker Compose  
**Initial network:** ClickBank  
**Initial niche:** Health & fitness  
**Project type:** Private affiliate creative library

## 1. Executive summary

SwipeVault is a self-hosted application for discovering affiliate offers, collecting vendor-authorized email swipes, extracting and organizing email content, and preparing reviewed campaign drafts for Listmonk. The initial target is a curated collection of 50–100 ClickBank offers; actual swipe availability will vary by vendor.

The application must not depend on a universal ClickBank swipe API. Offer discovery and creative retrieval are separate processes. Begin with manually supplied offer and affiliate-resource URLs and file uploads, then add supported discovery sources after verifying their access terms, coverage and reliability.

### Goals

- Reduce repetitive manual work when finding and organizing affiliate email creatives.
- Maintain a searchable library of offers, email subjects, preheaders, body copy and calls to action.
- Preserve original vendor assets, attribution, usage conditions and source provenance.
- Detect duplicates and identify revised versions without losing the original content.
- Prepare approved email drafts with the user's affiliate links and optional Listmonk export.
- Support future expansion to Digistore24, BuyGoods and other authorized sources.

### Non-goals (MVP)

- Automatically sending campaigns, importing recipient lists, or obtaining email addresses.
- Bypassing vendor login, CAPTCHA, approval gates, rate limits or access restrictions.
- Scraping the entire ClickBank marketplace without a permitted discovery method.
- Automatically declaring health claims compliant or guaranteeing deliverability or revenue.
- Redistributing vendor creatives publicly or selling access to them.

## 2. Primary workflow

1. Add a ClickBank offer manually, via CSV, or via a verified provider adapter.
2. Record its marketplace URL, affiliate tools URL, vendor, niche, offer identifier and approval status.
3. Preview the source and confirm authorization to retrieve and use the assets.
4. Click **Scan resources**. A background worker discovers eligible links and downloads or parses authorized materials.
5. Extract candidate email swipes from HTML, text, PDF, DOCX and ZIP archives.
6. Detect duplicates, preserve originals and place ambiguous extractions into a review queue.
7. Review and approve individual swipes for internal use; verify claims, usage restrictions and affiliate links.
8. Create an editable campaign draft, choose a brand and insert an approved affiliate link.
9. Preview HTML and plain text; optionally export to Listmonk as a draft only.
10. Sending remains a separate deliberate action outside SwipeVault.

## 3. Architecture

```mermaid
flowchart TD
    UI[React dashboard] --> API[FastAPI REST API]
    API --> DB[(PostgreSQL)]
    API --> Q[(Redis job queue)]
    Q --> W[Python worker]
    W --> S[Permission-aware source adapters]
    S --> V[Authorized vendor resource pages]
    W --> E[Document extraction and deduplication]
    E --> DB
    E --> A[(Private asset storage)]
    API --> L[Listmonk draft adapter]
    E -. Optional .-> AI[LLM classification]
```

| Layer | Proposed technology |
|---|---|
| API | Python 3.12+ supported runtime, FastAPI, Pydantic |
| Database | PostgreSQL, SQLAlchemy 2.x, Alembic |
| Jobs | Redis + RQ (separate worker process) |
| Static retrieval | HTTPX + BeautifulSoup |
| Dynamic pages | Playwright, only where authorized and necessary |
| Extraction | PyMuPDF, python-docx, standard ZIP and text libraries |
| Frontend | React + TypeScript + Vite + Tailwind CSS |
| Storage | Private persistent Docker volume; S3-compatible adapter later |
| Search | PostgreSQL full-text search and pg_trgm |
| AI (optional) | OpenAI API or local Ollama, behind a provider interface |
| Deployment | Docker Compose on Proxmox LXC or VM |
| Access | Private LAN or authenticated Cloudflare Access tunnel; application login |
| Testing | pytest, Vitest, Playwright end-to-end tests |

Versions must be pinned to mutually compatible stable releases during implementation. n8n is optional for notifications or external workflows; core retrieval must not require it.

### Deployment services

- `frontend`: dashboard, reverse-proxied with `/api` routing.
- `api`: authenticated REST API.
- `worker`: background jobs; separate resource limits from the API.
- `postgres`: persistent database; not exposed publicly.
- `redis`: private queue; not exposed publicly.
- Optional `playwright-worker`: isolated browser execution for dynamic authorized sources.

Use `.env.example` for configuration, Docker health checks, persistent volumes and backup/restore instructions. Run workers as non-root with no Docker socket access. Disable browser access to internal networks and cloud metadata endpoints.

## 4. Feature requirements

### FR-01 — Offer catalog

Each offer stores network, external offer ID or vendor nickname where available, title, niche, vendor name, official offer URL, affiliate resources URL, optional commission/gravity metadata, source of metrics, and last verification timestamp. Store affiliate approval state separately from asset availability.

- CRUD, CSV import with preview and duplicate handling, search and filtering.
- CSV columns: `network,external_offer_id,title,niche,vendor_name,offer_url,affiliate_resources_url,notes`.
- Do not fabricate marketplace metrics or offer availability. Unknown data stays null.
- Support explicit approval/authorization records and notes.
- Source adapters expose discovery capability only when verified. No dependency on unverified third-party marketplace services.

### FR-02 — Resource discovery and retrieval

- Manual URL entry and local file upload must work without marketplace integration.
- Manual **Scan resources**, **Re-scan** and **Cancel job** controls.
- Before retrieval, show domain, access status, scope and any recorded vendor restrictions.
- Use HTTP retrieval first; browser rendering only where necessary and allowed.
- Identify links labeled email swipe, email copy, subject lines, creatives, affiliate tools, promotional materials and related variants.
- Restrict navigation to approved source domains and explicitly approved linked asset hosts.
- Check robots directives and site terms where applicable; do not interpret public access as blanket permission to reuse content.
- Respect `429`, `Retry-After`, timeouts, rate limits and permission boundaries. No CAPTCHA-solving, proxy rotation or evasion.
- If access requires login or affiliate approval, mark `restricted` or `approval_required`; accept vendor-provided files manually after authorization.
- Default: at most one concurrent request per host, 2 seconds between requests, 30-second request timeout, depth 2, 30 pages per offer per scan. Configurable within operator-defined ceilings.
- Never recursively crawl unrelated marketing sites or purchase/checkout pages.

### FR-03 — File ingestion

Supported input: HTML, TXT, PDF with embedded text, DOCX and ZIP containing supported files. Scanned PDF OCR is optional later; unsupported or ambiguous inputs go to review.

- Validate file type using content signature as well as extension.
- Preserve original asset bytes and SHA-256 hash in private storage.
- Initial limits: 25 MB per download, 100 MB total ZIP expanded size, 200 archive entries, no nested archives in MVP.
- Reject path traversal, symlinks, zip bombs, executable content and unsupported files.
- Parse documents as data; never run macros, JavaScript or embedded commands.
- Record source URL, retrieval time, asset name, media type, extraction engine/version and any failure reason.

### FR-04 — Swipe extraction

Use deterministic parsing before optional AI. Detect blocks such as `Email 1`, `Subject:`, `SL:`, `Preheader:`, `Body:`, subject variants and common CTA placeholders. Maintain paragraph boundaries and links. An asset may contain many swipes or several subject variants for a single body.

Extract:

- Original heading and swipe number, if present.
- One or more subject line variants.
- Optional preheader.
- Original body text and sanitized HTML where available.
- CTA text, original destinations and link placeholders.
- Source asset ID, page number or document section, parser version and extraction confidence.

Do not invent missing content. Low-confidence boundaries, missing subjects and questionable extraction results require review. Preserve the exact original separately from edited drafts.

Optional AI output uses strict JSON schema, validated server-side. Treat source content as untrusted data, not instructions; do not give the model tools or credentials. Do not send private vendor assets to a third-party AI provider unless authorized by the operator and vendor terms.

### FR-05 — Deduplication and versioning

1. Asset deduplication by SHA-256.
2. Exact swipe deduplication by normalized subject set and normalized body hash (Unicode normalization, whitespace normalization, retain original copy).
3. Near-duplicate suggestions using pg_trgm or text similarity; start at configurable 0.90 similarity and validate with fixtures.
4. Never automatically merge distinct offers, substantially different claims, or materially different CTA destinations.
5. Preserve all source references even when a swipe is an exact duplicate.
6. Changed assets create new versions; never overwrite original vendor copy or historical review decisions.

### FR-06 — Search and review

- Search subjects, body copy, offer titles, vendor names and tags.
- Filter by network, niche, angle, review state, source status, date, and offer.
- Swipe detail shows sanitized preview, plain text, all subject variants, source attribution, asset download where allowed and editable notes.
- Review states: `pending`, `needs_changes`, `approved`, `rejected`, `archived`.
- Approval is an internal editorial decision, not a legal/compliance certification.
- Bulk tagging and bulk archive supported; draft export requires an approved swipe and explicit operator confirmation.

### FR-07 — Brand profiles and campaign drafts

Brand profiles allow MyFitterU or other newsletter brands to be configured independently. Each profile stores display name, approved sending identity reference, affiliate tracking settings, disclaimer/footer template and optional Listmonk configuration reference. Do not assume a sender or domain has been verified.

- Create a draft from an approved swipe; source remains immutable.
- Choose a subject variant, edit body and preheader, insert a verified affiliate URL and preview.
- Replace only recognized CTA placeholders or explicitly selected links; do not globally replace all URLs.
- Preserve unsubscribe, legal, disclosure and non-affiliate links.
- Validate outbound destination syntax and flag unexpected redirects/domains; never create tracking links by guessing network parameters.
- Include a clear affiliate disclosure and appropriate sender identification.
- Re-run review checks after material edits.
- Optional campaign sequence: ordered drafts with suggested intervals; no scheduling/sending in MVP.

### FR-08 — Listmonk draft integration

Implement behind an adapter, initially disabled until tested against the installed Listmonk version. Confirm supported authentication, campaign creation fields, template handling, list requirements and exact draft semantics from that instance's API documentation or a disposable test instance.

- Test connection without exposing credentials.
- Create a draft only after preview and explicit approval.
- Preserve subject, HTML/plain text as supported, brand identity and approved template/footer.
- If Listmonk requires list selection, allow only an explicitly chosen, consent-based test or production list; never automatically select all subscribers.
- Store remote campaign ID and idempotency key; retries must not create duplicate campaigns. On ambiguous network failure, mark export as `needs_reconciliation` rather than blindly retrying creation.
- No start, schedule, send, or subscriber import endpoints in the adapter.
- If the API cannot reliably create an unsent draft, disable remote export and provide copy/download HTML and plain text instead.
- Display export status, errors and remote link when supported.

### FR-09 — Jobs and operational controls

- Manual scan triggers only in MVP. No scheduled background collection.
- States: `queued`, `running`, `completed`, `partial`, `failed`, `cancel_requested`, `cancelled`.
- Show pages checked, assets found, swipes extracted, duplicates, warnings and elapsed time.
- Per-offer and per-source job locking to avoid overlapping scans.
- Retry transient failures with bounded exponential backoff; do not retry permanent authorization failures.
- Persist progress and logs; recover interrupted jobs safely after restart.
- Support cooperative cancellation and preserve already committed results.

## 5. Data model

Use UUID primary keys, UTC timestamps and Alembic migrations. Foreign keys, check constraints and indexes should enforce invariants. Credentials live in server-side secret configuration; database stores only secret references where necessary.

| Table | Key fields |
|---|---|
| `users` | id, email, password_hash, role, active, created_at |
| `networks` | id, slug, name, enabled |
| `offers` | id, network_id, external_offer_id, title, niche, vendor_name, offer_url, approval_state, metrics_json, metrics_source, metrics_as_of, notes |
| `sources` | id, offer_id, url, normalized_url, source_type, access_state, permission_notes, allowed_hosts, last_checked_at |
| `assets` | id, sha256, storage_key, filename, media_type, size_bytes, extraction_state |
| `asset_sources` | id, asset_id, source_id, retrieval_url, retrieved_at, version_label |
| `swipes` | id, offer_id, title, review_state, current_version_id, created_at |
| `swipe_versions` | id, swipe_id, version_number, body_text, body_html_sanitized, preheader, normalized_hash, parser_version, confidence |
| `subject_variants` | id, swipe_version_id, subject, position |
| `swipe_provenance` | id, swipe_version_id, asset_source_id, page_number, section_label |
| `tags` | id, slug, label |
| `swipe_tags` | swipe_id, tag_id |
| `review_events` | id, swipe_version_id, user_id, decision, notes, created_at |
| `brand_profiles` | id, name, sender_identity_ref, affiliate_settings_json, footer_template, integration_ref |
| `drafts` | id, swipe_version_id, brand_id, subject, preheader, body_html, body_text, status, version, approved_at |
| `exports` | id, draft_id, draft_version, target, idempotency_key, remote_id, status, error_summary |
| `jobs` | id, offer_id, source_id, type, state, progress_json, attempts, started_at, finished_at |
| `job_events` | id, job_id, level, event_type, message, created_at |
| `audit_events` | id, user_id, action, entity_type, entity_id, metadata_json, created_at |

Required indexes/constraints: unique network slug, unique `(network_id, external_offer_id)` where external ID is non-null, unique `(offer_id, normalized_url)` for sources, unique asset hash, unique `(swipe_id, version_number)`, unique export idempotency key, GIN full-text indexes and trigram indexes on searchable fields. Ensure `current_version_id` belongs to its parent swipe. Draft approvals are version-specific and invalidated by material edits.

## 6. REST API (proposed)

Prefix `/api/v1`. Use authenticated endpoints, pagination, structured errors and OpenAPI documentation. Request bodies are validated; job endpoints return HTTP 202 where appropriate.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/login` | Sign in |
| POST | `/auth/logout` | End session |
| GET | `/auth/me` | Current user |
| GET, POST | `/offers` | List/create offers |
| GET, PATCH | `/offers/{id}` | Offer detail/update |
| POST | `/offers/import/preview` | Validate CSV |
| POST | `/offers/import/commit` | Commit reviewed import |
| POST | `/offers/{id}/sources` | Add source |
| POST | `/sources/{id}/scan` | Start manual scan |
| POST | `/offers/{id}/assets` | Upload authorized asset |
| GET | `/jobs/{id}` | Progress |
| POST | `/jobs/{id}/cancel` | Cancel job |
| GET | `/swipes` | Search/filter/paginate |
| GET | `/swipes/{id}` | Content and versions |
| POST | `/swipes/{id}/review` | Review a specific version |
| POST | `/swipes/{id}/tags` | Update tags |
| GET, POST | `/brands` | Brand profiles |
| GET, POST | `/drafts` | List/create drafts |
| GET, PATCH | `/drafts/{id}` | Preview/edit draft |
| POST | `/drafts/{id}/approve` | Approve specific draft version |
| POST | `/drafts/{id}/export/listmonk` | Create unsent remote draft |
| GET | `/exports/{id}` | Export status |
| POST | `/integrations/listmonk/test` | Connection validation |
| GET | `/health/live`, `/health/ready` | Health checks |

## 7. Dashboard / UI

Design for desktop first, responsive tablet/mobile. Use readable tables, compact filters, consistent keyboard navigation, accessible forms and non-blocking job updates. Avoid fake statistics: dashboard values come from the database.

### Main navigation

1. Overview — total offers, unique swipes, pending reviews, failed scans, last retrieval.
2. Offers — list/grid, add offer, CSV import, approval filters and scan action.
3. Swipe Library — search, category filters, review state, subject/body preview and quick copy.
4. Review Queue — source versus extracted content, flags, approve/reject and notes.
5. Drafts — brand, subject variants, CTA insertion, HTML/text preview and explicit export.
6. Jobs — scan history, progress, warnings, cancellation and retry.
7. Settings — networks, brand profiles, allowed hosts, retrieval limits, Listmonk connection and AI opt-in.

### Sample layout

```text
+-----------------------------------------------------------+
| SwipeVault           Search...                Settings   |
+-------------+---------------------------------------------+
| Overview    | Offers | Unique swipes | Pending | Errors   |
| Offers      +---------------------------------------------+
| Swipes      | Filter: Network | Niche | Status | Angle    |
| Review      +---------------------------------------------+
| Drafts      | Offer      Subject      State       Actions |
| Jobs        | ...        ...          ...         View    |
| Settings    | ...        ...          ...         Review  |
+-------------+---------------------------------------------+
```

## 8. Security, permissions and email compliance

- Single operator/admin MVP; future editor and reviewer roles. Passwords hashed with Argon2id, authenticated sessions, secure HttpOnly cookies, CSRF protection where applicable and login rate limiting.
- SSRF defenses: only HTTP(S), no userinfo URLs, block loopback/private/link-local/reserved addresses, validate DNS and connection destination on every redirect, enforce egress policy, protect against DNS rebinding. Listmonk's configured internal endpoint is handled separately by its fixed-purpose adapter, not by crawler URLs.
- HTML previews must sanitize scripts, event handlers, unsafe URLs and remote tracking pixels. Use isolated preview rendering; no active vendor scripts.
- Never log passwords, API keys, session cookies or token-bearing URLs. Encrypt backups and restrict asset access.
- Respect vendor license terms, affiliate approval requirements and restrictions on modifying swipes. Record permission and provenance; allow removing or quarantining material when authorization expires.
- Flag health claims, promises of guaranteed results, misleading subject lines, unsupported endorsements/testimonials, missing disclosures and suspicious destinations for human review. A flag-free result does not prove compliance.
- Use only appropriately permissioned recipient lists, honor unsubscribes and suppression lists, and follow relevant marketing law and ESP policies. For US recipients, account for CAN-SPAM and applicable FTC advertising/endorsement standards; other jurisdictions may impose stricter consent requirements. This system is not a legal compliance determination.
- No functionality for harvested or unauthorized recipient lists, automated mass sending, deliverability evasion or bypassing vendor restrictions.
- Document backup and restoration of PostgreSQL and private assets. Retention and deletion controls must cover source assets, metadata, drafts and logs.

## 9. Testing and acceptance criteria

| ID | Acceptance criterion |
|---|---|
| AC-01 | A fresh Docker Compose deployment starts and passes health checks; no public database/Redis ports. |
| AC-02 | CSV preview identifies invalid rows and duplicates; committing valid rows creates the expected offers. |
| AC-03 | A permitted fixture affiliate page with HTML/PDF/DOCX/ZIP resources yields expected swipes and provenance. |
| AC-04 | Re-scanning an unchanged fixture adds no duplicate assets or exact swipes. |
| AC-05 | A changed document creates versioned content while preserving the prior original and review history. |
| AC-06 | Login-gated, forbidden or rate-limited resources are handled without bypassing controls. |
| AC-07 | Private IPs, malicious redirects, unsafe archives and active HTML are blocked in security tests. |
| AC-08 | Search returns expected subjects/body results and respects network, niche and state filters. |
| AC-09 | A low-confidence extraction stays pending review; no missing body/subject is fabricated. |
| AC-10 | An approved swipe can create a brand-specific draft without altering source content. |
| AC-11 | Material draft edits invalidate approval; unapproved drafts cannot be exported. |
| AC-12 | A test Listmonk instance receives one unsent draft; retries do not duplicate it and no sending endpoint is called. |
| AC-13 | Cancelling a scan stops further retrieval at safe boundaries and reports committed results. |
| AC-14 | Failed/partial jobs provide actionable logs, and a worker restart does not corrupt or duplicate records. |
| AC-15 | Backup/restore restores a fixture offer, source asset, swipe, version and draft. |

### Test strategy

Use synthetic or explicitly authorized local fixtures for CI; no live vendor dependencies in automated tests. Include malformed documents, multiple subject variants, missing labels, duplicate bodies across offers, unexpected links, oversized downloads, redirects, DNS/SSRF attempts, ZIP traversal, 429 responses, and simulated Listmonk connection loss. Mock external AI unless an explicit opt-in integration test is requested.

## 10. Implementation milestones

### Phase 0 — Project foundation

- Initialize repo, Docker Compose, database migrations, authentication and CI.
- Add test fixtures, logging, health checks and documentation.
- Record architecture decisions and threat model.
- Exit: reproducible local deployment and green foundation tests.

### Phase 1 — Manual swipe library (first usable MVP)

- Offer catalog, CSV import, manual source URLs and authorized file uploads.
- Extract TXT/HTML/PDF/DOCX/ZIP, persist originals, deduplicate and search.
- Review queue and swipe detail UI.
- Exit: one can populate and search the library without any live crawler or paid AI service.

### Phase 2 — Permission-aware collection

- Worker queue, domain-scoped scans, bounded crawling, safe download and progress UI.
- Add optional browser adapter only after static retrieval is stable.
- Validate against authorized vendor samples supplied by the operator.
- Exit: repeated scans work safely and idempotently; partial failures remain visible.

### Phase 3 — Draft workflow and Listmonk

- Brand profiles, draft editor, subject variants, link mapping, disclosure and review checks.
- Verify installed Listmonk API with a disposable test campaign; implement draft-only export or file fallback.
- Exit: one reviewed swipe becomes an unsent draft safely.

### Phase 4 — Controlled expansion

- Pilot with 10 authorized offers before expanding to 50–100.
- Evaluate extraction accuracy and false duplicate suggestions on a reviewed sample.
- Add verified marketplace discovery provider adapters if terms permit.
- Optional AI classification, other networks, n8n notifications and campaign sequence planning.

## 11. Suggested repository layout

```text
SwipeVault/
  PRD.md
  README.md
  AGENTS.md
  .env.example
  .gitignore
  compose.yaml
  backend/
    pyproject.toml
    alembic.ini
    alembic/
    app/
      api/
      auth/
      models/
      schemas/
      services/
      workers/
      adapters/
        discovery/
        sources/
        extraction/
        listmonk/
        ai/
      security/
      settings.py
      main.py
    tests/
  frontend/
    package.json
    src/
      components/
      features/
      pages/
      api/
  fixtures/
  docs/
    architecture.md
    threat-model.md
    deployment.md
    testing.md
    adr/
  scripts/
```

### Environment configuration (example names, no secrets)

```dotenv
APP_ENV=development
APP_BASE_URL=http://localhost:8080
DATABASE_URL=postgresql+psycopg://swipevault:CHANGE_ME@postgres:5432/swipevault
REDIS_URL=redis://redis:6379/0
SESSION_SECRET=CHANGE_ME
ASSET_STORAGE_PATH=/data/assets
CRAWL_DELAY_SECONDS=2
CRAWL_MAX_PAGES=30
CRAWL_MAX_DEPTH=2
DOWNLOAD_MAX_BYTES=26214400
LISTMONK_ENABLED=false
LISTMONK_BASE_URL=
LISTMONK_API_USERNAME=
LISTMONK_API_TOKEN=
AI_PROVIDER=none
```

These are placeholders; adapt authentication fields to the verified Listmonk API. Production credentials must not be committed. Use strong generated secrets and a deployment-specific configuration.

## 12. Success metrics and pilot evaluation

- Target: 50–100 curated health and fitness offers after a 10-offer pilot; not a guarantee that all provide swipes.
- Measure offer-to-authorized-resource coverage, extraction success, manually verified subject/body accuracy, exact duplicate rate, near-duplicate false positives and job failures.
- Measure time from adding an authorized offer to obtaining reviewed drafts compared with manual collection.
- Aim for at least 95% correct subject/body extraction on a representative labeled pilot sample before expanding automation; keep uncertain results in review.
- Track 100% source provenance for stored swipes and zero unintended campaign sends.
- Do not use revenue, inbox placement or raw swipe count as proof of correctness.

## 13. Open decisions / assumptions

- The operator will supply an initial set of authorized affiliate URLs or files; there is no assumption of access to every ClickBank offer.
- No third-party discovery provider has been selected or verified. The MVP functions without one.
- Manual collection, internal single-user access, and unsent Listmonk drafts are proposed safe defaults.
- Confirm the actual Proxmox host resources, deployment path, brand settings and installed Listmonk version before production setup.
- AI is optional and off by default. No external AI costs are required for the first milestone.
- Use a private repository and private storage unless the operator explicitly changes the deployment model.

## 14. Codex kickoff prompt

Copy the prompt below into Codex or another coding agent after placing this PRD in the project root.

> You are the implementation agent for SwipeVault, a private self-hosted affiliate email swipe library. Read PRD.md end to end, inspect the existing repository before making changes, and follow any existing AGENTS.md or repository conventions. If this is a new project, initialize the structure proposed in the PRD. If a Project Command Center/Vault exists and is accessible, register SwipeVault as an active project with this PRD, milestone tracker and repo path; do not overwrite unrelated files or assume the vault path.
>
> Start with Phase 0 and Phase 1 only. Use Python/FastAPI, PostgreSQL, SQLAlchemy/Alembic, Redis/RQ, React/TypeScript/Vite and Docker Compose. Keep dependencies pinned and compatible. Build a functional manual offer catalog, CSV preview/import, authorized asset upload, deterministic extraction, exact deduplication, source provenance, search and review queue. Add synthetic fixtures, security controls and automated tests. Do not require paid AI, a ClickBank marketplace API, or real vendor credentials for the MVP.
>
> Do not bypass login, CAPTCHA, vendor approval, rate limits or source restrictions. Treat downloaded assets and AI inputs as untrusted. Keep credentials outside source control, and do not send campaigns, import recipients or interact with production Listmonk. Add a clear plan for later adapter verification.
>
> First report the repository state, architecture decisions and a short implementation plan. Then implement the agreed initial scope, run tests and builds, and document the exact commands and any failures. Do not fabricate test results. Update README.md, docs/architecture.md, docs/threat-model.md, docs/deployment.md and the milestone tracker. Stop before production deployment, paid service activation, or destructive changes unless explicitly authorized.
>
> At the end, provide a concise handoff: files changed, working features, test/build results, known limitations, local startup commands and next milestone. Prioritize a working, tested vertical slice over placeholders.

## 15. Definition of done

The MVP is done when an authenticated operator can add authorized ClickBank offer resources, import and extract email swipes, trace each to its source, search and deduplicate them, review and edit a brand-specific draft, and export the reviewed content locally (or as a verified unsent Listmonk draft in Phase 3), using a reproducible private deployment and documented tests. No unrestricted collection or automatic sending is part of the definition of done.
