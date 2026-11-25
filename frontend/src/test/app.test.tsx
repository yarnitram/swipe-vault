import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  api,
  ApiError,
  CSRF_COOKIE,
  CSRF_HEADER,
  parseApiError,
  request,
  setUnauthorizedHandler,
} from '../api/client';
import type { DraftDetail, ImportPreviewRow, Source } from '../api/types';
import HtmlPreview, { buildPreviewSrcDoc, PREVIEW_CSP } from '../components/HtmlPreview';
import ImportPreviewTable from '../components/ImportPreviewTable';
import { ToastProvider } from '../components/Toast';
import DraftDetailPage from '../pages/DraftDetailPage';
import { ScanSourceModal } from '../pages/OfferDetailPage';
import OverviewPage from '../pages/OverviewPage';

describe('api/client CSRF & error handling', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    document.cookie = `${CSRF_COOKIE}=; Max-Age=0`;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    setUnauthorizedHandler(null);
    vi.restoreAllMocks();
  });

  it('sends X-CSRF-Token header from sv_csrf cookie on unsafe methods (POST/PATCH/PUT/DELETE) and NOT on GET', async () => {
    document.cookie = `${CSRF_COOKIE}=csrf-secret-token-123`;
    const calls: { url: string; init?: RequestInit }[] = [];

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }) as unknown as typeof fetch;

    await request('/offers', { method: 'GET' });
    await request('/offers', { method: 'POST', json: { network_slug: 'clickbank', title: 'Test' } });
    await request('/offers/1', { method: 'PATCH', json: { title: 'Updated' } });
    await request('/offers/1', { method: 'DELETE' });

    expect(calls).toHaveLength(4);

    // GET must not send X-CSRF-Token
    const getHeaders = calls[0].init?.headers as Record<string, string>;
    expect(getHeaders[CSRF_HEADER]).toBeUndefined();
    expect(calls[0].init?.credentials).toBe('include');

    // POST, PATCH, DELETE must send X-CSRF-Token
    for (const call of calls.slice(1)) {
      const headers = call.init?.headers as Record<string, string>;
      expect(headers[CSRF_HEADER]).toBe('csrf-secret-token-123');
      expect(call.init?.credentials).toBe('include');
    }
  });

  it('parses the {error: {code, message, details}} envelope into a typed ApiError and triggers 401 handler', async () => {
    const res422 = new Response(
      JSON.stringify({
        error: {
          code: 'unsafe_url',
          message: 'Host resolves to private or loopback address',
          details: [{ loc: ['body', 'url'], msg: 'Loopback IP not allowed' }],
        },
      }),
      { status: 422, statusText: 'Unprocessable Entity' },
    );

    const parsed = await parseApiError(res422);
    expect(parsed).toBeInstanceOf(ApiError);
    expect(parsed.status).toBe(422);
    expect(parsed.code).toBe('unsafe_url');
    expect(parsed.message).toBe('Host resolves to private or loopback address');
    expect(parsed.fieldErrors).toEqual(['url: Loopback IP not allowed']);

    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);

    globalThis.fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({
          error: { code: 'not_authenticated', message: 'Session required', details: null },
        }),
        { status: 401 },
      ),
    ) as unknown as typeof fetch;

    await expect(api.overview()).rejects.toMatchObject({
      status: 401,
      code: 'not_authenticated',
      message: 'Session required',
    });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

