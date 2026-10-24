import { Button } from '@alfalab/core-components/button';
import { useState } from 'react';

import { useFeedback } from '../../api/hooks';
import type { FeedbackReason, InsightDetail } from '../../api/types';
import { FEEDBACK_REASON, NEGATIVE_REASONS, POSITIVE_REASONS } from '../../lib/labels';
import styles from './sections.module.css';

export function FeedbackBar({ detail }: { detail: InsightDetail }) {
  const send = useFeedback(detail.insight.id);
  const [useful, setUseful] = useState<boolean | null>(detail.my_feedback?.useful ?? null);
  const [reason, setReason] = useState<FeedbackReason | null>(detail.my_feedback?.reason ?? null);
  const [comment, setComment] = useState('');
  const done = send.isSuccess;

  const submit = (u: boolean, r: FeedbackReason | null, c?: string) =>
    send.mutate({ useful: u, reason: r, comment: c || null });

  return (
    <div className="card" style={{ boxShadow: 'none', background: 'var(--ai-bg-subtle)', border: 0 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>Полезно?</strong>
        <div className="row">
          <Button
            size={40}
            view={useful === true ? 'primary' : 'secondary'}
            onClick={() => {
              setUseful(true);
              setReason(null);
              submit(true, null);
            }}
            aria-pressed={useful === true}
          >
            👍 Да
          </Button>
          <Button
            size={40}
            view={useful === false ? 'primary' : 'secondary'}
            onClick={() => {
              setUseful(false);
              setReason(null);
            }}
            aria-pressed={useful === false}
          >
            👎 Нет
          </Button>
        </div>
      </div>
      {useful !== null && (
        <div className={styles.chips} style={{ marginTop: 14 }}>
          {(useful ? POSITIVE_REASONS : NEGATIVE_REASONS).map((r) => (
            <button
              key={r}
              type="button"
              className={`${styles.chip} ${reason === r ? styles.chipFor : ''}`}
              style={{ cursor: 'pointer' }}
              onClick={() => {
                setReason(r);
                submit(useful, r, comment);
              }}
            >
              {FEEDBACK_REASON[r]}
            </button>
          ))}
        </div>
      )}
      {useful === false && reason && (
        <div className="row" style={{ marginTop: 12 }}>
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={500}
            placeholder="Что было не так? (необязательно)"
            style={{
              flex: 1,
              minWidth: 200,
              padding: '10px 12px',
              borderRadius: 10,
              border: '1px solid var(--ai-border)',
              font: 'inherit',
            }}
          />
          <Button size={40} view="secondary" onClick={() => submit(false, reason, comment)}>
            Отправить
          </Button>
        </div>
      )}
      {done && (
        <div className="caption" style={{ marginTop: 10 }} role="status">
          Спасибо! Учтём в следующих разборах.
        </div>
      )}
    </div>
  );
}
