import { describe, expect, it } from 'vitest';

import {
  formatElapsedSecondsSummary,
  formatElapsedSecondsJson,
} from '../useElapsedSeconds';

describe('useElapsedSeconds audit helpers', () => {
  it('formats elapsed seconds summary and json', () => {
    expect(formatElapsedSecondsSummary(true, 18)).toBe('active=true · elapsed=18s');
    const parsed = JSON.parse(formatElapsedSecondsJson(true, 18));
    expect(parsed).toEqual({
      active: true,
      elapsedSeconds: 18,
    });
  });

  it('handles inactive or nullish inputs safely', () => {
    expect(formatElapsedSecondsSummary(false, null)).toBe('active=false · elapsed=0s');
    expect(JSON.parse(formatElapsedSecondsJson(null, -5)).elapsedSeconds).toBe(0);
  });
});
