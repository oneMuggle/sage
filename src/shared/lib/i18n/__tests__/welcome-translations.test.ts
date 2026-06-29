/**
 * @vitest-environment jsdom
 */
import { describe, expect, it } from 'vitest';

import { en } from '../en';
import { zh, type TranslationKey } from '../zh';

const welcomeKeys: TranslationKey[] = [
  'welcome.hero.greeting',
  'welcome.hero.subtitle',
  'welcome.hero.back',
  'welcome.input.placeholder',
  'welcome.rec.title',
  'welcome.rec.code.title',
  'welcome.rec.code.desc',
  'welcome.rec.search.title',
  'welcome.rec.search.desc',
  'welcome.rec.idea.title',
  'welcome.rec.idea.desc',
  'welcome.quick.feedback',
  'welcome.quick.feedback_desc',
  'welcome.quick.github',
  'welcome.quick.github_desc',
  'welcome.quick.webui',
  'welcome.quick.webui_desc',
  'welcome.quick.webui_unavailable',
];

describe('welcome translation keys', () => {
  it('zh dictionary has all welcome keys with non-empty values', () => {
    for (const key of welcomeKeys) {
      expect(zh[key], `zh missing key: ${key}`).toBeTruthy();
    }
  });

  it('en dictionary has all welcome keys with non-empty values', () => {
    for (const key of welcomeKeys) {
      expect(en[key], `en missing key: ${key}`).toBeTruthy();
    }
  });

  it('zh and en have identical key sets', () => {
    const zhKeys = Object.keys(zh).sort();
    const enKeys = Object.keys(en).sort();
    expect(zhKeys).toEqual(enKeys);
  });
});
