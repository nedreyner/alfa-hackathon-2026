import { Button } from '@alfalab/core-components/button';
import { useEffect, useState } from 'react';

import { useCounterparties, useProfile, useReference, useSaveOverrides } from '../api/hooks';
import type { CompanyProfile, ProfileResponse } from '../api/types';
import { ErrorState } from '../components/common/ErrorState';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { formatRub, formatShare } from '../lib/format';
import { Section } from '../components/insight/Sections';
import styles from './ProfilePage.module.css';

const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
const COLORS = ['#0e0e10', '#4a4a50', '#7a7a80', '#a5a5ab', '#c7c7cc', '#dcdce0'];
const PRODUCT_NAMES: Record<string, string> = {
  credit: 'Кредит',
  leasing: 'Лизинг',
  deposit: 'Депозит',
  guarantee: 'Банковская гарантия',
  factoring: 'Факторинг',
  acquiring: 'Эквайринг',
  salary: 'Зарплатный проект',
  fx: 'Валютные операции',
};

function FactsGrid({ p }: { p: CompanyProfile }) {
  return (
    <div className={styles.facts}>
      {p.features
        .filter((f) => !/^(suppliers|buyers|factor|coverage)\./.test(f.key))
        .map((f) => (
          <div key={f.key} id={`feature-${f.key}`} className={styles.fact}>
            <div className="caption">{f.label}</div>
            <div style={{ fontWeight: 500 }}>{f.value}</div>
            <div className={styles.origin}>
              {f.source === 'override'
                ? 'уточнено вами'
                : f.source === 'prior'
                  ? 'отраслевая модель'
                  : 'из данных банка'}
            </div>
          </div>
        ))}
    </div>
  );
}

