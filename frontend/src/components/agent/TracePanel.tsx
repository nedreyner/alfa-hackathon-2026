import { Link } from 'react-router';

import { useTrace } from '../../api/hooks';
import { Panel } from '../common/Panel';
import { SkeletonCard } from '../common/SkeletonCard';
import { AgentTimeline, RunSummary } from './AgentTimeline';

export default function TracePanel({ insightId, onClose }: { insightId: string; onClose: () => void }) {
  const trace = useTrace(insightId);
  return (
    <Panel open onClose={onClose} title="Как мы пришли к выводу">
      {trace.isPending ? (
        <SkeletonCard />
      ) : trace.data ? (
        <div style={{ paddingBottom: 24 }}>
          <RunSummary run={trace.data.run} events={trace.data.events} />
          <AgentTimeline events={trace.data.events} />
          <p style={{ marginTop: 20 }}>
            <Link to={`/insights/${insightId}/trace`} className="secondary">
              Открыть на всю страницу
            </Link>
          </p>
        </div>
      ) : (
        <p className="secondary">Трасса недоступна</p>
      )}
    </Panel>
  );
}
