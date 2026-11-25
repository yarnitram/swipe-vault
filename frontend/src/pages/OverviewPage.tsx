import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { OverviewStats } from '../api/types';
import { EmptyState, ErrorState, JobStateBadge, PageHeader, Section, Spinner } from '../components/ui';
import { formatDateTime, formatDuration, jobElapsed } from '../lib/format';
import { useAsync } from '../lib/useAsync';

function StatCard({ label, value, to, tone = 'text-slate-900' }: { label: string; value: number | string; to?: string; tone?: string }) {
  const body = (
    <div className="card h-full p-4 transition-shadow hover:shadow-md">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
  return to ? (
    <Link to={to} className="block rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">
      {body}
    </Link>
  ) : (
    body
  );
}

function StatsGrid({ stats }: { stats: OverviewStats }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <StatCard label="Offers" value={stats.offers_total} to="/offers" />
      <StatCard label="Unique swipes" value={stats.swipes_total} to="/swipes" />
      <StatCard label="Pending reviews" value={stats.pending_reviews} to="/review" tone="text-amber-700" />
      <StatCard label="Needs changes" value={stats.needs_changes} to="/swipes?review_state=needs_changes" tone="text-violet-700" />
      <StatCard label="Approved" value={stats.approved} to="/swipes?review_state=approved" tone="text-emerald-700" />
      <StatCard label="Campaign drafts" value={stats.drafts_total ?? 0} to="/drafts" tone="text-indigo-700" />
      <StatCard label="Assets" value={stats.assets_total} />
      <StatCard label="Active jobs" value={stats.active_jobs} to="/jobs?state=running" tone="text-sky-700" />
      <StatCard label="Failed jobs" value={stats.failed_jobs} to="/jobs?state=failed" tone={stats.failed_jobs ? 'text-rose-700' : undefined} />
      <StatCard label="Last ingested" value={stats.last_ingested_at ? formatDateTime(stats.last_ingested_at) : 'Never'} />
    </div>
  );
}

export default function OverviewPage() {
  const stats = useAsync(() => api.overview(), []);
  const jobs = useAsync(() => api.listJobs({ page: 1, page_size: 8 }), []);

  return (
    <div>
      <PageHeader title="Overview" subtitle="Live counts from the database." />
      <div className="mb-6">
        {stats.loading && !stats.data ? (
          <Spinner label="Loading stats…" />
        ) : stats.error ? (
          <ErrorState message={stats.error} onRetry={stats.reload} />
        ) : stats.data ? (
          <StatsGrid stats={stats.data} />
        ) : null}
      </div>

      <Section title="Recent jobs" actions={<Link to="/jobs" className="link text-sm">All jobs →</Link>}>
        {jobs.loading && !jobs.data ? (
          <Spinner />
        ) : jobs.error ? (
          <ErrorState message={jobs.error} onRetry={jobs.reload} />
        ) : !jobs.data || jobs.data.items.length === 0 ? (
          <EmptyState title="No jobs yet">Upload an authorized file on an offer to start an ingest job.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Offer</th>
                  <th>State</th>
                  <th>Swipes new</th>
                  <th>Created</th>
                  <th>Elapsed</th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link to={`/jobs/${j.id}`} className="link font-mono text-xs">
                        {j.type} · {j.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td>
                      {j.offer_id ? (
                        <Link to={`/offers/${j.offer_id}`} className="link">
                          {j.offer_title ?? j.offer_id.slice(0, 8)}
                        </Link>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      <JobStateBadge state={j.state} />
                    </td>
                    <td className="tabular-nums">{j.progress.swipes_new}</td>
                    <td>{formatDateTime(j.created_at)}</td>
                    <td>{formatDuration(jobElapsed(j))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
