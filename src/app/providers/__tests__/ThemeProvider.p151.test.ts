import { describe, expect, it } from 'vitest';

import { auditThemeProviderGovernance } from '../ThemeProvider';

describe('ThemeProvider P151 governance audit', () => {
  it('returns healthy defaults for ThemeProvider governance', () => {
    const res = auditThemeProviderGovernance();
    expect(res.module).toBe('src/app/providers/ThemeProvider.tsx');
    expect(res.phase).toBe('P151');
    expect(res.mode).toBe('system');
    expect(res.presetActive).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes mode and presetActive flag', () => {
    const res = auditThemeProviderGovernance({
      mode: 'dark',
      presetActive: false,
    });
    expect(res.mode).toBe('dark');
    expect(res.presetActive).toBe(false);
    expect(res.healthy).toBe(true);
  });
});
