// src/widgets/chat/__tests__/Message.streaming.test.tsx
// P1 (UI 优化方案 2026-09-13): 流式反馈 — shimmer 占位 / 生成光标 / 未闭合围栏降级。
import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { THINKING_PLACEHOLDER } from '../../../features/send-message/thinkingPlaceholder';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const base: MessageType = {
  id: 'm1',
  session_id: 's1',
  role: 'assistant',
  content: '',
  created_at: 1,
};

function renderMessage(content: string, isStreaming = false) {
  return render(
    <I18nProvider>
      <Message message={{ ...base, content }} isStreaming={isStreaming} />
    </I18nProvider>,
  );
}

describe('Message streaming feedback (P1)', () => {
  it('renders shimmer placeholder instead of literal placeholder text', () => {
    const { queryByTestId, queryByText } = renderMessage(THINKING_PLACEHOLDER, true);
    expect(queryByTestId('thinking-shimmer')).not.toBeNull();
    // 哨兵文本不应作为 markdown 静态文本出现
    expect(queryByText(THINKING_PLACEHOLDER)).toBeNull();
  });

  it('renders blinking cursor while streaming real content', () => {
    const { queryByTestId } = renderMessage('正在生成的回答', true);
    expect(queryByTestId('stream-cursor')).not.toBeNull();
  });

  it('does not render cursor for finished messages', () => {
    const { queryByTestId } = renderMessage('已完成的回答', false);
    expect(queryByTestId('stream-cursor')).toBeNull();
  });

  it('degrades unclosed code fence to plain pre while streaming', () => {
    const { container } = renderMessage('```python\nprint(1)', true);
    // 未闭合围栏: 不触发 Shiki 高亮 DOM, 代码原样在 <pre><code> 里
    expect(container.querySelector('.shiki')).toBeNull();
    const pre = container.querySelector('pre');
    expect(pre).not.toBeNull();
    expect(pre!.textContent).toContain('print(1)');
  });

  it('renders closed code fence normally when streaming', () => {
    const { container } = renderMessage('前文。\n\n```python\nprint(1)\n```\n', true);
    expect(container.querySelector('pre')).not.toBeNull();
    expect(container.textContent).toContain('前文');
  });
});
