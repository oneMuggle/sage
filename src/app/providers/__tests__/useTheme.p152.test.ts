import { describe, expect, it } from 'vitest';

import { auditUseThemeGovernance } from '../useTheme';

describe('useTheme P152 governance audit', () => {
  it('returns healthy defaults for useTheme governance', () => {
    const res = auditUseThemeGovernance();
    expect(res.module).toBe('src/app/providers/useTheme.ts');
    expect(res.phase).toBe('P152');
    expect(res.mode).toBe('system');
    expect(res.resolvedTheme).toBe('dark');
    expect(res.healthy).toBe(true);
  });

  it('normalizes mode and resolvedTheme', () => {
    const res = auditUseThemeGovernance({
      mode: 'light',
      resolvedTheme: 'light',
    });
    expect(res.mode).toBe('light');
    expect(res.resolvedTheme).toBe('light');
    expect(res.healthy).toBe(true);
  });
});
