import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { ApprovalState, ExtractionState, JobState, ReviewState } from '../api/types';
import { FLAG_DESCRIPTIONS } from '../api/types';

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
      <div className="flex items-center justify-between gap-3">
        <span>{message}</span>
        {onRetry && (
          <button type="button" className="btn-secondary btn-xs" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card mb-4">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
        {actions}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

type Tone = 'slate' | 'indigo' | 'emerald' | 'amber' | 'rose' | 'sky' | 'violet';
const toneClasses: Record<Tone, string> = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
  indigo: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  rose: 'bg-rose-50 text-rose-700 ring-rose-200',
  sky: 'bg-sky-50 text-sky-700 ring-sky-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
};

export function Badge({ tone = 'slate', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}

const reviewTone: Record<ReviewState, Tone> = {
  pending: 'amber',
  needs_changes: 'violet',
  approved: 'emerald',
  rejected: 'rose',
  archived: 'slate',
};
export function ReviewBadge({ state }: { state: ReviewState }) {
  return <Badge tone={reviewTone[state] ?? 'slate'}>{state.replace('_', ' ')}</Badge>;
}

const approvalTone: Record<ApprovalState, Tone> = {
  unknown: 'slate',
  requested: 'sky',
  approved: 'emerald',
  denied: 'rose',
  revoked: 'amber',
};
export function ApprovalBadge({ state }: { state: ApprovalState }) {
  return <Badge tone={approvalTone[state] ?? 'slate'}>{state}</Badge>;
}

const jobTone: Record<JobState, Tone> = {
  queued: 'slate',
  running: 'sky',
  completed: 'emerald',
  partial: 'amber',
  failed: 'rose',
  cancel_requested: 'violet',
  cancelled: 'slate',
};
export function JobStateBadge({ state }: { state: JobState }) {
  return <Badge tone={jobTone[state] ?? 'slate'}>{state.replace('_', ' ')}</Badge>;
}

const extractionTone: Record<ExtractionState, Tone> = {
  pending: 'slate',
  processing: 'sky',
  extracted: 'emerald',
  needs_review: 'amber',
  failed: 'rose',
  unsupported: 'violet',
};
export function ExtractionBadge({ state }: { state: ExtractionState }) {
  return <Badge tone={extractionTone[state] ?? 'slate'}>{state.replace('_', ' ')}</Badge>;
}

export function FlagBadge({ flag }: { flag: string }) {
  return (
    <Badge tone="amber" title={FLAG_DESCRIPTIONS[flag] ?? flag}>
      {flag}
    </Badge>
  );
}

export function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-slate-400">—</span>;
  const pct = Math.round(value * 100);
  const tone: Tone = pct >= 80 ? 'emerald' : pct >= 50 ? 'amber' : 'rose';
  return <Badge tone={tone}>{pct}%</Badge>;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav className="flex items-center justify-between gap-2 px-1 py-2 text-sm text-slate-600" aria-label="Pagination">
      <span>
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button type="button" className="btn-secondary btn-xs" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ← Prev
        </button>
        <span className="px-2">
          Page {page} / {pages}
        </span>
        <button type="button" className="btn-secondary btn-xs" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next →
        </button>
      </div>
    </nav>
  );
}

export function Modal({
  title,
  open,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const first = ref.current?.querySelector<HTMLElement>('input, select, textarea, button');
    first?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-16">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`card w-full ${wide ? 'max-w-5xl' : 'max-w-lg'}`}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" className="btn-ghost btn-xs" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function CopyButton({ text, label = 'Copy', className = '' }: { text: string; label?: string; className?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const onClick = async () => {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch {
      setState('failed');
    }
    window.setTimeout(() => setState('idle'), 1500);
  };
  return (
    <button
      type="button"
      className={`btn-secondary btn-xs ${className}`}
      onClick={onClick}
      disabled={!text}
      aria-label={`${label}${state === 'copied' ? ' (copied)' : ''}`}
    >
      {state === 'copied' ? 'Copied ✓' : state === 'failed' ? 'Copy failed' : label}
    </button>
  );
}

export function Field({ label, htmlFor, children, hint }: { label: string; htmlFor: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <dt className="w-36 shrink-0 text-slate-500">{k}</dt>
          <dd className="min-w-0 break-words text-slate-800">{v ?? <span className="text-slate-400">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}
