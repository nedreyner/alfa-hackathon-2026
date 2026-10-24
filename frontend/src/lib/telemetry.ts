import type { components } from '../api/schema';

type UiEvent = components['schemas']['UiEventIn'];

/** Fire-and-forget: телеметрия не должна мешать интерфейсу. */
export function sendUiEvent(
  type: UiEvent['type'],
  insightId?: string | null,
  payload: Record<string, unknown> = {},
): void {
  try {
    void fetch('/api/ui-events', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, insight_id: insightId ?? null, payload }),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* ignore */
  }
}
