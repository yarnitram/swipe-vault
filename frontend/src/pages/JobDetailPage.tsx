import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import { TERMINAL_JOB_STATES, type JobDetail, type JobState } from '../api/types';
import { useToast } from '../components/Toast';
import {
  Badge,
  EmptyState,
  ErrorState,
  JobStateBadge,
  KeyValue,
  PageHeader,
  Section,
  Spinner,
} from '../components/ui';
import { formatDateTime, formatDuration, jobElapsed } from '../lib/format';
import { JOB_POLL_INTERVAL_MS } from '../lib/useJobPoller';

const CANCELLABLE: readonly JobState[] = ['queued', 'running'];
const RETRIABLE: readonly JobState[] = ['failed', 'partial', 'cancelled'];

export default function JobDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    const tick = async () => {
      try {
        const res = await api.getJob(id, controller.signal);
        if (cancelled) return;
        setJob(res);
        setLoading(false);
        setError(null);
        if (TERMINAL_JOB_STATES.includes(res.state)) return;
      } catch (e) {
        if (cancelled) return;
        setLoading(false);
        setError(errorMessage(e));
      }
      timer = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);
    };
    void tick();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [id]);

  const onCancel = async () => {
    if (!job) return;
    setBusy(true);
    try {
      const updated = await api.cancelJob(job.id);
      setJob((prev) => (prev ? { ...prev, ...updated } : null));
      toast.info('Cancellation requested.');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onRetry = async () => {
    if (!job) return;
    setBusy(true);
    try {
      const next = await api.retryJob(job.id);
      toast.success('Retry job queued.');
      navigate(`/jobs/${next.id}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading && !job) return <Spinner label="Loading job…" />;
  if (error && !job) return <ErrorState message={error} />;
  if (!job) return <EmptyState title="Job not found" />;

  const p = job.progress;

  return (
    <div>
      <PageHeader
        title={`Job ${job.id.slice(0, 8)}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{job.type}</span>
            <span>·</span>
            <JobStateBadge state={job.state} />
            <span>· Elapsed: {formatDuration(jobElapsed(job))}</span>
          </span>
        }
        actions={
          <>
            {CANCELLABLE.includes(job.state) && (
              <button type="button" className="btn-danger" disabled={busy} onClick={onCancel}>
                Cancel job
              </button>
            )}
            {RETRIABLE.includes(job.state) && (
              <button type="button" className="btn-primary" disabled={busy} onClick={onRetry}>
                Retry job
              </button>
            )}
            <Link to="/jobs" className="btn-secondary">
              ← All jobs
            </Link>
          </>
        }
      />

      {job.error_summary && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
        >
          <span className="font-semibold">Error summary: </span>
          {job.error_summary}
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <CounterCard label="Pages checked" value={p.pages_checked ?? 0} />
        <CounterCard label="Assets found" value={p.assets_found} />
        <CounterCard label="Assets processed" value={p.assets_processed} />
        <CounterCard label="Swipes extracted" value={p.swipes_extracted} />
        <CounterCard label="Swipes new" value={p.swipes_new} tone="text-emerald-700" />
        <CounterCard label="Versions new" value={p.versions_new} tone="text-indigo-700" />
        <CounterCard label="Duplicates" value={p.duplicates} />
        <CounterCard label="Warnings" value={p.warnings} tone={p.warnings ? 'text-amber-700' : undefined} />
      </div>

      <Section title="Metadata">
        <KeyValue
          items={[
            ['Job ID', <span className="font-mono text-xs">{job.id}</span>],
            ['Type', <span className="font-mono text-xs">{job.type}</span>],
            ['State', <JobStateBadge state={job.state} />],
            [
              'Offer',
              job.offer_id ? (
                <Link to={`/offers/${job.offer_id}`} className="link">
                  {job.offer_title ?? job.offer_id}
                </Link>
              ) : null,
            ],
            ['Attempts', job.attempts],
            ['Elapsed', formatDuration(jobElapsed(job))],
            ['Created', formatDateTime(job.created_at)],
            ['Started', formatDateTime(job.started_at)],
            ['Finished', formatDateTime(job.finished_at)],
          ]}
        />
      </Section>

      <Section title={`Events log (${job.events.length})`}>
        {job.events.length === 0 ? (
          <EmptyState title="No events logged yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Level</th>
                  <th>Event type</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {job.events.map((ev) => (
                  <tr key={ev.id}>
                    <td className="whitespace-nowrap font-mono text-xs text-slate-500">
                      {formatDateTime(ev.created_at)}
                    </td>
                    <td>
                      <Badge
                        tone={ev.level === 'error' ? 'rose' : ev.level === 'warning' ? 'amber' : 'slate'}
                      >
                        {ev.level}
                      </Badge>
                    </td>
                    <td className="font-mono text-xs">{ev.event_type}</td>
                    <td className="break-words text-sm">{ev.message}</td>
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

function CounterCard({ label, value, tone = 'text-slate-900' }: { label: string; value: number; tone?: string }) {
  return (
    <div className="card p-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}
