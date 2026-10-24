import { useEffect, useRef, useState } from 'react';

import type { TraceEvent } from './types';

export type RunStatus = 'idle' | 'connecting' | 'running' | 'succeeded' | 'failed';

export interface RunEnd {
  status: 'succeeded' | 'failed' | 'cancelled';
  insight_id: string | null;
  message_id: number | null;
  error_code: string | null;
  error_message: string | null;
  duration_ms: number | null;
  cost_rub: number;
}

export const END_TIMEOUT_MS = 90_000;

/** Добавить события с дедупликацией по seq и сортировкой. */
export function mergeEvents(current: TraceEvent[], incoming: TraceEvent[]): TraceEvent[] {
  const bySeq = new Map(current.map((e) => [e.seq, e]));
  for (const e of incoming) bySeq.set(e.seq, e);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

interface RunState {
  runId: string | null;
  events: TraceEvent[];
  status: RunStatus;
  end?: RunEnd;
}

const initial = (runId: string | null): RunState => ({
  runId,
  events: [],
  status: runId ? 'connecting' : 'idle',
});

/** Живая трасса прогона по SSE: события уникальны по seq, `end` закрывает поток, 90 с без событий — сбой. */
export function useRunEvents(runId: string | null, timeoutMs: number = END_TIMEOUT_MS) {
  const [state, setState] = useState<RunState>(() => initial(runId));
  const lastActivity = useRef(0);

  useEffect(() => {
    if (!runId) return;
    const update = (fn: (s: RunState) => RunState) =>
      setState((cur) => fn(cur.runId === runId ? cur : initial(runId)));
    lastActivity.current = Date.now();
    const source = new EventSource(`/api/runs/${runId}/events`, { withCredentials: true });
    let finished = false;
    const onTrace = (msg: MessageEvent<string>) => {
      lastActivity.current = Date.now();
      try {
        const ev = JSON.parse(msg.data) as TraceEvent;
        update((s) => ({ ...s, events: mergeEvents(s.events, [ev]), status: 'running' }));
      } catch {
        /* битое событие пропускаем */
      }
    };
    const onEnd = (msg: MessageEvent<string>) => {
      finished = true;
      source.close();
      try {
        const data = JSON.parse(msg.data) as RunEnd;
        update((s) => ({ ...s, end: data, status: data.status === 'succeeded' ? 'succeeded' : 'failed' }));
      } catch {
        update((s) => ({ ...s, status: 'failed' }));
      }
    };
    source.addEventListener('trace', onTrace as EventListener);
    source.addEventListener('end', onEnd as EventListener);
    source.onerror = () => {
      if (!finished) update((s) => ({ ...s, status: s.status === 'running' ? 'running' : 'connecting' }));
    };
    const timer = setInterval(() => {
      if (!finished && Date.now() - lastActivity.current > timeoutMs) {
        finished = true;
        source.close();
        const end: RunEnd = {
          status: 'failed',
          insight_id: null,
          message_id: null,
          error_code: 'connection_lost',
          error_message: 'Соединение потеряно',
          duration_ms: null,
          cost_rub: 0,
        };
        update((s) => ({ ...s, end, status: 'failed' }));
      }
    }, 1000);
    return () => {
      clearInterval(timer);
      source.close();
    };
  }, [runId, timeoutMs]);

  const view = state.runId === runId ? state : initial(runId);
  return { events: view.events, status: view.status, end: view.end };
}
