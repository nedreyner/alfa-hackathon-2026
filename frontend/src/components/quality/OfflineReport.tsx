import type { OfflineSummary } from '../../api/types';
import { formatCost, formatDuration, formatShare } from '../../lib/format';
import { LABELS_SOURCE, RANKING_VARIANT } from '../../lib/labels';

const ORDER = ['ours', 'no_payments', 'industry_only', 'random'];

function Bar({ label, value, accent }: { label: string; value: number | null | undefined; accent: boolean }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(140px, 220px) 1fr 44px',
        gap: 12,
        alignItems: 'center',
      }}
    >
      <span className={accent ? undefined : 'secondary'} style={{ fontWeight: accent ? 600 : 400 }}>
        {label}
      </span>
      <div style={{ height: 10, borderRadius: 10, background: 'var(--ai-border)', overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: `${Math.round((value ?? 0) * 100)}%`,
            background: accent ? 'var(--ai-accent)' : 'var(--ai-text-secondary)',
          }}
        />
      </div>
      <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: accent ? 600 : 400 }}>
        {value == null ? '—' : value.toFixed(2)}
      </span>
    </div>
  );
}

function Tile({ value, label }: { value: string; label: string }) {
  return (
    <div style={{ padding: '16px 18px', borderRadius: 16, background: 'var(--ai-bg-subtle)' }}>
      <div style={{ fontSize: 26, lineHeight: '32px', fontWeight: 600 }}>{value}</div>
      <div className="caption">{label}</div>
    </div>
  );
}

export function OfflineReport({ data }: { data: OfflineSummary }) {
  const ours = data.ranking.ours?.ndcg5;
  const industry = data.ranking.industry_only?.ndcg5;
  return (
    <div style={{ display: 'grid', gap: 20 }}>
      {ours != null && industry != null && (
        <p style={{ fontSize: 17, margin: 0 }}>
          Цепная реакция поднимает nDCG@5 с <strong>{industry.toFixed(2)}</strong> (только своя отрасль) до{' '}
          <strong>{ours.toFixed(2)}</strong>.
        </p>
      )}
      <div style={{ display: 'grid', gap: 10 }}>
        {ORDER.filter((k) => k in data.ranking).map((k) => (
          <Bar key={k} label={RANKING_VARIANT[k] ?? k} value={data.ranking[k]?.ndcg5} accent={k === 'ours'} />
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12 }}>
        <Tile value={formatShare(data.grounded_share_llm)} label="утверждений подтверждено источниками" />
        <Tile value={formatShare(data.personalization_rate)} label="разборов опираются на данные компании" />
        <Tile value={formatShare(data.numbers_match_rate)} label="чисел сверено с источниками" />
        <Tile value={formatShare(data.completeness)} label="разборов с ответами на все 6 вопросов" />
        <Tile value={formatShare(data.contradiction_rate)} label="разборов с найденными противоречиями" />
        <Tile value={formatCost(data.cost_rub_mean)} label="стоимость одного разбора" />
        {data.analyze_p50_ms != null && (
          <Tile value={formatDuration(data.analyze_p50_ms)} label="разбор свежей ссылки, p50" />
        )}
      </div>
      <p className="caption" style={{ margin: 0 }}>
        {data.companies} компаний, {data.judgements} суждений о релевантности (
        {LABELS_SOURCE[data.labels_source] ?? data.labels_source}
        {data.kappa != null ? `, согласие разметчиков κ = ${data.kappa.toFixed(2)}` : ''}); {data.insights}{' '}
        разборов. Полный отчёт — eval/reports/latest.md.
      </p>
    </div>
  );
}
