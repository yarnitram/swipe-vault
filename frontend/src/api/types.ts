// TypeScript types mirroring docs/api.md (Phases 0–3 contract).

export type UUID = string;
export type ISODateTime = string;

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
  };
}

// ---- Auth ----
export interface User {
  id: UUID;
  email: string;
  role: 'admin';
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  user: User;
}

// ---- Health & Runtime Settings ----
export interface HealthLive {
  status: 'ok';
}

export interface HealthReady {
  status: 'ok' | 'degraded';
  database: 'ok' | 'error';
  redis: 'ok' | 'error';
}

export interface RuntimeSettings {
  crawl_delay_seconds: number;
  crawl_max_pages: number;
  crawl_max_depth: number;
  crawl_timeout_seconds: number;
  download_max_bytes: number;
  near_duplicate_threshold: number;
  listmonk_enabled: boolean;
  listmonk_configured: boolean;
  listmonk_base_url: string | null;
  ai_provider: string;
}

// ---- Overview ----
export interface OverviewStats {
  offers_total: number;
  swipes_total: number;
  pending_reviews: number;
  needs_changes: number;
  approved: number;
  assets_total: number;
  drafts_total?: number;
  failed_jobs: number;
  active_jobs: number;
  last_ingested_at: ISODateTime | null;
}

// ---- Networks ----
export interface Network {
  id: UUID;
  slug: string;
  name: string;
  enabled: boolean;
}

// ---- Offers ----
export const APPROVAL_STATES = ['unknown', 'requested', 'approved', 'denied', 'revoked'] as const;
export type ApprovalState = (typeof APPROVAL_STATES)[number];

export interface OfferNetworkRef {
  id: UUID;
  slug: string;
  name: string;
}

export interface Offer {
  id: UUID;
  network: OfferNetworkRef;
  external_offer_id: string | null;
  title: string;
  niche: string | null;
  vendor_name: string | null;
  offer_url: string | null;
  affiliate_resources_url: string | null;
  approval_state: ApprovalState;
  metrics_json: Record<string, unknown> | null;
  metrics_source: string | null;
  metrics_as_of: ISODateTime | null;
  notes: string | null;
  last_verified_at: ISODateTime | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  swipe_count: number;
  asset_count: number;
  source_count: number;
}

export interface OfferCreate {
  network_slug: string;
  title: string;
  external_offer_id?: string | null;
  niche?: string | null;
  vendor_name?: string | null;
  offer_url?: string | null;
  affiliate_resources_url?: string | null;
  notes?: string | null;
}

export interface OfferUpdate extends Partial<OfferCreate> {
  metrics_json?: Record<string, unknown> | null;
  metrics_source?: string | null;
  metrics_as_of?: ISODateTime | null;
  last_verified_at?: ISODateTime | null;
}

export interface OfferListParams {
  q?: string;
  network?: string;
  niche?: string;
  approval_state?: ApprovalState | '';
  page?: number;
  page_size?: number;
}

export interface Approval {
  id: UUID;
  state: ApprovalState;
  notes: string | null;
  user_email: string | null;
  created_at: ISODateTime;
}

export interface ApprovalCreate {
  state: ApprovalState;
  notes?: string | null;
}

// ---- CSV import ----
export interface ImportRowData {
  network: string;
  external_offer_id: string;
  title: string;
  niche: string;
  vendor_name: string;
  offer_url: string;
  affiliate_resources_url: string;
  notes: string;
}

export type ImportRowStatus = 'valid' | 'invalid' | 'duplicate_existing' | 'duplicate_in_file';

export interface ImportPreviewRow {
  row_number: number;
  data: ImportRowData;
  status: ImportRowStatus;
  errors: string[];
  existing_offer_id: UUID | null;
}

export interface ImportPreviewResponse {
  rows: ImportPreviewRow[];
  summary: {
    total: number;
    valid: number;
    invalid: number;
    duplicates: number;
  };
}

export interface ImportCommitRequest {
  rows: { row_number: number; data: ImportRowData }[];
}

export interface ImportCommitResponse {
  created: { row_number: number; offer_id: UUID }[];
  skipped: { row_number: number; reason: string }[];
}

// ---- Sources (Phase 2 scanning) ----
export const SOURCE_TYPES = ['affiliate_page', 'offer_page', 'asset_url', 'other'] as const;
export type SourceType = (typeof SOURCE_TYPES)[number];

export const ACCESS_STATES = [
  'unverified',
  'authorized',
  'restricted',
  'approval_required',
  'forbidden',
] as const;
export type AccessState = (typeof ACCESS_STATES)[number];

export const NON_SCANNABLE_ACCESS_STATES: readonly AccessState[] = [
  'restricted',
  'approval_required',
  'forbidden',
];

export interface Source {
  id: UUID;
  offer_id: UUID;
  url: string;
  normalized_url: string;
  source_type: SourceType;
  access_state: AccessState;
  permission_notes: string | null;
  allowed_hosts: string[];
  last_checked_at: ISODateTime | null;
  created_at: ISODateTime;
}

