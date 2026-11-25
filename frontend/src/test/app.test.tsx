import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
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
import type { ImportPreviewRow } from '../api/types';
import HtmlPreview, { buildPreviewSrcDoc, PREVIEW_CSP } from '../components/HtmlPreview';
import ImportPreviewTable from '../components/ImportPreviewTable';
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
    expect(screen.getByText('MetaboFlex Greens')).toBeInTheDocument();
    expect(screen.getByText(/ingest_asset · abcdef12/)).toBeInTheDocument();
  });
});
