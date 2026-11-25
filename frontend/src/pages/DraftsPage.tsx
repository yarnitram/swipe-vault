import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { DRAFT_STATUSES, type DraftStatus } from '../api/types';
import {
  Badge,
  DraftStatusBadge,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  Spinner,
} from '../components/ui';
import { formatDateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';

const PAGE_SIZE = 25;

export default function DraftsPage() {
  const [params, setParams] = useSearchParams();
  const brandId = params.get('brand_id') ?? '';
  const offerId = params.get('offer_id') ?? '';
  const status = (params.get('status') ?? '') as DraftStatus | '';
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1);

  const brands = useAsync(() => api.listBrands(), []);
  const drafts = useAsync(
    () =>
      api.listDrafts({
        brand_id: brandId || undefined,
        offer_id: offerId || undefined,
        status: status || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [brandId, offerId, status, page],
  );

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next);
  };

  return (
    <div>
      <PageHeader
        title="Campaign Drafts"
        subtitle="Brand-specific email drafts prepared from approved swipes."
        actions={
          <Link to="/swipes?review_state=approved" className="btn-secondary">
            Browse approved swipes →
          </Link>
        }
      />

      <div className="card mb-4 p-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label className="label" htmlFor="drafts-brand">
              Brand profile
            </label>
            <select
              id="drafts-brand"
              className="input"
              value={brandId}
              onChange={(e) => updateParam('brand_id', e.target.value)}
            >
              <option value="">All brands</option>
              {(brands.data ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="drafts-status">
              Status
            </label>
            <select
              id="drafts-status"
              className="input"
              value={status}
              onChange={(e) => updateParam('status', e.target.value)}
            >
              <option value="">All statuses</option>
              {DRAFT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
        {offerId && (
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-600">
            <span>Filtered by offer:</span>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">{offerId}</code>
            <button type="button" className="link" onClick={() => updateParam('offer_id', '')}>
              Clear offer filter
            </button>
          </div>
        )}
      </div>

      {drafts.loading && !drafts.data ? (
        <Spinner label="Loading drafts…" />
      ) : drafts.error ? (
        <ErrorState message={drafts.error} onRetry={drafts.reload} />
      ) : !drafts.data || drafts.data.items.length === 0 ? (
        <EmptyState title="No campaign drafts yet">
          Open an approved swipe in the Swipe Library and click &ldquo;Create Campaign Draft&rdquo;.
        </EmptyState>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Draft</th>
                  <th>Brand</th>
                  <th>Offer</th>
                  <th>Subject</th>
                  <th>Sequence</th>
                  <th>Version</th>
                  <th>Status</th>
                  <th>Checks</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {drafts.data.items.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <Link to={`/drafts/${d.id}`} className="link font-medium">
                        {d.title}
                      </Link>
                      <div className="text-xs text-slate-400">
                        from swipe v{d.swipe_version_number}
                      </div>
                    </td>
                    <td>
                      <Badge tone="indigo">{d.brand.name}</Badge>
                    </td>
                    <td>
                      <Link to={`/offers/${d.offer.id}`} className="link text-xs">
                        {d.offer.title}
                      </Link>
                    </td>
                    <td className="max-w-xs truncate text-sm">{d.subject}</td>
                    <td className="whitespace-nowrap text-xs">
                      {d.sequence_position !== null ? (
                        <Badge tone="slate">
                          #{d.sequence_position}
                          {d.suggested_day_offset !== null ? ` · +${d.suggested_day_offset}d` : ''}
                        </Badge>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      <Badge tone={d.approved_version === d.version ? 'emerald' : 'slate'}>
                        v{d.version}
                        {d.approved_version === d.version ? ' ✓' : ''}
                      </Badge>
                    </td>
                    <td>
                      <DraftStatusBadge status={d.status} />
                    </td>
                    <td>
                      {d.review_checks.ready_for_approval ? (
                        <Badge tone="emerald">ready</Badge>
                      ) : (
                        <Badge tone="amber">needs review</Badge>
                      )}
                    </td>
                    <td className="whitespace-nowrap text-xs text-slate-500">
                      {formatDateTime(d.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-100 px-3">
            <Pagination
              page={drafts.data.page}
              pageSize={drafts.data.page_size}
              total={drafts.data.total}
              onPage={(p) => updateParam('page', String(p))}
            />
          </div>
        </div>
      )}
    </div>
  );
}
