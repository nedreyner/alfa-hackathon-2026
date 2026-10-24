import { Button } from '@alfalab/core-components/button';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import { useGenerateInsight } from '../../api/hooks';
import { useRunEvents } from '../../api/sse';
import type { FeedItem } from '../../api/types';
import { errorText } from '../../lib/labels';
import { plural } from '../../lib/format';
import { MiniSteps } from '../agent/MiniSteps';
import { RelativeTime } from '../common/RelativeTime';
import { ConfidenceBadge, DirectionTag, ImpactBadge, WarnPlate } from './Badges';
import { ChainPreview } from './ChainPreview';
import styles from './InsightCard.module.css';

function Meta({ item }: { item: FeedItem }) {
  return (
    <div className={styles.meta}>
      <DirectionTag direction={item.direction} />
      <ImpactBadge level={item.impact_level} />
      <span className="caption">
        <RelativeTime value={item.published_at} /> · {item.source_count}{' '}
        {plural(item.source_count, 'источник', 'источника', 'источников')}
      </span>
      {item.stale && <WarnPlate>профиль изменился</WarnPlate>}
      {item.needs_review && <WarnPlate>на проверке</WarnPlate>}
    </div>
  );
}

/** Карточка целиком кликабельна через «растянутую» ссылку в заголовке: семантика ссылки и фокус с клавиатуры. */
function ReadyCard({ item }: { item: FeedItem }) {
  return (
    <article className={`${styles.card} ${styles.clickable} appear`}>
      <Meta item={item} />
      <h2 className={styles.headline}>
        <Link to={`/insights/${item.insight_id}`} className={styles.stretched}>
          {item.headline}
        </Link>
      </h2>
      {item.why_you && <p className={styles.why}>{item.why_you}</p>}
      <ChainPreview text={item.chain_preview} />
      <div className={styles.footer}>
        {item.confidence_level ? <ConfidenceBadge level={item.confidence_level} /> : <span />}
        <span className="caption">Открыть разбор →</span>
      </div>
    </article>
  );
}

/** pending / generating / failed: заголовок события, превью цепочки и запуск разбора с живыми шагами. */
function WaitingCard({ item }: { item: FeedItem }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const generate = useGenerateInsight();
  const [runId, setRunId] = useState<string | null>(item.status === 'generating' ? item.run_id : null);
  const run = useRunEvents(runId);
  const failed = item.status === 'failed' && !runId;

  useEffect(() => {
    if (run.end) {
      void qc.invalidateQueries({ queryKey: ['feed'] });
      void qc.invalidateQueries({ queryKey: ['brief'] });
    }
  }, [run.end, qc]);

  const start = () =>
    generate.mutate(item.event_id, {
      onSuccess: (res) => {
        if (res.status === 'ready' && res.insight_id) navigate(`/insights/${res.insight_id}`);
        else setRunId(res.run_id ?? null);
      },
    });

  const busy = !!runId && !run.end;
  return (
    <article className={`${styles.card} appear`} aria-busy={busy}>
      <Meta item={item} />
      <h2 className={styles.headline} style={{ fontSize: 18, lineHeight: '26px' }}>
        {item.event_title}
      </h2>
      <ChainPreview text={item.chain_preview} />
      {busy && <MiniSteps events={run.events} />}
      {run.end && run.end.status !== 'succeeded' && (
        <p className="secondary" role="alert" style={{ color: 'var(--ai-risk)' }}>
          {errorText(run.end.error_code)}
        </p>
      )}
      <div className={styles.footer}>
        <span className="caption">
          {failed ? 'Не удалось подготовить разбор' : busy ? 'Готовим разбор…' : 'Разбор ещё не готов'}
        </span>
        {!busy && (
          <Button
            view={failed ? 'secondary' : 'primary'}
            size={40}
            onClick={start}
            loading={generate.isPending}
          >
            {failed || run.end ? 'Повторить' : 'Разобрать для меня'}
          </Button>
        )}
      </div>
    </article>
  );
}

export function InsightCard({ item }: { item: FeedItem }) {
  return item.status === 'ready' && item.insight_id ? <ReadyCard item={item} /> : <WaitingCard item={item} />;
}
