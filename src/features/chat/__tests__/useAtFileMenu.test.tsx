import { fireEvent, render, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useAtFileMenu } from '../useAtFileMenu';

vi.mock('../AtEntityMenu', () => ({
  AtEntityMenu: () => null,
}));

vi.mock('../AtFileMenu', () => ({
  AtFileMenu: ({
    query,
    onSelect,
    onClose,
  }: {
    query: string | null;
    onSelect: (s: unknown) => void;
    onClose: () => void;
  }) => (
    <div data-testid="at-file-mock" data-query={query ?? ''}>
      <button
        data-testid="pick-file"
        onClick={() => onSelect({ kind: 'file', path: '/ws/a.txt', name: 'a.txt' })}
      >
        file
      </button>
      <button
        data-testid="pick-office"
        onClick={() =>
          onSelect({
            kind: 'office',
            ref: { docId: 'doc-1', docType: 'pdf', filename: 'a.pdf' },
          })
        }
      >
        office
      </button>
      <button data-testid="close-menu" onClick={onClose}>
        close
      </button>
    </div>
  ),
}));

vi.mock('../../office/importOfficeReference', () => ({
  importOfficeReference: vi.fn(),
}));

function setup(overrides: Partial<Parameters<typeof useAtFileMenu>[0]> = {}) {
  const onChange = vi.fn();
  const onCursorChange = vi.fn();
  const addOfficeRef = vi.fn();
  const onQueryActive = vi.fn();
  const { result } = renderHook(() =>
    useAtFileMenu({
      value: '@ap',
      cursorPos: 3,
      onChange,
      onCursorChange,
      workspacePath: '/ws',
      addOfficeRef,
      onQueryActive,
      ...overrides,
    }),
  );
  return { result, onChange, onCursorChange, addOfficeRef, onQueryActive };
}

describe('useAtFileMenu', () => {
  it('notifies the host when the @ query becomes active', () => {
    const { onQueryActive } = setup();
    expect(onQueryActive).toHaveBeenCalledWith('ap');
  });

  it('inserts @<path> when a plain file is picked', () => {
    const { result, onChange, onCursorChange } = setup();
    const view = render(<>{result.current.atFileMenu}</>);
    fireEvent.click(view.getByTestId('pick-file'));
    expect(onChange).toHaveBeenCalledWith('@/ws/a.txt ');
    expect(onCursorChange).toHaveBeenCalledWith(11);
  });

  it('adds an office ref and clears the @ query', () => {
    const { result, onChange, addOfficeRef } = setup();
    const view = render(<>{result.current.atFileMenu}</>);
    fireEvent.click(view.getByTestId('pick-office'));
    expect(addOfficeRef).toHaveBeenCalledWith({
      docId: 'doc-1',
      docType: 'pdf',
      filename: 'a.pdf',
    });
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('renders no menu when there is no active query', () => {
    const { result } = setup({ value: 'hello', cursorPos: 5 });
    expect(result.current.atFileMenu).toBeNull();
  });
});
