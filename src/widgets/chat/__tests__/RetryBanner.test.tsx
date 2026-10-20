// src/widgets/chat/__tests__/RetryBanner.test.tsx
// 2026-10-20: LLM 重试可视化 —— 横幅的次数/原因/倒计时/配色/进度点渲染。
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RetryInfo } from '../../../shared/api';
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

describe('RetryBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the attempt counter', () => {
    const { getByTestId } = render(<RetryBanner info={makeInfo()} />);
    expect(getByTestId('retry-banner').textContent).toContain('重试中 (1/3)');
  });

  it('renders the localized error reason', () => {
    const { getByTestId } = render(<RetryBanner info={makeInfo()} />);
    expect(getByTestId('retry-banner-reason').textContent).toContain('请求超时');
  });

  it('passes through unknown error types instead of hiding them', () => {
    const { getByTestId } = render(
      <RetryBanner info={makeInfo({ error_type: 'some_new_error' })} />,
    );
    expect(getByTestId('retry-banner-reason').textContent).toContain('some_new_error');
  });

  it('shows a countdown that ticks down', () => {
    const { getByTestId } = render(<RetryBanner info={makeInfo({ delay: 3 })} />);
    expect(getByTestId('retry-banner-countdown').textContent).toContain('3s');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(getByTestId('retry-banner-countdown').textContent).toContain('2s');
  });

  it('hides the countdown once it reaches zero', () => {
    const { queryByTestId } = render(<RetryBanner info={makeInfo({ delay: 1 })} />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(queryByTestId('retry-banner-countdown')).toBeNull();
  });

  it('color-codes transient failures as warning', () => {
    const { getByTestId } = render(<RetryBanner info={makeInfo({ error_type: 'rate_limited' })} />);
    expect(getByTestId('retry-banner').className).toContain('border-warning/30');
  });

  it('color-codes non-recoverable failures as error', () => {
    const { getByTestId } = render(<RetryBanner info={makeInfo({ error_type: 'auth_failed' })} />);
    expect(getByTestId('retry-banner').className).toContain('border-error/30');
  });

  it('renders one progress dot per max attempt', () => {
    const { getByTestId } = render(
      <RetryBanner info={makeInfo({ attempt: 2, max_attempts: 3 })} />,
    );
    const banner = getByTestId('retry-banner');
    const dots = banner.querySelectorAll('span.rounded-full');
    expect(dots.length).toBe(3);
    // 前 2 个已填充（bg-warning），最后一个空心（bg-border）
    expect(dots[0].className).toContain('bg-warning');
    expect(dots[1].className).toContain('bg-warning');
    expect(dots[2].className).toContain('bg-border');
  });

  it('exposes the raw backend error message as a title for troubleshooting', () => {
    const { getByTestId } = render(
      <RetryBanner info={makeInfo({ error_message: 'upstream said no' })} />,
    );
    expect(getByTestId('retry-banner-reason').getAttribute('title')).toBe('upstream said no');
  });
});
