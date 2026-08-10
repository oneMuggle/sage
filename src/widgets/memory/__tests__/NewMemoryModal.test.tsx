// @vitest-environment jsdom
/**
 * NewMemoryModal — fix/security-perf-quickwins §1.3b g (2026-08-09)
 *
 * Bug history:
 * - After successful save, the modal called `window.location.reload()`,
 *   throwing away React state and re-fetching everything (slow + loses
 *   user context like scroll position, focused element, sidebar selection).
 * - Modal markup was hand-rolled `<div fixed inset-0>` with manual click
 *   handlers — no Esc key support, no focus trap, no aria-modal.
 *
 * Fix: route the success signal through an `onSaved` callback so the
 * parent can do a targeted refresh, and use the shared `<Modal>` for
 * proper a11y semantics.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// jsdom does not implement ResizeObserver but @headlessui Dialog uses it
// internally; provide a no-op stub so the modal can render.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

import { memoryApi } from '../../../shared/api';
import { NewMemoryModal } from '../NewMemoryModal';

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    saveMemory: vi.fn(),
    getMemories: vi.fn(),
  },
}));

const mockedSaveMemory = vi.mocked(memoryApi.saveMemory);

beforeEach(() => {
  mockedSaveMemory.mockReset();
  // Default: successful save
  mockedSaveMemory.mockResolvedValue({
    id: 'mem-new',
    content: 'foo',
    memory_type: 'episodic',
    importance: 5,
    created_at: 0,
  } as never);
  // Stub window.location.reload so we can assert it is NEVER called
  Object.defineProperty(window, 'location', {
    value: { reload: vi.fn() },
    writable: true,
    configurable: true,
  });
});

describe('NewMemoryModal (fix/security-perf-quickwins §1.3b g)', () => {
  it('on successful save calls onSaved callback and closes (no window.location.reload)', async () => {
    const onClose = vi.fn();
    const onSaved = vi.fn();

    render(
      <NewMemoryModal isOpen onClose={onClose} onSaved={onSaved} />,
    );

    // Fill content and save
    fireEvent.change(screen.getByLabelText('内容'), {
      target: { value: 'remember this' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(mockedSaveMemory).toHaveBeenCalledWith(
        'remember this',
        'episodic',
        5,
      );
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);

    // CRITICAL: window.location.reload must NOT be called (the whole point
    // of the fix — we want a local refresh, not a full page reload).
    expect(
      (window.location.reload as unknown as { mock: { calls: unknown[] } })
        .mock.calls,
    ).toHaveLength(0);
  });

  it('does not call onSaved when save fails (error is shown, modal stays open)', async () => {
    mockedSaveMemory.mockRejectedValueOnce(new Error('网络异常'));

    const onClose = vi.fn();
    const onSaved = vi.fn();

    render(<NewMemoryModal isOpen onClose={onClose} onSaved={onSaved} />);

    fireEvent.change(screen.getByLabelText('内容'), {
      target: { value: 'some content' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(screen.getByText('网络异常')).toBeInTheDocument();
    });
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('does not call onSaved when content is empty (button disabled)', () => {
    const onClose = vi.fn();
    const onSaved = vi.fn();

    render(<NewMemoryModal isOpen onClose={onClose} onSaved={onSaved} />);

    const saveBtn = screen.getByRole('button', { name: '保存' });
    expect(saveBtn).toBeDisabled();
    fireEvent.click(saveBtn); // no-op
    expect(mockedSaveMemory).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });
});