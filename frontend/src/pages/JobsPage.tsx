import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import { JOB_STATES, type Job, type JobState } from '../api/types';
import { useToast } from '../components/Toast';
import { EmptyState, ErrorState, JobStateBadge, PageHeader, Pagination, Spinner } from '../components/ui';
import { formatDateTime, formatDuration, jobElapsed } from '../lib/format';
import { useAsync } from '../lib/useAsync';

const PAGE_SIZE = 25;
const CANCELLABLE: readonly JobState[] = ['queued', 'running'];
const RETRIABLE: readonly JobState[] = ['failed', 'partial', 'cancelled'];

export default function JobsPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const stateFilter = (params.get('state') ?? '') as JobState | '';
  const offerId = params.get('offer_id') ?? '';
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1);
  const [busyId, setBusyId] = useState<string | null>(null);

  const jobs = useAsync(
    () =>
      api.listJobs({
        state: stateFilter || undefined,
        offer_id: offerId || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [stateFilter, offerId, page],
  );

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next);
  };

  const onCancel = async (job: Job) => {
    setBusyId(job.id);
    try {
      await api.cancelJob(job.id);
      toast.info('Cancellation requested.');
      jobs.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onRetry = async (job: Job) => {
    setBusyId(job.id);
    try {
      const next = await api.retryJob(job.id);
      toast.success('Retry job queued.');
      navigate(`/jobs/${next.id}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Jobs"
        subtitle="Background ingestion and extraction jobs."
        actions={
          <button type="button" className="btn-secondary" onClick={jobs.reload}>
            Refresh
          </button>
        }
      />

      <div className="card mb-4 flex flex-wrap items-end gap-3 p-3">
        <div className="w-56">
          <label className="label" htmlFor="jobs-state">
            State
          </label>
          <select
            id="jobs-state"
            className="input"
            value={stateFilter}
            onChange={(e) => updateParam('state', e.target.value)}
          >
            <option value="">All states</option>
            {JOB_STATES.map((s) => (
              <option key={s} value={s}>
                {s.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>
        {offerId && (
          <div className="flex items-center gap-2 text-xs text-slate-600">
            <span>Offer:</span>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">{offerId}</code>
            <button type="button" className="link" onClick={() => updateParam('offer_id', '')}>
              Clear
            </button>
          </div>
        )}
      </div>

      {jobs.loading && !jobs.data ? (
        <Spinner label="Loading jobs…" />
      ) : jobs.error ? (
        <ErrorState message={jobs.error} onRetry={jobs.reload} />
      ) : !jobs.data || jobs.data.items.length === 0 ? (
        <EmptyState title="No jobs found" />
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Offer</th>
                  <th>State</th>
                  <th>Assets</th>
                  <th>Swipes (new / dup)</th>
                  <th>Warnings</th>
                  <th>Attempts</th>
                  <th>Created</th>
                  <th>Elapsed</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link to={`/jobs/${j.id}`} className="link font-mono text-xs font-medium">
                        {j.type} · {j.id.slice(0, 8)}
                      </Link>
                      {j.error_summary && (
                        <div className="mt-0.5 max-w-xs truncate text-xs text-rose-700" title={j.error_summary}>
                          {j.error_summary}
                        </div>
                      )}
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
                    <td className="tabular-nums">
                      {j.progress.assets_processed} / {j.progress.assets_found}
                    </td>
                    <td className="tabular-nums">
                      {j.progress.swipes_new} new · {j.progress.duplicates} dup
                    </td>
                    <td className="tabular-nums">{j.progress.warnings}</td>
                    <td className="tabular-nums">{j.attempts}</td>
                    <td className="whitespace-nowrap text-xs text-slate-500">{formatDateTime(j.created_at)}</td>
                    <td className="whitespace-nowrap tabular-nums">{formatDuration(jobElapsed(j))}</td>
                    <td>
                      <div className="flex items-center gap-1.5">
                        <Link to={`/jobs/${j.id}`} className="btn-secondary btn-xs">
                          View
                        </Link>
                        {CANCELLABLE.includes(j.state) && (
                          <button
                            type="button"
                            className="btn-danger btn-xs"
                            disabled={busyId === j.id}
                            onClick={() => onCancel(j)}
                          >
                            Cancel
                          </button>
                        )}
                        {RETRIABLE.includes(j.state) && (
                          <button
                            type="button"
                            className="btn-secondary btn-xs"
                            disabled={busyId === j.id}
                            onClick={() => onRetry(j)}
                          >
                            Retry
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-100 px-3">
            <Pagination
              page={jobs.data.page}
              pageSize={jobs.data.page_size}
              total={jobs.data.total}
              onPage={(p) => updateParam('page', String(p))}
            />
          </div>
        </div>
      )}
    </div>
  );
}