describe('HtmlPreview security sandbox', () => {
  it('renders an iframe with an empty sandbox attribute and injects strict CSP meta into srcdoc', () => {
    const sampleHtml = '<p>Hello <strong>affiliate</strong></p><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" />';
    const srcDoc = buildPreviewSrcDoc(sampleHtml);

    expect(srcDoc).toContain('<meta http-equiv="Content-Security-Policy"');
    expect(srcDoc).toContain(PREVIEW_CSP);
    expect(srcDoc).toContain("default-src 'none'; style-src 'unsafe-inline'; img-src data:");
    expect(srcDoc).toContain(sampleHtml);

    render(<HtmlPreview html={sampleHtml} title="Swipe preview" />);
    const iframe = screen.getByTitle('Swipe preview') as HTMLIFrameElement;
    expect(iframe.tagName).toBe('IFRAME');
    expect(iframe.getAttribute('sandbox')).toBe('');
    expect(iframe.getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(iframe.getAttribute('srcdoc')).toContain(PREVIEW_CSP);
  });
});

describe('ImportPreviewTable', () => {
  const sampleRows: ImportPreviewRow[] = [
    {
      row_number: 1,
      status: 'valid',
      errors: [],
      existing_offer_id: null,
      data: {
        network: 'clickbank',
        external_offer_id: 'fitburn1',
        title: 'FitBurn Pro',
        niche: 'Health & fitness',
        vendor_name: 'FitLabs',
        offer_url: 'https://fitburn.example.com',
        affiliate_resources_url: 'https://fitburn.example.com/affiliates',
        notes: '',
      },
    },
    {
      row_number: 2,
      status: 'invalid',
      errors: ['title is required', 'offer_url must be http or https'],
      existing_offer_id: null,
      data: {
        network: 'clickbank',
        external_offer_id: 'badrow',
        title: '',
        niche: 'Health & fitness',
        vendor_name: '',
        offer_url: 'ftp://bad',
        affiliate_resources_url: '',
        notes: '',
      },
    },
    {
      row_number: 3,
      status: 'duplicate_existing',
      errors: [],
      existing_offer_id: '11111111-2222-3333-4444-555555555555',
      data: {
        network: 'clickbank',
        external_offer_id: 'existing1',
        title: 'Existing Offer',
        niche: 'Health & fitness',
        vendor_name: 'VendorX',
        offer_url: '',
        affiliate_resources_url: '',
        notes: '',
      },
    },
    {
      row_number: 4,
      status: 'duplicate_in_file',
      errors: ['Duplicate of row 1 in CSV'],
      existing_offer_id: null,
      data: {
        network: 'clickbank',
        external_offer_id: 'fitburn1',
        title: 'FitBurn Pro Duplicate',
        niche: 'Health & fitness',
        vendor_name: 'FitLabs',
        offer_url: '',
        affiliate_resources_url: '',
        notes: '',
      },
    },
  ];

  it('renders all row statuses, error messages, and only allows selecting valid rows', async () => {
    const onToggle = vi.fn();
    const onToggleAll = vi.fn();
    render(
      <ImportPreviewTable
        rows={sampleRows}
        selected={new Set([1])}
        onToggle={onToggle}
        onToggleAll={onToggleAll}
      />,
    );

    expect(screen.getByText('valid')).toBeInTheDocument();
    expect(screen.getByText('invalid')).toBeInTheDocument();
    expect(screen.getByText('duplicate (existing)')).toBeInTheDocument();
    expect(screen.getByText('duplicate (in file)')).toBeInTheDocument();

    expect(screen.getByText('title is required')).toBeInTheDocument();
    expect(screen.getByText('offer_url must be http or https')).toBeInTheDocument();
    expect(screen.getByText('existing offer')).toHaveAttribute(
      'href',
      '/offers/11111111-2222-3333-4444-555555555555',
    );

    const row1Box = screen.getByLabelText('Select row 1') as HTMLInputElement;
    const row2Box = screen.getByLabelText('Select row 2') as HTMLInputElement;
    const row3Box = screen.getByLabelText('Select row 3') as HTMLInputElement;
    const row4Box = screen.getByLabelText('Select row 4') as HTMLInputElement;

    expect(row1Box).not.toBeDisabled();
    expect(row1Box).toBeChecked();
    expect(row2Box).toBeDisabled();
    expect(row3Box).toBeDisabled();
    expect(row4Box).toBeDisabled();

    await userEvent.click(row1Box);
    expect(onToggle).toHaveBeenCalledWith(1);
  });
});

describe('OverviewPage render with mocked fetch', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('renders live overview statistics and recent jobs from the API', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/stats/overview')) {
        return new Response(
          JSON.stringify({
            offers_total: 42,
            swipes_total: 187,
            pending_reviews: 19,
            needs_changes: 4,
            approved: 150,
            assets_total: 63,
            drafts_total: 7,
            failed_jobs: 1,
            active_jobs: 2,
            last_ingested_at: '2026-11-25T01:30:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url.includes('/api/v1/jobs')) {
        return new Response(
          JSON.stringify({
            items: [
              {
                id: 'abcdef12-3456-7890-abcd-ef1234567890',
                offer_id: 'offer-uuid-1',
                source_id: null,
                type: 'ingest_asset',
                state: 'completed',
                progress: {
                  pages_checked: 0,
                  assets_found: 1,
                  assets_processed: 1,
                  swipes_extracted: 5,
                  swipes_new: 5,
                  versions_new: 0,
                  duplicates: 0,
                  warnings: 0,
                },
                attempts: 1,
                error_summary: null,
                created_at: '2026-11-25T01:29:00Z',
                started_at: '2026-11-25T01:29:01Z',
                finished_at: '2026-11-25T01:29:04Z',
                elapsed_seconds: 3,
                offer_title: 'MetaboFlex Greens',
              },
            ],
            total: 1,
            page: 1,
            page_size: 8,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response('Not found', { status: 404 });
    }) as unknown as typeof fetch;

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('42')).toBeInTheDocument();
    });
    expect(screen.getByText('187')).toBeInTheDocument();
    expect(screen.getByText('19')).toBeInTheDocument();
    expect(screen.getByText('150')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('MetaboFlex Greens')).toBeInTheDocument();
    expect(screen.getByText(/ingest_asset · abcdef12/)).toBeInTheDocument();
  });
});

