import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InputCard } from '../InputCard';

// Mock useI18n
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
    locale: 'zh',
  }),
}));

describe('InputCard', () => {
  let defaultProps: {
    value: string;
    onChange: ReturnType<typeof vi.fn>;
    onSubmit: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    defaultProps = {
      value: '',
      onChange: vi.fn(),
      onSubmit: vi.fn(),
    };
  });

  it('renders textarea with placeholder', () => {
    render(<InputCard {...defaultProps} placeholder="Type here" />);
    const textarea = screen.getByPlaceholderText('Type here');
    expect(textarea).toBeInTheDocument();
  });

  it('calls onChange when typing', () => {
    render(<InputCard {...defaultProps} />);
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'hello' } });
    expect(defaultProps.onChange).toHaveBeenCalledWith('hello');
  });

  it('calls onSubmit on Enter key', () => {
    render(<InputCard {...defaultProps} value="test message" />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(defaultProps.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('does not call onSubmit on Shift+Enter', () => {
    render(<InputCard {...defaultProps} value="test message" />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('disables textarea when disabled prop is true', () => {
    render(<InputCard {...defaultProps} disabled />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).toBeDisabled();
  });

  it('auto-focuses textarea when autoFocus is true', () => {
    render(<InputCard {...defaultProps} autoFocus />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).toHaveFocus();
  });

  it('shows send button disabled when value is empty', () => {
    render(<InputCard {...defaultProps} />);
    const sendButton = screen.getByRole('button', { name: /chat\.send/i });
    expect(sendButton).toBeDisabled();
  });

  it('shows interrupt button when isLoading is true', () => {
    const onInterrupt = vi.fn();
    render(<InputCard {...defaultProps} isLoading onInterrupt={onInterrupt} />);
    const stopButton = screen.getByRole('button', { name: /chat\.stop/i });
    expect(stopButton).toBeInTheDocument();
    stopButton.click();
    expect(onInterrupt).toHaveBeenCalledTimes(1);
  });
  // Autosize: textarea must auto-grow when value spans multiple lines.
  // jsdom does not compute layout, so scrollHeight is not meaningful here.
  // We assert the inline style is updated on value change — the shape that
  // ensures the textarea's height tracks the content visually in a real DOM.
  it('updates textarea height inline style when value changes (autosize)', () => {
    const { rerender } = render(<InputCard {...defaultProps} value="" />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;

    // Baseline: empty value still triggers an autosize pass to reset
    // the height to 'auto' before measuring.
    expect(textarea.style.height).not.toBe('');

    rerender(<InputCard {...defaultProps} value={'line1\nline2\nline3\nline4'} />);

    // After multi-line content, autosize must apply an explicit pixel height
    // (capped at 200px). jsdom reports a 0 scrollHeight, so the cap branch
    // is exercised — what we care about is that style.height is set.
    expect(textarea.style.height).toMatch(/^\d+px$/);
  });

  // U20: Emacs-style keybindings wired into the textarea.
  it('Ctrl+A moves cursor to line start without calling onChange', () => {
    render(<InputCard {...defaultProps} value="hello world" />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    textarea.setSelectionRange(5, 5);

    const handled = fireEvent.keyDown(textarea, { key: 'a', ctrlKey: true });

    expect(handled).toBe(false); // default prevented
    expect(textarea.selectionStart).toBe(0);
    expect(defaultProps.onChange).not.toHaveBeenCalled();
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('Ctrl+K kills to end of line via onChange', () => {
    render(<InputCard {...defaultProps} value="hello world" />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    textarea.setSelectionRange(5, 5);

    fireEvent.keyDown(textarea, { key: 'k', ctrlKey: true });

    expect(defaultProps.onChange).toHaveBeenCalledWith('hello');
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('Emacs bindings are inert when disabled', () => {
    render(<InputCard {...defaultProps} value="hello world" disabled />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;

    // jsdom still dispatches keydown to disabled textareas via fireEvent;
    // the hook must ignore it because enabled=false.
    const handled = fireEvent.keyDown(textarea, { key: 'k', ctrlKey: true });

    expect(handled).toBe(true); // default NOT prevented
    expect(defaultProps.onChange).not.toHaveBeenCalled();
  });
});
