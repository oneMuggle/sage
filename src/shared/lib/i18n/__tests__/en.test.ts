import { describe, expect, it } from 'vitest';

import {
  en,
  formatEnglishTranslationsJson,
  formatEnglishTranslationsSummary,
} from '../en';

describe('en i18n aggregator audit diagnostics', () => {
  it('formats English translation aggregator summary', () => {
    const keyCount = Object.keys(en).length;
    expect(keyCount).toBeGreaterThan(100);
    expect(formatEnglishTranslationsSummary()).toBe(`locale=en · keys=${keyCount}`);
  });

  it('serializes English translation aggregator audit JSON', () => {
    const parsed = JSON.parse(formatEnglishTranslationsJson());
    expect(parsed).toEqual({
      locale: 'en',
      keyCount: Object.keys(en).length,
      hasChatTitle: true,
    });
  });
});
