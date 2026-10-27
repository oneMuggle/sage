// RT5 (round7): 运行中允许发送 —— isLoading 时 Enter 触发 onSend，
// 由 useChat.sendMessage 决定 steering 注入或排队（不再 UI 硬拦截）。
import { render, screen, fireEvent } from '@testing-library/react';
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

const renderWithI18n = (ui: React.ReactElement) => {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
};

describe('ChatInput — send while streaming (RT5 steering)', () => {
  it('calls onSend via Enter while isLoading=true', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} isLoading />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '补充指示：改用方法 B' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith(
      '补充指示：改用方法 B',
      expect.objectContaining({ knowledgeRefs: undefined }),
    );
  });

  it('shows the stop (interrupt) button while isLoading', () => {
    const onSend = vi.fn();
    const onInterrupt = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} isLoading onInterrupt={onInterrupt} />);
    const stop = screen.getByRole('button', { name: /停止/ });
    fireEvent.click(stop);
    expect(onInterrupt).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('still blocks empty send while isLoading', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} isLoading />);
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
  });

  // P2-a (2026-09-20): ChatInput 只负责把用户显式选择的通道透传给 onSend。
  it('Alt+Enter forwards the queue channel', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} isLoading />);
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '这条等下一轮' } });
    fireEvent.keyDown(input, { key: 'Enter', altKey: true });
    expect(onSend).toHaveBeenCalledWith(
      '这条等下一轮',
      expect.objectContaining({ delivery: 'queue' }),
    );
  });

  it('choosing a channel in the split menu forwards it', async () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} isLoading />);
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '换个方向' } });
    fireEvent.pointerDown(screen.getByTestId('chat-delivery-menu'), { button: 0 });
    fireEvent.click(await screen.findByTestId('chat-delivery-interrupt'));
    expect(onSend).toHaveBeenCalledWith(
      '换个方向',
      expect.objectContaining({ delivery: 'interrupt' }),
    );
  });

  it('plain Enter keeps the channel implicit (default = steer downstream)', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} isLoading />);
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '默认插话' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend.mock.calls[0]?.[1]).not.toHaveProperty('delivery');
  });
});
