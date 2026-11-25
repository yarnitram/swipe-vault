import { useEffect, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError, assetDownloadUrl, errorMessage } from '../api/client';
import {
  ACCESS_STATES,
  APPROVAL_STATES,
  SOURCE_TYPES,
  type AccessState,
  type ApprovalState,
  type Offer,
  type SourceType,
} from '../api/types';
import { useToast } from '../components/Toast';
import {
  ApprovalBadge,
  Badge,
  ConfidenceBadge,
  EmptyState,
  ErrorState,
  ExtractionBadge,
  Field,
  FlagBadge,
  JobStateBadge,
  PageHeader,
  ReviewBadge,
  Section,
  Spinner,
} from '../components/ui';
import { formatBytes, formatDateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import { useJobPoller } from '../lib/useJobPoller';

export default function OfferDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const toast = useToast();

  const offer = useAsync(() => api.getOffer(id), [id]);
  const approvals = useAsync(() => api.listApprovals(id), [id]);
  const sources = useAsync(() => api.listSources(id), [id]);
  const assets = useAsync(() => api.listAssets(id), [id]);
  const swipes = useAsync(() => api.listSwipes({ offer_id: id, page: 1, page_size: 50 }), [id]);

  // Active upload job being polled
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const { job: activeJob, error: pollError } = useJobPoller(activeJobId, (finishedJob) => {
    assets.reload();
    swipes.reload();
    offer.reload();
    if (finishedJob.state === 'completed') {
      toast.success(
        `Ingest completed: ${finishedJob.progress.swipes_new} new swipe(s), ${finishedJob.progress.duplicates} duplicate(s).`,
      );
    } else if (finishedJob.state === 'partial') {
      toast.info(`Ingest finished with warnings (${finishedJob.progress.warnings}).`);
    } else if (finishedJob.state === 'failed') {
      toast.error(finishedJob.error_summary || 'Ingest job failed.');
    }
  });

  if (offer.loading && !offer.data) return <Spinner label="Loading offer…" />;
  if (offer.error) return <ErrorState message={offer.error} onRetry={offer.reload} />;
  if (!offer.data) return <EmptyState title="Offer not found" />;

  const o = offer.data;

  return (
    <div>
      <PageHeader
        title={o.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span>{o.network.name}</span>
            {o.external_offer_id && <span className="font-mono text-xs">({o.external_offer_id})</span>}
            <span>·</span>
            <ApprovalBadge state={o.approval_state} />
            <span>· Updated {formatDateTime(o.updated_at)}</span>
          </span>
        }
        actions={
          <Link to="/offers" className="btn-secondary">
            ← All offers
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <OfferEditSection
            offer={o}
            onSaved={(updated) => {
              offer.setData(updated);
              toast.success('Offer updated.');
            }}
          />
        </div>
        <div>
          <ApprovalSection
            offerId={o.id}
            currentState={o.approval_state}
            approvals={approvals.data ?? []}
            loading={approvals.loading && !approvals.data}
            error={approvals.error}
            onRecorded={() => {
              approvals.reload();
              offer.reload();
              toast.success('Approval state recorded.');
            }}
          />
        </div>
      </div>

      <SourcesSection
        offerId={o.id}
        sources={sources.data ?? []}
        loading={sources.loading && !sources.data}
        error={sources.error}
        onRetry={sources.reload}
        onChanged={() => {
          sources.reload();
          offer.reload();
        }}
      />

      <AssetUploadSection
        offerId={o.id}
        sources={sources.data ?? []}
        activeJob={activeJob}
        pollError={pollError}
        onUploaded={(jobId, duplicate) => {
          setActiveJobId(jobId);
          assets.reload();
          offer.reload();
          if (duplicate) {
            toast.info('Duplicate asset SHA-256 detected; ingestion job queued.');
          } else {
            toast.info('Asset uploaded; extraction job started.');
          }
        }}
      />

      <Section title={`Assets (${assets.data?.length ?? o.asset_count})`}>
        {assets.loading && !assets.data ? (
          <Spinner />
        ) : assets.error ? (
          <ErrorState message={assets.error} onRetry={assets.reload} />
        ) : !assets.data || assets.data.length === 0 ? (
          <EmptyState title="No assets uploaded yet">
            Upload an authorized TXT, HTML, PDF, DOCX, or ZIP file above to extract email swipes.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Origin</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>State</th>
                  <th>Swipes</th>
                  <th>Retrieved</th>
                  <th>Download</th>
                </tr>
              </thead>
              <tbody>
                {assets.data.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <div className="font-medium text-slate-900">
                        {a.parent_asset_id && <span className="mr-1 text-slate-400">↳</span>}
                        {a.filename}
                      </div>
                      <div className="font-mono text-[11px] text-slate-400" title={a.sha256}>
                        sha256: {a.sha256.slice(0, 12)}…
                      </div>
                      {a.extraction_error && (
                        <div className="mt-1 rounded bg-rose-50 px-2 py-1 text-xs text-rose-700" role="alert">
                          {a.extraction_error}
                        </div>
                      )}
                    </td>
                    <td>
                      <Badge>{a.origin}</Badge>
                    </td>
                    <td className="font-mono text-xs">{a.media_type}</td>
                    <td className="whitespace-nowrap tabular-nums">{formatBytes(a.size_bytes)}</td>
                    <td>
                      <ExtractionBadge state={a.extraction_state} />
                    </td>
                    <td className="tabular-nums">{a.swipe_count}</td>
                    <td className="whitespace-nowrap text-xs text-slate-500">{formatDateTime(a.retrieved_at)}</td>
                    <td>
                      <a
                        href={assetDownloadUrl(a.id)}
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
      </Section>

      <Section
        title={`Swipes for this offer (${swipes.data?.total ?? o.swipe_count})`}
        actions={
          <Link to={`/swipes?offer_id=${encodeURIComponent(o.id)}`} className="link text-sm">
            Open in Swipe Library →
          </Link>
        }
      >
        {swipes.loading && !swipes.data ? (
          <Spinner />
        ) : swipes.error ? (
          <ErrorState message={swipes.error} onRetry={swipes.reload} />
        ) : !swipes.data || swipes.data.items.length === 0 ? (
          <EmptyState title="No swipes extracted for this offer yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Subject / Title</th>
                  <th>Excerpt</th>
                  <th>Confidence</th>
                  <th>Flags</th>
                  <th>State</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {swipes.data.items.map((s) => {
                  const extra = Math.max(0, s.current_version.subject_count - 1);
                  return (
                    <tr key={s.id}>
                      <td>
                        <Link to={`/swipes/${s.id}`} className="link font-medium">
                          {s.current_version.primary_subject || s.title || '(No subject)'}
                        </Link>
                        {extra > 0 && (
                          <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                            +{extra} variant{extra > 1 ? 's' : ''}
                          </span>
                        )}
                      </td>
                      <td className="max-w-md truncate text-xs text-slate-600">{s.current_version.body_excerpt}</td>
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
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

function OfferEditSection({ offer, onSaved }: { offer: Offer; onSaved: (o: Offer) => void }) {
  const [title, setTitle] = useState(offer.title);
  const [externalOfferId, setExternalOfferId] = useState(offer.external_offer_id ?? '');
  const [vendorName, setVendorName] = useState(offer.vendor_name ?? '');
  const [niche, setNiche] = useState(offer.niche ?? '');
  const [offerUrl, setOfferUrl] = useState(offer.offer_url ?? '');
  const [affiliateResourcesUrl, setAffiliateResourcesUrl] = useState(offer.affiliate_resources_url ?? '');
  const [notes, setNotes] = useState(offer.notes ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTitle(offer.title);
    setExternalOfferId(offer.external_offer_id ?? '');
    setVendorName(offer.vendor_name ?? '');
    setNiche(offer.niche ?? '');
    setOfferUrl(offer.offer_url ?? '');
    setAffiliateResourcesUrl(offer.affiliate_resources_url ?? '');
    setNotes(offer.notes ?? '');
  }, [offer]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateOffer(offer.id, {
        title: title.trim(),
        external_offer_id: externalOfferId.trim() || null,
        vendor_name: vendorName.trim() || null,
        niche: niche.trim() || null,
        offer_url: offerUrl.trim() || null,
        affiliate_resources_url: affiliateResourcesUrl.trim() || null,
        notes: notes.trim() || null,
      });
      onSaved(updated);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section title="Offer details">
      <form onSubmit={onSubmit} className="space-y-3">
        {error && (
          <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Title *" htmlFor="edit-offer-title">
            <input
              id="edit-offer-title"
              className="input"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
          <Field label="External offer ID" htmlFor="edit-offer-ext-id">
            <input
              id="edit-offer-ext-id"
              className="input"
              value={externalOfferId}
              onChange={(e) => setExternalOfferId(e.target.value)}
            />
          </Field>
          <Field label="Vendor name" htmlFor="edit-offer-vendor">
            <input
              id="edit-offer-vendor"
              className="input"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
            />
          </Field>
          <Field label="Niche" htmlFor="edit-offer-niche">
            <input
              id="edit-offer-niche"
              className="input"
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
            />
          </Field>
          <Field label="Official offer URL" htmlFor="edit-offer-url">
            <input
              id="edit-offer-url"
              type="url"
              className="input"
              value={offerUrl}
              onChange={(e) => setOfferUrl(e.target.value)}
            />
          </Field>
          <Field label="Affiliate resources URL" htmlFor="edit-offer-aff-url">
            <input
              id="edit-offer-aff-url"
              type="url"
              className="input"
              value={affiliateResourcesUrl}
              onChange={(e) => setAffiliateResourcesUrl(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Notes" htmlFor="edit-offer-notes">
          <textarea
            id="edit-offer-notes"
            rows={2}
            className="input"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Field>
        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-slate-500">
            Metrics: {offer.metrics_source ? `${offer.metrics_source} (${formatDateTime(offer.metrics_as_of)})` : 'none recorded'}
          </span>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>
    </Section>
  );
}

function ApprovalSection({
  offerId,
  currentState,
  approvals,
  loading,
  error,
  onRecorded,
}: {
  offerId: string;
  currentState: ApprovalState;
  approvals: { id: string; state: ApprovalState; notes: string | null; user_email: string | null; created_at: string }[];
  loading: boolean;
  error: string | null;
  onRecorded: () => void;
}) {
  const [state, setState] = useState<ApprovalState>(currentState);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  useEffect(() => {
    setState(currentState);
  }, [currentState]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setSubmitErr(null);
    try {
      await api.createApproval(offerId, { state, notes: notes.trim() || null });
      setNotes('');
      onRecorded();
    } catch (err) {
      setSubmitErr(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Section title="Affiliate approval">
      <form onSubmit={onSubmit} className="space-y-2 border-b border-slate-100 pb-3">
        {submitErr && (
          <div role="alert" className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-800">
            {submitErr}
          </div>
        )}
        <Field label="Record new approval state" htmlFor="approval-state">
          <select
            id="approval-state"
            className="input"
            value={state}
            onChange={(e) => setState(e.target.value as ApprovalState)}
          >
            {APPROVAL_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Approval / permission notes" htmlFor="approval-notes">
          <input
            id="approval-notes"
            className="input"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Vendor approval ID, restrictions, etc."
          />
        </Field>
        <button type="submit" className="btn-secondary w-full" disabled={submitting}>
          {submitting ? 'Recording…' : 'Record approval'}
        </button>
      </form>

      <div className="mt-3">
        <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">History</div>
        {loading ? (
          <Spinner />
        ) : error ? (
          <p className="text-xs text-rose-700">{error}</p>
        ) : approvals.length === 0 ? (
          <p className="text-xs text-slate-500">No approval records yet.</p>
        ) : (
          <ul className="max-h-48 space-y-2 overflow-y-auto text-xs">
            {approvals.map((a) => (
              <li key={a.id} className="rounded border border-slate-100 bg-slate-50 p-2">
                <div className="flex items-center justify-between gap-2">
                  <ApprovalBadge state={a.state} />
                  <span className="text-slate-500">{formatDateTime(a.created_at)}</span>
                </div>
                {a.notes && <p className="mt-1 text-slate-700">{a.notes}</p>}
                {a.user_email && <p className="mt-0.5 text-[11px] text-slate-400">by {a.user_email}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}

function SourcesSection({
  offerId,
  sources,
  loading,
  error,
  onRetry,
  onChanged,
}: {
  offerId: string;
  sources: {
    id: string;
    url: string;
    source_type: SourceType;
    access_state: AccessState;
    permission_notes: string | null;
    allowed_hosts: string[];
    created_at: string;
  }[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [url, setUrl] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('affiliate_page');
  const [accessState, setAccessState] = useState<AccessState>('unverified');
  const [permissionNotes, setPermissionNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formErr, setFormErr] = useState<{ code?: string; message: string; details?: string[] } | null>(null);

  const onAdd = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormErr(null);
    try {
      await api.createSource(offerId, {
        url: url.trim(),
        source_type: sourceType,
        access_state: accessState,
        permission_notes: permissionNotes.trim() || null,
      });
      setUrl('');
      setPermissionNotes('');
      toast.success('Source added.');
      onChanged();
    } catch (err) {
      if (err instanceof ApiError && err.code === 'unsafe_url') {
        setFormErr({
          code: 'unsafe_url',
          message: `Unsafe URL rejected (${err.code}): ${err.message}`,
          details: err.fieldErrors,
        });
      } else if (err instanceof ApiError && err.code === 'duplicate_source') {
        setFormErr({ code: 'duplicate_source', message: 'This source URL is already registered for this offer.' });
      } else if (err instanceof ApiError) {
        setFormErr({ code: err.code, message: err.message, details: err.fieldErrors });
      } else {
        setFormErr({ message: errorMessage(err) });
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Section
      title={`Sources (${sources.length})`}
      actions={<Badge tone="slate">Scanning arrives in Phase 2</Badge>}
    >
      <p className="mb-3 text-xs text-slate-600">
        Record authorized affiliate resource pages and asset URLs. Automated scanning arrives in Phase 2; in Phase 1,
        upload downloaded vendor files directly in the section below.
      </p>

      <form onSubmit={onAdd} className="mb-4 rounded-md border border-slate-200 bg-slate-50/70 p-3">
        {formErr && (
          <div
            role="alert"
            data-testid="source-error"
            className="mb-3 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900"
          >
            <div className="font-semibold">
              {formErr.code === 'unsafe_url' ? 'Blocked by SSRF / URL safety policy (422 unsafe_url)' : 'Could not add source'}
            </div>
            <div className="mt-0.5">{formErr.message}</div>
            {formErr.details && formErr.details.length > 0 && (
              <ul className="mt-1 list-inside list-disc text-xs">
                {formErr.details.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <div className="sm:col-span-2">
            <Field label="Source URL *" htmlFor="source-url">
              <input
                id="source-url"
                type="url"
                required
                className="input"
                placeholder="https://vendor.example.com/affiliates"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </Field>
          </div>
          <Field label="Type" htmlFor="source-type">
            <select
              id="source-type"
              className="input"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value as SourceType)}
            >
              {SOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Access state" htmlFor="source-access">
            <select
              id="source-access"
              className="input"
              value={accessState}
              onChange={(e) => setAccessState(e.target.value as AccessState)}
            >
              {ACCESS_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <div className="flex-1">
            <Field label="Permission notes" htmlFor="source-notes">
              <input
                id="source-notes"
                className="input"
                value={permissionNotes}
                onChange={(e) => setPermissionNotes(e.target.value)}
                placeholder="e.g. Approved affiliate tools page; email swipes section"
              />
            </Field>
          </div>
          <button type="submit" className="btn-secondary" disabled={submitting}>
            {submitting ? 'Adding…' : '+ Add source'}
          </button>
        </div>
      </form>

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorState message={error} onRetry={onRetry} />
      ) : sources.length === 0 ? (
        <EmptyState title="No source URLs recorded" />
      ) : (
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>URL</th>
                <th>Type</th>
                <th>Access</th>
                <th>Allowed hosts</th>
                <th>Permission notes</th>
                <th>Added</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.id}>
                  <td className="max-w-md break-all font-mono text-xs">{s.url}</td>
                  <td>
                    <Badge>{s.source_type}</Badge>
                  </td>
                  <td>
                    <Badge tone={s.access_state === 'authorized' ? 'emerald' : s.access_state === 'forbidden' ? 'rose' : 'slate'}>
                      {s.access_state}
                    </Badge>
                  </td>
                  <td className="font-mono text-xs">{s.allowed_hosts.join(', ') || '—'}</td>
                  <td className="text-xs">{s.permission_notes ?? '—'}</td>
                  <td className="whitespace-nowrap text-xs text-slate-500">{formatDateTime(s.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function AssetUploadSection({
  offerId,
  sources,
  activeJob,
  pollError,
  onUploaded,
}: {
  offerId: string;
  sources: { id: string; url: string }[];
  activeJob: {
    id: string;
    state: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancel_requested' | 'cancelled';
    progress: {
      assets_found: number;
      assets_processed: number;
      swipes_extracted: number;
      swipes_new: number;
      versions_new: number;
      duplicates: number;
      warnings: number;
    };
    error_summary: string | null;
  } | null;
  pollError: string | null;
  onUploaded: (jobId: string, duplicateAsset: boolean) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [sourceId, setSourceId] = useState('');
  const [notes, setNotes] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || !confirmed) return;
    setUploading(true);
    setError(null);
    try {
      const res = await api.uploadAsset(offerId, file, {
        sourceId: sourceId || undefined,
        notes: notes.trim() || undefined,
      });
      setFile(null);
      setNotes('');
      setConfirmed(false);
      onUploaded(res.job.id, res.duplicate_asset);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Section title="Upload authorized asset">
      <form onSubmit={onSubmit} className="space-y-3">
        {error && (
          <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field
            label="File (.txt, .html, .pdf, .docx, .zip — max 25 MB) *"
            htmlFor="asset-file"
          >
            <input
              id="asset-file"
              type="file"
              accept=".txt,.html,.htm,.pdf,.docx,.zip"
              required
              className="input"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>
          <Field label="Attributed source (optional)" htmlFor="asset-source">
            <select
              id="asset-source"
              className="input"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
            >
              <option value="">None (direct upload)</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.url}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Notes (optional)" htmlFor="asset-notes">
            <input
              id="asset-notes"
              className="input"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Version label or context"
            />
          </Field>
        </div>

        <label className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 p-2.5 text-sm text-slate-800">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5"
          />
          <span>I confirm I am authorized to store and use these materials</span>
        </label>

        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-slate-500">
            Original bytes and SHA-256 are preserved; documents are parsed as data with no macros or script execution.
          </span>
          <button type="submit" className="btn-primary" disabled={!file || !confirmed || uploading}>
            {uploading ? 'Uploading…' : 'Upload & extract'}
          </button>
        </div>
      </form>

      {activeJob && (
        <div
          className="mt-4 rounded-md border border-indigo-200 bg-indigo-50/60 p-3 text-sm"
          data-testid="active-ingest-job"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-800">Ingest job</span>
              <Link to={`/jobs/${activeJob.id}`} className="link font-mono text-xs">
                {activeJob.id.slice(0, 8)}
              </Link>
              <JobStateBadge state={activeJob.state} />
            </div>
            <div className="text-xs text-slate-600">
              Assets: {activeJob.progress.assets_processed}/{activeJob.progress.assets_found} · Extracted:{' '}
              {activeJob.progress.swipes_extracted} · New: {activeJob.progress.swipes_new} · Duplicates:{' '}
              {activeJob.progress.duplicates}
            </div>
          </div>
          {activeJob.error_summary && (
            <p className="mt-1 text-xs text-rose-700">{activeJob.error_summary}</p>
          )}
          {pollError && <p className="mt-1 text-xs text-rose-700">{pollError}</p>}
        </div>
      )}
    </Section>
  );
}
