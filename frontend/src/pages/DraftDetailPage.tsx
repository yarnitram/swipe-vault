import { useEffect, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError, errorMessage, getDraftDownloadUrl } from '../api/client';
import { FLAG_DESCRIPTIONS, type DraftDetail, type ListmonkTestResponse } from '../api/types';
import HtmlPreview from '../components/HtmlPreview';
import { useToast } from '../components/Toast';
import {
  Badge,
  CopyButton,
  DraftStatusBadge,
  EmptyState,
  ErrorState,
  ExportStatusBadge,
  Field,
  FlagBadge,
  PageHeader,
  Section,
  Spinner,
} from '../components/ui';
import { formatDateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';

export default function DraftDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const toast = useToast();
  const draftState = useAsync(() => api.getDraft(id), [id]);

  // Form fields
  const [title, setTitle] = useState('');
  const [subject, setSubject] = useState('');
  const [preheader, setPreheader] = useState('');
  const [affiliateUrl, setAffiliateUrl] = useState('');
  const [replacePlaceholders, setReplacePlaceholders] = useState(true);
  const [appendBrandFooter, setAppendBrandFooter] = useState(false);
  const [replaceUrls, setReplaceUrls] = useState<Set<string>>(new Set());
  const [sequencePosition, setSequencePosition] = useState('');
  const [suggestedDayOffset, setSuggestedDayOffset] = useState('');
  const [bodyText, setBodyText] = useState('');
  const [bodyHtml, setBodyHtml] = useState('');

  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [previewTab, setPreviewTab] = useState<'html' | 'text'>('html');

  // Listmonk state
  const [listmonkTest, setListmonkTest] = useState<ListmonkTestResponse | null>(null);
  const [testingListmonk, setTestingListmonk] = useState(false);
  const [selectedListIds, setSelectedListIds] = useState<Set<number>>(new Set());
  const [confirmUnsent, setConfirmUnsent] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!draftState.data) return;
    const d = draftState.data;
    setTitle(d.title);
    setSubject(d.subject);
    setPreheader(d.preheader ?? '');
    setAffiliateUrl(d.affiliate_url ?? '');
    setSequencePosition(d.sequence_position !== null ? String(d.sequence_position) : '');
    setSuggestedDayOffset(d.suggested_day_offset !== null ? String(d.suggested_day_offset) : '');
    setBodyText(d.body_text);
    setBodyHtml(d.body_html);
    setAppendBrandFooter(false);
  }, [draftState.data]);

  if (draftState.loading && !draftState.data) return <Spinner label="Loading draft…" />;
  if (draftState.error) return <ErrorState message={draftState.error} onRetry={draftState.reload} />;
  if (!draftState.data) return <EmptyState title="Draft not found" />;

  const draft: DraftDetail = draftState.data;
  const checks = draft.review_checks;
  const isApprovedForCurrentVersion =
    (draft.status === 'approved' || draft.status === 'exported') && draft.approved_version === draft.version;

  const sourceUrls = Array.from(
    new Set((draft.source_ctas ?? []).map((c) => c.url).filter((u): u is string => Boolean(u))),
  );

  const toggleSourceUrl = (u: string) => {
    setReplaceUrls((prev) => {
      const next = new Set(prev);
      if (next.has(u)) next.delete(u);
      else next.add(u);
      return next;
    });
  };

  const onSave = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await api.updateDraft(draft.id, {
        title: title.trim(),
        subject: subject.trim(),
        preheader: preheader.trim() || null,
        affiliate_url: affiliateUrl.trim() || null,
        replace_placeholders: replacePlaceholders,
        replace_urls: replaceUrls.size > 0 ? Array.from(replaceUrls) : undefined,
        append_brand_footer: appendBrandFooter,
        sequence_position: sequencePosition.trim() ? Number(sequencePosition) : null,
        suggested_day_offset: suggestedDayOffset.trim() ? Number(suggestedDayOffset) : null,
        body_text: bodyText,
        body_html: bodyHtml,
      });
      draftState.setData(updated);
      toast.success(`Saved draft (v${updated.version}).`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const onApprove = async () => {
    setApproving(true);
    try {
      const updated = await api.approveDraft(draft.id, { version: draft.version });
      draftState.setData(updated);
      toast.success(`Draft v${updated.version} approved.`);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'stale_draft_version') {
        toast.error('Draft version changed; reloading latest version.');
        draftState.reload();
      } else {
        toast.error(errorMessage(err));
      }
    } finally {
      setApproving(false);
    }
  };

  const onLoadListmonkLists = async () => {
    setTestingListmonk(true);
    try {
      const res = await api.testListmonkConnection();
      setListmonkTest(res);
      // Never auto-select all lists (FR-08)
      setSelectedListIds(new Set());
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setTestingListmonk(false);
    }
  };

  const toggleListId = (listId: number) => {
    setSelectedListIds((prev) => {
      const next = new Set(prev);
      if (next.has(listId)) next.delete(listId);
      else next.add(listId);
      return next;
    });
  };

  const onExportListmonk = async (e: FormEvent) => {
    e.preventDefault();
    if (!isApprovedForCurrentVersion || selectedListIds.size === 0 || !confirmUnsent) return;
    setExporting(true);
    try {
      const exp = await api.exportDraftToListmonk(draft.id, {
        list_ids: Array.from(selectedListIds),
        confirm_unsent_draft: true,
      });
      if (exp.status === 'completed') {
        toast.success(`Unsent draft campaign created in Listmonk (remote ID: ${exp.remote_id ?? 'n/a'}).`);
      } else if (exp.status === 'needs_reconciliation') {
        toast.info('Export marked needs_reconciliation — check Listmonk before retrying.');
      } else {
        toast.error(exp.error_summary || 'Listmonk export failed.');
      }
      setConfirmUnsent(false);
      draftState.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div>
      <PageHeader
        title={draft.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone="indigo">{draft.brand.name}</Badge>
            <Badge tone={isApprovedForCurrentVersion ? 'emerald' : 'slate'}>
              v{draft.version}
              {draft.approved_version ? ` (approved v${draft.approved_version})` : ''}
            </Badge>
            <DraftStatusBadge status={draft.status} />
            <span>· Offer:</span>
            <Link to={`/offers/${draft.offer.id}`} className="link font-medium">
              {draft.offer.title}
            </Link>
            <span>· Source:</span>
            <Link to={`/swipes/${draft.swipe_id}`} className="link">
              Immutable swipe (v{draft.swipe_version_number}) →
            </Link>
          </span>
        }
        actions={
          <Link to="/drafts" className="btn-secondary">
            ← All drafts
          </Link>
        }
      />

      <div
        role="note"
        className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900"
      >
        <strong>Versioned approval rule (AC-11):</strong> Material edits to subject, preheader, body, or affiliate URL
        increment the draft version, reset status to <code>editing</code>, and invalidate prior approval. Re-approve the
        new version after reviewing checks before exporting.
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Left 2 cols: Editor + Preview */}
        <div className="space-y-4 lg:col-span-2">
          <Section title={`Draft editor (v${draft.version})`}>
            <form onSubmit={onSave} className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="sm:col-span-2">
                  <Field label="Draft title *" htmlFor="draft-edit-title">
                    <input
                      id="draft-edit-title"
                      className="input"
                      required
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                    />
                  </Field>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Seq #" htmlFor="draft-edit-seq">
                    <input
                      id="draft-edit-seq"
                      type="number"
                      min={1}
                      className="input"
                      value={sequencePosition}
                      onChange={(e) => setSequencePosition(e.target.value)}
                    />
                  </Field>
                  <Field label="Day +" htmlFor="draft-edit-day">
                    <input
                      id="draft-edit-day"
                      type="number"
                      min={0}
                      className="input"
                      value={suggestedDayOffset}
                      onChange={(e) => setSuggestedDayOffset(e.target.value)}
                    />
                  </Field>
                </div>
              </div>

              <Field
                label="Subject line *"
                htmlFor="draft-edit-subject"
                hint={
                  draft.available_subjects.length > 1 ? (
                    <span className="flex flex-wrap items-center gap-1">
                      <span>Switch to source variant:</span>
                      {draft.available_subjects.map((s, i) => (
                        <button
                          key={i}
                          type="button"
                          className="link text-xs"
                          onClick={() => setSubject(s)}
                        >
                          [#{i + 1}]
                        </button>
                      ))}
                    </span>
                  ) : undefined
                }
              >
                <input
                  id="draft-edit-subject"
                  className="input"
                  required
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                />
              </Field>

              <Field label="Preheader" htmlFor="draft-edit-preheader">
                <input
                  id="draft-edit-preheader"
                  className="input"
                  value={preheader}
                  onChange={(e) => setPreheader(e.target.value)}
                />
              </Field>

              <Field
                label="Verified affiliate URL"
                htmlFor="draft-edit-affiliate-url"
                hint="Only recognized CTA placeholders and explicitly checked source CTA links below are replaced—unsubscribe, legal, disclosure, and non-affiliate links are preserved (FR-07)."
              >
                <input
                  id="draft-edit-affiliate-url"
                  type="url"
                  className="input"
                  value={affiliateUrl}
                  onChange={(e) => setAffiliateUrl(e.target.value)}
                  placeholder="https://hop.clickbank.net/?affiliate=..."
                />
              </Field>

              <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="font-semibold text-slate-700">Targeted link & footer rules on save:</div>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={replacePlaceholders}
                    onChange={(e) => setReplacePlaceholders(e.target.checked)}
                  />
                  <span>Replace recognized CTA placeholders (e.g. [AFFILIATE_LINK], {'{{AFFILIATE_URL}}'}) with verified affiliate URL</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={appendBrandFooter}
                    onChange={(e) => setAppendBrandFooter(e.target.checked)}
                  />
                  <span>Append brand affiliate disclosure & sender footer template if missing</span>
                </label>

                {sourceUrls.length > 0 && (
                  <div className="border-t border-slate-200 pt-2">
                    <div className="mb-1 font-medium text-slate-700">
                      Specific source CTA URLs to replace with your affiliate URL:
                    </div>
                    <div className="space-y-1">
                      {sourceUrls.map((u) => (
                        <label key={u} className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={replaceUrls.has(u)}
                            onChange={() => toggleSourceUrl(u)}
                          />
                          <span className="break-all font-mono">{u}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                <Field label="Plain-text body" htmlFor="draft-edit-body-text">
                  <textarea
                    id="draft-edit-body-text"
                    rows={12}
                    className="input font-mono text-xs"
                    value={bodyText}
                    onChange={(e) => setBodyText(e.target.value)}
                  />
                </Field>
                <Field label="HTML body" htmlFor="draft-edit-body-html">
                  <textarea
                    id="draft-edit-body-html"
                    rows={12}
                    className="input font-mono text-xs"
                    value={bodyHtml}
                    onChange={(e) => setBodyHtml(e.target.value)}
                  />
                </Field>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button type="submit" className="btn-primary" disabled={saving}>
                  {saving ? 'Saving & re-running checks…' : 'Save draft changes'}
                </button>
              </div>
            </form>
          </Section>

          <Section
            title="Isolated preview"
            actions={
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  className={previewTab === 'html' ? 'btn-primary btn-xs' : 'btn-secondary btn-xs'}
                  onClick={() => setPreviewTab('html')}
                >
                  Sanitized HTML
                </button>
                <button
                  type="button"
                  className={previewTab === 'text' ? 'btn-primary btn-xs' : 'btn-secondary btn-xs'}
                  onClick={() => setPreviewTab('text')}
                >
                  Plain Text
                </button>
              </div>
            }
          >
            {previewTab === 'html' ? (
              <HtmlPreview html={draft.body_html} title="Draft sanitized HTML preview" />
            ) : (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-3 font-sans text-sm leading-relaxed text-slate-900">
                {draft.body_text}
              </pre>
            )}
          </Section>
        </div>

        {/* Right col: Review Checks, Approval, Export */}
        <div className="space-y-4">
          <Section
            title="Review checks"
            actions={
              checks.ready_for_approval ? (
                <Badge tone="emerald">Ready for approval</Badge>
              ) : (
                <Badge tone="amber">Action required</Badge>
              )
            }
          >
            <ul className="space-y-2 text-xs">
              <CheckRow ok={checks.has_affiliate_url} label="Verified affiliate URL provided" />
              <CheckRow ok={checks.affiliate_url_valid} label="Affiliate URL syntax & host policy valid" />
              <CheckRow ok={checks.has_disclosure} label="Affiliate disclosure present" />
              <CheckRow ok={checks.has_sender_footer} label="Sender identification / unsubscribe footer present" />
              <CheckRow
                ok={checks.unresolved_placeholders.length === 0}
                label={
                  checks.unresolved_placeholders.length === 0
                    ? 'No unresolved CTA placeholders'
                    : `Unresolved placeholders: ${checks.unresolved_placeholders.join(', ')}`
                }
              />
              <CheckRow
                ok={checks.unexpected_hosts.length === 0}
                warnOnly
                label={
                  checks.unexpected_hosts.length === 0
                    ? 'Outbound link domains match expected hosts'
                    : `Unexpected outbound hosts: ${checks.unexpected_hosts.join(', ')}`
                }
              />
            </ul>

            {checks.claim_flags.length > 0 && (
              <div className="mt-3 border-t border-slate-100 pt-2">
                <div className="mb-1 text-xs font-semibold text-slate-600">Heuristic claim hints:</div>
                <div className="flex flex-wrap gap-1">
                  {checks.claim_flags.map((f) => (
                    <FlagBadge key={f} flag={f} />
                  ))}
                </div>
                <p className="mt-1 text-[11px] text-slate-500">
                  {checks.claim_flags.map((f) => FLAG_DESCRIPTIONS[f] ?? f).join(' · ')}
                </p>
              </div>
            )}

            {checks.warnings.length > 0 && (
              <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
                <ul className="list-inside list-disc space-y-0.5">
                  {checks.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-4 border-t border-slate-100 pt-3">
              {isApprovedForCurrentVersion ? (
                <div
                  className="rounded-md border border-emerald-200 bg-emerald-50 p-2.5 text-xs text-emerald-900"
                  data-testid="draft-approved-banner"
                >
                  <strong>Version v{draft.version} approved</strong>
                  {draft.approved_at ? ` on ${formatDateTime(draft.approved_at)}` : ''}. Export controls are unlocked
                  below.
                </div>
              ) : (
                <button
                  type="button"
                  className="btn-primary w-full"
                  disabled={!checks.ready_for_approval || approving}
                  onClick={onApprove}
                >
                  {approving ? 'Approving…' : `Approve Draft v${draft.version}`}
                </button>
              )}
            </div>
          </Section>

          <Section title="Local download & copy (fallback)">
            {!isApprovedForCurrentVersion ? (
              <p className="text-xs text-slate-500" data-testid="export-locked-msg">
                Approve draft v{draft.version} above to unlock HTML/text downloads and Listmonk draft export (AC-11).
              </p>
            ) : (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  <a
                    href={getDraftDownloadUrl(draft.id, 'html')}
                    className="btn-secondary btn-xs"
                    download
                  >
                    Download HTML
                  </a>
                  <a
                    href={getDraftDownloadUrl(draft.id, 'txt')}
                    className="btn-secondary btn-xs"
                    download
                  >
                    Download Plain Text
                  </a>
                </div>
                <div className="flex flex-wrap gap-2">
                  <CopyButton text={draft.subject} label="Copy subject" />
                  <CopyButton text={draft.body_html} label="Copy HTML" />
                  <CopyButton text={draft.body_text} label="Copy plain text" />
                </div>
              </div>
            )}
          </Section>

          <Section
            title="Listmonk unsent draft export"
            actions={<Badge tone="slate">Never sends campaigns</Badge>}
          >
            <p className="mb-3 text-xs text-slate-600">
              Creates an <strong>unsent draft campaign</strong> in Listmonk via idempotent API call. SwipeVault never
              starts, schedules, or sends campaigns.
            </p>

            {!isApprovedForCurrentVersion ? (
              <button type="button" className="btn-secondary w-full" disabled>
                Export locked until v{draft.version} is approved
              </button>
            ) : (
              <div className="space-y-3">
                <button
                  type="button"
                  className="btn-secondary btn-xs"
                  disabled={testingListmonk}
                  onClick={onLoadListmonkLists}
                >
                  {testingListmonk ? 'Checking Listmonk…' : 'Load consent-based lists from Listmonk'}
                </button>

                {listmonkTest && (
                  <div className="rounded border border-slate-200 bg-slate-50 p-2.5 text-xs">
                    <div className="font-medium text-slate-800">{listmonkTest.message}</div>
                    {!listmonkTest.enabled || !listmonkTest.reachable ? (
                      <p className="mt-1 text-amber-800">
                        Remote Listmonk export is unavailable; use the local HTML / Plain Text downloads above.
                      </p>
                    ) : listmonkTest.lists.length === 0 ? (
                      <p className="mt-1 text-slate-600">No lists returned by Listmonk.</p>
                    ) : (
                      <form onSubmit={onExportListmonk} className="mt-2 space-y-2.5">
                        <div>
                          <div className="mb-1 font-semibold text-slate-700">
                            Explicitly select target list(s) *
                          </div>
                          <div className="space-y-1">
                            {listmonkTest.lists.map((lst) => (
                              <label key={lst.id} className="flex items-center gap-2">
                                <input
                                  type="checkbox"
                                  checked={selectedListIds.has(lst.id)}
                                  onChange={() => toggleListId(lst.id)}
                                />
                                <span>
                                  {lst.name} <span className="text-slate-400">(#{lst.id} · {lst.type})</span>
                                </span>
                              </label>
                            ))}
                          </div>
                        </div>

                        <label className="flex items-start gap-2 rounded border border-slate-200 bg-white p-2 text-slate-800">
                          <input
                            type="checkbox"
                            required
                            checked={confirmUnsent}
                            onChange={(e) => setConfirmUnsent(e.target.checked)}
                            className="mt-0.5"
                          />
                          <span>
                            Create as an unsent draft campaign only (sending remains a separate action in Listmonk)
                          </span>
                        </label>

                        <button
                          type="submit"
                          className="btn-primary w-full"
                          disabled={selectedListIds.size === 0 || !confirmUnsent || exporting}
                        >
                          {exporting ? 'Creating unsent draft…' : 'Export unsent draft to Listmonk'}
                        </button>
                      </form>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="mt-4 border-t border-slate-100 pt-3">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Export history ({draft.exports.length})
              </div>
              {draft.exports.length === 0 ? (
                <p className="text-xs text-slate-500">No exports recorded for this draft.</p>
              ) : (
                <ul className="space-y-2 text-xs">
                  {draft.exports.map((ex) => (
                    <li key={ex.id} className="rounded border border-slate-200 bg-slate-50 p-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">
                          {ex.target} · v{ex.draft_version}
                        </span>
                        <ExportStatusBadge status={ex.status} />
                      </div>
                      {ex.remote_id && (
                        <div className="mt-1 font-mono text-[11px] text-slate-600">
                          Remote campaign ID: {ex.remote_id}
                          {ex.remote_url && (
                            <>
                              {' · '}
                              <a
                                href={ex.remote_url}
                                target="_blank"
                                rel="noreferrer"
                                className="link"
                              >
                                open in Listmonk ↗
                              </a>
                            </>
                          )}
                        </div>
                      )}
                      {ex.error_summary && (
                        <div className="mt-1 rounded bg-rose-50 px-2 py-1 text-rose-800">
                          {ex.error_summary}
                        </div>
                      )}
                      <div className="mt-0.5 text-[11px] text-slate-400">{formatDateTime(ex.created_at)}</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

function CheckRow({ ok, label, warnOnly = false }: { ok: boolean; label: string; warnOnly?: boolean }) {
  return (
    <li className="flex items-start gap-2">
      <span
        className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
          ok
            ? 'bg-emerald-100 text-emerald-800'
            : warnOnly
              ? 'bg-amber-100 text-amber-800'
              : 'bg-rose-100 text-rose-800'
        }`}
        aria-hidden
      >
        {ok ? '✓' : '!'}
      </span>
      <span className={ok ? 'text-slate-700' : 'font-medium text-slate-900'}>{label}</span>
    </li>
  );
}
