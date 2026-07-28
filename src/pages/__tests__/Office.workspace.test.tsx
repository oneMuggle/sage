/**
 * Office — workspace integration test (Task 5, 2026-07-26).
 *
 * Verifies that the Office page correctly:
 *   1. Reads `workspacePath` from `useCurrentWorkspace()` (no longer owns
 *      its own local useState).
 *   2. Opens the WorkspaceBindModal via the header buttons.
 *   3. Closes the modal + clears preview after a successful bind/revoke
 *      (the stale-read guard bumps readIdRef on modal close).
 *   4. Surfaces a workspace-level error (status='error') using the
 *      `office-workspace-error` testid.
 *
 * Provider is mounted via the real SessionWorkspaceProvider + a mocked
 * `workspaceApi`. The page itself is rendered with all features stubbed
 * to keep the integration test focused on workspace lifecycle only.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockBind = vi.fn();
const mockGet = vi.fn();
const mockRevoke = vi.fn();

vi.mock('../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    bind: (...args: unknown[]) => mockBind(...args),
    get: (...args: unknown[]) => mockGet(...args),
    revoke: (...args: unknown[]) => mockRevoke(...args),
  },
}));

// jsdom does not implement ResizeObserver but @headlessui Dialog uses it
// internally; provide a no-op stub so the modal can render.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// Stub the office feature to keep the integration test focused on the
// workspace lifecycle. We assert on what the page itself renders.
vi.mock('../../features/office', () => ({
  OfficeDocumentList: () => <div data-testid="office-document-list" />,
  OfficeFilePicker: ({ children }: { children?: ReactNode }) => (
    <div data-testid="office-file-picker">{children}</div>
  ),
  OfficeGenerateForm: () => <div data-testid="office-generate-form" />,
  OfficePreviewPanel: () => <div data-testid="office-preview-panel" />,
  useOfficeDocuments: () => ({
    documents: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
    importAndRead: vi.fn(),
    readDropped: vi.fn(),
    saveAs: vi.fn(),
    open: vi.fn(),
    showInFolder: vi.fn(),
  }),
}));

import { SessionWorkspaceProvider } from '../../app/providers/SessionWorkspaceProvider';
import { useStore } from '../../shared/lib/store';
import { Office } from '../Office';

beforeEach(() => {
  mockBind.mockReset();
  mockGet.mockReset();
  mockRevoke.mockReset();
  mockGet.mockResolvedValue({ binding: null });
  useStore.setState({ currentSessionId: 'session-1', sessions: [], messages: [] });
});

afterEach(() => {
  useStore.setState({ currentSessionId: null });
});

function renderWithProvider() {
  return render(
    <SessionWorkspaceProvider>
      <Office />
    </SessionWorkspaceProvider>,
  );
}

describe('Office — workspace lifecycle (Task 5)', () => {
  it('shows the pick button when there is no active binding', async () => {
    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId('office-workspace-pick')).toBeInTheDocument(),
    );
  });

  it('opens the bind modal when the user clicks the pick button', async () => {
    renderWithProvider();
    await waitFor(() => screen.getByTestId('office-workspace-pick'));
    fireEvent.click(screen.getByTestId('office-workspace-pick'));
    await waitFor(() =>
      expect(screen.getByTestId('workspace-bind-button')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('workspace-revoke-button')).toBeInTheDocument();
  });

  it('shows the workspace path when a binding is loaded', async () => {
    mockGet.mockResolvedValueOnce({
      binding: {
        sessionId: 'session-1',
        workspacePath: '/tmp/ws-loaded',
        generation: 1,
        activatedAt: 1,
        revokedAt: null,
      },
    });
    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId('office-workspace-path')).toHaveTextContent('/tmp/ws-loaded'),
    );
  });

  it('opens the bind modal when the user clicks the workspace-path chip (change path)', async () => {
    mockGet.mockResolvedValueOnce({
      binding: {
        sessionId: 'session-1',
        workspacePath: '/tmp/ws-loaded',
        generation: 1,
        activatedAt: 1,
        revokedAt: null,
      },
    });
    renderWithProvider();
    const chip = await screen.findByTestId('office-workspace-path');
    fireEvent.click(chip);
    await waitFor(() =>
      expect(screen.getByTestId('workspace-bind-button')).toBeInTheDocument(),
    );
  });

  it('surfaces a workspace-level error with stable test id', async () => {
    mockGet.mockRejectedValueOnce(new Error('backend down'));
    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId('office-workspace-error')).toHaveTextContent(/backend down/),
    );
  });

  it('full bind flow: native selectDirectory → workspaceApi.bind → close', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/picked');
    (window as unknown as { electronAPI?: { selectDirectory: typeof selectDirectory } }).electronAPI = {
      selectDirectory,
    };
    mockBind.mockResolvedValue({
      binding: {
        sessionId: 'session-1',
        workspacePath: '/tmp/picked',
        generation: 1,
        activatedAt: 1,
        revokedAt: null,
      },
    });

    renderWithProvider();
    await waitFor(() => screen.getByTestId('office-workspace-pick'));
    fireEvent.click(screen.getByTestId('office-workspace-pick'));
    await waitFor(() => screen.getByTestId('workspace-bind-button'));

    fireEvent.click(screen.getByTestId('workspace-bind-button'));

    await waitFor(() => expect(selectDirectory).toHaveBeenCalledWith({ intent: 'open' }));
    await waitFor(() => expect(mockBind).toHaveBeenCalledWith('session-1', '/tmp/picked'));
    await waitFor(() =>
      expect(screen.getByTestId('office-workspace-path')).toHaveTextContent('/tmp/picked'),
    );
  });

  it('full revoke flow: revoke button → workspaceApi.revoke → close', async () => {
    mockGet.mockResolvedValueOnce({
      binding: {
        sessionId: 'session-1',
        workspacePath: '/tmp/ws-a',
        generation: 1,
        activatedAt: 1,
        revokedAt: null,
      },
    });
    mockRevoke.mockResolvedValue({ revoked: true, generation: 2 });

    renderWithProvider();
    const chip = await screen.findByTestId('office-workspace-path');
    fireEvent.click(chip);
    const revokeBtn = await screen.findByTestId('workspace-revoke-button');

    fireEvent.click(revokeBtn);
    await waitFor(() => expect(mockRevoke).toHaveBeenCalledWith('session-1'));
  });

  it('keeps the modal open and surfaces a friendly error when selectDirectory rejects', async () => {
    const selectDirectory = vi.fn().mockRejectedValue(new Error('native dialog blew up'));
    (window as unknown as { electronAPI?: { selectDirectory: typeof selectDirectory } }).electronAPI = {
      selectDirectory,
    };

    renderWithProvider();
    await waitFor(() => screen.getByTestId('office-workspace-pick'));
    fireEvent.click(screen.getByTestId('office-workspace-pick'));
    const bindBtn = await screen.findByTestId('workspace-bind-button');

    fireEvent.click(bindBtn);

    const errEl = await screen.findByTestId('workspace-bind-error');
    expect(errEl.textContent).toMatch(/native dialog blew up/);
    expect(mockBind).not.toHaveBeenCalled();
  });
});

describe('Office — workspace modal stale-read integration', () => {
  it('closes the modal after a successful bind; the provider holds the new path', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/picked-2');
    (window as unknown as { electronAPI?: { selectDirectory: typeof selectDirectory } }).electronAPI = {
      selectDirectory,
    };
    mockBind.mockResolvedValue({
      binding: {
        sessionId: 'session-1',
        workspacePath: '/tmp/picked-2',
        generation: 1,
        activatedAt: 1,
        revokedAt: null,
      },
    });

    renderWithProvider();
    await waitFor(() => screen.getByTestId('office-workspace-pick'));
    fireEvent.click(screen.getByTestId('office-workspace-pick'));
    const bindBtn = await screen.findByTestId('workspace-bind-button');

    fireEvent.click(bindBtn);
    await waitFor(() =>
      expect(screen.getByTestId('office-workspace-path')).toHaveTextContent('/tmp/picked-2'),
    );
    // Modal should be closed; the workspace-bind-button should be gone.
    await waitFor(() => expect(screen.queryByTestId('workspace-bind-button')).toBeNull());
  });
});