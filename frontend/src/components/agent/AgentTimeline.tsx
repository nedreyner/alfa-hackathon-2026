import { useState } from 'react';

import type { RunInfo, TraceEvent } from '../../api/types';
import { formatCost, formatDuration, formatShare, plural } from '../../lib/format';
import { PHASE } from '../../lib/labels';
import styles from './timeline.module.css';

const HIDDEN = new Set(['phase.started', 'phase.completed']);
const MODEL_TITLES: Record<string, string> = {
  deepseek: 'DeepSeek-V4.1-Flash',
  glm: 'GLM-5.3-Flash',
  kimi: 'Kimi-K2.6',
  gemma: 'Gemma 4',
  qwen_text: 'Qwen3.6',
  qwen_vl: 'Qwen3-VL',
  fake: 'FakeLLM',
};

type P = Record<string, unknown>;

function Details({ e }: { e: TraceEvent }) {
  const p = e.payload as P;
  if (e.type === 'llm.call') {
    return (
      <div className={styles.details}>
        {MODEL_TITLES[String(p.model)] ?? String(p.model)} · вход {String(p.tokens_in)} / выход{' '}
        {String(p.tokens_out)} токенов · {formatCost(Number(p.cost_rub ?? 0))}
        {p.cached ? ' · из кеша' : ''}
        {p.fallback_model_used ? ' · запасная модель' : ''}
      </div>
    );
  }
  if (e.type === 'verify.report') {
    const share = Number(p.supported_share ?? 0);
    const issues = (p.issues as string[] | undefined) ?? [];
    return (
      <div className={styles.details}>
        <div>Подтверждено источниками: {formatShare(share)}</div>
        <div className={styles.bar}>
          <div className={styles.barFill} style={{ width: `${Math.round(share * 100)}%` }} />
        </div>
        {issues.length > 0 && (
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {issues.map((i, k) => (
              <li key={k}>{i}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  if (e.type === 'plan' || e.type === 'thought') {
    return (
      <div className={styles.details} style={{ whiteSpace: 'pre-wrap' }}>
        {String(p.text ?? '')}
      </div>
    );
  }
  const shown = Object.fromEntries(Object.entries(p).filter(([k]) => !['duration_ms'].includes(k)));
  if (!Object.keys(shown).length) return null;
  return (
    <div className={styles.details}>
      <pre>{JSON.stringify(shown, null, 2)}</pre>
    </div>
  );
}

function Step({ e, index }: { e: TraceEvent; index: number }) {
  const [open, setOpen] = useState(false);
  const duration = e.latency_ms ?? (e.payload as P).duration_ms;
  return (
    <li className={styles.step} style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}>
      <span className={`${styles.dot} ${styles[e.status]}`} aria-hidden="true" />
      <button type="button" className={styles.head} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className={styles.title}>{e.title}</span>
        <span className="caption" style={{ whiteSpace: 'nowrap' }}>
          {typeof duration === 'number' ? formatDuration(duration) : ''}
        </span>
      </button>
      {open && <Details e={e} />}
    </li>
  );
}

/** Шаги прогона по фазам; работает и со статической трассой, и с живой (новые шаги появляются каскадом). */
export function AgentTimeline({ events, live = false }: { events: TraceEvent[]; live?: boolean }) {
  const visible = events.filter((e) => !HIDDEN.has(e.type));
  const groups: { phase: string; items: TraceEvent[] }[] = [];
  for (const e of visible) {
    const last = groups[groups.length - 1];
    if (last && last.phase === e.phase) last.items.push(e);
    else groups.push({ phase: e.phase, items: [e] });
  }
  let index = 0;
  return (
    <div aria-live={live ? 'polite' : undefined}>
      {groups.map((g, gi) => (
        <section key={`${g.phase}-${gi}`}>
          <div className={styles.phase}>{PHASE[g.phase] ?? g.phase}</div>
          <ol className={styles.list}>
            {g.items.map((e) => (
              <Step key={e.seq} e={e} index={live ? 0 : index++} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

export function RunSummary({ run, events }: { run?: RunInfo | null; events: TraceEvent[] }) {
  const models = [
    ...new Set(
      events
        .filter((e) => e.type === 'llm.call')
        .map((e) => MODEL_TITLES[String((e.payload as P).model)] ?? String((e.payload as P).model)),
    ),
  ];
  const sources = events.filter((e) => e.type === 'evidence.added').length;
  const report = [...events].reverse().find((e) => e.type === 'verify.report');
  const cost = run?.cost_rub ?? events.reduce((s, e) => s + (e.cost_rub ?? 0), 0);
  return (
    <div className={styles.summary}>
      <div>
        <div className={styles.metric}>{formatDuration(run?.duration_ms ?? null)}</div>
        <div className="caption">общее время</div>
      </div>
      <div>
        <div className={styles.metric}>{formatCost(cost)}</div>
        <div className="caption">стоимость</div>
      </div>
      <div>
        <div className={styles.metric}>{sources}</div>
        <div className="caption">{plural(sources, 'источник', 'источника', 'источников')}</div>
      </div>
      <div style={{ gridColumn: '1 / -1' }}>
        <div className="caption">Модели: {models.join(', ') || '—'}</div>
        {report && <div className="caption">Проверка: {report.title}</div>}
      </div>
    </div>
  );
}
