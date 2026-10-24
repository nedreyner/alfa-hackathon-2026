import { Skeleton } from '@alfalab/core-components/skeleton';

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card" aria-busy="true" aria-label="Загрузка">
      <Skeleton visible animate style={{ height: 14, width: '40%', borderRadius: 8 }} />
      <div style={{ height: 14 }} />
      <Skeleton visible animate style={{ height: 24, width: '85%', borderRadius: 8 }} />
      {Array.from({ length: lines - 1 }, (_, i) => (
        <div key={i} style={{ marginTop: 10 }}>
          <Skeleton visible animate style={{ height: 14, width: `${70 - i * 12}%`, borderRadius: 8 }} />
        </div>
      ))}
    </div>
  );
}
