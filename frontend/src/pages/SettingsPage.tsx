import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Badge, EmptyState, ErrorState, KeyValue, PageHeader, Section, Spinner } from '../components/ui';
import { useAsync } from '../lib/useAsync';

export default function SettingsPage() {
  const { user } = useAuth();
  const networks = useAsync(() => api.networks(), []);

  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" />

      <Section title="Account">
        <KeyValue
          items={[
            ['Email', user?.email],
            ['Role', user?.role],
            ['User ID', <span className="font-mono text-xs">{user?.id}</span>],
          ]}
        />
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

      <Section title="Retrieval limits / Listmonk / AI (read-only)">
        <div className="space-y-3 text-sm text-slate-600">
          <p>
            These settings are <strong>not configurable in this version</strong>. They arrive in later phases:
          </p>
          <ul className="list-inside list-disc space-y-1">
            <li>
              <strong>Retrieval limits, allowed hosts and permission-aware scanning</strong> — Phase 2.
            </li>
            <li>
              <strong>Brand profiles, drafts and Listmonk draft export</strong> — Phase 3. No email is ever sent from
              SwipeVault.
            </li>
            <li>
              <strong>Optional AI assistance</strong> — later phase, opt-in only. No paid AI service is used today.
            </li>
          </ul>
          <p className="text-xs text-slate-500">
            Server-side limits (upload size, ZIP expansion limits) are enforced by the API and configured via environment
            variables at deployment.
          </p>
        </div>
      </Section>
    </div>
  );
}
