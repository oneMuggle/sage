// 对话阅读导航 A1/A2: MessageList 消费"定位到消息"请求 ——
// 尾窗外扩窗、标题精确定位、同步粘底状态、短暂高亮、等待消息加载、TTL 过期。
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  MESSAGE_JUMP_TTL_MS,
  requestMessageJump,
  useMessageJumpStore,
} from '../../../features/chat/messageJumpStore';
import { JUMP_FLASH_MS } from '../../../features/chat/useMessageJump';
import type { Message as MessageType } from '../../../shared/lib/store';
import { MessageList } from '../MessageList';

vi.mock('../Message', () => ({
  Message: ({ message }: { message: { id: string; content: string } }) => (
    <div data-testid={`msg-${message.id}`}>
      {message.content
        .split('\n')
        .map((line, i) =>
          line.startsWith('## ') ? (
            <h2 key={i}>{line.slice(3).replace(/\*/g, '')}</h2>
          ) : (
            <p key={i}>{line}</p>
          ),
        )}
    </div>
  ),
}));

vi.mock('../../../features/chat', () => ({
  BtwOverlay: () => null,
}));

function makeMessages(n: number, prefix = 'm'): MessageType[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `${prefix}${i + 1}`,
    session_id: 's1',
    role: i % 2 === 0 ? ('user' as const) : ('assistant' as const),
    content: `内容 ${i + 1}`,
    created_at: i,
  }));
}

const scrolled: Element[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
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

describe('MessageList jump-to-message (A1)', () => {
  it('expands the tail window to reach an older message, scrolls and flashes it', () => {
    render(<MessageList messages={makeMessages(150)} />);
    expect(screen.queryByTestId('msg-m5')).toBeNull();

    act(() => {
      requestMessageJump({ messageId: 'm5' });
    });
    flushFrame();

    const wrapper = document.querySelector('[data-message-id="m5"]') as HTMLElement;
    expect(wrapper).not.toBeNull();
    expect(scrolled).toEqual([wrapper]);
    expect(wrapper).toHaveAttribute('data-jump-flash', 'true');
    expect(useMessageJumpStore.getState().pending).toBeNull();
    // 窗口固化：m5 之前还剩 4 条未渲染
    expect(screen.getByTestId('load-earlier')).toHaveTextContent(/还有 4 条/);

    act(() => {
      vi.advanceTimersByTime(JUMP_FLASH_MS);
    });
    expect(wrapper).not.toHaveAttribute('data-jump-flash');
    expect(screen.getByTestId('msg-m5')).toBeInTheDocument();
  });

  it('scrolls to the matching heading inside the message (A2)', () => {
    const messages = makeMessages(3);
    messages[1] = { ...messages[1], content: '导语\n## 背景\n## **实现** 细节' };
    render(<MessageList messages={messages} />);

    act(() => {
      requestMessageJump({ messageId: 'm2', headingText: '**实现** 细节', headingIndex: 1 });
    });
    flushFrame();

    expect(scrolled).toHaveLength(1);
    expect(scrolled[0].tagName).toBe('H2');
    expect(scrolled[0].textContent).toBe('实现 细节');
  });

  it('falls back to the heading index, then to the message itself', () => {
    const messages = makeMessages(2);
    messages[0] = { ...messages[0], content: '## 第一节\n## 第二节' };
    render(<MessageList messages={messages} />);

    act(() => {
      requestMessageJump({ messageId: 'm1', headingText: '已改名的标题', headingIndex: 1 });
    });
    flushFrame();
    expect(scrolled[0].textContent).toBe('第二节');

    act(() => {
      requestMessageJump({ messageId: 'm1', headingText: '不存在', headingIndex: 9 });
    });
    flushFrame();
    expect(scrolled[1]).toBe(document.querySelector('[data-message-id="m1"]'));
  });

  it('syncs the sticky-bottom state by dispatching scroll on the scroll container', () => {
    const onScroll = vi.fn();
    render(
      <div style={{ overflowY: 'auto' }} data-testid="scroller">
        <MessageList messages={makeMessages(3)} />
      </div>,
    );
    screen.getByTestId('scroller').addEventListener('scroll', onScroll);

    act(() => {
      requestMessageJump({ messageId: 'm1' });
    });
    flushFrame();
    expect(onScroll).toHaveBeenCalledTimes(1);
  });

  it('waits for the target to be loaded (cross-session jump)', () => {
    const { rerender } = render(<MessageList messages={makeMessages(3)} />);
    act(() => {
      requestMessageJump({ messageId: 'x2' });
    });
    flushFrame();
    expect(scrolled).toHaveLength(0);
    expect(useMessageJumpStore.getState().pending?.messageId).toBe('x2');

    rerender(<MessageList messages={makeMessages(3, 'x')} />);
    flushFrame();
    expect(scrolled).toEqual([document.querySelector('[data-message-id="x2"]')]);
    expect(useMessageJumpStore.getState().pending).toBeNull();
  });

  it('drops a request whose target never shows up once the TTL passes', () => {
    render(<MessageList messages={makeMessages(3)} />);
    act(() => {
      requestMessageJump({ messageId: 'gone' });
    });
    act(() => {
      vi.advanceTimersByTime(MESSAGE_JUMP_TTL_MS);
    });
    expect(useMessageJumpStore.getState().pending).toBeNull();
    expect(scrolled).toHaveLength(0);
  });
});
