import type { Edge, Node } from '@xyflow/react';

import type { ChainGraph, ChainNode } from '../../api/types';

export type FlowData = { node: ChainNode; vertical: boolean; onOpen?: (n: ChainNode) => void };

/** Перевод серверного графа в узлы и рёбра xyflow; на мобильных x и y меняются местами. */
export function toFlow(chain: ChainGraph, vertical: boolean, onOpen?: (n: ChainNode) => void) {
  const nodes: Node<FlowData>[] = chain.nodes.map((n) => ({
    id: n.id,
    type: 'chain',
    position: vertical ? { x: n.y * 1.9, y: n.x * 0.55 } : { x: n.x * 0.8, y: n.y * 1.05 },
    data: { node: n, vertical, onOpen },
    draggable: false,
    connectable: false,
    selectable: false,
  }));
  const edges: Edge[] = chain.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label ? `вклад ${e.weight.toFixed(2)}` : undefined,
    style: { strokeWidth: 1 + 4 * Math.min(1, e.weight * 2), stroke: '#9a9aa0' },
    labelStyle: { fontSize: 11, fill: '#6e6e73' },
    labelBgStyle: { fill: '#f3f4f5' },
  }));
  return { nodes, edges };
}
