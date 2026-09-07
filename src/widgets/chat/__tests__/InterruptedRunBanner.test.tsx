// src/widgets/chat/__tests__/InterruptedRunBanner.test.tsx
// L16 run 级崩溃恢复横幅: 渲染 + 重试/忽略回调。
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { INTERRUPTED_RUN_ERROR, InterruptedRunBanner } from '../InterruptedRunBanner';

describe('InterruptedRunBanner', () => {
  it('渲染中断文案与操作按钮', () => {
    render(<InterruptedRunBanner onRetry={() => undefined} onDismiss={() => undefined} />);
    expect(screen.getByTestId('interrupted-run-banner')).toBeInTheDocument();
    expect(screen.getByText(/上次运行被应用重启中断/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重发最后一条消息' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '忽略中断提示' })).toBeInTheDocument();
  });

  it('点击触发 onRetry / onDismiss', () => {
    const onRetry = vi.fn();
    const onDismiss = vi.fn();
    render(<InterruptedRunBanner onRetry={onRetry} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole('button', { name: '重发最后一条消息' }));
    fireEvent.click(screen.getByRole('button', { name: '忽略中断提示' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('恢复文案常量与后端 session_repo 恢复文案一致', () => {
    // backend/data/session_repo.py recover_stale_run_states 的 last_error 文案
    expect(INTERRUPTED_RUN_ERROR).toBe('应用重启，运行中断');
  });
});
