import { describe, expect, it } from 'vitest';

import * as L from './labels';

describe('labels', () => {
  it('all enum maps are complete and non-empty', () => {
    const maps: Record<string, Record<string, string>> = {
      DIRECTION: L.DIRECTION,
      IMPACT: L.IMPACT,
      LEVEL: L.LEVEL,
      CLAIM_TYPE: L.CLAIM_TYPE,
      ROLE: L.ROLE,
      ROLE_SHORT: L.ROLE_SHORT,
      URGENCY: L.URGENCY,
      HORIZON: L.HORIZON,
      SOURCE_KIND: L.SOURCE_KIND,
      ALIGNMENT: L.ALIGNMENT,
      BUDGET_MODE: L.BUDGET_MODE,
      FEEDBACK_REASON: L.FEEDBACK_REASON,
      ERROR_TEXT: L.ERROR_TEXT,
    };
    for (const [name, map] of Object.entries(maps)) {
      expect(Object.keys(map).length, name).toBeGreaterThan(1);
      for (const [k, v] of Object.entries(map)) expect(v.trim(), `${name}.${k}`).not.toBe('');
    }
    expect(Object.keys(L.DIRECTION).sort()).toEqual(['mixed', 'opportunity', 'risk']);
    expect(Object.keys(L.IMPACT)).toEqual(['low', 'medium', 'high', 'critical']);
    expect(Object.keys(L.ROLE).sort()).toEqual(['cfo', 'owner', 'treasurer']);
  });

  it('error codes from 08-agent §17 have texts', () => {
    for (const code of [
      'llm_unavailable',
      'budget_exhausted',
      'invalid_output',
      'fetch_failed',
      'unsupported_content',
      'blocked_url',
      'timeout',
      'interrupted',
    ]) {
      expect(L.errorText(code), code).not.toBe(L.ERROR_TEXT.internal);
    }
    expect(L.errorText('unknown_code')).toBe(L.ERROR_TEXT.internal);
    expect(L.errorText(null)).toBe(L.ERROR_TEXT.internal);
  });

  it('phases and examples', () => {
    expect(Object.keys(L.PHASE)).toEqual([
      'intake',
      'plan',
      'tools',
      'draft',
      'verify',
      'revise',
      'finalize',
    ]);
    expect(L.ANALYZE_EXAMPLES).toHaveLength(3);
  });
});
