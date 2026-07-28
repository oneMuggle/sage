/**
 * WorkspaceBindModal — Task 5 (2026-07-26).
 *
 * Coverage:
 *   - Renders bind / change / revoke controls with stable test IDs:
 *       workspace-bind-button, workspace-revoke-button, workspace-bind-error
 *   - Calls `window.electronAPI.selectDirectory({ intent: 'open' })`
 *   - Cancel (selectDirectory → null) leaves state untouched and does NOT
 *     call bind().
 *   - Successful pick → bind() called with the picked path.
 *   - selectDirectory rejecting surfaces the error and keeps the modal
 *     open for retry.
 *   - bind() rejecting surfaces the error in the modal (testid
 *     `workspace-bind-error`) and does NOT close.
 *   - Revoke button calls the revoke action and closes.
 *   - Modal disables the bind button while bind() is in flight (busy).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState, type ComponentProps } from 'react';
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

import { WorkspaceBindModal } from '../WorkspaceBindModal';

interface FakeWindow {
  electronAPI?: { selectDirectory: (opts: { intent: string }) => Promise<string | null> };
}

const mockBind = vi.fn();
const mockRevoke = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  (window as unknown as FakeWindow).electronAPI = {
    selectDirectory: vi.fn(),
  };
});

function renderModal(
  props: Partial<ComponentProps<typeof WorkspaceBindModal>> = {},
) {
  const onClose = vi.fn();
  const utils = render(
    <WorkspaceBindModal
      isOpen
      onClose={onClose}
      currentPath={null}
      bind={mockBind}
      revoke={mockRevoke}
      {...props}
    />,
  );
  return { ...utils, onClose };
}

describe('WorkspaceBindModal — rendering', () => {
  it('renders bind and revoke controls with stable test IDs', () => {
    renderModal();
    expect(screen.getByTestId('workspace-bind-button')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-revoke-button')).toBeInTheDocument();
  });

  it('does not call selectDirectory before the user clicks bind', () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/picked');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    renderModal();
    expect(selectDirectory).not.toHaveBeenCalled();
  });
});

describe('WorkspaceBindModal — bind flow', () => {
  it('calls selectDirectory with { intent: "open" } on bind click', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/ws-a');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    mockBind.mockResolvedValue(undefined);
    renderModal();

    fireEvent.click(screen.getByTestId('workspace-bind-button'));

    await waitFor(() => expect(selectDirectory).toHaveBeenCalledWith({ intent: 'open' }));
  });

  it('calls bind() with the picked path on success', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/ws-a');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    mockBind.mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <WorkspaceBindModal
        isOpen
        onClose={onClose}
        currentPath={null}
        bind={mockBind}
        revoke={mockRevoke}
      />,
    );

    fireEvent.click(screen.getByTestId('workspace-bind-button'));

    await waitFor(() => expect(mockBind).toHaveBeenCalledWith('/tmp/ws-a'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('keeps the modal open and does not call bind() when the user cancels', async () => {
    const selectDirectory = vi.fn().mockResolvedValue(null);
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    renderModal();

    fireEvent.click(screen.getByTestId('workspace-bind-button'));

    await waitFor(() => expect(selectDirectory).toHaveBeenCalled());
    expect(mockBind).not.toHaveBeenCalled();
    expect(screen.queryByTestId('workspace-bind-error')).toBeNull();
  });

  it('surfaces bind() errors with stable test id and keeps the modal open', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/ws-a');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    mockBind.mockRejectedValue(new Error('bind refused'));
    const onClose = vi.fn();
    render(
      <WorkspaceBindModal
        isOpen
        onClose={onClose}
        currentPath={null}
        bind={mockBind}
        revoke={mockRevoke}
      />,
    );

    fireEvent.click(screen.getByTestId('workspace-bind-button'));

    await waitFor(() => expect(mockBind).toHaveBeenCalledWith('/tmp/ws-a'));
    const errEl = await screen.findByTestId('workspace-bind-error');
    expect(errEl.textContent).toMatch(/bind refused/);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('surfaces selectDirectory errors with stable test id (no crash)', async () => {
    const selectDirectory = vi.fn().mockRejectedValue(new Error('native dialog blew up'));
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    renderModal();

    fireEvent.click(screen.getByTestId('workspace-bind-button'));

    const errEl = await screen.findByTestId('workspace-bind-error');
    expect(errEl.textContent).toMatch(/native dialog blew up/);
    expect(mockBind).not.toHaveBeenCalled();
  });

  it('disables the bind button while a bind() is in flight', async () => {
    let resolveBind!: () => void;
    mockBind.mockReturnValueOnce(
      new Promise<void>((res) => {
        resolveBind = res;
      }),
    );
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/ws-a');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };

    renderModal();
    fireEvent.click(screen.getByTestId('workspace-bind-button'));

    await waitFor(() => expect(mockBind).toHaveBeenCalled());
    expect(
      (screen.getByTestId('workspace-bind-button') as HTMLButtonElement).disabled,
    ).toBe(true);

    resolveBind();
    await waitFor(() => {
      expect(
        (screen.getByTestId('workspace-bind-button') as HTMLButtonElement).disabled,
      ).toBe(false);
    });
  });

  it('surfaces a friendly error when the electronAPI bridge is missing', async () => {
    delete (window as unknown as FakeWindow).electronAPI;
    renderModal();
    fireEvent.click(screen.getByTestId('workspace-bind-button'));
    const errEl = await screen.findByTestId('workspace-bind-error');
    expect(errEl.textContent).toMatch(/Electron|IPC|bridge|桌面端|不可用/);
  });
});

describe('WorkspaceBindModal — revoke flow', () => {
  it('renders the revoke button as enabled when currentPath is set', () => {
    renderModal({ currentPath: '/tmp/ws-a' });
    const btn = screen.getByTestId('workspace-revoke-button') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('disables the revoke button when currentPath is null', () => {
    renderModal({ currentPath: null });
    const btn = screen.getByTestId('workspace-revoke-button') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('calls revoke() and closes on click', async () => {
    mockRevoke.mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <WorkspaceBindModal
        isOpen
        onClose={onClose}
        currentPath="/tmp/ws-a"
        bind={mockBind}
        revoke={mockRevoke}
      />,
    );
    fireEvent.click(screen.getByTestId('workspace-revoke-button'));
    await waitFor(() => expect(mockRevoke).toHaveBeenCalled());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('surfaces revoke() errors and keeps the modal open', async () => {
    mockRevoke.mockRejectedValue(new Error('revoke refused'));
    const onClose = vi.fn();
    render(
      <WorkspaceBindModal
        isOpen
        onClose={onClose}
        currentPath="/tmp/ws-a"
        bind={mockBind}
        revoke={mockRevoke}
      />,
    );
    fireEvent.click(screen.getByTestId('workspace-revoke-button'));
    await waitFor(() => expect(mockRevoke).toHaveBeenCalled());
    const errEl = await screen.findByTestId('workspace-bind-error');
    expect(errEl.textContent).toMatch(/revoke refused/);
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('WorkspaceBindModal — controlled parent smoke', () => {
  it('clears the prior error when reopened', async () => {
    const selectDirectory = vi.fn().mockResolvedValueOnce('/tmp/ws-a');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    mockBind.mockRejectedValueOnce(new Error('first run bad'));

    const Parent = () => {
      const [open, setOpen] = useState(true);
      return (
        <>
          <button data-testid="parent-toggle" onClick={() => setOpen((o) => !o)}>
            toggle
          </button>
          <WorkspaceBindModal
            isOpen={open}
            onClose={() => setOpen(false)}
            currentPath={null}
            bind={mockBind}
            revoke={mockRevoke}
          />
        </>
      );
    };

    render(<Parent />);
    fireEvent.click(screen.getByTestId('workspace-bind-button'));
    await screen.findByTestId('workspace-bind-error');

    fireEvent.click(screen.getByTestId('parent-toggle'));
    await waitFor(() => expect(screen.queryByTestId('workspace-bind-error')).toBeNull());
  });
});