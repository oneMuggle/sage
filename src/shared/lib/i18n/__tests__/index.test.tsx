import { afterEach, describe, expect, it } from 'vitest';

import { formatI18nProviderJson, formatI18nProviderSummary, translateStatic } from '../index';

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

describe('translateStatic', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('无持久化 locale 时默认中文', () => {
    expect(translateStatic('chat.retry.in_progress')).toContain('重试中');
  });

  it('读取 Provider 持久化的英文 locale', () => {
    localStorage.setItem('sage.locale', 'en');
    expect(translateStatic('chat.retry.in_progress')).toContain('Retrying');
  });

  it('未知 key 原样返回，便于暴露缺词', () => {
    expect(translateStatic('missing.key' as never)).toBe('missing.key');
  });
});
