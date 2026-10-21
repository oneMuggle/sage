import { describe, expect, it } from 'vitest';

import {
  formatI18nProviderJson,
  formatI18nProviderSummary,
} from '../index';

describe('I18nProvider audit diagnostics', () => {
  it('formats i18n provider summary for zh and en', () => {
    expect(formatI18nProviderSummary('zh')).toContain('locale=zh · keys=');
    expect(formatI18nProviderSummary('zh')).toContain('storageKey=sage.locale');
    expect(formatI18nProviderSummary('en')).toContain('locale=en · keys=');
  });

  it('serializes i18n provider audit JSON', () => {
    const parsed = JSON.parse(formatI18nProviderJson('en'));
    expect(parsed.locale).toBe('en');
    expect(parsed.keyCount).toBeGreaterThan(100);
    expect(parsed.storageKey).toBe('sage.locale');
  });
});
