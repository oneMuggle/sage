/**
 * M4: 消息级分叉按钮测试
 *
 * - onFork 提供时 user/assistant 消息显示分叉按钮，点击携带 message.id
 * - 未提供 onFork / system、tool 消息 → 不渲染按钮
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const baseMsg = (
  id: string,
  role: MessageType['role'],
  content = '分叉测试消息',
): MessageType => ({
  id,
  session_id: 's-1',
  role,
  content,
  created_at: 1_750_000_000_000,
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('Message — fork action (M4)', () => {
  it('renders fork button on user messages and invokes onFork with message id', () => {
    const onFork = vi.fn();
    renderWithI18n(<Message message={baseMsg('u-1', 'user')} onFork={onFork} />);

    const btn = screen.getByTestId('fork-message');
    expect(btn).toHaveAttribute('title', '从此处分叉');
    fireEvent.click(btn);
    expect(onFork).toHaveBeenCalledWith('u-1');
  });

  it('renders fork button on assistant messages', () => {
    const onFork = vi.fn();
    renderWithI18n(<Message message={baseMsg('a-1', 'assistant')} onFork={onFork} />);

    fireEvent.click(screen.getByTestId('fork-message'));
    expect(onFork).toHaveBeenCalledWith('a-1');
  });

  it('does not render fork button when onFork is not provided', () => {
    renderWithI18n(<Message message={baseMsg('u-2', 'user')} />);
    expect(screen.queryByTestId('fork-message')).not.toBeInTheDocument();
  });

  it('does not render fork button for system/tool messages', () => {
    const onFork = vi.fn();
    const { rerender } = renderWithI18n(
      <Message message={baseMsg('s-1', 'system')} onFork={onFork} />,
    );
    expect(screen.queryByTestId('fork-message')).not.toBeInTheDocument();

    rerender(
      <I18nProvider defaultLocale="zh">
        <Message message={baseMsg('t-1', 'tool')} onFork={onFork} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId('fork-message')).not.toBeInTheDocument();
  });
});
