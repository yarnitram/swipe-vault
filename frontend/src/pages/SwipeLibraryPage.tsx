import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import { REVIEW_STATES, type ReviewState, type SwipeSort, type SwipeSummary } from '../api/types';
import { useToast } from '../components/Toast';
import {
  Badge,
  ConfidenceBadge,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  FlagBadge,
  Modal,
  PageHeader,
  Pagination,
  ReviewBadge,
  Spinner,
} from '../components/ui';
import { parseTags } from '../lib/format';
import { useAsync } from '../lib/useAsync';

const PAGE_SIZE = 25;

export default function SwipeLibraryPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const network = params.get('network') ?? '';
  const niche = params.get('niche') ?? '';
  const reviewState = (params.get('review_state') ?? '') as ReviewState | '';
  const tag = params.get('tag') ?? '';
  const offerId = params.get('offer_id') ?? '';
  const sort = (params.get('sort') ?? (q ? 'relevance' : 'newest')) as SwipeSort;
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1);

  const [qInput, setQInput] = useState(q);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkTagOpen, setBulkTagOpen] = useState(false);
  const [bulkTagInput, setBulkTagInput] = useState('');
  const [bulkBusy, setBulkBusy] = useState(false);

  // Sync local search input when query param changes (e.g. from top bar global search).
  useEffect(() => {
    setQInput(q);
  }, [q]);

  const networks = useAsync(() => api.networks(), []);
  const niches = useAsync(() => api.niches(), []);
  const tags = useAsync(() => api.tags(), []);
  const swipes = useAsync(
    () =>
      api.listSwipes({
        q: q || undefined,
        network: network || undefined,
        niche: niche || undefined,
        review_state: reviewState || undefined,
        tag: tag || undefined,
        offer_id: offerId || undefined,
        sort: sort || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [q, network, niche, reviewState, tag, offerId, sort, page],
  );

  // Clear selection when the result page changes.
  useEffect(() => {
    setSelected(new Set());
  }, [q, network, niche, reviewState, tag, offerId, sort, page]);

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next);
  };

  const onSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    updateParam('q', qInput.trim());
  };

  const items = swipes.data?.items ?? [];
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.id));

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = (checked: boolean) => {
    if (!checked) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(items.map((i) => i.id)));
  };

  const onBulkAddTags = async (e: FormEvent) => {
    e.preventDefault();
    const parsed = parseTags(bulkTagInput);
    if (parsed.length === 0 || selected.size === 0) return;
    setBulkBusy(true);
    try {
      const res = await api.bulkSwipes({
        swipe_ids: Array.from(selected),
        action: 'add_tags',
        tags: parsed,
      });
      toast.success(`Added tags to ${res.updated} swipe(s).`);
      setBulkTagInput('');
      setBulkTagOpen(false);
      setSelected(new Set());
      swipes.reload();
      tags.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const onBulkArchive = async () => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    try {
      const res = await api.bulkSwipes({
        swipe_ids: Array.from(selected),
        action: 'archive',
      });
      toast.success(`Archived ${res.updated} swipe(s).`);
      setSelected(new Set());
      swipes.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Swipe Library"
        subtitle="Search subjects, body copy, offers, and tags."
      />

      <div className="card mb-4 p-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-7">
          <form onSubmit={onSearchSubmit} className="sm:col-span-2">
            <label className="label" htmlFor="swipes-search">
              Search
            </label>
            <div className="flex gap-2">
              <input
                id="swipes-search"
                type="search"
                className="input"
                placeholder="Subjects, body, offer, vendor…"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
              />
              <button type="submit" className="btn-secondary">
                Search
              </button>
            </div>
          </form>

          <div>
            <label className="label" htmlFor="swipes-network">
              Network
            </label>
            <select
              id="swipes-network"
              className="input"
              value={network}
              onChange={(e) => updateParam('network', e.target.value)}
            >
              <option value="">All networks</option>
              {(networks.data ?? []).map((n) => (
                <option key={n.id} value={n.slug}>
                  {n.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="swipes-niche">
              Niche
            </label>
            <select
              id="swipes-niche"
              className="input"
              value={niche}
              onChange={(e) => updateParam('niche', e.target.value)}
            >
              <option value="">All niches</option>
              {(niches.data ?? []).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="swipes-state">
              Review state
            </label>
            <select
              id="swipes-state"
              className="input"
              value={reviewState}
              onChange={(e) => updateParam('review_state', e.target.value)}
            >
              <option value="">All states</option>
              {REVIEW_STATES.map((s) => (
                <option key={s} value={s}>
                  {s.replace('_', ' ')}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="swipes-tag">
              Tag / Angle
            </label>
            <select
              id="swipes-tag"
              className="input"
              value={tag}
              onChange={(e) => updateParam('tag', e.target.value)}
            >
              <option value="">All tags</option>
              {(tags.data ?? []).map((t) => (
                <option key={t.id} value={t.label}>
                  {t.label} ({t.swipe_count})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="swipes-sort">
              Sort
            </label>
            <select
              id="swipes-sort"
              className="input"
              value={sort}
              onChange={(e) => updateParam('sort', e.target.value)}
            >
              <option value="relevance">Relevance</option>
              <option value="newest">Newest</option>
              <option value="confidence">Confidence (low → high)</option>
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

      {selected.size > 0 && (
        <div
          className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm"
          role="region"
          aria-label="Bulk actions"
        >
          <span className="font-medium text-indigo-900">{selected.size} swipe(s) selected</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-secondary btn-xs"
              disabled={bulkBusy}
              onClick={() => setBulkTagOpen(true)}
            >
              + Add tags
            </button>
            <button
              type="button"
              className="btn-danger btn-xs"
              disabled={bulkBusy}
              onClick={onBulkArchive}
            >
              Archive
            </button>
            <button
              type="button"
              className="btn-ghost btn-xs"
              onClick={() => setSelected(new Set())}
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {swipes.loading && !swipes.data ? (
        <Spinner label="Loading swipes…" />
      ) : swipes.error ? (
        <ErrorState message={swipes.error} onRetry={swipes.reload} />
      ) : !swipes.data || swipes.data.items.length === 0 ? (
        <EmptyState title="No swipes match your filters" />
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th className="w-8">
                    <input
                      type="checkbox"
                      aria-label="Select all swipes on this page"
                      checked={allSelected}
                      onChange={(e) => toggleAll(e.target.checked)}
                    />
                  </th>
                  <th>Offer</th>
                  <th>Primary subject</th>
                  <th>Excerpt</th>
                  <th>Confidence</th>
                  <th>Flags</th>
                  <th>State</th>
                  <th>Tags</th>
                  <th>Quick copy</th>
                </tr>
              </thead>
              <tbody>
                {swipes.data.items.map((s) => (
                  <SwipeRow
                    key={s.id}
                    swipe={s}
                    checked={selected.has(s.id)}
                    onToggle={() => toggleOne(s.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-100 px-3">
            <Pagination
              page={swipes.data.page}
              pageSize={swipes.data.page_size}
              total={swipes.data.total}
              onPage={(p) => updateParam('page', String(p))}
            />
          </div>
        </div>
      )}

      <Modal title={`Add tags to ${selected.size} swipe(s)`} open={bulkTagOpen} onClose={() => setBulkTagOpen(false)}>
        <form onSubmit={onBulkAddTags} className="space-y-3">
          <Field
            label="Tags (comma-separated)"
            htmlFor="bulk-tags-input"
            hint="Use angle:<name> for angles (e.g. angle:weight-loss, morning-routine)."
          >
            <input
              id="bulk-tags-input"
              className="input"
              required
              value={bulkTagInput}
              onChange={(e) => setBulkTagInput(e.target.value)}
              placeholder="angle:weight-loss, story"
            />
          </Field>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setBulkTagOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={bulkBusy}>
              {bulkBusy ? 'Applying…' : 'Add tags'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function SwipeRow({
  swipe: s,
  checked,
  onToggle,
}: {
  swipe: SwipeSummary;
  checked: boolean;
  onToggle: () => void;
}) {
  const toast = useToast();
  const [copyingBody, setCopyingBody] = useState(false);
  const extraSubjects = Math.max(0, s.current_version.subject_count - 1);

  const onCopyBody = async () => {
    setCopyingBody(true);
    try {
      const detail = await api.getSwipe(s.id);
      const current = detail.versions.find((v) => v.id === detail.current_version_id) ?? detail.versions[0];
      const text = current?.body_text ?? s.current_version.body_excerpt;
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      toast.success('Body copied to clipboard.');
    } catch {
      // Fall back to copying excerpt if full fetch or clipboard fails
      try {
        await navigator.clipboard?.writeText(s.current_version.body_excerpt);
        toast.info('Excerpt copied to clipboard.');
      } catch {
        toast.error('Could not copy to clipboard.');
      }
    } finally {
      setCopyingBody(false);
    }
  };

  return (
    <tr>
      <td>
        <input
          type="checkbox"
          aria-label={`Select swipe ${s.current_version.primary_subject ?? s.id}`}
          checked={checked}
          onChange={onToggle}
        />
      </td>
      <td>
        <Link to={`/offers/${s.offer.id}`} className="link font-medium">
          {s.offer.title}
        </Link>
        <div className="text-xs text-slate-500">
          {s.offer.network_slug}
          {s.offer.niche ? ` · ${s.offer.niche}` : ''}
        </div>
      </td>
      <td className="max-w-xs">
        <Link to={`/swipes/${s.id}`} className="link font-medium">
          {s.current_version.primary_subject || s.title || '(No subject)'}
        </Link>
        {extraSubjects > 0 && (
          <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
            +{extraSubjects}
          </span>
        )}
        {s.version_count > 1 && (
          <span className="ml-1 text-xs text-slate-400">v{s.current_version.version_number}</span>
        )}
      </td>
      <td className="max-w-md">
        <p className="line-clamp-2 text-xs text-slate-600">{s.current_version.body_excerpt}</p>
      </td>
      <td>
        <ConfidenceBadge value={s.current_version.confidence} />
      </td>
      <td>
        <div className="flex flex-wrap gap-1">
          {s.current_version.flags.map((f) => (
            <FlagBadge key={f} flag={f} />
          ))}
        </div>
      </td>
      <td>
        <ReviewBadge state={s.review_state} />
      </td>
      <td>
        <div className="flex flex-wrap gap-1">
          {s.tags.map((t) => (
            <Badge key={t} tone="indigo">
              {t}
            </Badge>
          ))}
        </div>
      </td>
      <td>
        <div className="flex flex-wrap gap-1">
          <CopyButton text={s.current_version.primary_subject ?? ''} label="Copy subject" />
          <button
            type="button"
            className="btn-secondary btn-xs"
            disabled={copyingBody}
            onClick={onCopyBody}
          >
            {copyingBody ? 'Copying…' : 'Copy body'}
          </button>
        </div>
      </td>
    </tr>
  );
}
