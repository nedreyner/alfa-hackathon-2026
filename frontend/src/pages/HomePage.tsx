import { Button } from '@alfalab/core-components/button';
import { useEffect, useState } from 'react';
import { Link } from 'react-router';

import { useBrief, useCounterparties, useProfile, useSession } from '../api/hooks';
import type { BriefItem } from '../api/types';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { formatRub, formatShare, plural } from '../lib/format';
import { ROLE, URGENCY } from '../lib/labels';
import { sendUiEvent } from '../lib/telemetry';
import styles from './HomePage.module.css';

const DOT = {
  risk: 'var(--ai-risk)',
  opportunity: 'var(--ai-opportunity)',
  mixed: 'var(--ai-mixed)',
} as const;

function BriefRow({ item, expanded }: { item: BriefItem; expanded: boolean }) {
  const to = item.insight_id ? `/insights/${item.insight_id}` : '/feed';
  return (
    <Link to={to} className={styles.item}>
      <span className={styles.dot} style={{ background: DOT[item.direction] }} aria-hidden="true" />
      <span>
        <div className={styles.headline}>{item.headline}</div>
        {item.why_you && <div className="secondary">{item.why_you}</div>}
        {expanded && item.action && (
          <div style={{ marginTop: 8, fontSize: 15 }}>
            <strong>{item.action.title}</strong> ·{' '}
            <span className="secondary">{URGENCY[item.action.urgency]}</span>
            {item.product && (
              <div className="caption" style={{ color: 'var(--ai-accent-text)' }}>
                Альфа-Банк: {item.product.name}
              </div>
            )}
          </div>
        )}
        {expanded && !item.action && item.status === 'pending' && (
          <div className="caption" style={{ marginTop: 6 }}>
            Разбор подготовим по запросу
          </div>
        )}
      </span>
    </Link>
  );
}

const readLabel = (s: number) => `Прочитать за ${s} ${plural(s, 'секунду', 'секунды', 'секунд')}`;

function TodayWidget() {
  const session = useSession();
  const brief = useBrief(session.data?.role);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => sendUiEvent('brief_view'), []);
  const items = brief.data?.items ?? [];
  return (
    <section className={styles.today} aria-labelledby="today">
      <div className="caption">{session.data ? ROLE[session.data.role] : ''}</div>
      <h1 className="h1" id="today" style={{ fontSize: 28, lineHeight: '36px' }}>
        Сегодня важно для вас: {items.length} {plural(items.length, 'событие', 'события', 'событий')}
      </h1>
      {brief.isPending ? (
        <SkeletonCard />
      ) : (
        items.map((it) => <BriefRow key={it.event_id} item={it} expanded={expanded} />)
      )}
      <div className="row" style={{ marginTop: 16, justifyContent: 'space-between' }}>
        <Button view="accent" size={48} onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'Свернуть' : readLabel(Math.max(30, brief.data?.reading_time_s ?? 60))}
        </Button>
        <Link to="/feed" className="secondary">
          Вся лента →
        </Link>
      </div>
    </section>
  );
}

/** Детерминированный «остаток» из выручки компании — только для макета. */
function mockBalances(revenue: number | null | undefined, hasVed: boolean) {
  const base = revenue ?? 3e10;
  return [
    { name: 'Расчётный счёт ₽', value: base * 0.031 },
    hasVed
      ? { name: 'Валютный счёт CNY (в ₽)', value: base * 0.006 }
      : { name: 'Счёт для платежей поставщикам', value: base * 0.009 },
    { name: 'Депозит', value: base * 0.012 },
  ];
}

export default function HomePage() {
  const profile = useProfile();
  const suppliers = useCounterparties('suppliers', undefined, 5);
  const revenue = profile.data?.profile.revenue_rub;
  return (
    <div className="page-wide">
      <div className={styles.grid}>
        <TodayWidget />
        <div className="stack">
          <section className={`card ${styles.mock}`}>
            <span className={styles.demoPlate}>демо-данные</span>
            <h2 className="h2">Счета</h2>
            {mockBalances(revenue, (profile.data?.profile.ved ?? []).length > 0).map((a) => (
              <div key={a.name} className={styles.account}>
                <span>{a.name}</span>
                <span className={styles.amount}>{formatRub(a.value)}</span>
              </div>
            ))}
          </section>
          <section className={`card ${styles.mock}`}>
            <span className={styles.demoPlate}>демо-данные</span>
            <h2 className="h2">Последние платежи</h2>
            {(suppliers.data?.items ?? []).map((c, i) => (
              <div key={i} className={styles.account}>
                <span style={{ minWidth: 0 }}>
                  {c.name}
                  <div className="caption">{c.industry_name}</div>
                </span>
                <span className={styles.amount}>−{formatRub((revenue ?? 3e10) * c.share * 0.02)}</span>
              </div>
            ))}
            {suppliers.data && (
              <div className="caption" style={{ marginTop: 8 }}>
                Доли поставщиков: {suppliers.data.items.map((c) => formatShare(c.share)).join(', ')}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
