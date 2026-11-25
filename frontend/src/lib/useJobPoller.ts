import { useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { TERMINAL_JOB_STATES, type JobDetail } from '../api/types';

export const JOB_POLL_INTERVAL_MS = 1500;

/**
 * Poll GET /jobs/{id} every ~1.5s until the job reaches a terminal state.
 * Calls `onTerminal` once when it does.
 */
export function useJobPoller(jobId: string | null, onTerminal?: (job: JobDetail) => void) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const controller = new AbortController();

    const tick = async () => {
      try {
        const j = await api.getJob(jobId, controller.signal);
        if (cancelled) return;
        setJob(j);
        setError(null);
        if (TERMINAL_JOB_STATES.includes(j.state)) {
          onTerminalRef.current?.(j);
          return;
        }
      } catch (e) {
        if (cancelled) return;
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
  }, [jobId]);

  return { job, error };
}
