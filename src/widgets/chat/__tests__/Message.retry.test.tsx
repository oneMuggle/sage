// src/widgets/chat/__tests__/Message.retry.test.tsx
// 2026-10-20: LLM 重试可视化 —— store → Message.tsx → RetryBanner 的集成链路。
// 覆盖「retry 事件到达时显示横幅」「非 retry 状态到达时延迟 3 秒后自动消失」
// 「只挂在正在流式的那条消息上」「重试期间抑制 shimmer 占位」。
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { THINKING_PLACEHOLDER } from '../../../features/send-message/thinkingPlaceholder';
import type { RetryInfo } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const SESSION = 's1';

const retryInfo: RetryInfo = {
  attempt: 1,
  max_attempts: 3,
  error_type: 'timeout',
  error_message: '请求 LLM 超时',
  delay: 0,
};

const base: MessageType = {
  id: 'm1',
  session_id: SESSION,
  role: 'assistant',
  content: '',
  created_at: 1,
};

function renderAssistant(content: string, messageId = 'm1') {
  return render(
    <I18nProvider defaultLocale="zh">
      <Message message={{ ...base, id: messageId, content }} isStreaming={true} />
    </I18nProvider>,
  );
}

describe('Message — LLM 重试横幅集成', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} } as never);
  });

  afterEach(() => {
    cleanup();
    useChatStreamStore.setState({ sessions: {} } as never);
  });

  it('renders the retry banner when the stream slot carries retryInfo', () => {
    act(() => {
      const store = useChatStreamStore.getState();
      store.startStream(SESSION, 'm1');
      store.setRetryInfo(SESSION, 'm1', retryInfo);
    });

    act(() => {
      renderAssistant(THINKING_PLACEHOLDER);
    });

    const banner = screen.getByTestId('retry-banner');
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain('重试中 (1/3)');
  });

  it('suppresses the thinking shimmer while retrying', () => {
    act(() => {
      const store = useChatStreamStore.getState();
      store.startStream(SESSION, 'm1');
      store.setRetryInfo(SESSION, 'm1', retryInfo);
    });

    act(() => {
      renderAssistant(THINKING_PLACEHOLDER);
    });

    expect(screen.queryByTestId('thinking-shimmer')).toBeNull();
  });

  it('does not render the banner on a different message of the same session', () => {
    act(() => {
      const store = useChatStreamStore.getState();
      store.startStream(SESSION, 'm1');
      store.setRetryInfo(SESSION, 'm1', retryInfo);
    });

    renderAssistant(THINKING_PLACEHOLDER, 'm-other');

    expect(screen.queryByTestId('retry-banner')).toBeNull();
  });

  it('drops the banner 3 seconds after a non-retry state arrives', () => {
    vi.useFakeTimers();
    try {
      act(() => {
        const store = useChatStreamStore.getState();
        store.startStream(SESSION, 'm1');
        store.setRetryInfo(SESSION, 'm1', retryInfo);
        store.setStreamingMeta(SESSION, 'm1', { state: 'retry' });
      });

      const { rerender } = renderAssistant(THINKING_PLACEHOLDER);
      expect(screen.getByTestId('retry-banner')).toBeInTheDocument();

      // content_delta 到达 → setStreamingMeta 触发 3 秒延迟隐藏
      act(() => {
        useChatStreamStore.getState().setStreamingMeta(SESSION, 'm1', { state: 'acting' });
      });
      rerender(
        <I18nProvider defaultLocale="zh">
          <Message message={{ ...base, content: '恢复后的回答' }} isStreaming={true} />
        </I18nProvider>,
      );

      // 3 秒内横幅仍然可见
      expect(screen.getByTestId('retry-banner')).toBeInTheDocument();

      // 推进 3 秒后定时器触发，retryInfo 清 null，横幅消失
      act(() => {
        vi.advanceTimersByTime(3000);
      });
      rerender(
        <I18nProvider defaultLocale="zh">
          <Message message={{ ...base, content: '恢复后的回答' }} isStreaming={true} />
        </I18nProvider>,
      );
      expect(screen.queryByTestId('retry-banner')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders no banner for a non-streaming assistant message', () => {
    act(() => {
      const store = useChatStreamStore.getState();
      store.startStream(SESSION, 'm1');
      store.setRetryInfo(SESSION, 'm1', retryInfo);
    });

    render(
      <I18nProvider defaultLocale="zh">
        <Message message={{ ...base, content: '已完成的回答' }} isStreaming={false} />
      </I18nProvider>,
    );

    expect(screen.queryByTestId('retry-banner')).toBeNull();
  });
});
