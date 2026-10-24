import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import chain from '../../test/fixtures/chain.json';
import type { ChainGraph as ChainData } from '../../api/types';
import ChainGraph from './ChainGraph';
import { toFlow } from './chainFlow';

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

describe('ChainGraph', () => {
  it('maps server graph to flow; vertical layout swaps axes', () => {
    const { nodes, edges } = toFlow(chain as ChainData, false);
    expect(nodes.map((n) => n.id)).toEqual(['event', 'P1-driver', 'P1-exposure', 'P1-consequence']);
    expect(nodes[2].position).toEqual({ x: 560, y: 0 });
    expect(edges[2].label).toBe('вклад 0.39');
    expect((edges[0].style as { strokeWidth: number }).strokeWidth).toBeCloseTo(1 + 4 * 0.78);
    const vertical = toFlow(chain as ChainData, true);
    expect(vertical.nodes[2].position.y).toBeGreaterThan(vertical.nodes[1].position.y);
    expect(vertical.nodes[2].position.x).toBe(0);
  });

  it('renders custom nodes', () => {
    render(<ChainGraph chain={chain as ChainData} onOpenSources={() => undefined} />);
    expect(screen.getByLabelText('Граф цепной реакции')).toBeTruthy();
    expect(screen.getByText(/Цепная реакция/)).toBeTruthy();
  });
});
