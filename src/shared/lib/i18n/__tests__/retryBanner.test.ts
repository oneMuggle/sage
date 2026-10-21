import { describe, expect, it } from 'vitest';

import {
  formatRetryBannerI18nJson,
  formatRetryBannerI18nSummary,
  retryBannerEn,
  retryBannerZh,
} from '../retryBanner';

describe('retryBanner i18n audit diagnostics', () => {
  it('formats retryBanner i18n summary with full parity', () => {
    expect(formatRetryBannerI18nSummary()).toBe('zh=10 · en=10 · parity=true');
    expect(Object.keys(retryBannerZh)).toEqual(Object.keys(retryBannerEn));
  });

  it('serializes retryBanner i18n audit JSON', () => {
    const parsed = JSON.parse(formatRetryBannerI18nJson());
    expect(parsed.zhCount).toBe(10);
    expect(parsed.enCount).toBe(10);
    expect(parsed.parity).toBe(true);
    expect(parsed.keys).toContain('chat.retry.in_progress');
  });
});
