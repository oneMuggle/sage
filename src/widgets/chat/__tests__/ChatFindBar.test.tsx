// 对话阅读体验 B4：会话内查找栏 —— Ctrl+F 接管、命中计数、Enter / Shift+Enter 翻页、
// 防抖前回车、输入法组词、Esc 关闭。
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { dispatchFindShortcut } from '../../../features/chat/chatFind';
import { useMessageJumpStore } from '../../../features/chat/messageJumpStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatFindBar } from '../ChatFindBar';

const messages = [
  { id: 'm1', role: 'user', content: '部署 sage 的步骤' },
  { id: 'm2', role: 'assistant', content: 'Sage 支持两种部署：`sage up` 或安装包。' },
  { id: 'm3', role: 'assistant', content: '无关内容' },
];

function renderBar() {
  return render(
    <I18nProvider defaultLocale="zh">
      <ChatFindBar messages={messages} />
    </I18nProvider>,
  );
}

function openBar(): boolean {
  let handled = false;
  act(() => {
    handled = dispatchFindShortcut(false);
  });
  return handled;
}

function typeQuery(value: string) {
  fireEvent.change(screen.getByTestId('chat-find-input'), { target: { value } });
  act(() => {
    vi.advanceTimersByTime(200);
  });
}

const count = () => screen.getByTestId('chat-find-count');
const pending = () => useMessageJumpStore.getState().pending;

beforeEach(() => {
  vi.useFakeTimers();
  useMessageJumpStore.setState({ pending: null });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ChatFindBar (B4)', () => {
  it('stays hidden until Ctrl+F, then claims the shortcut and focuses the input', () => {
    renderBar();
    expect(screen.queryByTestId('chat-find-bar')).toBeNull();
    expect(openBar()).toBe(true);
    expect(screen.getByTestId('chat-find-input')).toHaveFocus();
  });

  it('counts matches across messages and starts from the newest one', () => {
    renderBar();
    openBar();
    typeQuery('SAGE');
    expect(count()).toHaveTextContent('3/3');
    expect(pending()).toMatchObject({ messageId: 'm2', highlightQuery: 'SAGE', highlightIndex: 1 });
  });

  it('Enter goes to older matches and Shift+Enter to newer ones, wrapping around', () => {
    renderBar();
    openBar();
    typeQuery('sage');
    const input = screen.getByTestId('chat-find-input');

    fireEvent.keyDown(input, { key: 'Enter' });
    expect(count()).toHaveTextContent('2/3');
    expect(pending()).toMatchObject({ messageId: 'm2', highlightIndex: 0 });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(pending()).toMatchObject({ messageId: 'm1', highlightIndex: 0 });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(count()).toHaveTextContent('3/3');
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(count()).toHaveTextContent('1/3');
    fireEvent.click(screen.getByTestId('chat-find-prev'));
    expect(count()).toHaveTextContent('3/3');
    fireEvent.click(screen.getByTestId('chat-find-next'));
    expect(count()).toHaveTextContent('1/3');
  });

  it('shows "no results" and disables navigation for a query without matches', () => {
    renderBar();
    openBar();
    typeQuery('不存在的词');
    expect(count()).toHaveTextContent('无结果');
    expect(screen.getByTestId('chat-find-next')).toBeDisabled();
    expect(pending()).toBeNull();
  });

  it('Enter before the debounce fires submits the query right away', () => {
    renderBar();
    openBar();
    const input = screen.getByTestId('chat-find-input');
    fireEvent.change(input, { target: { value: 'sage' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(count()).toHaveTextContent('3/3');
  });

  it('ignores Enter while an IME composition is in progress', () => {
    renderBar();
    openBar();
    typeQuery('sage');
    fireEvent.keyDown(screen.getByTestId('chat-find-input'), { key: 'Enter', isComposing: true });
    expect(count()).toHaveTextContent('3/3');
  });

  it('Esc closes the bar without reaching window listeners; Ctrl+F reopens it empty', () => {
    const onWindowKey = vi.fn();
    window.addEventListener('keydown', onWindowKey);
    renderBar();
    openBar();
    typeQuery('sage');
    fireEvent.keyDown(screen.getByTestId('chat-find-input'), { key: 'Escape' });
    window.removeEventListener('keydown', onWindowKey);
    expect(screen.queryByTestId('chat-find-bar')).toBeNull();
    expect(onWindowKey).not.toHaveBeenCalled();

    openBar();
    expect(screen.getByTestId('chat-find-input')).toHaveValue('');
  });
});
