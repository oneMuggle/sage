import { describe, expect, it } from 'vitest';

import {
  DEFAULT_THEME_ID,
  formatThemePresetsJson,
  formatThemePresetsSummary,
} from '../presets';

describe('theme presets audit helpers', () => {
  it('formats theme presets summary', () => {
    const summary = formatThemePresetsSummary();
    expect(summary).toContain(`defaultId=${DEFAULT_THEME_ID}`);
    expect(summary).toContain('indigo');
  });

  it('exports theme presets JSON snapshot', () => {
    const parsed = JSON.parse(formatThemePresetsJson());
    expect(parsed.defaultId).toBe(DEFAULT_THEME_ID);
    expect(parsed.count).toBeGreaterThanOrEqual(5);
    expect(parsed.ids).toContain('indigo');
  });
});

