/**
 * Multi-Agent Orchestration: /orchestrate + /single slash command tests。
 * 两个命令是 tool-toggle 门的用户 override 逃生门:
 *  /orchestrate → force_multi（复杂消息必进编排）
 *  /single → force_single（简单消息强制走单 agent）
 * 链路: slash 菜单选中 → ChatInput.onSend(content, { orchestrationMode }) →
 *       Chat.tsx handleSendMessage 透传 → useChat.sendMessage 第 4 参 → chatStream。
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

describe('ChatInput — /orchestrate override', () => {
  it('sends args with orchestrationMode force_multi when body present', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/orchestrate 学习量化交易并整理指南' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/orchestrate/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith('学习量化交易并整理指南', {
      orchestrationMode: 'force_multi',
    });
    expect((input as HTMLInputElement).value).toBe('');
  });

  it('shows usage hint when command has no body', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), {
      target: { value: '/orchestrate' },
    });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/orchestrate/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0]).toMatch(/用法/);
  });
});

describe('ChatInput — /single override', () => {
  it('sends args with orchestrationMode force_single when body present', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), {
      target: { value: '/single 今天天气' },
    });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/single/ }));

    expect(onSend).toHaveBeenCalledWith('今天天气', { orchestrationMode: 'force_single' });
  });

  it('shows usage hint when command has no body', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: '/single' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/single/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0]).toMatch(/用法/);
  });
});

describe('ChatInput — 模板选择器 (Wave 3 C6)', () => {
  it('选 research-write → 发送带 orchestrationMode=template:research-write', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), {
      target: { value: '写一份量化学习指南' },
    });
    fireEvent.change(screen.getByTestId('orch-mode-select'), {
      target: { value: 'template:research-write' },
    });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));

    expect(onSend).toHaveBeenCalledWith(
      '写一份量化学习指南',
      expect.objectContaining({ orchestrationMode: 'template:research-write' }),
    );
  });

  it('默认 auto → 发送不传 orchestrationMode（保持既有 undefined → auto 语义）', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: 'hello' } });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][1]).not.toHaveProperty('orchestrationMode');
  });
});
