import { describe, expect, it } from 'vitest';

import {
  formatSettingsRegistryJson,
  formatSettingsRegistrySummary,
} from '../settingsRegistry';

describe('settingsRegistry audit helpers', () => {
  it('formats settings registry summary', () => {
    const summary = formatSettingsRegistrySummary();
    expect(summary).toContain('total=');
    expect(summary).toContain('basic=');
    expect(summary).toContain('advanced=');
  });

  it('exports settings registry JSON snapshot', () => {
    const parsed = JSON.parse(formatSettingsRegistryJson());
    expect(parsed.total).toBeGreaterThan(10);
    expect(parsed.basic + parsed.advanced).toBeLessThanOrEqual(parsed.total);
  });
});