function MixBar({ direction, title }: { direction: 'suppliers' | 'buyers'; title: string }) {
  const q = useCounterparties(direction, undefined, 10);
  if (!q.data) return <SkeletonCard lines={2} />;
  const { mix, coverage, basis, items } = q.data;
  const top = [...mix].sort((a, b) => b.share_total - a.share_total).slice(0, 6);
  const other = Math.max(
    0,
    mix.reduce((s, m) => s + m.share_total, 0) - top.reduce((s, m) => s + m.share_total, 0),
  );
  const unknown = Math.max(0, 1 - mix.reduce((s, m) => s + m.share_total, 0));
  return (
    <div className="card" style={{ boxShadow: 'none' }}>
      <h3 className="h2" style={{ fontSize: 18 }}>
        {title}
      </h3>
      <div className="caption">
        {basis === 'prior'
          ? 'Оценка по отраслевой модели: данных о платежах нет'
          : `Данные по ${formatShare(coverage)} платежей`}
      </div>
      {top.length > 0 && (
        <>
          <div className={styles.bar} role="img" aria-label={`${title}: структура по отраслям`}>
            {top.map((m, i) => (
              <span
                key={m.industry_id}
                style={{ width: `${m.share_total * 100}%`, background: COLORS[i] }}
                title={`${m.name}: ${formatShare(m.share_total)}`}
              />
            ))}
            {other > 0 && <span style={{ width: `${other * 100}%`, background: '#e7e8eb' }} title="прочее" />}
            {unknown > 0 && (
              <span
                style={{
                  width: `${unknown * 100}%`,
                  background: 'repeating-linear-gradient(45deg,#f3f4f5,#f3f4f5 4px,#e7e8eb 4px,#e7e8eb 8px)',
                }}
                title="неизвестно"
              />
            )}
          </div>
          <div className={styles.legend}>
            {top.map((m, i) => (
              <span key={m.industry_id}>
                <span className={styles.swatch} style={{ background: COLORS[i] }} />
                {m.name} {formatShare(m.share_total)}
              </span>
            ))}
            {unknown > 0.005 && <span className="secondary">неизвестно {formatShare(unknown)}</span>}
          </div>
        </>
      )}
      {items.length > 0 && (
        <table className={styles.table} style={{ marginTop: 14 }}>
          <tbody>
            {items.map((c, i) => (
              <tr key={i}>
                <td>
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

function FactorList({ p }: { p: CompanyProfile }) {
  return (
    <table className={styles.table}>
      <tbody>
        {[...p.factor_exposure]
          .sort((a, b) => b.exposure - a.exposure)
          .map((f) => (
            <tr key={f.factor_id} id={`feature-factor.${f.factor_id}`}>
              <td>
                {f.name}
                <div className="caption">
                  {f.sign < 0 ? 'риск при росте' : 'выгода при росте'} · {f.reasons.join(', ')}
                </div>
              </td>
              <td style={{ width: 140 }}>
                <div className={styles.scale}>
                  <div className={styles.scaleFill} style={{ width: `${f.exposure * 100}%` }} />
                </div>
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}

function OverridesForm({ data }: { data: ProfileResponse }) {
  const ref = useReference();
  const save = useSaveOverrides();
  const p = data.profile;
  const [industry, setIndustry] = useState(p.industry_id);
  const [ved, setVed] = useState(
    p.ved
      .filter((v) => v.country_iso2)
      .map((v) => ({ country_iso2: v.country_iso2!, direction: v.direction })),
  );
  const [products, setProducts] = useState<Record<string, boolean>>(
    Object.fromEntries(Object.keys(PRODUCT_NAMES).map((k) => [k, !!p.products[k]?.has])),
  );
  const [notes, setNotes] = useState(p.notes ?? '');
  const [newCountry, setNewCountry] = useState('');
  useEffect(() => {
    if (save.isSuccess) {
      const t = setTimeout(() => save.reset(), 4000);
      return () => clearTimeout(t);
    }
  }, [save.isSuccess, save]);
  const submit = () => save.mutate({ industry_id: industry, ved, products, notes, reset: [] });
  return (
    <div className={styles.form}>
      <label className={styles.field}>
        Основная отрасль
        <select className={styles.control} value={industry} onChange={(e) => setIndustry(e.target.value)}>
          {(ref.data?.industries ?? []).map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
      </label>
      <div className={styles.field}>
        Страны ВЭД
        {ved.map((v, i) => (
          <div key={v.country_iso2} className="row">
            <span style={{ minWidth: 140 }}>
              {cap(ref.data?.countries.find((c) => c.id === v.country_iso2)?.name ?? v.country_iso2)}
            </span>
            <select
              className={styles.control}
              value={v.direction}
              onChange={(e) =>
                setVed(
                  ved.map((x, k) =>
                    k === i ? { ...x, direction: e.target.value as typeof v.direction } : x,
                  ),
                )
              }
            >
              <option value="import">импорт</option>
              <option value="export">экспорт</option>
              <option value="unknown">не указано</option>
            </select>
            <button
              type="button"
              onClick={() => setVed(ved.filter((_, k) => k !== i))}
              style={{ border: 0, background: 'none', cursor: 'pointer', color: 'var(--ai-text-secondary)' }}
            >
              убрать
            </button>
          </div>
        ))}
        <div className="row">
          <select
            className={styles.control}
            value={newCountry}
            onChange={(e) => setNewCountry(e.target.value)}
          >
            <option value="">Добавить страну…</option>
            {(ref.data?.countries ?? [])
              .filter((c) => !ved.some((v) => v.country_iso2 === c.id))
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {cap(c.name)}
                </option>
              ))}
          </select>
          <Button
            size={40}
            view="secondary"
            disabled={!newCountry}
            onClick={() => {
              setVed([...ved, { country_iso2: newCountry, direction: 'import' }]);
              setNewCountry('');
            }}
          >
            Добавить
          </Button>
        </div>
      </div>
      <div className={styles.field}>
        Продукты в Альфа-Банке
        <div className="row">
          {Object.entries(PRODUCT_NAMES).map(([k, name]) => (
            <label key={k} className="row secondary" style={{ gap: 6 }}>
              <input
                type="checkbox"
                checked={products[k]}
                onChange={(e) => setProducts({ ...products, [k]: e.target.checked })}
              />
              {name}
            </label>
          ))}
        </div>
      </div>
      <label className={styles.field}>
        Заметка для аналитика
        <textarea
          className={styles.control}
          rows={3}
          maxLength={1000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Например: основной поставщик — завод в Китае, оплата в юанях"
        />
      </label>
      <div className="row">
        <Button view="accent" size={48} onClick={submit} loading={save.isPending}>
          Сохранить и пересчитать ленту
        </Button>
        {data.overrides.length > 0 && (
          <Button
            view="secondary"
            size={48}
            onClick={() => save.mutate({ reset: ['industry_id', 'ved', 'products', 'notes'] })}
          >
            Сбросить уточнения
          </Button>
        )}
      </div>
      {save.isSuccess && (
        <div role="status" className="card" style={{ boxShadow: 'none' }}>
          Профиль обновлён, лента пересчитана
        </div>
      )}
      {save.isError && (
        <div role="alert" style={{ color: 'var(--ai-risk)' }}>
          Не удалось сохранить: проверьте поля
        </div>
      )}
    </div>
  );
}

export default function ProfilePage() {
  const q = useProfile();
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
  const p = q.data.profile;
  return (
    <div className="page">
      <h1 className="h1">Что мы знаем о вас</h1>
      <p className="secondary" style={{ fontSize: 17, lineHeight: '26px' }}>
        {p.name} · {p.industry_name}
        {p.revenue_rub ? ` · выручка ≈ ${formatRub(p.revenue_rub)}` : ''}. Эти данные определяют, какие
        новости важны вам и почему. Поправьте, если что-то не так — лента пересчитается.
      </p>
      <Section title="Факты" id="facts">
        <FactsGrid p={p} />
      </Section>
      <Section title="Закупки и продажи" id="mix">
        <div className="stack">
          <MixBar direction="suppliers" title="Поставщики" />
          <MixBar direction="buyers" title="Покупатели" />
        </div>
      </Section>
      <Section title="Чувствительность к макрофакторам" id="factors">
        <FactorList p={p} />
      </Section>
      <Section title="Уточнить профиль" id="overrides">
        <OverridesForm key={p.profile_version} data={q.data} />
      </Section>
    </div>
  );
}
