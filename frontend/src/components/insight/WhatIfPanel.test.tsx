import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { WhatIfOut } from '../../api/types';
import { renderWithProviders } from '../../test/render';
import { WhatIfPanel } from './WhatIfPanel';

const state: { data: WhatIfOut | undefined; calls: unknown[] } = { data: undefined, calls: [] };
vi.mock('../../api/hooks', () => ({
  useWhatIf: (_id: string, params: unknown) => {
    state.calls.push(params);
    return { data: state.data };
  },
}));

const full: WhatIfOut = {
  rate_available: true,
  currencies: ['CNY', 'USD'],
  rate: {
    key_rate_now: 14,
    key_rate_new: 14,
    debt_rub: 9.6e9,
    delta_rub_year: 0,
    share_of_revenue: 0,
    level: 'high',
    text: 'Сдвиньте ставку, чтобы увидеть изменение процентных расходов за год.',
  },
  fx: {
    currency: 'CNY',
    rate_now: 12,
    rate_new: 12,
    direction: 'import',
    delta_rub_per_billion: 0,
    level: 'medium',
    text: 'Сдвиньте курс, чтобы увидеть эффект на расчёты в валюте.',
  },
  label: 'Вывод ИИ: оценка',
  disclaimer: 'Арифметическая оценка.',
};

describe('WhatIfPanel', () => {
  it('hidden without rate and fx paths', () => {
    state.data = { ...full, rate_available: false, currencies: [], rate: null, fx: null };
    const { container } = renderWithProviders(<WhatIfPanel insightId="ins_1" />);
    expect(container.innerHTML).toBe('');
  });

  it('shows sliders, current levels and the AI-estimate label', () => {
    state.data = full;
    renderWithProviders(<WhatIfPanel insightId="ins_1" />);
    expect(screen.getByRole('heading', { name: 'Что если' })).toBeTruthy();
    expect(screen.getByText('14% → 14%')).toBeTruthy();
    expect(screen.getByText('Вывод ИИ: оценка')).toBeTruthy();
    expect(screen.getByText('чувствительность высокая')).toBeTruthy();
    const [rate] = screen.getAllByRole('slider');
    fireEvent.change(rate, { target: { value: '-2' } });
    expect(screen.getByText('14% → 12%')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'USD' }));
    expect(screen.getByRole('button', { name: 'USD' }).getAttribute('aria-pressed')).toBe('true');
  });
});
