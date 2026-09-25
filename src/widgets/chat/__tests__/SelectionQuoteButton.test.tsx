// 对话阅读导航 A4: 划词引用浮动按钮。
import { act, fireEvent, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { SelectionQuoteButton } from '../SelectionQuoteButton';

function Harness({ onQuote }: { onQuote: (text: string) => void }) {
  const rootRef = useRef<HTMLDivElement>(null);
  return (
    <I18nProvider defaultLocale="zh">
      <div ref={rootRef}>
        <div data-quote-scope="message-body">
          <p data-testid="body">可以引用的一段回答</p>
        </div>
        <span data-testid="chrome">工具卡片</span>
      </div>
      <SelectionQuoteButton rootRef={rootRef} onQuote={onQuote} />
    </I18nProvider>
  );
}

function selectContents(el: HTMLElement) {
  const selection = window.getSelection() as Selection;
  const range = document.createRange();
  range.selectNodeContents(el);
  selection.removeAllRanges();
  selection.addRange(range);
}

function mouseUpAndFlush() {
  fireEvent.mouseUp(document);
  act(() => {
    vi.advanceTimersByTime(1);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
});

afterEach(() => {
  window.getSelection()?.removeAllRanges();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SelectionQuoteButton', () => {
  it('shows a quote button for a selection inside a message body and quotes it', () => {
    const onQuote = vi.fn();
    render(<Harness onQuote={onQuote} />);

    selectContents(screen.getByTestId('body'));
    mouseUpAndFlush();

    const button = screen.getByTestId('selection-quote-button');
    expect(button).toHaveTextContent('引用');
    expect(button).toHaveAttribute('aria-label', '引用所选内容到输入框');

    fireEvent.mouseDown(button);
    fireEvent.click(button);
    expect(onQuote).toHaveBeenCalledWith('可以引用的一段回答');
    expect(screen.queryByTestId('selection-quote-button')).toBeNull();
    expect(window.getSelection()?.isCollapsed ?? true).toBe(true);
  });

  it('ignores selections outside quote scopes', () => {
    render(<Harness onQuote={vi.fn()} />);
    selectContents(screen.getByTestId('chrome'));
    mouseUpAndFlush();
    expect(screen.queryByTestId('selection-quote-button')).toBeNull();
  });

  it('hides on Escape and when the selection collapses', () => {
    render(<Harness onQuote={vi.fn()} />);

    selectContents(screen.getByTestId('body'));
    mouseUpAndFlush();
    expect(screen.getByTestId('selection-quote-button')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('selection-quote-button')).toBeNull();

    selectContents(screen.getByTestId('body'));
    mouseUpAndFlush();
    expect(screen.getByTestId('selection-quote-button')).toBeInTheDocument();
    act(() => {
      window.getSelection()?.removeAllRanges();
      document.dispatchEvent(new Event('selectionchange'));
    });
    expect(screen.queryByTestId('selection-quote-button')).toBeNull();
  });

  it('hides when the conversation scrolls', () => {
    render(<Harness onQuote={vi.fn()} />);
    selectContents(screen.getByTestId('body'));
    mouseUpAndFlush();
    act(() => {
      screen.getByTestId('body').dispatchEvent(new Event('scroll'));
    });
    expect(screen.queryByTestId('selection-quote-button')).toBeNull();
  });
});
