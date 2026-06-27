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
});
