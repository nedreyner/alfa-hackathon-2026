import { Button } from '@alfalab/core-components/button';
import { Tag } from '@alfalab/core-components/tag';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';

import { type FeedFilters, useFeed, useSession } from '../api/hooks';
import { EmptyState } from '../components/common/EmptyState';
import { ErrorState } from '../components/common/ErrorState';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { InsightCard } from '../components/insight/InsightCard';
import { sendUiEvent } from '../lib/telemetry';

const FILTERS: { key: string; label: string; value: FeedFilters }[] = [
  { key: 'all', label: 'Все', value: {} },
  { key: 'risk', label: 'Риски', value: { direction: 'risk' } },
  { key: 'opportunity', label: 'Возможности', value: { direction: 'opportunity' } },
  { key: 'impact', label: 'Влияние от среднего', value: { min_impact: 'medium' } },
];

export default function FeedPage() {
  const session = useSession();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('all');
  const value = FILTERS.find((f) => f.key === filter)!.value;
  const feed = useFeed(session.data?.role, value);
  useEffect(() => sendUiEvent('feed_view'), []);
  const items = feed.data?.pages.flatMap((p) => p.items) ?? [];
  const total = feed.data?.pages[0]?.total ?? 0;

  return (
    <div className="page">
      <h1 className="h1">Лента для {session.data?.company.name}</h1>
      <p className="secondary" style={{ margin: '0 0 20px' }}>
        События отсортированы по силе влияния на вашу компанию{total ? ` · ${total} в ленте` : ''}
      </p>
      <div className="row" style={{ marginBottom: 20 }}>
        <div className="row" role="group" aria-label="Фильтры">
          {FILTERS.map((f) => (
            <Tag
              key={f.key}
              size={32}
              shape="rounded"
              view="filled"
              checked={filter === f.key}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </Tag>
          ))}
        </div>
      </div>
      {feed.isPending ? (
        <div className="stack">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : feed.isError ? (
        <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          title="Пока нет событий, влияющих на вашу компанию"
          text="Проверьте любую новость — покажем, как она касается вас"
          action={
            <Button view="accent" size={48} onClick={() => navigate('/analyze')}>
              Проверить новость
            </Button>
          }
        />
      ) : (
        <div className="stack">
          {items.map((item) => (
            <InsightCard key={item.event_id} item={item} />
          ))}
          {feed.hasNextPage && (
            <Button
              view="secondary"
              size={48}
              block
              onClick={() => void feed.fetchNextPage()}
              loading={feed.isFetchingNextPage}
            >
              Показать ещё
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
