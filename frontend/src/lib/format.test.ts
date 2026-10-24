import { describe, expect, it } from 'vitest';

import { formatDate, formatDuration, formatRelative, formatRub, formatShare, plural } from './format';

describe('format', () => {
  it('shares and money', () => {
    expect(formatShare(0.34)).toBe('34%');
    expect(formatShare(null)).toBe('—');
    expect(formatRub(1.2e9)).toBe('1,2 млрд ₽');
    expect(formatRub(48_000_000_000)).toBe('48 млрд ₽');
    expect(formatRub(3_500_000)).toBe('3,5 млн ₽');
    expect(formatRub(950)).toBe('950 ₽');
  });

  it('dates in Moscow time', () => {
    expect(formatDate('2026-10-22T06:10:00Z')).toBe('22 окт, 09:10');
    const now = new Date('2026-10-22T12:00:00Z');
    expect(formatRelative('2026-10-22T10:00:00Z', now)).toBe('2 ч назад');
    expect(formatRelative('2026-10-22T11:59:30Z', now)).toBe('только что');
    expect(formatRelative('2026-10-22T11:15:00Z', now)).toBe('45 мин назад');
    expect(formatRelative('2026-10-19T12:00:00Z', now)).toBe('3 дн назад');
  });

  it('durations and plurals', () => {
    expect(formatDuration(17_340)).toBe('17 с');
    expect(formatDuration(1_500)).toBe('1,5 с');
    expect(formatDuration(420)).toBe('420 мс');
    expect(plural(1, 'событие', 'события', 'событий')).toBe('событие');
    expect(plural(3, 'событие', 'события', 'событий')).toBe('события');
    expect(plural(11, 'событие', 'события', 'событий')).toBe('событий');
    expect(plural(22, 'событие', 'события', 'событий')).toBe('события');
  });
});
