import { describe, expect, it } from 'vitest';

import {
  formatAtEntityMenuJson,
  formatAtEntityMenuSummary,
} from '../AtEntityMenu';

describe('AtEntityMenu audit helpers', () => {
  it('formats at entity menu summary', () => {
    expect(formatAtEntityMenuSummary('')).toBe(
      'query=empty · matches=4 · kinds=memory,wiki,skill,agent',
    );
    expect(formatAtEntityMenuSummary('mem')).toBe(
      'query=mem · matches=1 · kinds=memory,wiki,skill,agent',
    );
  });

  it('exports at entity menu JSON snapshot', () => {
    const parsed = JSON.parse(formatAtEntityMenuJson('wi'));
    expect(parsed.query).toBe('wi');
    expect(parsed.matchCount).toBe(1);
    expect(parsed.matchedKinds).toEqual(['wiki']);
  });
});

