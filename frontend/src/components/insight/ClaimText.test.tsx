import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ClaimText } from './ClaimText';
import { SourceDrawerContext } from './sourceContext';

describe('ClaimText', () => {
  it('shows origin badge and opens sources on click', () => {
    const open = vi.fn();
    render(
      <SourceDrawerContext.Provider value={{ open }}>
        <ClaimText
          claim={{
            text: 'Металлурги поднимают цены на 8%.',
            type: 'fact',
            refs: ['news:1', 'news:2'],
            confidence: null,
          }}
        />
      </SourceDrawerContext.Provider>,
    );
    expect(screen.getByText('Факт')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Металлурги поднимают цены на 8%.' }));
    expect(open).toHaveBeenCalledWith(['news:1', 'news:2'], 'Источники утверждения');
  });

  it('bank and ai badges; no refs — not clickable', () => {
    render(
      <>
        <ClaimText claim={{ text: 'Аналитики ожидают роста цен.', type: 'bank', refs: ['alfa:x:p1:c1'] }} />
        <ClaimText
          claim={{ text: 'Себестоимость может вырасти.', type: 'ai', refs: [], confidence: 'medium' }}
        />
      </>,
    );
    expect(screen.getByText('Альфа-Банк')).toBeTruthy();
    expect(screen.getByText('Вывод ИИ').getAttribute('title')).toContain('средняя');
    expect(screen.queryByRole('button', { name: 'Себестоимость может вырасти.' })).toBeNull();
  });
});
