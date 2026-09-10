/**
 * PM2 (round8): /plan 计划模式 slash 命令测试。
 * 链路: slash 菜单选中 → ChatInput.onSend(content, { planMode: true }) →
 *       Chat.handleSendMessage 透传 → useChat.sendMessage opts → chatStream
 *       body plan_mode → 后端只读门 + 计划指令。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('ChatInput — /plan 计划模式 (PM2)', () => {
  it('sends remaining text with planMode=true', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/plan 修复登录页面的空指针' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/plan/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith('修复登录页面的空指针', { planMode: true });
    expect((input as HTMLInputElement).value).toBe('');
  });

  it('does not send when no goal text follows /plan', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), {
      target: { value: '/plan' },
    });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/plan/ }));

    expect(onSend).not.toHaveBeenCalled();
  });

  it('does not send while streaming (isLoading)', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} isLoading />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), {
      target: { value: '/plan 修复登录' },
    });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/plan/ }));

    expect(onSend).not.toHaveBeenCalled();
  });
});
