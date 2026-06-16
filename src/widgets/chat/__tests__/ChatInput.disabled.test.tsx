import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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

import { ChatInput } from '../ChatInput';

describe('ChatInput — disabled when settings missing', () => {
  it('renders enabled by default when no disabled prop is passed', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: 'hi' } });

    const button = screen.getByRole('button', { name: /发送/ });
    // value 有内容,但没收到外部 disabled 提示,默认应可点
    expect(button).not.toBeDisabled();
  });

  it('disables send button when disabled prop is true', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled={true} />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: 'hi' } });

    const button = screen.getByRole('button', { name: /发送/ });
    expect(button).toBeDisabled();
  });
});