describe('Phase 2 ScanSourceModal authorization confirmation', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const sampleSource: Source = {
    id: 'src-uuid-123',
    offer_id: 'offer-uuid-1',
    url: 'https://vendor.example.com/affiliates/swipes',
    normalized_url: 'https://vendor.example.com/affiliates/swipes',
    source_type: 'affiliate_page',
    access_state: 'authorized',
    permission_notes: 'Approved affiliate tools page',
    allowed_hosts: ['vendor.example.com'],
    last_checked_at: null,
    created_at: '2026-11-25T01:00:00Z',
  };

  it('requires confirm_authorized checkbox before calling POST /sources/{id}/scan', async () => {
    const calls: { url: string; body: unknown }[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null });
      return new Response(
        JSON.stringify({
          id: 'job-scan-12345678',
          offer_id: 'offer-uuid-1',
          source_id: 'src-uuid-123',
          type: 'scan_source',
          state: 'queued',
          progress: {
            pages_checked: 0,
            assets_found: 0,
            assets_processed: 0,
            swipes_extracted: 0,
            swipes_new: 0,
            versions_new: 0,
            duplicates: 0,
            warnings: 0,
          },
          attempts: 0,
          error_summary: null,
          created_at: '2026-11-25T02:00:00Z',
          started_at: null,
          finished_at: null,
          elapsed_seconds: null,
          offer_title: 'FitBurn Pro',
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      );
    }) as unknown as typeof fetch;

    const onStarted = vi.fn();
    const onClose = vi.fn();
    render(<ScanSourceModal source={sampleSource} onClose={onClose} onStarted={onStarted} />);

    expect(screen.getAllByText('vendor.example.com').length).toBeGreaterThan(0);
    expect(screen.getByText('Approved affiliate tools page')).toBeInTheDocument();

    const startBtn = screen.getByRole('button', { name: 'Start scan' });
    expect(startBtn).toBeDisabled();
    expect(calls).toHaveLength(0);

    const checkbox = screen.getByRole('checkbox', {
      name: /I confirm I am authorized to retrieve and store creative assets from this vendor source/i,
    });
    await userEvent.click(checkbox);
    expect(startBtn).not.toBeDisabled();

    await userEvent.click(startBtn);
    await waitFor(() => {
      expect(onStarted).toHaveBeenCalledWith('job-scan-12345678');
    });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('/api/v1/sources/src-uuid-123/scan');
    expect(calls[0].body).toEqual({ confirm_authorized: true });
  });
});

