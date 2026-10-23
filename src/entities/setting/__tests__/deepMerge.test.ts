import { describe, expect, it } from 'vitest';

import {
  deepMerge,
  formatDeepMergeJson,
  formatDeepMergeSummary,
} from '../deepMerge';

describe('deepMerge audit helpers', () => {
  it('merges nested objects and formats summary', () => {
    const merged = deepMerge({ a: 1, b: { x: 10 } }, { a: 2, b: { x: 20 } });
    expect(merged).toEqual({ a: 2, b: { x: 20 } });
    expect(formatDeepMergeSummary({ policy: 'local-wins' }, 2)).toBe(
      'policy=local-wins · conflicts=2 · customHandler=false',
    );
  });

  it('serializes deepMerge audit JSON', () => {
    const raw = formatDeepMergeJson(
      { policy: 'remote-wins', onConflict: () => undefined },
      1,
    );
    expect(JSON.parse(raw)).toEqual({
      policy: 'remote-wins',
      conflictCount: 1,
      hasConflictHandler: true,
    });
  });
});
