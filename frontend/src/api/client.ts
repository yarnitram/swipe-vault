import type {
  Approval,
  ApprovalCreate,
  Asset,
  AssetUploadResponse,
  ImportCommitRequest,
  ImportCommitResponse,
  ImportPreviewResponse,
  Job,
  JobDetail,
  JobListParams,
  LoginRequest,
  LoginResponse,
  Network,
  Offer,
  OfferCreate,
  OfferListParams,
  OfferUpdate,
  OverviewStats,
  Paginated,
  Source,
  SourceCreate,
  SourceUpdate,
  SwipeBulkRequest,
  SwipeBulkResponse,
  SwipeDetail,
  SwipeListParams,
  SwipeReviewRequest,
  SwipeSummary,
  SwipeUpdate,
  Tag,
  User,
} from './types';

export const API_BASE = '/api/v1';
export const CSRF_COOKIE = 'sv_csrf';
export const CSRF_HEADER = 'X-CSRF-Token';

const UNSAFE_METHODS = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

/** Typed error parsed from the `{error: {code, message, details}}` envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field errors for `422 validation_error`, flattened to readable strings. */
  get fieldErrors(): string[] {
    if (!Array.isArray(this.details)) return [];
    return this.details.map((d) => {
      if (typeof d === 'string') return d;
      if (d && typeof d === 'object') {
        const rec = d as Record<string, unknown>;
        const loc = Array.isArray(rec.loc) ? rec.loc.filter((p) => p !== 'body').join('.') : rec.field;
        const msg = rec.msg ?? rec.message ?? JSON.stringify(d);
        return loc ? `${String(loc)}: ${String(msg)}` : String(msg);
      }
      return String(d);
    });
  }
}

/** Convert any Response into an ApiError, tolerating non-envelope bodies. */
export async function parseApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  const text = await res.text().catch(() => '');
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (body && typeof body === 'object' && 'error' in body) {
    const err = (body as { error: unknown }).error;
    if (err && typeof err === 'object') {
      const e = err as Record<string, unknown>;
      return new ApiError(
        res.status,
        typeof e.code === 'string' ? e.code : `http_${res.status}`,
        typeof e.message === 'string' ? e.message : res.statusText || 'Request failed',
        e.details ?? null,
      );
    }
  }
  return new ApiError(res.status, `http_${res.status}`, res.statusText || `Request failed (${res.status})`, null);
}

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const parts = document.cookie ? document.cookie.split(';') : [];
  for (const part of parts) {
    const idx = part.indexOf('=');
    if (idx < 0) continue;
    const k = part.slice(0, idx).trim();
    if (k === name) return decodeURIComponent(part.slice(idx + 1).trim());
  }
  return null;
}

type UnauthorizedHandler = () => void;

const defaultUnauthorizedHandler: UnauthorizedHandler = () => {
  if (typeof window === 'undefined') return;
  const { pathname, search } = window.location;
  if (pathname === '/login') return;
  const next = encodeURIComponent(pathname + search);
  window.location.assign(`/login?next=${next}`);
};

let unauthorizedHandler: UnauthorizedHandler = defaultUnauthorizedHandler;

/** Override the 401 behaviour (used by tests or the auth context). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler ?? defaultUnauthorizedHandler;
}

export interface RequestOptions {
  method?: string;
  query?: object;
  json?: unknown;
  body?: FormData;
  signal?: AbortSignal;
  /** Do not trigger the global 401 redirect (login and /auth/me). */
  skipAuthRedirect?: boolean;
}

