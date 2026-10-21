// src/widgets/chat/__tests__/RetryBanner.test.tsx
// 2026-10-20: LLM 重试可视化 —— 横幅的次数/原因/倒计时/配色/进度点渲染。
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RetryInfo } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import { RetryBanner } from '../RetryBanner';

function makeInfo(overrides: Partial<RetryInfo> = {}): RetryInfo {
  return {
    attempt: 1,
    max_attempts: 3,
    error_type: 'timeout',
    error_message: 'Request timed out after 120s',
    delay: 2,
    ...overrides,
  };
}

function renderBanner(info: RetryInfo, locale: 'zh' | 'en' = 'zh') {
  return render(
    <I18nProvider defaultLocale={locale}>
      <RetryBanner info={info} />
    </I18nProvider>,
  );
}

describe('RetryBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the attempt counter', () => {
    const { getByTestId } = renderBanner(makeInfo());
    expect(getByTestId('retry-banner').textContent).toContain('重试中 (1/3)');
  });

  it('renders the localized error reason', () => {
    const { getByTestId } = renderBanner(makeInfo());
    expect(getByTestId('retry-banner-reason').textContent).toContain('请求超时');
  });

  it('passes through unknown error types instead of hiding them', () => {
    const { getByTestId } = renderBanner(makeInfo({ error_type: 'some_new_error' }));
    expect(getByTestId('retry-banner-reason').textContent).toContain('some_new_error');
  });

  it('shows a countdown that ticks down', () => {
    const { getByTestId } = renderBanner(makeInfo({ delay: 3 }));
    expect(getByTestId('retry-banner-countdown').textContent).toContain('3 秒');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(getByTestId('retry-banner-countdown').textContent).toContain('2 秒');
  });

  it('hides the countdown once it reaches zero', () => {
    const { queryByTestId } = renderBanner(makeInfo({ delay: 1 }));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(queryByTestId('retry-banner-countdown')).toBeNull();
  });

  it('color-codes transient failures as warning', () => {
    const { getByTestId } = renderBanner(makeInfo({ error_type: 'rate_limited' }));
    expect(getByTestId('retry-banner').className).toContain('border-warning/30');
  });

  it('color-codes non-recoverable failures as error', () => {
    const { getByTestId } = renderBanner(makeInfo({ error_type: 'auth_failed' }));
    expect(getByTestId('retry-banner').className).toContain('border-error/30');
  });

  it('renders one progress dot per max attempt', () => {
    const { getByTestId } = renderBanner(makeInfo({ attempt: 2, max_attempts: 3 }));
    const banner = getByTestId('retry-banner');
    const dots = banner.querySelectorAll('span.rounded-full');
    expect(dots.length).toBe(3);
    // 前 2 个已填充（bg-warning），最后一个空心（bg-border）
    expect(dots[0].className).toContain('bg-warning');
    expect(dots[1].className).toContain('bg-warning');
    expect(dots[2].className).toContain('bg-border');
  });

  it('exposes the raw backend error message as a title for troubleshooting', () => {
    const { getByTestId } = renderBanner(makeInfo({ error_message: 'upstream said no' }));
    expect(getByTestId('retry-banner-reason').getAttribute('title')).toBe('upstream said no');
  });

  it('renders English labels when locale is en', () => {
    const { getByTestId } = renderBanner(makeInfo(), 'en');
    expect(getByTestId('retry-banner').textContent).toContain('Retrying (1/3)');
    expect(getByTestId('retry-banner-reason').textContent).toContain('Request timed out');
  });

  it('formats RetryBanner audit summary and JSON (Phase P119)', async () => {
    const { formatRetryBannerSummary, formatRetryBannerJson } = await import('../RetryBanner');
    const info = makeInfo({ attempt: 2, max_attempts: 3, error_type: 'timeout', delay: 4 });
    expect(formatRetryBannerSummary(info)).toBe(
      'attempt=2/3 · type=timeout · severity=warning · delay=4s',
    );
    expect(JSON.parse(formatRetryBannerJson(info))).toEqual({
      attempt: 2,
      maxAttempts: 3,
      errorType: 'timeout',
      severity: 'warning',
      delay: 4,
    });
  });
});
