import { Link, useParams } from 'react-router';

import { useTrace } from '../api/hooks';
import { AgentTimeline, RunSummary } from '../components/agent/AgentTimeline';
import { ErrorState } from '../components/common/ErrorState';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { ArrowLeft } from '../components/common/icons';

export default function TracePage() {
  const { insightId } = useParams();
  const trace = useTrace(insightId);
  return (
    <div className="page">
      <Link
        to={`/insights/${insightId}`}
        className="secondary"
        style={{ display: 'inline-flex', gap: 4, alignItems: 'center', textDecoration: 'none' }}
      >
        <ArrowLeft size={16} /> К разбору
      </Link>
      <h1 className="h1" style={{ marginTop: 16 }}>
        Как мы пришли к выводу
      </h1>
      <p className="secondary">
        Каждый шаг агента: какие данные собраны, какие модели вызывались и как проверялись утверждения.
      </p>
      {trace.isPending ? (
        <SkeletonCard lines={6} />
      ) : trace.isError ? (
        <ErrorState error={trace.error} />
      ) : (
        <>
          <RunSummary run={trace.data.run} events={trace.data.events} />
          <AgentTimeline events={trace.data.events} />
        </>
      )}
    </div>
  );
}
