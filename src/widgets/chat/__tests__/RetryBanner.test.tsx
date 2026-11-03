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

  it('shows the remaining total-budget when the backend reports it', () => {
    const { getByTestId } = renderBanner(
      makeInfo({ budget_total_s: 180, budget_remaining_s: 140 }),
    );
    expect(getByTestId('retry-banner-budget').textContent).toContain('剩余预算 140 秒');
  });

  it('hides the budget line when the backend omits budget fields', () => {
    const { queryByTestId } = renderBanner(makeInfo());
    expect(queryByTestId('retry-banner-budget')).toBeNull();
  });

  it('formats RetryBanner audit summary and JSON (Phase P119)', async () => {
    const { formatRetryBannerSummary, formatRetryBannerJson } = await import('../RetryBanner');
    const info = makeInfo({
      attempt: 2,
      max_attempts: 3,
      error_type: 'timeout',
      delay: 4,
      phase: 'in_flight',
      elapsed_s: 12,
      attempt_timeout_s: 86,
      budget_total_s: 180,
      budget_remaining_s: 113,
    });
    expect(formatRetryBannerSummary(info)).toBe(
      'attempt=2/3 · type=timeout · severity=warning · delay=4s · phase=in_flight · elapsed=12s · timeout=86s · budget=113s',
    );
    expect(JSON.parse(formatRetryBannerJson(info))).toEqual({
      attempt: 2,
      maxAttempts: 3,
      errorType: 'timeout',
      severity: 'warning',
      delay: 4,
      phase: 'in_flight',
      elapsedS: 12,
      attemptTimeoutS: 86,
      budgetTotalS: 180,
      budgetRemainingS: 113,
      source: null,
    });
  });

  // 2026-11-03: 双阶段渲染 —— in_flight 阶段用 Loader2 图标 + 在途提示 + 单次上限
  it('renders Loader2 spinner and in-flight hint when phase is in_flight', () => {
    const { getByTestId, queryByTestId, container } = renderBanner(
      makeInfo({
        phase: 'in_flight',
        attempt_timeout_s: 86,
        elapsed_s: 12,
        budget_total_s: 180,
        budget_remaining_s: 113,
      }),
    );
    // 横幅 data-phase 属性标记 in_flight
    expect(getByTestId('retry-banner').getAttribute('data-phase')).toBe('in_flight');
    // in_flight 阶段副标题 = "重试请求已发出"（非倒计时）
    expect(getByTestId('retry-banner-subtitle').textContent).toContain('重试请求已发出');
    // 单次上限字段
    expect(getByTestId('retry-banner-attempt-timeout').textContent).toContain('单次上限 86 秒');
    // 累计已等待
    expect(getByTestId('retry-banner-elapsed').textContent).toContain('已等待 12 秒');
    // 预算
    expect(getByTestId('retry-banner-budget').textContent).toContain('剩余预算 113 秒');
    // 退避期倒计时字段不应出现在 in_flight
    expect(queryByTestId('retry-banner-countdown')).toBeNull();
    void container;
  });

  // 2026-11-03: 退避期保留原 countdown 显示
  it('keeps the countdown in backoff phase and hides attempt-timeout fields', () => {
    const { getByTestId, queryByTestId } = renderBanner(makeInfo({ phase: 'backoff', delay: 5 }));
    expect(getByTestId('retry-banner').getAttribute('data-phase')).toBe('backoff');
    expect(getByTestId('retry-banner-countdown')).toBeInTheDocument();
    expect(getByTestId('retry-banner-subtitle').textContent).toContain('将在');
    expect(queryByTestId('retry-banner-attempt-elapsed')).toBeNull();
    expect(queryByTestId('retry-banner-attempt-timeout')).toBeNull();
  });

  // 2026-11-03: 累计已等待必须是"活的" —— 后端快照是事件时刻的值，
  // 叠加本地计时后数字才随时间推进（否则在途 60s 里数字完全静止）。
  it('advances the cumulative elapsed counter over time', () => {
    const { getByTestId } = renderBanner(makeInfo({ phase: 'in_flight', elapsed_s: 10 }));
    expect(getByTestId('retry-banner-elapsed').textContent).toContain('已等待 10 秒');

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(getByTestId('retry-banner-elapsed').textContent).toContain('已等待 13 秒');
  });

  // 2026-11-03: source 字段 —— compaction 来源时显示"正在压缩上下文"前缀
  it('renders compaction source label when info.source is compaction', () => {
    const { getByTestId } = renderBanner(makeInfo({ source: 'compaction' }));
    expect(getByTestId('retry-banner-source').textContent).toContain('正在压缩上下文');
  });

  // 2026-11-03: phase 默认为 backoff（旧后端未推送 phase 字段时）
  it('defaults to backoff phase when info.phase is omitted', () => {
    const info = makeInfo();
    delete (info as { phase?: string }).phase;
    const { getByTestId } = renderBanner(info);
    expect(getByTestId('retry-banner').getAttribute('data-phase')).toBe('backoff');
  });
});
