// 对话阅读体验第二轮：MessageList 接线 —— B3 搜索命中高亮、B4 查找定位与查找栏挂载、
// B2「继续生成」只交给最后一条消息。
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { dispatchFindShortcut } from '../../../features/chat/chatFind';
import { requestMessageJump, useMessageJumpStore } from '../../../features/chat/messageJumpStore';
import {
  FIND_CURRENT_HIGHLIGHT,
  FIND_HIGHLIGHT,
  SEARCH_HIT_HIGHLIGHT,
} from '../../../features/chat/textHighlight';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { MessageList } from '../MessageList';

vi.mock('../Message', () => ({
  Message: ({
    message,
    onContinue,
  }: {
    message: { id: string; content: string };
    onContinue?: () => void;
  }) => (
    <div data-testid={`msg-${message.id}`}>
      <div data-quote-scope="message-body">
        <p>{message.content}</p>
      </div>
      {onContinue && (
        <button type="button" data-testid={`continue-${message.id}`} onClick={onContinue} />
      )}
    </div>
  ),
}));

vi.mock('../../../features/chat', () => ({
  BtwOverlay: () => null,
}));

class FakeHighlight {
  ranges: Range[];
  priority = 0;
  constructor(...ranges: Range[]) {
    this.ranges = ranges;
  }
}

const messages: MessageType[] = [
  { id: 'm1', session_id: 's1', role: 'user', content: 'foo 在哪里', created_at: 1 },
  { id: 'm2', session_id: 's1', role: 'assistant', content: 'alpha beta', created_at: 2 },
  { id: 'm3', session_id: 's1', role: 'assistant', content: 'foo 与 foo', created_at: 3 },
];

let registry: Map<string, FakeHighlight>;
const scrolled: Element[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
  registry = new Map();
  vi.stubGlobal('Highlight', FakeHighlight);
  vi.stubGlobal('CSS', { highlights: registry });
  scrolled.length = 0;
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this);
  };
  useMessageJumpStore.setState({ pending: null });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  // @ts-expect-error -- jsdom 原生没有 scrollIntoView，测试结束移除桩
  delete Element.prototype.scrollIntoView;
});

function flushFrame() {
  act(() => {
    vi.advanceTimersByTime(1);
  });
}

describe('MessageList — reading round 2', () => {
  it('B3: a search-hit jump highlights the query in the target and still flashes it', () => {
    render(<MessageList messages={messages} />);
    act(() => {
      requestMessageJump({ messageId: 'm2', highlightQuery: 'beta' });
    });
    flushFrame();

    const wrapper = document.querySelector('[data-message-id="m2"]');
    expect(wrapper).toHaveAttribute('data-jump-flash', 'true');
    expect(registry.get(SEARCH_HIT_HIGHLIGHT)?.ranges.map((r) => r.toString())).toEqual(['beta']);
    // jsdom 没有 Range 几何信息 → 回退为元素级滚动
    expect(scrolled).toEqual([wrapper]);
  });

  it('B4: a find jump marks all matches, emphasises the current one and skips the flash', () => {
    render(<MessageList messages={messages} />);
    act(() => {
      requestMessageJump({ messageId: 'm3', highlightQuery: 'foo', highlightIndex: 1 });
    });
    flushFrame();

    expect(document.querySelector('[data-message-id="m3"]')).not.toHaveAttribute('data-jump-flash');
    expect(registry.get(FIND_HIGHLIGHT)?.ranges).toHaveLength(3);
    const current = registry.get(FIND_CURRENT_HIGHLIGHT)?.ranges[0];
    expect(current?.startContainer.textContent).toBe('foo 与 foo');
    expect(current?.startOffset).toBe(6);
    expect(useMessageJumpStore.getState().pending).toBeNull();
  });

  it('B4: Ctrl+F opens the find bar only when the conversation has messages', () => {
    const { rerender } = render(
      <I18nProvider defaultLocale="zh">
        <MessageList messages={[]} />
      </I18nProvider>,
    );
    expect(dispatchFindShortcut(false)).toBe(false);

    rerender(
      <I18nProvider defaultLocale="zh">
        <MessageList messages={messages} />
      </I18nProvider>,
    );
    act(() => {
      dispatchFindShortcut(false);
    });
    expect(screen.getByTestId('chat-find-bar')).toBeInTheDocument();
  });

  it('B2: passes onContinue to the last message only, and not while streaming', () => {
    const onContinue = vi.fn();
    const { rerender } = render(<MessageList messages={messages} onContinue={onContinue} />);
    expect(screen.queryByTestId('continue-m1')).toBeNull();
    expect(screen.queryByTestId('continue-m2')).toBeNull();
    fireEvent.click(screen.getByTestId('continue-m3'));
    expect(onContinue).toHaveBeenCalledTimes(1);

    rerender(<MessageList messages={messages} onContinue={onContinue} streamingMessageId="m3" />);
    expect(screen.queryByTestId('continue-m3')).toBeNull();
  });
});
