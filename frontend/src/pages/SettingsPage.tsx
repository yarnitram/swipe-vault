import { useEffect, useState, type FormEvent } from 'react';
import { api, errorMessage } from '../api/client';
import type { BrandProfile, ListmonkTestResponse } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/Toast';
import {
  Badge,
  EmptyState,
  ErrorState,
  Field,
  KeyValue,
  Modal,
  PageHeader,
  Section,
  Spinner,
} from '../components/ui';
import { formatBytes, formatDateTime, parseTags } from '../lib/format';
import { useAsync } from '../lib/useAsync';

export default function SettingsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const networks = useAsync(() => api.networks(), []);
  const runtime = useAsync(() => api.getRuntimeSettings(), []);
  const brands = useAsync(() => api.listBrands(), []);

  const [brandModalOpen, setBrandModalOpen] = useState(false);
  const [editingBrand, setEditingBrand] = useState<BrandProfile | null>(null);

  const [lmTesting, setLmTesting] = useState(false);
  const [lmResult, setLmResult] = useState<ListmonkTestResponse | null>(null);
  const [lmError, setLmError] = useState<string | null>(null);

  const onTestListmonk = async () => {
    setLmTesting(true);
    setLmError(null);
    try {
      const res = await api.testListmonkConnection();
      setLmResult(res);
    } catch (err) {
      setLmError(errorMessage(err));
    } finally {
      setLmTesting(false);
    }
  };

  return (
    <div className="max-w-5xl">
      <PageHeader title="Settings" subtitle="Account, brand profiles, retrieval ceilings, and Listmonk adapter." />

      <Section title="Account">
        <KeyValue
          items={[
            ['Email', user?.email],
            ['Role', user?.role],
            ['User ID', <span className="font-mono text-xs">{user?.id}</span>],
          ]}
        />
      </Section>

      <Section
        title={`Brand profiles (${brands.data?.length ?? 0})`}
        actions={
          <button
            type="button"
            className="btn-primary btn-xs"
            onClick={() => {
              setEditingBrand(null);
              setBrandModalOpen(true);
            }}
          >
            + Add brand profile
          </button>
        }
      >
        <p className="mb-3 text-xs text-slate-600">
          Each newsletter brand stores its display name, sender identity reference, affiliate tracking parameters,
          allowed affiliate hosts, affiliate disclosure, and sender footer template (FR-07).
        </p>

        {brands.loading && !brands.data ? (
          <Spinner />
        ) : brands.error ? (
          <ErrorState message={brands.error} onRetry={brands.reload} />
        ) : !brands.data || brands.data.length === 0 ? (
          <EmptyState title="No brand profiles configured" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Brand</th>
                  <th>Sender identity ref</th>
                  <th>Tracking / Allowed hosts</th>
                  <th>Disclosure preview</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {brands.data.map((b) => (
                  <tr key={b.id}>
                    <td>
                      <div className="font-medium text-slate-900">{b.name}</div>
                      <div className="font-mono text-xs text-slate-400">{b.slug}</div>
                    </td>
                    <td className="font-mono text-xs">{b.sender_identity_ref ?? '—'}</td>
                    <td className="text-xs">
                      {b.affiliate_settings_json?.default_tracking_param && (
                        <div>
                          Param:{' '}
                          <code className="rounded bg-slate-100 px-1">
                            {b.affiliate_settings_json.default_tracking_param}
                          </code>
                        </div>
                      )}
                      <div className="font-mono text-[11px] text-slate-500">
                        {(b.affiliate_settings_json?.allowed_affiliate_hosts ?? []).join(', ') || 'Default hosts'}
                      </div>
                    </td>
                    <td className="max-w-xs truncate text-xs text-slate-600">{b.disclosure_text}</td>
                    <td className="whitespace-nowrap text-xs text-slate-500">{formatDateTime(b.updated_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn-secondary btn-xs"
                        onClick={() => {
                          setEditingBrand(b);
                          setBrandModalOpen(true);
                        }}
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section
        title="Listmonk draft integration (FR-08)"
        actions={
          <button
            type="button"
            className="btn-secondary btn-xs"
            disabled={lmTesting}
            onClick={onTestListmonk}
          >
            {lmTesting ? 'Testing connection…' : 'Test Listmonk connection'}
          </button>
        }
      >
        <p className="mb-3 text-xs text-slate-600">
          Validates connectivity to the configured Listmonk instance without exposing API credentials. The adapter only
          creates unsent draft campaigns and never invokes send, schedule, or subscriber import endpoints.
        </p>

        {runtime.data && (
          <div className="mb-3">
            <KeyValue
              items={[
                [
                  'Adapter enabled',
                  runtime.data.listmonk_enabled ? <Badge tone="emerald">enabled</Badge> : <Badge>disabled</Badge>,
                ],
                [
                  'Credentials configured',
                  runtime.data.listmonk_configured ? (
                    <Badge tone="emerald">configured</Badge>
                  ) : (
                    <Badge tone="amber">not configured</Badge>
                  ),
                ],
                ['Base URL', <span className="font-mono text-xs">{runtime.data.listmonk_base_url ?? '—'}</span>],
              ]}
            />
          </div>
        )}

        {lmError && (
          <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            {lmError}
          </div>
        )}

        {lmResult && (
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={lmResult.reachable ? 'emerald' : 'amber'}>
                {lmResult.reachable ? 'Reachable' : 'Not reachable / disabled'}
              </Badge>
              <span className="font-medium text-slate-800">{lmResult.message}</span>
            </div>
            {lmResult.lists.length > 0 && (
              <div className="mt-2">
                <div className="mb-1 font-semibold text-slate-700">
                  Discovered lists ({lmResult.lists.length}):
                </div>
                <ul className="list-inside list-disc space-y-0.5 text-slate-600">
                  {lmResult.lists.map((l) => (
                    <li key={l.id}>
                      {l.name} (#{l.id} · {l.type})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title="Runtime retrieval limits & AI configuration (read-only)">
        {runtime.loading && !runtime.data ? (
          <Spinner />
        ) : runtime.error ? (
          <ErrorState message={runtime.error} onRetry={runtime.reload} />
        ) : runtime.data ? (
          <KeyValue
            items={[
              ['Crawl delay per host', `${runtime.data.crawl_delay_seconds}s`],
              ['Max pages per scan', runtime.data.crawl_max_pages],
              ['Max crawl depth', runtime.data.crawl_max_depth],
              ['Request timeout', `${runtime.data.crawl_timeout_seconds}s`],
              ['Max download size', formatBytes(runtime.data.download_max_bytes)],
              ['Near-duplicate similarity threshold', `${Math.round(runtime.data.near_duplicate_threshold * 100)}%`],
              ['AI provider', <Badge>{runtime.data.ai_provider}</Badge>],
            ]}
          />
        ) : null}
        <p className="mt-3 text-xs text-slate-500">
          Operator ceilings are configured via server environment variables at deployment.
        </p>
      </Section>

      <Section title="Networks (read-only)">
        {networks.loading && !networks.data ? (
          <Spinner />
        ) : networks.error ? (
          <ErrorState message={networks.error} onRetry={networks.reload} />
        ) : !networks.data || networks.data.length === 0 ? (
          <EmptyState title="No networks configured" />
        ) : (
          <table className="table-base">
            <thead>
              <tr>
                <th>Name</th>
                <th>Slug</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {networks.data.map((n) => (
                <tr key={n.id}>
                  <td className="font-medium">{n.name}</td>
                  <td className="font-mono text-xs">{n.slug}</td>
                  <td>{n.enabled ? <Badge tone="emerald">enabled</Badge> : <Badge>disabled</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <BrandProfileModal
        open={brandModalOpen}
        brand={editingBrand}
        onClose={() => setBrandModalOpen(false)}
        onSaved={() => {
          setBrandModalOpen(false);
          brands.reload();
          toast.success(editingBrand ? 'Brand profile updated.' : 'Brand profile created.');
        }}
      />
    </div>
  );
}

function BrandProfileModal({
  open,
  brand,
  onClose,
  onSaved,
}: {
  open: boolean;
  brand: BrandProfile | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState('');
  const [senderIdentityRef, setSenderIdentityRef] = useState('');
  const [defaultTrackingParam, setDefaultTrackingParam] = useState('');
  const [allowedHosts, setAllowedHosts] = useState('');
  const [disclosureText, setDisclosureText] = useState('');
  const [footerTemplate, setFooterTemplate] = useState('');
  const [integrationRef, setIntegrationRef] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (brand) {
      setName(brand.name);
      setSenderIdentityRef(brand.sender_identity_ref ?? '');
      setDefaultTrackingParam(brand.affiliate_settings_json?.default_tracking_param ?? '');
      setAllowedHosts((brand.affiliate_settings_json?.allowed_affiliate_hosts ?? []).join(', '));
      setDisclosureText(brand.disclosure_text);
      setFooterTemplate(brand.footer_template);
      setIntegrationRef(brand.integration_ref ?? '');
    } else {
      setName('');
      setSenderIdentityRef('');
      setDefaultTrackingParam('tid');
      setAllowedHosts('hop.clickbank.net');
      setDisclosureText(
        'Affiliate disclosure: This email contains affiliate links. If you purchase through these links, we may earn a commission at no extra cost to you.',
      );
      setFooterTemplate(
        'Sent by {{brand_name}} ({{sender_identity}}). To stop receiving these emails, use the unsubscribe link provided by our mailing list.',
      );
      setIntegrationRef('');
    }
    setError(null);
  }, [brand, open]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const payload = {
      name: name.trim(),
      sender_identity_ref: senderIdentityRef.trim() || null,
      affiliate_settings_json: {
        default_tracking_param: defaultTrackingParam.trim() || null,
        allowed_affiliate_hosts: parseTags(allowedHosts),
      },
      disclosure_text: disclosureText.trim(),
      footer_template: footerTemplate.trim(),
      integration_ref: integrationRef.trim() || null,
    };
    try {
      if (brand) {
        await api.updateBrand(brand.id, payload);
      } else {
        await api.createBrand(payload);
      }
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={brand ? `Edit brand: ${brand.name}` : 'Add brand profile'} open={open} onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-3">
        {error && (
          <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Brand display name *" htmlFor="brand-name">
            <input
              id="brand-name"
              className="input"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. MyFitterU"
            />
          </Field>
          <Field label="Approved sender identity reference" htmlFor="brand-sender">
            <input
              id="brand-sender"
              className="input"
              value={senderIdentityRef}
              onChange={(e) => setSenderIdentityRef(e.target.value)}
              placeholder="e.g. newsletter@myfitteru.example"
            />
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Default tracking parameter" htmlFor="brand-tracking">
            <input
              id="brand-tracking"
              className="input"
              value={defaultTrackingParam}
              onChange={(e) => setDefaultTrackingParam(e.target.value)}
              placeholder="e.g. tid"
            />
          </Field>
          <Field label="Allowed affiliate hosts (comma-separated)" htmlFor="brand-hosts">
            <input
              id="brand-hosts"
              className="input"
              value={allowedHosts}
              onChange={(e) => setAllowedHosts(e.target.value)}
              placeholder="hop.clickbank.net"
            />
          </Field>
        </div>

        <Field label="Affiliate disclosure text *" htmlFor="brand-disclosure">
          <textarea
            id="brand-disclosure"
            rows={2}
            className="input"
            required
            value={disclosureText}
            onChange={(e) => setDisclosureText(e.target.value)}
          />
        </Field>

        <Field label="Footer & sender identification template *" htmlFor="brand-footer">
          <textarea
            id="brand-footer"
            rows={2}
            className="input"
            required
            value={footerTemplate}
            onChange={(e) => setFooterTemplate(e.target.value)}
          />
        </Field>

        <Field label="Integration reference (optional)" htmlFor="brand-integration">
          <input
            id="brand-integration"
            className="input"
            value={integrationRef}
            onChange={(e) => setIntegrationRef(e.target.value)}
            placeholder="e.g. listmonk:default"
          />
        </Field>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : brand ? 'Save changes' : 'Create brand'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
