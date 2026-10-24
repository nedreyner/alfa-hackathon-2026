import { Button } from '@alfalab/core-components/button';
import { Input } from '@alfalab/core-components/input';
import { useState } from 'react';
import { Link } from 'react-router';

import { adminToken, setAdminToken, useReview, useReviewQueue } from '../../api/hooks';
import type { ReviewItem } from '../../api/types';
import { formatShare } from '../../lib/format';
import { REVIEW } from '../../lib/labels';
import { Section } from '../insight/Sections';

function Row({ item, ownCompany }: { item: ReviewItem; ownCompany: string | undefined }) {
  const review = useReview();
  const busy = review.isPending;
  return (
    <li style={{ padding: '14px 0', borderBottom: '1px solid var(--ai-border)', display: 'grid', gap: 8 }}>
      <div style={{ fontWeight: 600 }}>
        {item.company_id === ownCompany ? (
          <Link to={`/insights/${item.insight_id}`} style={{ color: 'inherit' }}>
            {item.headline}
          </Link>
        ) : (
          item.headline
        )}
      </div>
      <div className="caption">
        {item.company_id} · {REVIEW.status[item.status] ?? item.status} · {REVIEW.share}{' '}
        {formatShare(item.supported_share)}
        {item.removed_claims ? ` · скрыто выводов: ${item.removed_claims}` : ''}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <Button
          size={32}
          view="secondary"
          loading={busy && review.variables?.status === 'published'}
          disabled={busy}
          onClick={() => review.mutate({ insightId: item.insight_id, status: 'published' })}
        >
          {REVIEW.approve}
        </Button>
        <Button
          size={32}
          view="transparent"
          loading={busy && review.variables?.status === 'rejected'}
          disabled={busy}
          onClick={() => review.mutate({ insightId: item.insight_id, status: 'rejected' })}
        >
          {REVIEW.reject}
        </Button>
      </div>
    </li>
  );
}

/** Очередь проверки на странице «Качество»: жюри — своя компания, админ с токеном — все компании. */
export function ReviewQueue({ jury, companyId }: { jury: boolean; companyId: string | undefined }) {
  const [version, setVersion] = useState(0);
  const [entering, setEntering] = useState(false);
  const [token, setToken] = useState('');
  const hasToken = !!adminToken();
  const q = useReviewQueue(jury || hasToken, version);

  if (!jury && !hasToken) {
    return entering ? (
      <form
        className="row"
        style={{ gap: 8, marginTop: 16 }}
        onSubmit={(e) => {
          e.preventDefault();
          setAdminToken(token.trim() || null);
          setEntering(false);
          setVersion((v) => v + 1);
        }}
      >
        <Input
          size={48}
          type="password"
          placeholder={REVIEW.tokenPlaceholder}
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="off"
        />
        <Button size={48} view="secondary" type="submit">
          {REVIEW.tokenSave}
        </Button>
      </form>
    ) : (
      <button type="button" className="link-button caption" onClick={() => setEntering(true)}>
        {REVIEW.expert}
      </button>
    );
  }

  return (
    <Section title={REVIEW.title} id="review">
      <p className="secondary" style={{ marginTop: 0 }}>
        {REVIEW.intro}
      </p>
      {q.isError && <p className="secondary">Нет доступа к очереди проверки.</p>}
      {q.data && q.data.length === 0 && <p className="secondary">{REVIEW.empty}</p>}
      {q.data && q.data.length > 0 && (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {q.data.map((it) => (
            <Row key={it.insight_id} item={it} ownCompany={companyId} />
          ))}
        </ul>
      )}
      {hasToken && (
        <button
          type="button"
          className="link-button caption"
          style={{ marginTop: 12 }}
          onClick={() => {
            setAdminToken(null);
            setVersion((v) => v + 1);
          }}
        >
          {REVIEW.tokenExit}
        </button>
      )}
    </Section>
  );
}
