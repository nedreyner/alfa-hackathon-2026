import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mergeEvents, useRunEvents } from './sse';
import type { TraceEvent } from './types';

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  onerror: ((e: Event) => void) | null = null;
  private listeners: Record<string, ((e: MessageEvent<string>) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent<string>) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  emit(type: string, data: unknown) {
    for (const fn of this.listeners[type] ?? []) fn({ data: JSON.stringify(data) } as MessageEvent<string>);
  }
  close() {
    this.closed = true;
  }
}

const ev = (seq: number): TraceEvent => ({
  seq,
  ts: '2026-10-22T10:00:00Z',
  type: 'tool.call',
  phase: 'tools',
  title: `шаг ${seq}`,
  status: 'ok',
  payload: {},
  model: null,
  tokens_in: null,
  tokens_out: null,
  cost_rub: null,
  latency_ms: null,
});

describe('useRunEvents', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('merges by seq and sorts', () => {
    expect(mergeEvents([ev(2), ev(1)], [ev(2), ev(3)]).map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it('dedupes events, handles end and closes', () => {
    const { result } = renderHook(() => useRunEvents('run_1'));
    const src = FakeEventSource.instances[0];
    expect(src.url).toBe('/api/runs/run_1/events');
    expect(result.current.status).toBe('connecting');
    act(() => {
      src.emit('trace', ev(1));
      src.emit('trace', ev(2));
      src.emit('trace', ev(2)); // повтор после переподключения
    });
    expect(result.current.events.map((e) => e.seq)).toEqual([1, 2]);
    expect(result.current.status).toBe('running');
    act(() =>
      src.emit('end', {
        status: 'succeeded',
        insight_id: 'ins_1',
        message_id: null,
        error_code: null,
        error_message: null,
        duration_ms: 1200,
        cost_rub: 0.4,
      }),
    );
    expect(result.current.status).toBe('succeeded');
    expect(result.current.end?.insight_id).toBe('ins_1');
    expect(src.closed).toBe(true);
  });

  it('fails after timeout without end', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useRunEvents('run_2', 3_000));
    act(() => {
      vi.advanceTimersByTime(4_500);
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.end?.error_code).toBe('connection_lost');
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it('idle without run id', () => {
    const { result } = renderHook(() => useRunEvents(null));
    expect(result.current.status).toBe('idle');
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
