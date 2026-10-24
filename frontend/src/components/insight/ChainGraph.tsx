import { Background, Handle, Position, ReactFlow, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { memo, useMemo, useSyncExternalStore } from 'react';

import type { ChainGraph as ChainGraphData, ChainNode } from '../../api/types';
import styles from './ChainGraph.module.css';
import { type FlowData, toFlow } from './chainFlow';

const KIND: Record<ChainNode['kind'], string> = {
  event: 'Событие',
  industry: 'Отрасль',
  factor: 'Фактор',
  exposure: 'Ваша компания',
  consequence: 'Последствие',
};

const ChainNodeView = memo(function ChainNodeView({ data }: NodeProps<Node<FlowData>>) {
  const { node, vertical, onOpen } = data;
  const clickable = (node.source_ids ?? []).length > 0 && !!onOpen;
  const tone = node.kind === 'consequence' && node.direction ? styles[node.direction] : '';
  return (
    <div
      className={`${styles.node} ${styles[node.kind] ?? ''} ${tone} ${clickable ? styles.clickable : ''}`}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={() => clickable && onOpen?.(node)}
      onKeyDown={(e) => e.key === 'Enter' && clickable && onOpen?.(node)}
      title={clickable ? 'Показать источники' : undefined}
    >
      <Handle type="target" position={vertical ? Position.Top : Position.Left} style={{ opacity: 0 }} />
      <div className={styles.kind}>{KIND[node.kind]}</div>
      <div>{node.label}</div>
      {node.sublabel && <div className={styles.sub}>{node.sublabel}</div>}
      <Handle type="source" position={vertical ? Position.Bottom : Position.Right} style={{ opacity: 0 }} />
    </div>
  );
});

const nodeTypes = { chain: ChainNodeView };

const MOBILE = '(max-width: 720px)';
function subscribe(cb: () => void) {
  const mq = window.matchMedia(MOBILE);
  mq.addEventListener?.('change', cb);
  return () => mq.removeEventListener?.('change', cb);
}
const useVertical = () =>
  useSyncExternalStore(
    subscribe,
    () => window.matchMedia(MOBILE).matches,
    () => false,
  );

export default function ChainGraph({
  chain,
  onOpenSources,
}: {
  chain: ChainGraphData;
  onOpenSources?: (ids: string[], title: string) => void;
}) {
  const vertical = useVertical();
  const { nodes, edges } = useMemo(
    () =>
      toFlow(chain, vertical, onOpenSources ? (n) => onOpenSources(n.source_ids ?? [], n.label) : undefined),
    [chain, vertical, onOpenSources],
  );
  return (
    <figure style={{ margin: 0 }}>
      <div className={styles.wrap} aria-label="Граф цепной реакции">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          panOnDrag={false}
          panOnScroll={false}
          preventScrolling={false}
        >
          <Background gap={24} size={1} color="#e2e3e6" />
        </ReactFlow>
      </div>
      <figcaption className={`caption ${styles.hint}`}>
        Цепная реакция: как событие доходит до вашей компании. Нажмите на узел, чтобы увидеть источник.
      </figcaption>
    </figure>
  );
}
