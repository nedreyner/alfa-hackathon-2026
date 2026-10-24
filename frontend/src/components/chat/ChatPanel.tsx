import { Panel } from '../common/Panel';

export default function ChatPanel({ onClose }: { insightId: string; onClose: () => void }) {
  return (
    <Panel open onClose={onClose} title="Спросить аналитика">
      <p className="secondary">Чат появится в следующем шаге.</p>
    </Panel>
  );
}
