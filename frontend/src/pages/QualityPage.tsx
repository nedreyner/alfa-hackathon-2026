import { lazy, Suspense } from 'react';

import { useQuality } from '../api/hooks';
import { ErrorState } from '../components/common/ErrorState';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { Section } from '../components/insight/Sections';
import { formatCost, formatDuration, formatShare } from '../lib/format';
import { BUDGET_MODE, ERROR_TEXT } from '../lib/labels';

const BudgetChart = lazy(() => import('../components/quality/BudgetChart'));

function Tile({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div style={{ padding: '16px 18px', borderRadius: 16, background: 'var(--ai-bg-subtle)' }} title={hint}>
      <div style={{ fontSize: 26, lineHeight: '32px', fontWeight: 600 }}>{value}</div>
      <div className="caption">{label}</div>
    </div>
  );
}

const grid = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))',
  gap: 12,
} as const;

export default function QualityPage() {
  const q = useQuality();
  if (q.isPending)
    return (
      <div className="page">
        <SkeletonCard lines={6} />
      </div>
    );
  if (q.isError || !q.data)
    return (
      <div className="page">
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </div>
    );
  const { online, budget, verification, offline } = q.data;
  const off = offline as Record<string, number | string> | null;
  return (
    <div className="page">
      <h1 className="h1">Качество и бюджет</h1>
      <p className="secondary">
        За последние {q.data.window_days} дней. Как мы проверяем, что разборы полезны, точны и укладываются в
        бюджет.
      </p>

      <Section title="Офлайн-оценка" id="offline">
        {off ? (
          <div style={grid}>
            {['ndcg@5', 'p@5', 'groundedness', 'completeness', 'contradiction_rate']
              .filter((k) => k in off)
              .map((k) => (
                <Tile
                  key={k}
                  value={typeof off[k] === 'number' ? (off[k] as number).toFixed(2) : String(off[k])}
                  label={k}
                />
              ))}
          </div>
        ) : (
          <p className="secondary">Отчёт офлайн-оценки ещё не сформирован (alfa eval report).</p>
        )}
      </Section>

      <Section title="Онлайн-метрики" id="online">
        <div style={grid}>
          <Tile
            value={formatShare(online.useful_rate)}
            label={`полезно (👍), оценок: ${online.feedback_total}`}
          />
          <Tile value={formatShare(online.source_ctr)} label="открывают источники" />
          <Tile value={formatShare(online.trace_open_rate)} label="смотрят трассу" />
          <Tile value={formatShare(online.followup_rate)} label="задают вопросы" />
          <Tile
            value={formatDuration(online.time_to_insight_ms.p50 ?? null)}
            label={`время до инсайта, p50 (p95 ${formatDuration(online.time_to_insight_ms.p95 ?? null)})`}
          />
          <Tile value={formatCost(online.cost_per_insight_rub)} label="стоимость одного инсайта" />
        </div>
        {Object.keys(online.top_errors).length > 0 && (
          <p className="caption" style={{ marginTop: 12 }}>
            Частые ошибки:{' '}
            {Object.entries(online.top_errors)
              .map(([k, v]) => `${(ERROR_TEXT as Record<string, string>)[k] ?? k} — ${v}`)
              .join('; ')}
          </p>
        )}
      </Section>

      <Section title="Бюджет LLM" id="budget">
        <div style={{ marginBottom: 12 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <strong>
              Сегодня: {formatCost(budget.today_spent_rub)} из {formatCost(budget.daily_limit_rub)}
            </strong>
            <span className="caption">
              {BUDGET_MODE[budget.mode as keyof typeof BUDGET_MODE] ?? budget.mode}
            </span>
          </div>
          <div
            style={{
              height: 8,
              borderRadius: 8,
              background: 'var(--ai-border)',
              overflow: 'hidden',
              marginTop: 8,
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${Math.min(100, (budget.today_spent_rub / budget.daily_limit_rub) * 100)}%`,
                background: 'var(--ai-text)',
              }}
            />
          </div>
        </div>
        <Suspense fallback={<SkeletonCard />}>
          <BudgetChart days={budget.by_day as { day: string; by_task: Record<string, number> }[]} />
        </Suspense>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, marginTop: 16 }}>
          <thead>
            <tr className="caption" style={{ textAlign: 'left' }}>
              <th>Модель</th>
              <th>Вызовы</th>
              <th>Токены</th>
              <th>₽</th>
              <th>Из кеша</th>
            </tr>
          </thead>
          <tbody>
            {(budget.by_model as Record<string, number | string>[]).map((m) => (
              <tr key={String(m.model)} style={{ borderTop: '1px solid var(--ai-border)' }}>
                <td style={{ padding: '6px 0' }}>{String(m.model)}</td>
                <td>{m.calls}</td>
                <td>{(Number(m.tokens_in) + Number(m.tokens_out)).toLocaleString('ru-RU')}</td>
                <td>{Number(m.cost_rub).toFixed(2)}</td>
                <td>{formatShare(Number(m.cache_share))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Проверка фактов" id="verification">
        <div style={grid}>
          <Tile value={String(verification.insights)} label="инсайтов за период" />
          <Tile
            value={formatShare(verification.avg_supported_share)}
            label="утверждений подтверждено источниками"
          />
          <Tile
            value={formatShare(verification.needs_review_share)}
            label="отправлено на проверку аналитику"
          />
          <Tile value={verification.avg_removed_claims?.toFixed(2) ?? '—'} label="скрыто выводов в среднем" />
        </div>
        <p className="caption" style={{ marginTop: 12 }}>
          В очереди экспертной проверки: {q.data.review_queue_size}
        </p>
      </Section>
    </div>
  );
}
