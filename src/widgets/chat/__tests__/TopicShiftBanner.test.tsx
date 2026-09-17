// src/widgets/chat/__tests__/TopicShiftBanner.test.tsx
// Task 11 (2026-09-17): topic shift 横幅 — 渲染 + 自动消失 + 恢复/忽略回调。
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    retreatSegment: vi.fn(),
  },
}));

import { sessionApi } from '../../../shared/api/sessionApi';
import { TopicShiftBanner } from '../TopicShiftBanner';

describe('TopicShiftBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(sessionApi.retreatSegment).mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('渲染检测提示与操作按钮', () => {
    render(
      <TopicShiftBanner
        sessionId="s-1"
        reason="explicit_signal"
        onRetreat={() => undefined}
      />,
    );
    expect(screen.getByTestId('topic-shift-banner')).toBeInTheDocument();
    expect(screen.getByText(/检测到新话题/)).toBeInTheDocument();
    expect(screen.getByText(/explicit_signal/)).toBeInTheDocument();
    expect(screen.getByTestId('topic-shift-retreat')).toBeInTheDocument();
    expect(screen.getByTestId('topic-shift-dismiss')).toBeInTheDocument();
  });

  it('省略 reason 时只显示基础提示', () => {
    render(<TopicShiftBanner sessionId="s-1" reason="" onRetreat={() => undefined} />);
    expect(screen.getByText(/检测到新话题/)).toBeInTheDocument();
    // 不应附带括号注释
    expect(screen.queryByText(/（/)).toBeNull();
  });

  it('10s 后自动消失', () => {
    render(<TopicShiftBanner sessionId="s-1" reason="r" onRetreat={() => undefined} />);
    expect(screen.getByTestId('topic-shift-banner')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.queryByTestId('topic-shift-banner')).toBeNull();
  });

  it('点 × 立即消失,不调 retreat', () => {
    render(<TopicShiftBanner sessionId="s-1" reason="r" onRetreat={() => undefined} />);
    fireEvent.click(screen.getByTestId('topic-shift-dismiss'));
    expect(screen.queryByTestId('topic-shift-banner')).toBeNull();
    expect(sessionApi.retreatSegment).not.toHaveBeenCalled();
  });

  it('点恢复按钮调 retreat + 触发 onRetreat + 横幅消失', async () => {
    const onRetreat = vi.fn();
    render(<TopicShiftBanner sessionId="s-1" reason="r" onRetreat={onRetreat} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('topic-shift-retreat'));
      // 等待 retreatSegment 的 Promise 链 resolve
      await vi.runOnlyPendingTimersAsync();
    });
    expect(sessionApi.retreatSegment).toHaveBeenCalledWith('s-1');
    expect(onRetreat).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('topic-shift-banner')).toBeNull();
  });
});
