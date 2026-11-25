import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, ApiError, errorMessage } from '../api/client';
import {
  APPROVAL_STATES,
  type ApprovalState,
  type ImportCommitResponse,
  type ImportPreviewResponse,
  type OfferCreate,
} from '../api/types';
import ImportPreviewTable from '../components/ImportPreviewTable';
import { useToast } from '../components/Toast';
import {
  ApprovalBadge,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageHeader,
  Pagination,
  Spinner,
} from '../components/ui';
import { formatDateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';

const PAGE_SIZE = 25;

export default function OffersPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const network = params.get('network') ?? '';
  const niche = params.get('niche') ?? '';
  const approvalState = (params.get('approval_state') ?? '') as ApprovalState | '';
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1);

  const [qInput, setQInput] = useState(q);
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const networks = useAsync(() => api.networks(), []);
  const niches = useAsync(() => api.niches(), []);
  const offers = useAsync(
    () =>
      api.listOffers({
        q: q || undefined,
        network: network || undefined,
        niche: niche || undefined,
        approval_state: approvalState || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [q, network, niche, approvalState, page],
  );

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

  const onCreated = () => {
    setAddOpen(false);
    offers.reload();
    niches.reload();
    toast.success('Offer created.');
  };

  const onImported = (count: number) => {
    offers.reload();
    niches.reload();
    toast.success(`Imported ${count} offer${count === 1 ? '' : 's'}.`);
  };

  return (
    <div>
      <PageHeader
        title="Offers"
        subtitle="Curated affiliate offer catalog."
        actions={
          <>
            <button type="button" className="btn-secondary" onClick={() => setImportOpen(true)}>
              Import CSV
            </button>
            <button type="button" className="btn-primary" onClick={() => setAddOpen(true)}>
              + Add offer
            </button>
          </>
        }
      />

      <div className="card mb-4 p-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <form onSubmit={onSearchSubmit} className="sm:col-span-2">
            <label className="label" htmlFor="offers-search">
              Search
            </label>
            <div className="flex gap-2">
              <input
                id="offers-search"
                type="search"
                className="input"
                placeholder="Title, vendor, offer ID…"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
              />
              <button type="submit" className="btn-secondary">
                Filter
              </button>
            </div>
          </form>

          <div>
            <label className="label" htmlFor="offers-network">
              Network
            </label>
            <select
              id="offers-network"
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
            <label className="label" htmlFor="offers-niche">
              Niche
            </label>
            <select
              id="offers-niche"
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
            <label className="label" htmlFor="offers-approval">
              Approval state
            </label>
            <select
              id="offers-approval"
              className="input"
              value={approvalState}
              onChange={(e) => updateParam('approval_state', e.target.value)}
            >
              <option value="">All states</option>
              {APPROVAL_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {offers.loading && !offers.data ? (
        <Spinner label="Loading offers…" />
      ) : offers.error ? (
        <ErrorState message={offers.error} onRetry={offers.reload} />
      ) : !offers.data || offers.data.items.length === 0 ? (
        <EmptyState title="No offers found">
          Add an offer manually or import a CSV to populate your catalog.
        </EmptyState>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Offer</th>
                  <th>Network</th>
                  <th>Offer ID</th>
                  <th>Vendor</th>
                  <th>Niche</th>
                  <th>Approval</th>
                  <th>Swipes</th>
                  <th>Assets</th>
                  <th>Sources</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {offers.data.items.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <Link to={`/offers/${o.id}`} className="link font-medium">
                        {o.title}
                      </Link>
                    </td>
                    <td>{o.network.name}</td>
                    <td className="font-mono text-xs">{o.external_offer_id ?? '—'}</td>
                    <td>{o.vendor_name ?? '—'}</td>
                    <td>{o.niche ?? '—'}</td>
                    <td>
                      <ApprovalBadge state={o.approval_state} />
                    </td>
                    <td className="tabular-nums">{o.swipe_count}</td>
                    <td className="tabular-nums">{o.asset_count}</td>
                    <td className="tabular-nums">{o.source_count}</td>
                    <td className="whitespace-nowrap text-xs text-slate-500">{formatDateTime(o.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-100 px-3">
            <Pagination
              page={offers.data.page}
              pageSize={offers.data.page_size}
              total={offers.data.total}
              onPage={(p) => updateParam('page', String(p))}
            />
          </div>
        </div>
      )}

      <AddOfferModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        networks={networks.data ?? []}
        onCreated={onCreated}
      />

      <ImportCsvModal open={importOpen} onClose={() => setImportOpen(false)} onImported={onImported} />
    </div>
  );
}

function AddOfferModal({
  open,
  onClose,
  networks,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  networks: { id: string; slug: string; name: string; enabled: boolean }[];
  onCreated: () => void;
}) {
  const enabledNetworks = networks.filter((n) => n.enabled);
  const [networkSlug, setNetworkSlug] = useState('clickbank');
  const [title, setTitle] = useState('');
  const [externalOfferId, setExternalOfferId] = useState('');
  const [niche, setNiche] = useState('');
  const [vendorName, setVendorName] = useState('');
  const [offerUrl, setOfferUrl] = useState('');
  const [affiliateResourcesUrl, setAffiliateResourcesUrl] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setTitle('');
    setExternalOfferId('');
    setNiche('');
    setVendorName('');
    setOfferUrl('');
    setAffiliateResourcesUrl('');
    setNotes('');
    setError(null);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const body: OfferCreate = {
      network_slug: networkSlug,
      title: title.trim(),
      external_offer_id: externalOfferId.trim() || null,
      niche: niche.trim() || null,
      vendor_name: vendorName.trim() || null,
      offer_url: offerUrl.trim() || null,
      affiliate_resources_url: affiliateResourcesUrl.trim() || null,
      notes: notes.trim() || null,
    };
    try {
      await api.createOffer(body);
      reset();
      onCreated();
    } catch (err) {
      if (err instanceof ApiError && err.code === 'duplicate_offer') {
        setError('An offer with this network and external offer ID already exists.');
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="Add offer" open={open} onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-3">
        {error && (
          <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Network *" htmlFor="new-offer-network">
            <select
              id="new-offer-network"
              className="input"
              value={networkSlug}
              onChange={(e) => setNetworkSlug(e.target.value)}
              required
            >
              {(enabledNetworks.length ? enabledNetworks : [{ id: 'cb', slug: 'clickbank', name: 'ClickBank', enabled: true }]).map(
                (n) => (
                  <option key={n.slug} value={n.slug}>
                    {n.name}
                  </option>
                ),
              )}
            </select>
          </Field>
          <Field label="External offer ID / vendor nickname" htmlFor="new-offer-ext-id">
            <input
              id="new-offer-ext-id"
              className="input"
              value={externalOfferId}
              onChange={(e) => setExternalOfferId(e.target.value)}
              placeholder="e.g. fitburnpro"
            />
          </Field>
        </div>

        <Field label="Title *" htmlFor="new-offer-title">
          <input
            id="new-offer-title"
            className="input"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Offer title"
          />
        </Field>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Vendor name" htmlFor="new-offer-vendor">
            <input
              id="new-offer-vendor"
              className="input"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
            />
          </Field>
          <Field label="Niche" htmlFor="new-offer-niche">
            <input
              id="new-offer-niche"
              className="input"
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
              placeholder="e.g. Health & fitness"
            />
          </Field>
        </div>

        <Field label="Official offer URL" htmlFor="new-offer-url">
          <input
            id="new-offer-url"
            type="url"
            className="input"
            value={offerUrl}
            onChange={(e) => setOfferUrl(e.target.value)}
            placeholder="https://example.com"
          />
        </Field>

        <Field label="Affiliate resources URL" htmlFor="new-offer-aff-url">
          <input
            id="new-offer-aff-url"
            type="url"
            className="input"
            value={affiliateResourcesUrl}
            onChange={(e) => setAffiliateResourcesUrl(e.target.value)}
            placeholder="https://example.com/affiliates"
          />
        </Field>

        <Field label="Notes" htmlFor="new-offer-notes">
          <textarea
            id="new-offer-notes"
            rows={2}
            className="input"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Field>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create offer'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ImportCsvModal({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: (createdCount: number) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<ImportCommitResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setSelected(new Set());
    setResult(null);
    setError(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const onPreview = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.importPreview(file);
      setPreview(res);
      const validNums = new Set(res.rows.filter((r) => r.status === 'valid').map((r) => r.row_number));
      setSelected(validNums);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const onToggle = (rowNumber: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(rowNumber)) next.delete(rowNumber);
      else next.add(rowNumber);
      return next;
    });
  };

  const onToggleAll = (checked: boolean) => {
    if (!preview) return;
    if (!checked) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(preview.rows.filter((r) => r.status === 'valid').map((r) => r.row_number)));
  };

  const onCommit = async () => {
    if (!preview) return;
    const rowsToCommit = preview.rows
      .filter((r) => r.status === 'valid' && selected.has(r.row_number))
      .map((r) => ({ row_number: r.row_number, data: r.data }));
    if (rowsToCommit.length === 0) return;

    setLoading(true);
    setError(null);
    try {
      const res = await api.importCommit({ rows: rowsToCommit });
      setResult(res);
      onImported(res.created.length);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal title="Import offers from CSV" open={open} onClose={handleClose} wide>
      <div className="space-y-4">
        <p className="text-xs text-slate-600">
          Required header columns:{' '}
          <code className="rounded bg-slate-100 px-1 py-0.5 font-mono">
            network,external_offer_id,title,niche,vendor_name,offer_url,affiliate_resources_url,notes
          </code>
        </p>

        {error && (
          <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </div>
        )}

        {!result && (
          <form onSubmit={onPreview} className="flex flex-wrap items-end gap-3">
            <div className="flex-1">
              <label className="label" htmlFor="csv-file">
                CSV file
              </label>
              <input
                id="csv-file"
                type="file"
                accept=".csv,text/csv"
                className="input"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setPreview(null);
                  setResult(null);
                }}
              />
            </div>
            <button type="submit" className="btn-secondary" disabled={!file || loading}>
              {loading && !preview ? 'Validating…' : 'Preview CSV'}
            </button>
          </form>
        )}

        {preview && !result && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-slate-50 px-3 py-2 text-sm">
              <div className="flex flex-wrap gap-4">
                <span>
                  Total: <strong>{preview.summary.total}</strong>
                </span>
                <span className="text-emerald-700">
                  Valid: <strong>{preview.summary.valid}</strong>
                </span>
                <span className="text-rose-700">
                  Invalid: <strong>{preview.summary.invalid}</strong>
                </span>
                <span className="text-amber-700">
                  Duplicates: <strong>{preview.summary.duplicates}</strong>
                </span>
              </div>
              <span className="text-xs text-slate-600">{selected.size} valid row(s) selected</span>
            </div>

            <ImportPreviewTable
              rows={preview.rows}
              selected={selected}
              onToggle={onToggle}
              onToggleAll={onToggleAll}
            />

            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={handleClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={selected.size === 0 || loading}
                onClick={onCommit}
              >
                {loading ? 'Importing…' : `Commit ${selected.size} valid row(s)`}
              </button>
            </div>
          </>
        )}

        {result && (
          <div className="space-y-3" data-testid="import-result-summary">
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
              <p className="font-semibold">Import complete</p>
              <p className="mt-1">
                Created: <strong>{result.created.length}</strong> · Skipped: <strong>{result.skipped.length}</strong>
              </p>
            </div>
            {result.skipped.length > 0 && (
              <div className="rounded-md border border-slate-200 p-3 text-xs">
                <p className="mb-1 font-semibold text-slate-700">Skipped rows:</p>
                <ul className="list-inside list-disc space-y-0.5 text-slate-600">
                  {result.skipped.map((s) => (
                    <li key={s.row_number}>
                      Row {s.row_number}: {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={reset}>
                Import another file
              </button>
              <button type="button" className="btn-primary" onClick={handleClose}>
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
