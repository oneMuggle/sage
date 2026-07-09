import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

// Mocks
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

const openBtwMock = vi.fn();
const closeBtwMock = vi.fn();
vi.mock('../../../features/chat/useBtwCommand', () => ({
  useBtwCommand: () => ({
    open: openBtwMock,
    close: closeBtwMock,
    isOpen: false,
    question: '',
    answer: '',
    isLoading: false,
  }),
}));

const atFileOnSelectMock = vi.fn();
const atFileOnCloseMock = vi.fn();
vi.mock('../../../features/chat/AtFileMenu', () => ({
  AtFileMenu: ({
    query,
    onSelect,
    onClose,
  }: {
    query: string | null;
    onSelect: (p: string) => void;
    onClose: () => void;
  }) => {
    if (query === null) return null;
    return (
      <div data-testid="at-file-mock">
        <span data-testid="at-file-query">{query}</span>
        <button
          data-testid="at-file-mock-item"
          onClick={() => {
            atFileOnSelectMock('src/picked.ts');
            onSelect('src/picked.ts');
          }}
        >
          mock item
        </button>
        <button
          data-testid="at-file-mock-close"
          onClick={() => {
            atFileOnCloseMock();
            onClose();
          }}
        >
          close
        </button>
      </div>
    );
  },
}));

const renderWithI18n = (ui: React.ReactElement) => {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
};

describe('ChatInput — @ and /btw integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not show AtFileMenu initially', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    expect(screen.queryByTestId('at-file-mock')).toBeNull();
  });

  it('typing @ shows AtFileMenu with query', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '@fo' } });
    expect(screen.getByTestId('at-file-mock')).toBeInTheDocument();
    expect(screen.getByTestId('at-file-query').textContent).toBe('fo');
  });

  it('selecting file inserts @path into textarea', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '@fo' } });
    fireEvent.click(screen.getByTestId('at-file-mock-item'));
    expect(input.value).toContain('@src/picked.ts');
  });

  it('typing /btw then question triggers btw.open()', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '/btw 什么是 useEffect?' } });
    expect(openBtwMock).toHaveBeenCalledWith('什么是 useEffect?');
  });

  it('normal text does not trigger @ or /btw', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'hello world' } });
    expect(openBtwMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId('at-file-mock')).toBeNull();
  });
});
