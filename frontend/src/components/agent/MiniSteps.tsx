import type { TraceEvent } from '../../api/types';

const SHOWN = new Set([
  'tool.call',
  'intake.fetch',
  'intake.extract',
  'intake.tagged',
  'draft.ready',
  'verify.report',
  'revise.started',
  'llm.call',
]);

/** Компактная лента шагов прогона: последние 4 значимых шага, новый — сверху приглушённым каскадом. */
export function MiniSteps({ events }: { events: TraceEvent[] }) {
  const steps = events.filter((e) => SHOWN.has(e.type)).slice(-4);
  return (
    <ol
      aria-live="polite"
      style={{ listStyle: 'none', margin: '12px 0 0', padding: 0, display: 'grid', gap: 6 }}
    >
      {steps.map((e, i) => (
        <li
          key={e.seq}
          className="appear secondary"
          style={{ display: 'flex', gap: 8, alignItems: 'center', opacity: i === steps.length - 1 ? 1 : 0.6 }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 6,
              height: 6,
              borderRadius: 6,
              flex: 'none',
              background:
                e.status === 'error'
                  ? 'var(--ai-risk)'
                  : e.status === 'warn'
                    ? 'var(--ai-warn)'
                    : 'var(--ai-text-secondary)',
            }}
          />
          {e.title}
        </li>
      ))}
      {steps.length === 0 && <li className="secondary">Готовим разбор…</li>}
    </ol>
  );
}
