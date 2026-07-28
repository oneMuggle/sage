/**
 * M4: /compact slash action 测试
 *
 * 从 slash 菜单选择 /compact 时调用 onCompact（真实 action），
 * 而不是把命令转成提示词发给 LLM（旧行为）。
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

function openSlashMenuAndSelectCompact() {
  const input = screen.getByPlaceholderText(/输入消息/);
  fireEvent.change(input, { target: { value: '/compact' } });
  // SlashCommandMenu 项通过 onMouseDown 触发选择（按 role 定位菜单按钮，
  // 避免与 textarea 中的 "/compact" 文本冲突）
  const menuItem = screen.getByRole('button', { name: /\/compact/ });
  fireEvent.mouseDown(menuItem);
  return input;
}

describe('ChatInput — /compact action', () => {
  it('invokes onCompact (not onSend) when /compact is selected', () => {
    const onSend = vi.fn();
    const onCompact = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} onCompact={onCompact} />);

    const input = openSlashMenuAndSelectCompact();

    expect(onCompact).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
    // 命令文本被清空
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('is a safe no-op when onCompact is not provided', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    const input = openSlashMenuAndSelectCompact();

    expect(onSend).not.toHaveBeenCalled();
    expect((input as HTMLTextAreaElement).value).toBe('');
  });
});
