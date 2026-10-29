import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  WelcomeInputCard,
  formatWelcomeInputJson,
  formatWelcomeInputMarkdown,
} from '../WelcomeInputCard';

const renderWithI18n = (ui: React.ReactElement) => {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
};

describe('WelcomeInputCard', () => {
  it('renders with placeholder', () => {
    renderWithI18n(<WelcomeInputCard placeholder="测试占位符" />);
    expect(screen.getByPlaceholderText('测试占位符')).toBeInTheDocument();
  });

  it('renders with typewriter placeholder', () => {
    const phrases = ['第一个短语', '第二个短语'];
    renderWithI18n(<WelcomeInputCard typewriterPhrases={phrases} />);
    const input = screen.getByRole('textbox');
    expect(input).toHaveAttribute('placeholder');
  });

  it('auto-focuses on mount', () => {
    renderWithI18n(<WelcomeInputCard placeholder="测试" />);
    const input = screen.getByRole('textbox');
    expect(input).toHaveFocus();
  });

  it('calls onSend with input value when submitting', () => {
    const onSend = vi.fn();
    renderWithI18n(<WelcomeInputCard placeholder="测试" onSend={onSend} />);

    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '测试消息' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(onSend).toHaveBeenCalledWith('测试消息', undefined);
  });

  it('accepts drag-and-dropped files and forwards them as send options', async () => {
    const onSend = vi.fn();
    renderWithI18n(<WelcomeInputCard placeholder="测试" onSend={onSend} />);

    const input = screen.getByRole('textbox');
    const file = new File(['hello'], 'report.pdf', { type: 'application/pdf' });
    fireEvent.drop(input, { dataTransfer: { files: [file] } });

    // FileReader 异步读取完成后出现附件 chip
    await waitFor(() => expect(screen.getByText('report.pdf')).toBeInTheDocument());

    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    expect(onSend).toHaveBeenCalledTimes(1);
    const [, options] = onSend.mock.calls[0] as [string, { attachments?: Array<{ name: string }> }];
    expect(options.attachments?.[0]?.name).toBe('report.pdf');
  });

  it('opens the @ menu and notifies the host when the query becomes active', async () => {
    const onAtQueryActive = vi.fn();
    renderWithI18n(<WelcomeInputCard placeholder="测试" onAtQueryActive={onAtQueryActive} />);

    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '@' } });

    await waitFor(() => expect(onAtQueryActive).toHaveBeenCalled());
    // 尚无会话/工作区时菜单给出可诊断的空态，而不是静默无响应
    expect(screen.getByText('当前会话未绑定工作区，无法搜索文件')).toBeInTheDocument();
  });

  it('does not call onSend when input is empty', () => {
    const onSend = vi.fn();
    renderWithI18n(<WelcomeInputCard placeholder="测试" onSend={onSend} />);

    const input = screen.getByRole('textbox');
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(onSend).not.toHaveBeenCalled();
  });

  it('clears input after sending', () => {
    const onSend = vi.fn();
    renderWithI18n(<WelcomeInputCard placeholder="测试" onSend={onSend} />);

    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '测试消息' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(input).toHaveValue('');
  });

  it('formats and copies welcome input draft as Markdown and JSON', () => {
    const md = formatWelcomeInputMarkdown({
      value: '帮我写周报',
      placeholder: '请输入...',
      disabled: false,
    });
    expect(md).toContain('# 欢迎页输入卡片草稿 (Welcome Input Draft)');
    expect(md).toContain('帮我写周报');

    const parsed = JSON.parse(
      formatWelcomeInputJson({
        value: '',
        placeholder: '',
        disabled: true,
      }),
    );
    expect(parsed.disabled).toBe(true);

    renderWithI18n(<WelcomeInputCard placeholder="测试" />);
  });
});
