import { describe, expect, it } from 'vitest';

import {
  FONT_DEFAULTS,
  formatFontSettingsJson,
  formatFontSettingsSummary,
  normalizeFontSettings,
  normalizeFontSize,
} from '../fontOptions';

describe('fontOptions', () => {
  it('normalizes font sizes and settings with clamping and fallbacks', () => {
    expect(normalizeFontSize(8, 14)).toBe(10);
    expect(normalizeFontSize(30, 14)).toBe(24);
    expect(normalizeFontSize('', 14)).toBe(14);
    expect(normalizeFontSettings(null)).toEqual(FONT_DEFAULTS);
  });

  it('formats font settings summary and JSON (Phase P120)', () => {
    expect(formatFontSettingsSummary(FONT_DEFAULTS)).toBe(
      'ui=inter@14px · code=jetbrains-mono@13px',
    );
    expect(JSON.parse(formatFontSettingsJson(FONT_DEFAULTS))).toEqual(FONT_DEFAULTS);
  });
});
