import { useEffect, useState } from 'react';

import { useWhatIf } from '../../api/hooks';
import type { WhatIfOut } from '../../api/types';
import { WHAT_IF } from '../../lib/labels';
import { Section } from './Sections';
import styles from './WhatIfPanel.module.css';

function useDebounced<T>(value: T, ms = 200): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

const num = (v: number, digits = 2) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(v);
const signed = (v: number, unit: string) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v))} ${unit}`;

function Range(props: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
  valueText: string;
}) {
  return (
    <label className={styles.range}>
      <span className={styles.rangeHead}>
        <span>{props.label}</span>
        <strong>{props.valueText}</strong>
      </span>
      <input
        type="range"
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
        aria-valuetext={props.valueText}
      />
    </label>
  );
}

/** Фича C: ползунки ставки и курса для путей влияния карточки; без путей ставки и курса панель не показывается. */
export function WhatIfPanel({ insightId }: { insightId: string }) {
  const [rate, setRate] = useState(0);
  const [fx, setFx] = useState(0);
  const [currency, setCurrency] = useState<string | null>(null);
  const params = useDebounced({ rate_delta_pp: rate, fx_delta_pct: fx, currency });
  const q = useWhatIf(insightId, params);
  const data: WhatIfOut | undefined = q.data;
  if (!data || (!data.rate_available && data.currencies.length === 0)) return null;
  const cur = currency ?? data.currencies[0] ?? null;

  return (
    <Section title={WHAT_IF.title} id="what-if">
      <p className="secondary" style={{ marginTop: 0 }}>
        {WHAT_IF.intro}
      </p>
      <div className={styles.grid}>
        {data.rate && (
          <div className={styles.card}>
            <Range
              label={WHAT_IF.rate}
              min={-2}
              max={2}
              step={0.25}
              value={rate}
              onChange={setRate}
              valueText={
                data.rate.key_rate_now != null
                  ? `${num(data.rate.key_rate_now)}% → ${num(data.rate.key_rate_now + rate)}%`
                  : signed(rate, 'п. п.')
              }
            />
            <p className={styles.result}>{data.rate.text}</p>
            <span className="caption">{WHAT_IF.level[data.rate.level]}</span>
          </div>
        )}
        {data.fx && cur && (
          <div className={styles.card}>
            {data.currencies.length > 1 && (
              <div className={styles.currencies} role="group" aria-label={WHAT_IF.fx}>
                {data.currencies.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={c === cur ? `${styles.cur} ${styles.curActive}` : styles.cur}
                    aria-pressed={c === cur}
                    onClick={() => setCurrency(c)}
                  >
                    {c}
                  </button>
                ))}
              </div>
            )}
            <Range
              label={`${WHAT_IF.fx} ${cur}`}
              min={-10}
              max={10}
              step={1}
              value={fx}
              onChange={setFx}
              valueText={
                data.fx.rate_now != null
                  ? `${num(data.fx.rate_now)} ₽ → ${num(data.fx.rate_now * (1 + fx / 100))} ₽`
                  : signed(fx, '%')
              }
            />
            <p className={styles.result}>{data.fx.text}</p>
            <span className="caption">{WHAT_IF.level[data.fx.level]}</span>
          </div>
        )}
      </div>
      <p className="caption" style={{ marginTop: 12 }}>
        <span className={styles.label}>{WHAT_IF.label}</span> {data.disclaimer}
      </p>
    </Section>
  );
}