export function buildQuery(query?: object): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query as Record<string, unknown>)) {
    if (v === undefined || v === null || v === '') continue;
    params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = (opts.method ?? 'GET').toUpperCase();
  const headers: Record<string, string> = { Accept: 'application/json' };
  let body: BodyInit | undefined;

  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.json);
  } else if (opts.body) {
    body = opts.body; // browser sets multipart boundary
  }

  if (UNSAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers[CSRF_HEADER] = token;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}${buildQuery(opts.query)}`, {
      method,
      headers,
      body,
      credentials: 'include',
      signal: opts.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'network_error', 'Network error: could not reach the API server.', null);
  }

  if (!res.ok) {
    const err = await parseApiError(res);
    if (res.status === 401 && !opts.skipAuthRedirect) unauthorizedHandler();
    throw err;
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export function assetDownloadUrl(assetId: string): string {
  return `${API_BASE}/assets/${encodeURIComponent(assetId)}/download`;
}

const enc = encodeURIComponent;

export const api = {
  // Auth
  login: (body: LoginRequest) =>
    request<LoginResponse>('/auth/login', { method: 'POST', json: body, skipAuthRedirect: true }),
  logout: () => request<void>('/auth/logout', { method: 'POST', skipAuthRedirect: true }),
  me: () => request<User>('/auth/me', { skipAuthRedirect: true }),

  // Overview / networks
  overview: () => request<OverviewStats>('/stats/overview'),
  networks: () => request<Network[]>('/networks'),

  // Offers
  listOffers: (params: OfferListParams = {}) => request<Paginated<Offer>>('/offers', { query: params }),
  createOffer: (body: OfferCreate) => request<Offer>('/offers', { method: 'POST', json: body }),
  niches: () => request<string[]>('/offers/niches'),
  getOffer: (id: string) => request<Offer>(`/offers/${enc(id)}`),
  updateOffer: (id: string, body: OfferUpdate) =>
    request<Offer>(`/offers/${enc(id)}`, { method: 'PATCH', json: body }),
  listApprovals: (id: string) => request<Approval[]>(`/offers/${enc(id)}/approvals`),
  createApproval: (id: string, body: ApprovalCreate) =>
    request<Approval>(`/offers/${enc(id)}/approvals`, { method: 'POST', json: body }),
  importPreview: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<ImportPreviewResponse>('/offers/import/preview', { method: 'POST', body: fd });
  },
  importCommit: (body: ImportCommitRequest) =>
    request<ImportCommitResponse>('/offers/import/commit', { method: 'POST', json: body }),

  // Sources
  listSources: (offerId: string) => request<Source[]>(`/offers/${enc(offerId)}/sources`),
  createSource: (offerId: string, body: SourceCreate) =>
    request<Source>(`/offers/${enc(offerId)}/sources`, { method: 'POST', json: body }),
  updateSource: (id: string, body: SourceUpdate) =>
    request<Source>(`/sources/${enc(id)}`, { method: 'PATCH', json: body }),

  // Assets
  listAssets: (offerId: string) => request<Asset[]>(`/offers/${enc(offerId)}/assets`),
  uploadAsset: (offerId: string, file: File, opts: { sourceId?: string; notes?: string } = {}) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('confirm_authorized', 'true');
    if (opts.sourceId) fd.append('source_id', opts.sourceId);
    if (opts.notes) fd.append('notes', opts.notes);
    return request<AssetUploadResponse>(`/offers/${enc(offerId)}/assets`, { method: 'POST', body: fd });
  },

  // Jobs
  listJobs: (params: JobListParams = {}) => request<Paginated<Job>>('/jobs', { query: params }),
  getJob: (id: string, signal?: AbortSignal) => request<JobDetail>(`/jobs/${enc(id)}`, { signal }),
  cancelJob: (id: string) => request<Job>(`/jobs/${enc(id)}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/jobs/${enc(id)}/retry`, { method: 'POST' }),

  // Swipes
  listSwipes: (params: SwipeListParams = {}) => request<Paginated<SwipeSummary>>('/swipes', { query: params }),
  getSwipe: (id: string) => request<SwipeDetail>(`/swipes/${enc(id)}`),
  updateSwipe: (id: string, body: SwipeUpdate) =>
    request<SwipeDetail>(`/swipes/${enc(id)}`, { method: 'PATCH', json: body }),
  reviewSwipe: (id: string, body: SwipeReviewRequest) =>
    request<SwipeDetail>(`/swipes/${enc(id)}/review`, { method: 'POST', json: body }),
  setSwipeTags: (id: string, tags: string[]) =>
    request<SwipeDetail>(`/swipes/${enc(id)}/tags`, { method: 'POST', json: { tags } }),
  bulkSwipes: (body: SwipeBulkRequest) =>
    request<SwipeBulkResponse>('/swipes/bulk', { method: 'POST', json: body }),
  tags: () => request<Tag[]>('/tags'),
};

/** Human-readable message for any thrown value. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const fields = e.fieldErrors;
    return fields.length ? `${e.message} (${fields.join('; ')})` : e.message;
  }
  if (e instanceof Error) return e.message;
  return 'Unexpected error';
}
