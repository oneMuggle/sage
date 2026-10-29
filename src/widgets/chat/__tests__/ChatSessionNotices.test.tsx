// src/widgets/chat/__tests__/ChatSessionNotices.test.tsx
// Issue 1 (2026-10-29): 会话级通知组装 —— 失败横幅 / 中断横幅 / 错误横幅 / 话题切换横幅。
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { Message } from '../../../shared/lib/store';
import { ChatSessionNotices } from '../ChatSessionNotices';
import { INTERRUPTED_RUN_ERROR } from '../InterruptedRunBanner';

// sonner toast 在 retryLastUserMessage 找不到最后一条 user 消息时会弹，
// 测试里 mock 掉避免副作用。
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

const BASE_PROPS = {
  currentSessionId: 'sess-1' as string | null,
  currentSession: undefined as { run_status?: string | null; last_error?: string | null } | undefined,
  error: null as string | null,
  errorSessionId: null as string | null,
  messages: [] as Message[],
  shiftInfo: null as { reason: string } | null,
  isLoading: false,
  onClearError: vi.fn(),
  onSendMessage: vi.fn(),
  onRetreat: vi.fn(),
};

const USER_MSG: Message = {
  id: 'u1',
  role: 'user',
  content: 'hello',
  created_at: 0,
  session_id: 'sess-1',
};

function resetProps() {
  BASE_PROPS.error = null;
  BASE_PROPS.errorSessionId = null;
  BASE_PROPS.currentSession = undefined;
  BASE_PROPS.messages = [];
  BASE_PROPS.shiftInfo = null;
  BASE_PROPS.isLoading = false;
  (BASE_PROPS.onClearError as unknown as ReturnType<typeof vi.fn>).mockClear();
  (BASE_PROPS.onSendMessage as unknown as ReturnType<typeof vi.fn>).mockClear();
  (BASE_PROPS.onRetreat as unknown as ReturnType<typeof vi.fn>).mockClear();
}

describe('ChatSessionNotices — 会话失败横幅 (Issue 1)', () => {
  beforeEach(() => {
    resetProps();
  });

  it('run_status=failed 且 last_error 非空非中断文案时显示横幅', () => {
    render(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSession={{ run_status: 'failed', last_error: 'max_iterations_exceeded' }}
      />,
    );
    expect(screen.getByTestId('session-failed-banner')).toBeInTheDocument();
  });

  it('last_error 为 INTERRUPTED_RUN_ERROR 时不显示失败横幅（交给中断横幅）', () => {
    render(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSession={{ run_status: 'failed', last_error: INTERRUPTED_RUN_ERROR }}
      />,
    );
    expect(screen.queryByTestId('session-failed-banner')).not.toBeInTheDocument();
    expect(screen.getByTestId('interrupted-run-banner')).toBeInTheDocument();
  });

  it('last_error 为空串时不显示失败横幅', () => {
    render(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSession={{ run_status: 'failed', last_error: '' }}
      />,
    );
    expect(screen.queryByTestId('session-failed-banner')).not.toBeInTheDocument();
  });

  it('run_status 非 failed 时不显示失败横幅', () => {
    render(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSession={{ run_status: 'completed', last_error: 'max_iterations_exceeded' }}
      />,
    );
    expect(screen.queryByTestId('session-failed-banner')).not.toBeInTheDocument();
  });

  it('点击"关闭"隐藏横幅；切到别的会话再切回来时重新出现', () => {
    const { rerender } = render(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSessionId="sess-1"
        currentSession={{ run_status: 'failed', last_error: 'some_error' }}
      />,
    );
    fireEvent.click(screen.getByTestId('session-failed-dismiss'));
    expect(screen.queryByTestId('session-failed-banner')).not.toBeInTheDocument();

    // 切到 sess-2：不同会话的忽略互不影响
    rerender(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSessionId="sess-2"
        currentSession={{ run_status: 'failed', last_error: 'other_error' }}
      />,
    );
    expect(screen.getByTestId('session-failed-banner')).toBeInTheDocument();

    // 切回 sess-1：dismiss 状态按会话重置，横幅重新出现
    rerender(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSessionId="sess-1"
        currentSession={{ run_status: 'failed', last_error: 'some_error' }}
      />,
    );
    expect(screen.getByTestId('session-failed-banner')).toBeInTheDocument();
  });
});

describe('ChatSessionNotices — 重试最后一条 user 消息', () => {
  beforeEach(() => {
    resetProps();
  });

  it('点击"重新发送"调用 onSendMessage(content, sessionId)', () => {
    render(
      <ChatSessionNotices
        {...BASE_PROPS}
        currentSession={{ run_status: 'failed', last_error: 'some_error' }}
        messages={[USER_MSG]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '重新发送' }));
    expect(BASE_PROPS.onSendMessage).toHaveBeenCalledWith('hello', 'sess-1');
  });

  it('临时错误横幅的"重试"也带上 sessionId', () => {
    render(
      <ChatSessionNotices
        {...BASE_PROPS}
        error="网络错误"
        errorSessionId="sess-1"
        messages={[USER_MSG]}
      />,
    );
    fireEvent.click(screen.getByTestId('chat-error-retry'));
    expect(BASE_PROPS.onSendMessage).toHaveBeenCalledWith('hello', 'sess-1');
  });
});
