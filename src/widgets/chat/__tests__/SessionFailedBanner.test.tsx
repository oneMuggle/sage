// src/widgets/chat/__tests__/SessionFailedBanner.test.tsx
// Issue 1 (2026-10-29): 会话失败横幅 —— 渲染、错误码翻译、回调。
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import {
  auditSessionFailedBannerGovernance,
  formatSessionFailedReason,
  SessionFailedBanner,
} from '../SessionFailedBanner';

describe('formatSessionFailedReason', () => {
  it('已知错误码翻译为中文', () => {
    // 后端 agent.py 抛 max_iterations_exceeded 时落库字符串形如
    // "max_iterations_exceeded (limit=25)"，mapAgentErrorToText 会展开上限值
    expect(formatSessionFailedReason('max_iterations_exceeded (limit=25)')).toContain('25');
  });

  it('未知错误码回退原文', () => {
    expect(formatSessionFailedReason('some_future_error')).toBe('some_future_error');
  });

  it('空串/空白回退到兜底文案', () => {
    expect(formatSessionFailedReason('')).toBe('未知原因');
    expect(formatSessionFailedReason('   ')).toBe('未知原因');
  });
});

describe('SessionFailedBanner', () => {
  it('渲染失败原因与两个操作按钮', () => {
    render(
      <SessionFailedBanner
        reason="max_iterations_exceeded (limit=10)"
        onRetry={() => undefined}
        onDismiss={() => undefined}
      />,
    );
    expect(screen.getByTestId('session-failed-banner')).toBeInTheDocument();
    expect(screen.getByText('会话失败')).toBeInTheDocument();
    // 上限值 10 在翻译文本里
    expect(screen.getByText(/10/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新发送' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '忽略失败提示' })).toBeInTheDocument();
    // role=alert 供辅助技术
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('点击"重新发送"/"关闭"触发对应回调', () => {
    const onRetry = vi.fn();
    const onDismiss = vi.fn();
    render(
      <SessionFailedBanner
        reason="tool_budget_exceeded (limit=100)"
        onRetry={onRetry}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '重新发送' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '忽略失败提示' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

describe('auditSessionFailedBannerGovernance', () => {
  it('返回确定性的 governance 审计载荷', () => {
    const payload = JSON.parse(auditSessionFailedBannerGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('session-failed-banner');
    expect(payload.phase).toBe('P195');
    expect(payload.audited).toBe(true);
  });
});
