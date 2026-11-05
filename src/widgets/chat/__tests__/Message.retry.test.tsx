// src/widgets/chat/__tests__/Message.retry.test.tsx
// 2026-10-20: LLM 重试可视化 —— store → Message.tsx → RetryBanner 的集成链路。
// 覆盖「retry 事件到达时显示横幅」「非 retry 状态到达时立即消失」
// 「只挂在正在流式的那条消息上」「重试期间抑制 shimmer 占位」。
// 2026-11-03: 清除时机从「延迟 3 秒」改为「立即消失」（reasoning 事件会反复
// 重置旧定时器，导致横幅永不消失）。
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

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

  // 2026-11-03: 即时消失 —— 旧逻辑是 3 秒延迟隐藏，会被 reasoning 事件反复
  // 重设定时器导致横幅永不消失。修复为 setStreamingMeta 非 retry 状态立即清空 retryInfo。
  it('drops the banner immediately when a non-retry state arrives', () => {
    act(() => {
      const store = useChatStreamStore.getState();
      store.startStream(SESSION, 'm1');
      store.setRetryInfo(SESSION, 'm1', retryInfo);
      store.setStreamingMeta(SESSION, 'm1', { state: 'retry' });
    });

    const { rerender } = renderAssistant(THINKING_PLACEHOLDER);
    expect(screen.getByTestId('retry-banner')).toBeInTheDocument();

    // content_delta 到达 → setStreamingMeta 立即清空 retryInfo
    act(() => {
      useChatStreamStore.getState().setStreamingMeta(SESSION, 'm1', { state: 'acting' });
    });
    rerender(
      <I18nProvider defaultLocale="zh">
        <Message message={{ ...base, content: '恢复后的回答' }} isStreaming={true} />
      </I18nProvider>,
    );

    // 横幅立即消失，不再保留 3 秒
    expect(screen.queryByTestId('retry-banner')).toBeNull();
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
