import { describe, expect, it } from 'vitest';

import {
  formatRetryBannerI18nJson,
  formatRetryBannerI18nSummary,
  retryBannerEn,
  retryBannerZh,
} from '../retryBanner';

describe('retryBanner i18n audit diagnostics', () => {
  // 2026-11-03: 11 → 17 keys（新增 backoff_hint / in_flight_hint / elapsed /
  // attempt_elapsed / attempt_timeout / source.compaction）
  it('formats retryBanner i18n summary with full parity', () => {
    expect(formatRetryBannerI18nSummary()).toBe('zh=17 · en=17 · parity=true');
    expect(Object.keys(retryBannerZh)).toEqual(Object.keys(retryBannerEn));
  });

  it('serializes retryBanner i18n audit JSON', () => {
    const parsed = JSON.parse(formatRetryBannerI18nJson());
    expect(parsed.zhCount).toBe(17);
    expect(parsed.enCount).toBe(17);
    expect(parsed.parity).toBe(true);
    expect(parsed.keys).toContain('chat.retry.in_progress');
    expect(parsed.keys).toContain('chat.retry.backoff_hint');
    expect(parsed.keys).toContain('chat.retry.in_flight_hint');
    expect(parsed.keys).toContain('chat.retry.source.compaction');
  });
});
