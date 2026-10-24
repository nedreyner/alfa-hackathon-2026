import { Panel } from '../common/Panel';

export default function TracePanel({ onClose }: { insightId: string; onClose: () => void }) {
  return (
    <Panel open onClose={onClose} title="Как мы пришли к выводу">
      <p className="secondary">Трасса появится в следующем шаге.</p>
    </Panel>
  );
}