describe('Phase 3 DraftDetailPage approval & export gating (AC-11)', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const makeDraft = (overrides: Partial<DraftDetail> = {}): DraftDetail => ({
    id: 'draft-uuid-1',
    swipe_id: 'swipe-uuid-1',
    swipe_version_id: 'sv-uuid-1',
    swipe_version_number: 1,
    offer: {
      id: 'offer-uuid-1',
      title: 'FitBurn Pro',
      vendor_name: 'FitLabs',
      network_slug: 'clickbank',
    },
    brand: {
      id: 'brand-uuid-1',
      name: 'MyFitterU',
      slug: 'myfitteru',
    },
    title: 'FitBurn Morning Routine Draft',
    subject: 'The 30-second morning metabolism habit',
    preheader: 'Quick morning routine check',
    affiliate_url: 'https://hop.clickbank.net/?affiliate=myfitteru&vendor=fitburn',
    body_html:
      '<p>Read the morning guide: <a href="https://hop.clickbank.net/?affiliate=myfitteru&vendor=fitburn">Click here</a></p><hr><p>Affiliate disclosure: We may earn a commission.</p><p>Sent by MyFitterU. Unsubscribe anytime.</p>',
    body_text:
      'Read the morning guide: https://hop.clickbank.net/?affiliate=myfitteru&vendor=fitburn\n\nAffiliate disclosure: We may earn a commission.\nSent by MyFitterU. Unsubscribe anytime.',
    status: 'editing',
    version: 2,
    approved_version: null,
    approved_at: null,
    review_checks: {
      has_affiliate_url: true,
      affiliate_url_valid: true,
      has_disclosure: true,
      has_sender_footer: true,
      unresolved_placeholders: [],
      unexpected_hosts: [],
      claim_flags: [],
      warnings: [],
      ready_for_approval: true,
    },
    sequence_position: 1,
    suggested_day_offset: 0,
    created_at: '2026-11-25T01:00:00Z',
    updated_at: '2026-11-25T01:30:00Z',
    available_subjects: ['The 30-second morning metabolism habit', 'Why breakfast timing matters'],
    source_ctas: [{ text: 'Click here', url: 'https://vendor.example.com/go', placeholder: null }],
    exports: [],
    ...overrides,
  });

  it('disables export and local downloads when draft is in editing state (AC-11), and enables them once approved', async () => {
    let currentDraft = makeDraft({ status: 'editing', version: 2, approved_version: null });

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/drafts/draft-uuid-1' && (!init?.method || init.method === 'GET')) {
        return new Response(JSON.stringify(currentDraft), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/v1/drafts/draft-uuid-1/approve' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        expect(body).toEqual({ version: 2 });
        currentDraft = makeDraft({
          status: 'approved',
          version: 2,
          approved_version: 2,
          approved_at: '2026-11-25T02:10:00Z',
        });
        return new Response(JSON.stringify(currentDraft), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('Not found', { status: 404 });
    }) as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={['/drafts/draft-uuid-1']}>
        <ToastProvider>
          <Routes>
            <Route path="/drafts/:id" element={<DraftDetailPage />} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('FitBurn Morning Routine Draft')).toBeInTheDocument();
    });

    // In editing state: export is locked and download links are not rendered
    expect(screen.getByTestId('export-locked-msg')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Download HTML' })).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Export locked until v2 is approved/i }),
    ).toBeDisabled();

    // Approve draft v2
    const approveBtn = screen.getByRole('button', { name: 'Approve Draft v2' });
    expect(approveBtn).not.toBeDisabled();
    await userEvent.click(approveBtn);

    // After approval: download links and Listmonk list loader button are enabled
    await waitFor(() => {
      expect(screen.getByTestId('draft-approved-banner')).toBeInTheDocument();
    });

    const htmlDownload = screen.getByRole('link', { name: 'Download HTML' });
    const txtDownload = screen.getByRole('link', { name: 'Download Plain Text' });
    expect(htmlDownload).toHaveAttribute('href', '/api/v1/drafts/draft-uuid-1/download?format=html');
    expect(txtDownload).toHaveAttribute('href', '/api/v1/drafts/draft-uuid-1/download?format=txt');

    const loadListsBtn = screen.getByRole('button', { name: /Load consent-based lists from Listmonk/i });
    expect(loadListsBtn).not.toBeDisabled();
  });
});
