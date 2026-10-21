import { describe, expect, it } from 'vitest';

import {
  formatChineseTranslationsJson,
  formatChineseTranslationsSummary,
  zh,
} from '../zh';

describe('zh i18n aggregator audit diagnostics', () => {
  it('formats Chinese translation aggregator summary', () => {
    const keyCount = Object.keys(zh).length;
    expect(keyCount).toBeGreaterThan(100);
    expect(formatChineseTranslationsSummary()).toBe(`locale=zh · keys=${keyCount}`);
  });

  it('serializes Chinese translation aggregator audit JSON', () => {
    const parsed = JSON.parse(formatChineseTranslationsJson());
    expect(parsed).toEqual({
      locale: 'zh',
      keyCount: Object.keys(zh).length,
      hasChatTitle: true,
    });
  });
});
