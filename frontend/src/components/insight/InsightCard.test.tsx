import { act, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { FeedItem } from '../../api/types';
import { FakeEventSource, renderWithProviders } from '../../test/render';
import { InsightCard } from './InsightCard';

const base: FeedItem = {
  event_id: 7,
  status: 'ready',
  insight_id: 'ins_1',
  run_id: null,
  headline: 'Арматура дорожает: себестоимость может вырасти',
  why_you: '34% ваших закупок — металлургия',
  chain_preview: 'Металлурги поднимают цены → 34% ваших закупок — металлургия → риск: рост закупочных цен',
  direction: 'risk',
  impact_level: 'high',
  score: 0.43,
  confidence_level: 'high',
  event_title: 'Металлурги поднимают цены на арматуру на 8%',
  event_type: 'commodity_prices',
  published_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  publishers: ['Интерфакс', 'ТАСС'],
  source_count: 3,
  stale: false,
  needs_review: false,
};

describe('InsightCard', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('ready: headline, why, chain, labels', () => {
    renderWithProviders(<InsightCard item={base} />);
    expect(screen.getByRole('heading', { name: base.headline })).toBeTruthy();
    expect(screen.getByRole('link', { name: base.headline }).getAttribute('href')).toBe(
      `/insights/${base.insight_id}`,
    );
    expect(screen.getByText(base.why_you!, { selector: 'p' })).toBeTruthy();
    expect(screen.getByText('Риск')).toBeTruthy();
    expect(screen.getByText('Влияние: высокое')).toBeTruthy();
    expect(screen.getByText('Уверенность: высокая')).toBeTruthy();
    expect(screen.getByText('2 ч назад')).toBeTruthy();
    expect(screen.getByText(/3 источника/)).toBeTruthy();
  });

  it('ready + stale + needs_review show plates', () => {
    renderWithProviders(<InsightCard item={{ ...base, stale: true, needs_review: true }} />);
    expect(screen.getByText('профиль изменился')).toBeTruthy();
    expect(screen.getByText('на проверке')).toBeTruthy();
  });

  it('pending: event title and generate button', () => {
    renderWithProviders(
      <InsightCard item={{ ...base, status: 'pending', insight_id: null, confidence_level: null }} />,
    );
    expect(screen.getByRole('heading', { name: base.event_title })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Разобрать для меня' })).toBeTruthy();
  });

  it('generating: subscribes to run events and shows steps', () => {
    renderWithProviders(
      <InsightCard item={{ ...base, status: 'generating', insight_id: null, run_id: 'run_9' }} />,
    );
    expect(FakeEventSource.instances[0].url).toBe('/api/runs/run_9/events');
    expect(screen.getByText('Готовим разбор…', { selector: 'span' })).toBeTruthy();
    act(() =>
      FakeEventSource.instances[0].emit('trace', {
        seq: 1,
        ts: base.published_at,
        type: 'tool.call',
        phase: 'tools',
        title: 'Считаю цепную реакцию',
        status: 'ok',
        payload: {},
        model: null,
        tokens_in: null,
        tokens_out: null,
        cost_rub: null,
        latency_ms: null,
      }),
    );
    expect(screen.getByText('Считаю цепную реакцию')).toBeTruthy();
  });

  it('failed: retry button', () => {
    renderWithProviders(
      <InsightCard item={{ ...base, status: 'failed', insight_id: null, run_id: 'run_x' }} />,
    );
    expect(screen.getByText('Не удалось подготовить разбор')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeTruthy();
  });
});
