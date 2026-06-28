import { describe, expect, it } from 'vitest';

import { en } from '../en';
import { zh, type TranslationKey } from '../zh';

describe('translations consistency', () => {
  it('zh and en have same number of keys', () => {
    expect(Object.keys(en).length).toBe(Object.keys(zh).length);
  });

  it('every zh key exists in en', () => {
    const zhKeys = Object.keys(zh) as TranslationKey[];
    const enKeys = new Set(Object.keys(en));
    for (const key of zhKeys) {
      expect(enKeys.has(key), `missing en translation for key: ${key}`).toBe(true);
    }
  });

  it('no extra keys in en that are not in zh', () => {
    const zhKeys = new Set(Object.keys(zh));
    const enKeys = Object.keys(en);
    for (const key of enKeys) {
      expect(zhKeys.has(key), `extra en key not in zh: ${key}`).toBe(true);
    }
  });

  it('every en value is a non-empty string', () => {
    for (const [key, value] of Object.entries(en)) {
      expect(typeof value, `en[${key}] must be string`).toBe('string');
      expect(value.length, `en[${key}] must be non-empty`).toBeGreaterThan(0);
    }
  });

  it('every zh value is a non-empty string', () => {
    for (const [key, value] of Object.entries(zh)) {
      expect(typeof value, `zh[${key}] must be string`).toBe('string');
      expect(value.length, `zh[${key}] must be non-empty`).toBeGreaterThan(0);
    }
  });

  it('zh has exactly 40 keys (M1 16 + M2 theme 12 + P4 gallery 1 + M3 scheduled 11)', () => {
    expect(Object.keys(zh).length).toBe(40);
  });
});
