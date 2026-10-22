import { describe, expect, it } from 'vitest';

import {
  formatAttentionBarrelJson,
  formatAttentionBarrelSummary,
} from '../index';

describe('attention barrel audit helpers', () => {
  it('formats attention barrel summary', () => {
    expect(formatAttentionBarrelSummary()).toContain('module=features/attention');
    expect(formatAttentionBarrelSummary()).toContain('exports=8');
  });

  it('exports attention barrel JSON snapshot', () => {
    const parsed = JSON.parse(formatAttentionBarrelJson());
    expect(parsed.module).toBe('features/attention');
    expect(parsed.exportCount).toBe(8);
    expect(Array.isArray(parsed.kinds)).toBe(true);
  });
});

