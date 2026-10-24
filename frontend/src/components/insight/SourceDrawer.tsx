import { useEffect, useState } from 'react';

import { useSource } from '../../api/hooks';
import type { SourceDetail } from '../../api/types';
import { formatDay, formatShare } from '../../lib/format';
import { SOURCE_KIND } from '../../lib/labels';
import { sendUiEvent } from '../../lib/telemetry';
import { Panel } from '../common/Panel';
import { External } from '../common/icons';

function Sparkline({ points }: { points: { date: string; value: number }[] }) {
  if (points.length < 2) return null;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const w = 420;
  const h = 80;
  const d = points
    .map(
      (p, i) =>
        `${i ? 'L' : 'M'}${(i / (points.length - 1)) * w},${h - ((p.value - min) / (max - min || 1)) * (h - 8) - 4}`,
    )
    .join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label="Динамика показателя">
      <path d={d} fill="none" stroke="var(--ai-text)" strokeWidth={2} />
    </svg>
  );
}

interface MixRow {
  industry_id: string;
  name: string;
  share_total: number;
}
interface CpRow {
  name: string;
  industry_name: string;
  share: number;
}

function ClientData({ data }: { data: Record<string, unknown> }) {
  const mix = (data.mix as MixRow[] | undefined) ?? [];
  const cps = (data.counterparties as CpRow[] | undefined) ?? [];
  return (
    <div className="stack" style={{ gap: 12 }}>
      {mix.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <caption className="caption" style={{ textAlign: 'left' }}>
            Доли отраслей по платежам
          </caption>
          <tbody>
            {mix.slice(0, 6).map((m) => (
              <tr key={m.industry_id}>
                <td style={{ padding: '4px 0' }}>{m.name}</td>
                <td style={{ textAlign: 'right' }}>{formatShare(m.share_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {cps.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <caption className="caption" style={{ textAlign: 'left' }}>
            Крупнейшие контрагенты
          </caption>
          <tbody>
            {cps.slice(0, 8).map((c, i) => (
              <tr key={i}>
                <td style={{ padding: '4px 0' }}>
                  {c.name}
                  <div className="caption">{c.industry_name}</div>
                </td>
                <td style={{ textAlign: 'right' }}>{formatShare(c.share)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SourceItem({ id, index }: { id: string; index: number }) {
  const q = useSource(id);
  const [full, setFull] = useState(false);
  if (q.isPending) return <div className="secondary">Загружаем источник…</div>;
  if (q.isError || !q.data) return <div className="secondary">Источник недоступен</div>;
  const s: SourceDetail = q.data;
  const series = (s.data?.series as { date: string; value: number }[] | undefined) ?? [];
  return (
    <article style={{ borderTop: index ? '1px solid var(--ai-border)' : 0, paddingTop: index ? 16 : 0 }}>
      <div className="caption">
        {SOURCE_KIND[s.kind]}
        {s.publisher ? ` · ${s.publisher}` : ''}
        {s.published_at ? ` · ${formatDay(s.published_at)}` : ''}
        {s.page ? ` · с. ${s.page}` : ''}
      </div>
      <div style={{ fontWeight: 600, margin: '4px 0 8px' }}>{s.doc_title ?? s.title}</div>
      {s.kind === 'cbr' && s.data ? (
        <>
          <div style={{ fontSize: 24, fontWeight: 600 }}>
            {(s.data.latest as { value: number } | undefined)?.value?.toLocaleString('ru-RU')}
            {s.data.unit === '%' ? '%' : ' ₽'}
          </div>
          <Sparkline points={series} />
        </>
      ) : s.kind === 'client_data' && s.data && (s.data.mix || s.data.counterparties) ? (
        <>
          <p className="secondary" style={{ whiteSpace: 'pre-line', margin: '0 0 8px' }}>
            {s.excerpt}
          </p>
          <ClientData data={s.data} />
        </>
      ) : (
        <p style={{ whiteSpace: 'pre-line', margin: 0, fontSize: 15 }}>
          {full && s.text ? s.text : s.excerpt}
        </p>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        {s.text && s.text.length > s.excerpt.length && s.kind !== 'cbr' && (
          <button
            type="button"
            onClick={() => setFull((v) => !v)}
            style={{
              border: 0,
              background: 'none',
              color: 'var(--ai-text-secondary)',
              cursor: 'pointer',
              padding: 0,
              font: 'inherit',
              fontSize: 14,
            }}
          >
            {full ? 'Свернуть' : 'Показать полностью'}
          </button>
        )}
        {s.url && (
          <a
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            className="secondary"
            style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          >
            Оригинал <External size={14} />
          </a>
        )}
      </div>
      {s.kind === 'client_data' && (
        <div className="caption" style={{ marginTop: 6 }}>
          Рассчитано по данным о платежах компании, видно только вам
        </div>
      )}
      {typeof s.data?.coverage === 'number' && (
        <div className="caption">Покрытие данных: {formatShare(s.data.coverage as number)}</div>
      )}
    </article>
  );
}

export function SourceDrawer({
  ids,
  title,
  onClose,
  insightId,
}: {
  ids: string[];
  title: string;
  onClose: () => void;
  insightId?: string;
}) {
  useEffect(() => {
    if (ids.length) sendUiEvent('source_open', insightId, { count: ids.length });
  }, [ids, insightId]);
  return (
    <Panel open={ids.length > 0} onClose={onClose} title={title}>
      <div className="stack" style={{ paddingBottom: 24 }}>
        {ids.map((id, i) => (
          <SourceItem key={id} id={id} index={i} />
        ))}
      </div>
    </Panel>
  );
}
