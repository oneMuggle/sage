import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { WelcomeInputCard } from '../WelcomeInputCard';

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

    expect(onSend).toHaveBeenCalledWith('测试消息');
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
});
