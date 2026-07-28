/**
 * ChatInput office refs — Task 7 (2026-07-26) RED tests.
 *
 * Covers:
 *   - `@`-menu 'office' selection adds a ChatOfficeRef chip (deduped by docId)
 *   - `@`-menu 'file' selection does NOT add an office chip
 *   - `@`-menu 'office-import' selection calls importOfficeReference then adds the ref
 *   - chip remove callback fires `onRemoveOfficeRef(docId)`
 *   - onSend payload includes officeRefs; send clears the list
 *   - missing workspace binding: 'office-import' selection is a no-op (no chip)
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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

vi.mock('../../../shared/api/skillsApi', () => ({
  skillsApi: { list: vi.fn().mockResolvedValue([]), execute: vi.fn() },
}));

vi.mock('../../../features/chat/useBtwCommand', () => ({
  useBtwCommand: () => ({
    open: vi.fn(),
    close: vi.fn(),
    isOpen: false,
    question: '',
    answer: '',
    isLoading: false,
  }),
}));

vi.mock('../../../features/chat/useAtFileQuery', () => ({
  useAtFileQuery: () => ({ query: 'fo', startIdx: 0, endIdx: 3 }),
}));

const workspaceContextValue = vi.fn();
vi.mock('../../../shared/lib/workspaceContext', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/lib/workspaceContext')>(
    '../../../shared/lib/workspaceContext',
  );
  return {
    ...actual,
    useOptionalWorkspaceContext: () => workspaceContextValue(),
  };
});

const mockImportOfficeReference = vi.fn();
vi.mock('../../../features/office/importOfficeReference', () => ({
  importOfficeReference: (...args: unknown[]) => mockImportOfficeReference(...args),
}));

/**
 * Mock AtFileMenu exposes three buttons (file / office / office-import).
 * Each test clicks the matching button to drive the menu callback.
 */
vi.mock('../../../features/chat/AtFileMenu', () => ({
  AtFileMenu: ({ onSelect }: { onSelect: (s: unknown) => void }) => (
    <div data-testid="at-file-mock">
      <button
        data-testid="at-file-mock-file"
        onClick={() => onSelect({ kind: 'file', path: '/w/a.txt', name: 'a.txt' })}
      >
        file
      </button>
      <button
        data-testid="at-file-mock-office"
        onClick={() =>
          onSelect({
            kind: 'office',
            ref: { docId: 'doc-1', docType: 'ppt', filename: 'a.pptx' },
          })
        }
      >
        office
      </button>
      <button
        data-testid="at-file-mock-office-import"
        onClick={() =>
          onSelect({
            kind: 'office-import',
            result: {
              path: '/tmp/outside.pptx',
              name: 'outside.pptx',
              kind: 'office-ppt',
              docId: null,
              docType: 'ppt',
              sourcePath: '/tmp/outside.pptx',
            },
          })
        }
      >
        office-import
      </button>
    </div>
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
  workspaceContextValue.mockReturnValue({
    sessionId: 'session-1',
    binding: { workspacePath: '/w/my-ws' },
  });
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('ChatInput — office-ref chips', () => {
  it('renders a removable office-ref chip for a managed-ref selection', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);
    fireEvent.click(screen.getByTestId('at-file-mock-office'));
    expect(screen.getAllByTestId('office-ref-chip')).toHaveLength(1);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('does not add an office chip for a plain file selection', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);
    fireEvent.click(screen.getByTestId('at-file-mock-file'));
    expect(screen.queryByTestId('office-ref-chip')).toBeNull();
  });

  it('dedupes office chips by docId (clicking the same doc twice does not duplicate)', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);
    fireEvent.click(screen.getByTestId('at-file-mock-office'));
    fireEvent.click(screen.getByTestId('at-file-mock-office'));
    expect(screen.getAllByTestId('office-ref-chip')).toHaveLength(1);
  });

  it('removes an office chip when its X is clicked', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);
    fireEvent.click(screen.getByTestId('at-file-mock-office'));
    const removeBtn = screen.getByLabelText('remove office ref a.pptx');
    fireEvent.click(removeBtn);
    expect(screen.queryByTestId('office-ref-chip')).toBeNull();
  });

  it('passes officeRefs into onSend options and clears them after send', async () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);
    fireEvent.click(screen.getByTestId('at-file-mock-office'));
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'summarize this' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });

    await waitFor(() => {
      expect(onSend).toHaveBeenCalled();
    });
    const call = onSend.mock.calls[0];
    expect(call[0]).toBe('summarize this');
    expect(call[1]?.officeRefs).toEqual([{ docId: 'doc-1', docType: 'ppt', filename: 'a.pptx' }]);
    // chips cleared after send
    expect(screen.queryByTestId('office-ref-chip')).toBeNull();
  });

  it('imports an unmanaged office doc and adds the resulting ChatOfficeRef', async () => {
    mockImportOfficeReference.mockResolvedValueOnce({
      docId: 'doc-imp',
      docType: 'ppt',
      filename: 'outside.pptx',
    });
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);
    fireEvent.click(screen.getByTestId('at-file-mock-office-import'));

    await waitFor(() => {
      expect(screen.getAllByTestId('office-ref-chip')).toHaveLength(1);
    });
    expect(mockImportOfficeReference).toHaveBeenCalledWith(
      '/w/my-ws',
      expect.objectContaining({ sourcePath: '/tmp/outside.pptx' }),
    );
    expect(screen.getByTestId('office-ref-chip')).toHaveAttribute('data-doc-id', 'doc-imp');
  });

  it('does NOT import when workspace binding is missing (no chip added)', async () => {
    workspaceContextValue.mockReturnValue({ sessionId: 'session-1', binding: null });
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);
    fireEvent.click(screen.getByTestId('at-file-mock-office-import'));
    await new Promise((r) => setTimeout(r, 30));
    expect(mockImportOfficeReference).not.toHaveBeenCalled();
    expect(screen.queryByTestId('office-ref-chip')).toBeNull();
  });
});
