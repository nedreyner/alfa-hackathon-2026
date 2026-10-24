import type { ReactNode } from 'react';
import { Link } from 'react-router';

import type { Action, Consequence, Insight, ProductOffer, Role } from '../../api/types';
import { ALIGNMENT, HORIZON, LEVEL, ROLE_FOR, SOURCE_KIND, URGENCY } from '../../lib/labels';
import { formatDay } from '../../lib/format';
import { External } from '../common/icons';
import { ClaimText } from './ClaimText';
import styles from './sections.module.css';

export function Section({ title, children, id }: { title: string; children: ReactNode; id?: string }) {
  return (
    <section className={styles.section} aria-labelledby={id}>
      <h2 className="h2" id={id}>
        {title}
      </h2>
      {children}
    </section>
  );
}

export function StatusNotice({
  insight,
  stale,
  onRecompute,
}: {
  insight: Insight;
  stale: boolean;
  onRecompute?: () => void;
}) {
  const notes: ReactNode[] = [];
  if (stale)
    notes.push(
      <span key="stale">
        Профиль компании изменился.{' '}
        {onRecompute && (
          <button
            type="button"
            onClick={onRecompute}
            style={{
              border: 0,
              background: 'none',
              padding: 0,
              font: 'inherit',
              textDecoration: 'underline',
              cursor: 'pointer',
            }}
          >
            Пересчитать?
          </button>
        )}
      </span>,
    );
  if (insight.status === 'needs_review')
    notes.push('Часть выводов не подтверждена источниками и требует проверки аналитиком.');
  if (insight.verification.removed_claims > 0)
    notes.push('Часть выводов скрыта: не удалось подтвердить источниками.');
  if (insight.event.injection_suspected)
    notes.push('В исходном тексте была попытка управлять ИИ — она проигнорирована.');
  if (!notes.length) return null;
  return (
    <div className="stack" style={{ gap: 8, margin: '16px 0' }} role="note">
      {notes.map((n, i) => (
        <div key={i} className={styles.notice}>
          {n}
        </div>
      ))}
    </div>
  );
}

export function WhatHappened({ insight }: { insight: Insight }) {
  const { facts, assumptions } = insight.what_happened;
  return (
    <>
      <ul className={styles.list}>
        {facts.map((c, i) => (
          <li key={i} className={styles.item}>
            <ClaimText claim={c} />
          </li>
        ))}
      </ul>
      {assumptions && assumptions.length > 0 && (
        <>
          <div className="caption" style={{ margin: '18px 0 8px' }}>
            Оговорки
          </div>
          <ul className={`${styles.list} ${styles.muted}`}>
            {assumptions.map((c, i) => (
              <li key={i} className={styles.item} style={{ fontSize: 15 }}>
                <ClaimText claim={c} />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

export function FeatureChips({ keys, labels }: { keys: string[]; labels: Record<string, string> }) {
  if (!keys.length) return null;
  return (
    <div className={styles.chips} style={{ marginTop: 14 }}>
      <span className="caption" style={{ alignSelf: 'center' }}>
        Учли:
      </span>
      {keys.map((k) => (
        <Link key={k} to={`/profile#feature-${k}`} className={styles.featureChip}>
          {labels[k] ?? k}
        </Link>
      ))}
    </div>
  );
}

export function ConsequenceList({ items, empty }: { items: Consequence[]; empty: string }) {
  if (!items.length) return <p className="secondary">{empty}</p>;
  return (
    <ul className={styles.list}>
      {items.map((c, i) => (
        <li key={i} className={styles.cons}>
          <div className={styles.consTitle}>{c.title}</div>
          <ClaimText claim={c.claim} />
          <div className={styles.chips}>
            <span className={styles.chip}>вероятность: {LEVEL[c.probability]}</span>
            <span className={styles.chip}>сила: {LEVEL[c.impact]}</span>
            <span className={styles.chip}>горизонт: {HORIZON[c.horizon]}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ActionList({
  actions,
  products,
  role,
  onProduct,
}: {
  actions: Action[];
  products: ProductOffer[];
  role: Role;
  onProduct: (p: ProductOffer) => void;
}) {
  const ordered = actions
    .map((a, i) => ({ a, i }))
    .sort((x, y) => Number(y.a.owner_role === role) - Number(x.a.owner_role === role));
  return (
    <ol className={styles.list} style={{ paddingLeft: 0 }}>
      {ordered.map(({ a, i }) => {
        const product = products.find((p) => p.action_index === i);
        const mine = a.owner_role === role;
        return (
          <li
            key={i}
            className={styles.cons}
            style={mine ? { background: 'var(--ai-bg)', border: '1px solid var(--ai-text)' } : undefined}
          >
            <div className={styles.consTitle}>{a.title}</div>
            <ClaimText claim={a.claim} />
            <div className={styles.chips}>
              <span className={`${styles.chip} ${mine ? styles.chipFor : ''}`}>
                {mine ? 'для вас' : ROLE_FOR[a.owner_role]}
              </span>
              <span className={styles.chip}>{URGENCY[a.urgency]}</span>
            </div>
            {product && (
              <button type="button" className={styles.product} onClick={() => onProduct(product)}>
                Альфа-Банк: {product.name} →
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function BankViewBlock({ insight }: { insight: Insight }) {
  const bv = insight.bank_view;
  if (!bv.available || !bv.claims?.length)
    return <p className="secondary">У аналитиков Альфа-Банка нет публикаций по теме.</p>;
  const docs = insight.sources.filter((s) => s.kind === 'alfa');
  return (
    <div className={styles.bank}>
      <div className="row" style={{ marginBottom: 10 }}>
        <span className={styles.chip} style={{ borderColor: 'var(--ai-accent)', color: 'var(--ai-accent)' }}>
          {ALIGNMENT[bv.alignment]}
        </span>
      </div>
      <ul className={styles.list}>
        {bv.claims.map((c, i) => (
          <li key={i} className={styles.item}>
            <ClaimText claim={c} />
          </li>
        ))}
      </ul>
      {docs.length > 0 && (
        <div className="caption" style={{ marginTop: 12 }}>
          {docs.map((d) => `${d.title}${d.published_at ? `, ${formatDay(d.published_at)}` : ''}`).join(' · ')}
        </div>
      )}
    </div>
  );
}

export function SourcesList({ insight, onOpen }: { insight: Insight; onOpen: (id: string) => void }) {
  return (
    <ol className={styles.sources}>
      {insight.sources.map((s) => (
        <li key={s.id}>
          <button
            type="button"
            onClick={() => onOpen(s.id)}
            style={{
              border: 0,
              background: 'none',
              padding: 0,
              font: 'inherit',
              textAlign: 'left',
              cursor: 'pointer',
            }}
          >
            <span className="caption">{SOURCE_KIND[s.kind]} · </span>
            {s.title}
            {s.publisher ? <span className="secondary"> — {s.publisher}</span> : null}
            {s.published_at ? <span className="caption"> · {formatDay(s.published_at)}</span> : null}
          </button>
          {s.url && (
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Открыть оригинал"
              style={{ marginLeft: 6, color: 'var(--ai-text-secondary)' }}
            >
              <External size={14} />
            </a>
          )}
        </li>
      ))}
    </ol>
  );
}