export interface SourceCreate {
  url: string;
  source_type: SourceType;
  access_state?: AccessState;
  permission_notes?: string | null;
  allowed_hosts?: string[];
}

export interface SourceUpdate {
  access_state?: AccessState;
  permission_notes?: string | null;
  allowed_hosts?: string[];
  source_type?: SourceType;
}

export interface SourceScanRequest {
  confirm_authorized: boolean;
}

// ---- Assets ----
export type ExtractionState =
  | 'pending'
  | 'processing'
  | 'extracted'
  | 'needs_review'
  | 'failed'
  | 'unsupported';

export interface Asset {
  id: UUID;
  asset_source_id: UUID | null;
  sha256: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  extraction_state: ExtractionState;
  extraction_error: string | null;
  parent_asset_id: UUID | null;
  origin: 'upload' | 'scan' | 'archive_entry';
  retrieval_url?: string | null;
  version_label: string | null;
  retrieved_at: ISODateTime;
  swipe_count: number;
}

export interface AssetUploadResponse {
  job: Job;
  asset: Asset;
  duplicate_asset: boolean;
}

// ---- Jobs ----
export const JOB_STATES = [
  'queued',
  'running',
  'completed',
  'partial',
  'failed',
  'cancel_requested',
  'cancelled',
] as const;
export type JobState = (typeof JOB_STATES)[number];

export type JobType = 'ingest_asset' | 'scan_source';

export const TERMINAL_JOB_STATES: readonly JobState[] = ['completed', 'partial', 'failed', 'cancelled'];

export interface JobProgress {
  pages_checked?: number;
  assets_found: number;
  assets_processed: number;
  swipes_extracted: number;
  swipes_new: number;
  versions_new: number;
  duplicates: number;
  warnings: number;
}

export interface Job {
  id: UUID;
  offer_id: UUID | null;
  source_id: UUID | null;
  type: JobType;
  state: JobState;
  progress: JobProgress;
  attempts: number;
  error_summary: string | null;
  created_at: ISODateTime;
  started_at: ISODateTime | null;
  finished_at: ISODateTime | null;
  elapsed_seconds: number | null;
  offer_title: string | null;
}

export interface JobEvent {
  id: UUID;
  level: 'info' | 'warning' | 'error';
  event_type: string;
  message: string;
  created_at: ISODateTime;
}

export type JobDetail = Job & { events: JobEvent[] };

export interface JobListParams {
  state?: JobState | '';
  offer_id?: string;
  type?: JobType | '';
  page?: number;
  page_size?: number;
}

// ---- Swipes ----
export const REVIEW_STATES = ['pending', 'needs_changes', 'approved', 'rejected', 'archived'] as const;
export type ReviewState = (typeof REVIEW_STATES)[number];
export type ReviewDecision = ReviewState;

export type SwipeSort = 'relevance' | 'newest' | 'confidence';

export interface SwipeOfferRef {
  id: UUID;
  title: string;
  vendor_name: string | null;
  niche: string | null;
  network_slug: string;
}

export interface SwipeCurrentVersionSummary {
  id: UUID;
  version_number: number;
  primary_subject: string | null;
  subject_count: number;
  preheader: string | null;
  body_excerpt: string;
  confidence: number;
  flags: string[];
}

