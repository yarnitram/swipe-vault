import { useEffect, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError, assetDownloadUrl, errorMessage } from '../api/client';
import { FLAG_DESCRIPTIONS, type ReviewDecision, type SwipeDetail, type SwipeVersion } from '../api/types';
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
  ReviewBadge,
  Section,
  Spinner,
} from '../components/ui';
import { formatDateTime, parseTags } from '../lib/format';
import { useAsync } from '../lib/useAsync';

export default function SwipeDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const toast = useToast();
  const swipeState = useAsync(() => api.getSwipe(id), [id]);

  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [savingMeta, setSavingMeta] = useState(false);

  const [tagsInput, setTagsInput] = useState('');
  const [savingTags, setSavingTags] = useState(false);

  const [reviewNotes, setReviewNotes] = useState('');
  const [reviewBusy, setReviewBusy] = useState(false);

  useEffect(() => {
    if (!swipeState.data) return;
    const s = swipeState.data;
    setSelectedVersionId(s.current_version_id);
    setTitle(s.title ?? '');
    setNotes(s.notes ?? '');
    setTagsInput(s.tags.join(', '));
  }, [swipeState.data]);

  if (swipeState.loading && !swipeState.data) return <Spinner label="Loading swipe…" />;
  if (swipeState.error) return <ErrorState message={swipeState.error} onRetry={swipeState.reload} />;
  if (!swipeState.data) return <EmptyState title="Swipe not found" />;

  const swipe: SwipeDetail = swipeState.data;
  const activeVersion: SwipeVersion | undefined =
    swipe.versions.find((v) => v.id === selectedVersionId) ??
    swipe.versions.find((v) => v.id === swipe.current_version_id) ??
    swipe.versions[0];
  const isCurrentVersion = activeVersion?.id === swipe.current_version_id;

  const onSaveMeta = async (e: FormEvent) => {
    e.preventDefault();
    setSavingMeta(true);
    try {
      const updated = await api.updateSwipe(swipe.id, {
        title: title.trim() || null,
        notes: notes.trim() || null,
      });
      swipeState.setData(updated);
      toast.success('Title and notes saved.');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSavingMeta(false);
    }
  };

  const onSaveTags = async (e: FormEvent) => {
    e.preventDefault();
    setSavingTags(true);
    try {
      const updated = await api.setSwipeTags(swipe.id, parseTags(tagsInput));
      swipeState.setData(updated);
      toast.success('Tags updated.');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSavingTags(false);
    }
  };

  const onReview = async (decision: ReviewDecision) => {
    if (!activeVersion || !isCurrentVersion) return;
    setReviewBusy(true);
    try {
      const updated = await api.reviewSwipe(swipe.id, {
        version_id: activeVersion.id,
        decision,
        notes: reviewNotes.trim() || null,
      });
      swipeState.setData(updated);
      setReviewNotes('');
      toast.success(`Marked as ${decision.replace('_', ' ')}.`);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'stale_version') {
        toast.error('Stale version: a newer version exists. Reloading.');
        swipeState.reload();
      } else {
        toast.error(errorMessage(err));
      }
    } finally {
      setReviewBusy(false);
    }
  };

  const sortedSubjects = activeVersion
    ? [...activeVersion.subjects].sort((a, b) => a.position - b.position)
    : [];

  return (
    <div>
      <PageHeader
        title={sortedSubjects[0]?.subject || swipe.title || '(Untitled swipe)'}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Link to={`/offers/${swipe.offer.id}`} className="link font-medium">
              {swipe.offer.title}
            </Link>
            <span>· {swipe.offer.network_slug}</span>
            {swipe.offer.niche && <span>· {swipe.offer.niche}</span>}
            <span>·</span>
            <ReviewBadge state={swipe.review_state} />
            {activeVersion && (
              <>
                <span>· Confidence:</span>
                <ConfidenceBadge value={activeVersion.confidence} />
              </>
            )}
          </span>
        }
        actions={
          <>
            { activeVersion && (
              <div className="flex items-center gap-2">
                <label htmlFor="version-select" className="text-xs font-medium text-slate-600">
                  Version:
                </label>
                <select
                  id="version-select"
                  className="input w-auto"
                  value={activeVersion.id}
                  onChange={(e) => setSelectedVersionId(e.target.value)}
                >
                  {swipe.versions.map((v) => (
                    <option key={v.id} value={v.id}>
                      v{v.version_number} ({formatDateTime(v.created_at)})
                      {v.id === swipe.current_version_id ? ' — current' : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <Link to="/swipes" className="btn-secondary">
              ← Swipe Library
            </Link>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {activeVersion && (
            <>
              <Section
                title={`Subject variants (${sortedSubjects.length})`}
                actions={
                  activeVersion.section_label ? (
                    <Badge tone="slate">Section: {activeVersion.section_label}</Badge>
                  ) : undefined
                }
              >
                {sortedSubjects.length === 0 ? (
                  <p className="text-sm text-amber-700">No subject line was extracted for this version.</p>
                ) : (
                  <ul className="space-y-2">
                    {sortedSubjects.map((subj, idx) => (
                      <li
                        key={subj.id}
                        className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
                      >
                        <div className="min-w-0">
                          <span className="mr-2 font-mono text-xs text-slate-400">#{idx + 1}</span>
                          <span className="break-words font-medium text-slate-900">{subj.subject}</span>
                        </div>
                        <CopyButton text={subj.subject} label="Copy" />
                      </li>
                    ))}
                  </ul>
                )}

                {activeVersion.preheader !== null && (
                  <div className="mt-3 rounded-md border border-slate-200 px-3 py-2 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                          Preheader:{' '}
                        </span>
                        <span className="text-slate-800">{activeVersion.preheader || '—'}</span>
                      </div>
                      {activeVersion.preheader && <CopyButton text={activeVersion.preheader} label="Copy" />}
                    </div>
                  </div>
                )}
              </Section>

              <Section
                title="Plain-text body"
                actions={<CopyButton text={activeVersion.body_text} label="Copy body" />}
              >
                <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-3 font-sans text-sm leading-relaxed text-slate-900">
                  {activeVersion.body_text || '(Empty body)'}
                </pre>
              </Section>

              {activeVersion.body_html_sanitized && (
                <Section
                  title="Sanitized HTML preview (isolated sandbox)"
                  actions={<Badge tone="slate">Scripts & remote pixels blocked</Badge>}
                >
                  <HtmlPreview html={activeVersion.body_html_sanitized} />
                </Section>
              )}

              <Section title={`Calls to action / links (${activeVersion.ctas.length})`}>
                {activeVersion.ctas.length === 0 ? (
                  <p className="text-sm text-slate-500">No CTA links or placeholders detected.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="table-base">
                      <thead>
                        <tr>
                          <th>Anchor text</th>
                          <th>Destination URL</th>
                          <th>Placeholder</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeVersion.ctas.map((cta, i) => (
                          <tr key={i}>
                            <td className="font-medium">{cta.text || '—'}</td>
                            <td className="max-w-xs break-all font-mono text-xs">{cta.url ?? '—'}</td>
                            <td className="font-mono text-xs">
                              {cta.placeholder ? <Badge tone="amber">{cta.placeholder}</Badge> : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Section>

              <Section title={`Provenance (${activeVersion.provenance.length})`}>
                {activeVersion.provenance.length === 0 ? (
                  <p className="text-sm text-slate-500">No provenance records attached.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="table-base">
                      <thead>
                        <tr>
                          <th>Asset file</th>
                          <th>Origin</th>
                          <th>Location</th>
                          <th>Retrieved</th>
                          <th>Download</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeVersion.provenance.map((p) => (
                          <tr key={p.id}>
                            <td>
                              <a
                                href={assetDownloadUrl(p.asset_id)}
                                className="link font-medium"
                                download
                              >
                                {p.asset_filename}
                              </a>
                              {p.retrieval_url && (
                                <div className="max-w-xs truncate font-mono text-xs text-slate-500">
                                  {p.retrieval_url}
                                </div>
                              )}
                            </td>
                            <td>
                              <Badge>{p.origin}</Badge>
                            </td>
                            <td className="text-xs">
                              {[
                                p.page_number !== null ? `Page ${p.page_number}` : null,
                                p.section_label ? p.section_label : null,
                              ]
                                .filter(Boolean)
                                .join(' · ') || '—'}
                            </td>
                            <td className="whitespace-nowrap text-xs text-slate-500">
                              {formatDateTime(p.retrieved_at)}
                            </td>
                            <td>
                              <a
                                href={assetDownloadUrl(p.asset_id)}
                                className="btn-secondary btn-xs"
                                download
                              >
                                Download
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="mt-2 font-mono text-[11px] text-slate-400">
                  Parser: {activeVersion.parser_version} · Normalized hash: {activeVersion.normalized_hash}
                </div>
              </Section>
            </>
          )}
        </div>

        <div className="space-y-4">
          {activeVersion && (
            <Section title={`Review (v${activeVersion.version_number})`}>
              {!isCurrentVersion ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900">
                  Viewing historical version v{activeVersion.version_number}. Switch to the current version to submit
                  new review decisions.
                </div>
              ) : (
                <div className="space-y-3">
                  <Field label="Review notes (optional)" htmlFor="review-notes">
                    <textarea
                      id="review-notes"
                      rows={2}
                      className="input"
                      value={reviewNotes}
                      onChange={(e) => setReviewNotes(e.target.value)}
                      placeholder="Claims checked, required edits, etc."
                    />
                  </Field>
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      className="btn bg-emerald-600 text-white hover:bg-emerald-700"
                      disabled={reviewBusy}
                      onClick={() => onReview('approved')}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="btn bg-violet-600 text-white hover:bg-violet-700"
                      disabled={reviewBusy}
                      onClick={() => onReview('needs_changes')}
                    >
                      Needs changes
                    </button>
                    <button
                      type="button"
                      className="btn-danger"
                      disabled={reviewBusy}
                      onClick={() => onReview('rejected')}
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={reviewBusy}
                      onClick={() => onReview('archived')}
                    >
                      Archive
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={reviewBusy}
                      onClick={() => onReview('pending')}
                    >
                      Back to pending
                    </button>
                  </div>
                  <p className="text-[11px] text-slate-500">
                    Internal editorial decision only — not a legal or compliance certification.
                  </p>
                </div>
              )}

              <div className="mt-4 border-t border-slate-100 pt-3">
                <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Review history (v{activeVersion.version_number})
                </div>
                {activeVersion.review_events.length === 0 ? (
                  <p className="text-xs text-slate-500">No review events on this version yet.</p>
                ) : (
                  <ul className="max-h-48 space-y-2 overflow-y-auto text-xs">
                    {activeVersion.review_events.map((ev) => (
                      <li key={ev.id} className="rounded border border-slate-100 bg-slate-50 p-2">
                        <div className="flex items-center justify-between gap-2">
                          <ReviewBadge state={ev.decision} />
                          <span className="text-slate-500">{formatDateTime(ev.created_at)}</span>
                        </div>
                        {ev.notes && <p className="mt-1 text-slate-700">{ev.notes}</p>}
                        {ev.user_email && <p className="mt-0.5 text-[11px] text-slate-400">by {ev.user_email}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Section>
          )}

          {activeVersion && (
            <Section title={`Extraction flags (${activeVersion.flags.length})`}>
              {activeVersion.flags.length === 0 ? (
                <p className="text-xs text-slate-500">No heuristic flags emitted.</p>
              ) : (
                <ul className="space-y-1.5 text-xs">
                  {activeVersion.flags.map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <FlagBadge flag={f} />
                      <span className="text-slate-600">{FLAG_DESCRIPTIONS[f] ?? 'Heuristic review hint'}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-900">
                Flags are review hints, not compliance decisions. A flag-free swipe still requires human review of
                claims, disclosures, and vendor terms.
              </p>
            </Section>
          )}

          <Section title="Title & editorial notes">
            <form onSubmit={onSaveMeta} className="space-y-2.5">
              <Field label="Title" htmlFor="swipe-title">
                <input
                  id="swipe-title"
                  className="input"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Internal title / label"
                />
              </Field>
              <Field label="Notes" htmlFor="swipe-notes">
                <textarea
                  id="swipe-notes"
                  rows={3}
                  className="input"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Usage conditions, angle notes, edits needed…"
                />
              </Field>
              <button type="submit" className="btn-secondary w-full" disabled={savingMeta}>
                {savingMeta ? 'Saving…' : 'Save title & notes'}
              </button>
            </form>
          </Section>

          <Section title="Tags">
            <form onSubmit={onSaveTags} className="space-y-2">
              <Field
                label="Tags (comma-separated; replaces set)"
                htmlFor="swipe-tags"
                hint="Prefix angles with angle: (e.g. angle:weight-loss)."
              >
                <input
                  id="swipe-tags"
                  className="input"
                  value={tagsInput}
                  onChange={(e) => setTagsInput(e.target.value)}
                  placeholder="angle:story, curiosity"
                />
              </Field>
              <div className="flex flex-wrap gap-1">
                {swipe.tags.map((t) => (
                  <Badge key={t} tone="indigo">
                    {t}
                  </Badge>
                ))}
              </div>
              <button type="submit" className="btn-secondary w-full" disabled={savingTags}>
                {savingTags ? 'Saving…' : 'Update tags'}
              </button>
            </form>
          </Section>

          <Section title="Duplicates">
            <div className="space-y-3 text-xs">
              <div>
                <div className="mb-1 font-semibold text-slate-700">
                  Exact matches in other offers ({swipe.duplicates.exact_other_offers.length})
                </div>
                {swipe.duplicates.exact_other_offers.length === 0 ? (
                  <p className="text-slate-500">None detected.</p>
                ) : (
                  <ul className="space-y-1">
                    {swipe.duplicates.exact_other_offers.map((d) => (
                      <li key={d.swipe_id} className="flex items-center justify-between gap-2">
                        <Link to={`/swipes/${d.swipe_id}`} className="link">
                          {d.offer_title}
                        </Link>
                        <Link to={`/offers/${d.offer_id}`} className="text-slate-500 hover:underline">
                          offer →
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="border-t border-slate-100 pt-2">
                <div className="mb-1 font-semibold text-slate-700">
                  Near duplicates ({swipe.duplicates.near.length})
                </div>
                {swipe.duplicates.near.length === 0 ? (
                  <p className="text-slate-500">None detected.</p>
                ) : (
                  <ul className="space-y-1">
                    {swipe.duplicates.near.map((n) => (
                      <li key={n.swipe_id} className="flex items-center justify-between gap-2">
                        <Link to={`/swipes/${n.swipe_id}`} className="link truncate">
                          {n.title || n.offer_title}
                        </Link>
                        <Badge tone="amber">{Math.round(n.similarity * 100)}% similar</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
