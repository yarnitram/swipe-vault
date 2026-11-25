import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, assetDownloadUrl, errorMessage } from '../api/client';
import { FLAG_DESCRIPTIONS, type ReviewDecision, type SwipeDetail } from '../api/types';
import HtmlPreview from '../components/HtmlPreview';
import { useToast } from '../components/Toast';
import {
  Badge,
  ConfidenceBadge,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  FlagBadge,
  PageHeader,
  Pagination,
  Spinner,
} from '../components/ui';
import { formatDateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';

const PAGE_SIZE = 25;

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (el.isContentEditable) return true;
  return false;
}

export default function ReviewQueuePage() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [showHtml, setShowHtml] = useState(false);

  const queue = useAsync(
    () =>
      api.listSwipes({
        review_state: 'pending',
        sort: 'confidence',
        page,
        page_size: PAGE_SIZE,
      }),
    [page],
  );

  const items = queue.data?.items ?? [];
  const clampedIndex = items.length === 0 ? 0 : Math.min(selectedIndex, items.length - 1);
  const selectedSummary = items[clampedIndex];

  const detail = useAsync(
    () => (selectedSummary ? api.getSwipe(selectedSummary.id) : Promise.resolve(null as SwipeDetail | null)),
    [selectedSummary?.id],
  );

  useEffect(() => {
    setNotes('');
  }, [selectedSummary?.id]);

  const currentVersion = detail.data
    ? detail.data.versions.find((v) => v.id === detail.data?.current_version_id) ?? detail.data.versions[0]
    : undefined;

  const submitDecision = useCallback(
    async (decision: ReviewDecision) => {
      if (!detail.data || !currentVersion || submitting) return;
      setSubmitting(true);
      try {
        await api.reviewSwipe(detail.data.id, {
          version_id: currentVersion.id,
          decision,
          notes: notes.trim() || null,
        });
        toast.success(`Swipe marked ${decision.replace('_', ' ')}.`);
        setNotes('');
        queue.reload();
      } catch (err) {
        toast.error(errorMessage(err));
      } finally {
        setSubmitting(false);
      }
    },
    [detail.data, currentVersion, submitting, notes, toast, queue],
  );

  // Keyboard shortcuts: j/k to move, a approve, r reject, n needs_changes (never fire while typing).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target) || isTypingTarget(document.activeElement)) return;
      if (items.length === 0) return;

      if (e.key === 'j') {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(items.length - 1, i + 1));
      } else if (e.key === 'k') {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(0, i - 1));
      } else if (e.key === 'a') {
        e.preventDefault();
        void submitDecision('approved');
      } else if (e.key === 'n') {
        e.preventDefault();
        void submitDecision('needs_changes');
      } else if (e.key === 'r') {
        e.preventDefault();
        void submitDecision('rejected');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [items.length, submitDecision]);

  return (
    <div>
      <PageHeader
        title="Review Queue"
        subtitle="Pending swipes ordered by lowest extraction confidence first."
        actions={
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            <span>Shortcuts:</span>
            <kbd className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono">j</kbd>
            <span>/</span>
            <kbd className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono">k</kbd>
            <span>move</span>
            <kbd className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono">a</kbd>
            <span>approve</span>
            <kbd className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono">n</kbd>
            <span>needs changes</span>
            <kbd className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono">r</kbd>
            <span>reject</span>
          </div>
        }
      />

      {queue.loading && !queue.data ? (
        <Spinner label="Loading review queue…" />
      ) : queue.error ? (
        <ErrorState message={queue.error} onRetry={queue.reload} />
      ) : !queue.data || queue.data.items.length === 0 ? (
        <EmptyState title="Review queue is empty">All extracted swipes have been reviewed.</EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Left: queue list */}
          <div className="lg:col-span-5">
            <div className="card overflow-hidden">
              <div className="border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Pending ({queue.data.total})
              </div>
              <ul className="max-h-[72vh] divide-y divide-slate-100 overflow-y-auto" role="listbox" aria-label="Pending swipes">
                {items.map((item, idx) => {
                  const active = idx === clampedIndex;
                  return (
                    <li key={item.id} role="option" aria-selected={active}>
                      <button
                        type="button"
                        onClick={() => setSelectedIndex(idx)}
                        className={`w-full px-3 py-2.5 text-left transition-colors ${
                          active ? 'bg-indigo-50/80' : 'hover:bg-slate-50'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="line-clamp-1 text-sm font-medium text-slate-900">
                            {item.current_version.primary_subject || item.title || '(No subject)'}
                          </span>
                          <ConfidenceBadge value={item.current_version.confidence} />
                        </div>
                        <div className="mt-0.5 text-xs text-slate-500">
                          {item.offer.title} · {item.offer.network_slug}
                        </div>
                        <p className="mt-1 line-clamp-2 text-xs text-slate-600">{item.current_version.body_excerpt}</p>
                        {item.current_version.flags.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {item.current_version.flags.map((f) => (
                              <FlagBadge key={f} flag={f} />
                            ))}
                          </div>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div className="border-t border-slate-100 px-3">
                <Pagination
                  page={queue.data.page}
                  pageSize={queue.data.page_size}
                  total={queue.data.total}
                  onPage={(p) => {
                    setPage(p);
                    setSelectedIndex(0);
                  }}
                />
              </div>
            </div>
          </div>

          {/* Right: selected swipe detail + provenance + review actions */}
          <div className="lg:col-span-7">
            {detail.loading && !detail.data ? (
              <div className="card p-6">
                <Spinner label="Loading swipe content…" />
              </div>
            ) : detail.error ? (
              <ErrorState message={detail.error} onRetry={detail.reload} />
            ) : !detail.data || !currentVersion ? (
              <EmptyState title="Select a swipe to review" />
            ) : (
              <div className="card space-y-4 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 pb-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <Link to={`/offers/${detail.data.offer.id}`} className="link text-sm font-medium">
                        {detail.data.offer.title}
                      </Link>
                      <span className="text-xs text-slate-400">· v{currentVersion.version_number}</span>
                      <ConfidenceBadge value={currentVersion.confidence} />
                    </div>
                    <h2 className="mt-1 text-base font-semibold text-slate-900">
                      {currentVersion.subjects[0]?.subject || detail.data.title || '(No subject)'}
                    </h2>
                  </div>
                  <Link to={`/swipes/${detail.data.id}`} className="btn-secondary btn-xs">
                    Full detail →
                  </Link>
                </div>

                {/* Flags */}
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Flags ({currentVersion.flags.length})
                  </div>
                  {currentVersion.flags.length === 0 ? (
                    <p className="text-xs text-slate-500">No heuristic flags emitted.</p>
                  ) : (
                    <div className="space-y-1">
                      {currentVersion.flags.map((f) => (
                        <div key={f} className="flex items-center gap-2 text-xs">
                          <FlagBadge flag={f} />
                          <span className="text-slate-600">{FLAG_DESCRIPTIONS[f] ?? 'Review hint'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <p className="mt-1 text-[11px] text-slate-500">
                    Flags are hints, not compliance decisions. Verify claims, usage restrictions, and affiliate links.
                  </p>
                </div>

                {/* Provenance */}
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Source provenance ({currentVersion.provenance.length})
                  </div>
                  {currentVersion.provenance.length === 0 ? (
                    <p className="text-xs text-slate-500">No provenance records.</p>
                  ) : (
                    <ul className="space-y-1 text-xs">
                      {currentVersion.provenance.map((p) => (
                        <li
                          key={p.id}
                          className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-200 bg-slate-50 px-2.5 py-1.5"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <a href={assetDownloadUrl(p.asset_id)} className="link font-medium" download>
                              {p.asset_filename}
                            </a>
                            <Badge>{p.origin}</Badge>
                            {p.page_number !== null && <span className="text-slate-500">Page {p.page_number}</span>}
                            {p.section_label && <span className="text-slate-500">{p.section_label}</span>}
                          </div>
                          <span className="text-slate-400">{formatDateTime(p.retrieved_at)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Subject variants */}
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Subjects ({currentVersion.subjects.length})
                  </div>
                  {currentVersion.subjects.length === 0 ? (
                    <p className="text-xs text-amber-700">No subject lines detected.</p>
                  ) : (
                    <ul className="space-y-1">
                      {[...currentVersion.subjects]
                        .sort((a, b) => a.position - b.position)
                        .map((s, i) => (
                          <li
                            key={s.id}
                            className="flex items-center justify-between gap-2 rounded border border-slate-200 bg-slate-50 px-2.5 py-1 text-sm"
                          >
                            <span>
                              <span className="mr-1.5 font-mono text-xs text-slate-400">#{i + 1}</span>
                              {s.subject}
                            </span>
                            <CopyButton text={s.subject} label="Copy" />
                          </li>
                        ))}
                    </ul>
                  )}
                  {currentVersion.preheader && (
                    <div className="mt-1.5 text-xs text-slate-600">
                      <span className="font-semibold">Preheader:</span> {currentVersion.preheader}
                    </div>
                  )}
                </div>

                {/* Body content */}
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Extracted body
                    </span>
                    <div className="flex items-center gap-2">
                      {currentVersion.body_html_sanitized && (
                        <button
                          type="button"
                          className="btn-ghost btn-xs"
                          onClick={() => setShowHtml((h) => !h)}
                        >
                          {showHtml ? 'Show plain text' : 'Show sanitized HTML'}
                        </button>
                      )}
                      <CopyButton text={currentVersion.body_text} label="Copy body" />
                    </div>
                  </div>
                  {showHtml && currentVersion.body_html_sanitized ? (
                    <HtmlPreview html={currentVersion.body_html_sanitized} />
                  ) : (
                    <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-3 font-sans text-sm leading-relaxed text-slate-900">
                      {currentVersion.body_text || '(Empty body)'}
                    </pre>
                  )}
                </div>

                {/* Quick review controls */}
                <div className="border-t border-slate-200 pt-3">
                  <Field label="Review notes (optional)" htmlFor="queue-review-notes">
                    <input
                      id="queue-review-notes"
                      className="input"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder="Notes recorded with your decision…"
                    />
                  </Field>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn bg-emerald-600 text-white hover:bg-emerald-700"
                        disabled={submitting}
                        onClick={() => submitDecision('approved')}
                      >
                        Approve (a)
                      </button>
                      <button
                        type="button"
                        className="btn bg-violet-600 text-white hover:bg-violet-700"
                        disabled={submitting}
                        onClick={() => submitDecision('needs_changes')}
                      >
                        Needs changes (n)
                      </button>
                      <button
                        type="button"
                        className="btn-danger"
                        disabled={submitting}
                        onClick={() => submitDecision('rejected')}
                      >
                        Reject (r)
                      </button>
                    </div>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        className="btn-secondary btn-xs"
                        disabled={clampedIndex <= 0}
                        onClick={() => setSelectedIndex((i) => Math.max(0, i - 1))}
                      >
                        ↑ Prev (k)
                      </button>
                      <button
                        type="button"
                        className="btn-secondary btn-xs"
                        disabled={clampedIndex >= items.length - 1}
                        onClick={() => setSelectedIndex((i) => Math.min(items.length - 1, i + 1))}
                      >
                        ↓ Next (j)
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