export interface SwipeSummary {
  id: UUID;
  offer: SwipeOfferRef;
  title: string | null;
  review_state: ReviewState;
  current_version: SwipeCurrentVersionSummary;
  version_count: number;
  tags: string[];
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface SwipeSubject {
  id: UUID;
  subject: string;
  position: number;
}

export interface SwipeCta {
  text: string;
  url: string | null;
  placeholder: string | null;
}

export interface Provenance {
  id: UUID;
  asset_id: UUID;
  asset_filename: string;
  origin: string;
  retrieval_url: string | null;
  retrieved_at: ISODateTime;
  page_number: number | null;
  section_label: string | null;
}

export interface ReviewEvent {
  id: UUID;
  decision: ReviewDecision;
  notes: string | null;
  user_email: string | null;
  created_at: ISODateTime;
}

export interface SwipeVersion {
  id: UUID;
  version_number: number;
  subjects: SwipeSubject[];
  preheader: string | null;
  body_text: string;
  body_html_sanitized: string | null;
  ctas: SwipeCta[];
  normalized_hash: string;
  parser_version: string;
  confidence: number;
  flags: string[];
  section_label: string | null;
  created_at: ISODateTime;
  provenance: Provenance[];
  review_events: ReviewEvent[];
}

export interface SwipeDuplicates {
  exact_other_offers: { swipe_id: UUID; offer_id: UUID; offer_title: string }[];
  near: { swipe_id: UUID; offer_title: string; title: string | null; similarity: number }[];
}

export interface SwipeDetail extends Omit<SwipeSummary, 'current_version'> {
  notes: string | null;
  current_version_id: UUID;
  versions: SwipeVersion[];
  duplicates: SwipeDuplicates;
}

export interface SwipeListParams {
  q?: string;
  network?: string;
  niche?: string;
  review_state?: ReviewState | '';
  offer_id?: string;
  tag?: string;
  created_from?: string;
  created_to?: string;
  sort?: SwipeSort | '';
  page?: number;
  page_size?: number;
}

export interface SwipeUpdate {
  title?: string | null;
  notes?: string | null;
}

export interface SwipeReviewRequest {
  version_id: UUID;
  decision: ReviewDecision;
  notes?: string | null;
}

export interface SwipeBulkRequest {
  swipe_ids: UUID[];
  action: 'add_tags' | 'archive';
  tags?: string[];
}

export interface SwipeBulkResponse {
  updated: number;
}

export interface Tag {
  id: UUID;
  slug: string;
  label: string;
  swipe_count: number;
}

export const FLAG_DESCRIPTIONS: Record<string, string> = {
  missing_subject: 'No subject line was detected',
  missing_body: 'No body text was detected',
  no_boundary_marker: 'Email boundaries were inferred without explicit markers',
  short_body: 'Body is unusually short',
  missing_cta: 'No call-to-action link was detected',
  health_claim: 'Contains possible health claims',
  guarantee_claim: 'Contains possible guarantee/promise language',
  income_claim: 'Contains possible income claims',
  testimonial: 'Contains possible testimonial/endorsement',
  placeholder_link: 'Contains a placeholder link to replace',
};

// ---- Brand Profiles (Phase 3 — FR-07) ----
export interface BrandAffiliateSettings {
  default_tracking_param?: string | null;
  allowed_affiliate_hosts?: string[];
}

export interface BrandProfile {
  id: UUID;
  name: string;
  slug: string;
  sender_identity_ref: string | null;
  affiliate_settings_json: BrandAffiliateSettings;
  disclosure_text: string;
  footer_template: string;
  integration_ref: string | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface BrandCreate {
  name: string;
  sender_identity_ref?: string | null;
  affiliate_settings_json?: BrandAffiliateSettings;
  disclosure_text?: string;
  footer_template?: string;
  integration_ref?: string | null;
}

export type BrandUpdate = Partial<BrandCreate>;

// ---- Campaign Drafts (Phase 3 — FR-07) ----
export const DRAFT_STATUSES = ['editing', 'approved', 'exported', 'archived'] as const;
export type DraftStatus = (typeof DRAFT_STATUSES)[number];

export interface DraftReviewChecks {
  has_affiliate_url: boolean;
  affiliate_url_valid: boolean;
  has_disclosure: boolean;
  has_sender_footer: boolean;
  unresolved_placeholders: string[];
  unexpected_hosts: string[];
  claim_flags: string[];
  warnings: string[];
  ready_for_approval: boolean;
}

export interface DraftOfferRef {
  id: UUID;
  title: string;
  vendor_name: string | null;
  network_slug: string;
}

export interface DraftBrandRef {
  id: UUID;
  name: string;
  slug: string;
}

export interface Draft {
  id: UUID;
  swipe_id: UUID;
  swipe_version_id: UUID;
  swipe_version_number: number;
  offer: DraftOfferRef;
  brand: DraftBrandRef;
  title: string;
  subject: string;
  preheader: string | null;
  affiliate_url: string | null;
  body_html: string;
  body_text: string;
  status: DraftStatus;
  version: number;
  approved_version: number | null;
  approved_at: ISODateTime | null;
  review_checks: DraftReviewChecks;
  sequence_position: number | null;
  suggested_day_offset: number | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface DraftDetail extends Draft {
  available_subjects: string[];
  source_ctas: SwipeCta[];
  exports: ExportRecord[];
}

export interface DraftListParams {
  brand_id?: string;
  offer_id?: string;
  status?: DraftStatus | '';
  page?: number;
  page_size?: number;
}

export interface DraftCreate {
  swipe_id: UUID;
  brand_id: UUID;
  subject_position?: number;
  affiliate_url?: string | null;
  replace_urls?: string[];
  sequence_position?: number | null;
  suggested_day_offset?: number | null;
}

export interface DraftUpdate {
  title?: string;
  subject?: string;
  preheader?: string | null;
  body_text?: string;
  body_html?: string;
  affiliate_url?: string | null;
  replace_placeholders?: boolean;
  replace_urls?: string[];
  append_brand_footer?: boolean;
  sequence_position?: number | null;
  suggested_day_offset?: number | null;
  status?: 'editing' | 'archived';
}

export interface DraftApproveRequest {
  version: number;
}

// ---- Listmonk Draft Integration (Phase 3 — FR-08) ----
export type ExportStatus = 'pending' | 'completed' | 'failed' | 'needs_reconciliation';

export interface ExportRecord {
  id: UUID;
  draft_id: UUID;
  draft_version: number;
  target: 'listmonk' | 'local_download';
  idempotency_key: string;
  remote_id: string | null;
  remote_url: string | null;
  status: ExportStatus;
  error_summary: string | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ListmonkListRef {
  id: number;
  name: string;
  type: string;
}

export interface ListmonkTestResponse {
  enabled: boolean;
  configured: boolean;
  reachable: boolean;
  lists: ListmonkListRef[];
  message: string;
}

export interface ListmonkExportRequest {
  list_ids: number[];
  confirm_unsent_draft: boolean;
}
