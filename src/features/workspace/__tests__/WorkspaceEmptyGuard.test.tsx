import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkspaceEmptyGuard } from '../WorkspaceEmptyGuard';

interface FakeWindow {
  electronAPI?: { selectDirectory: (opts: { intent: string }) => Promise<string | null> };
}

const mockBind = vi.fn();

vi.mock('../../../shared/lib/workspaceContext', () => ({
  useOptionalWorkspaceContext: () => ({ bind: mockBind }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  (window as unknown as FakeWindow).electronAPI = {
    selectDirectory: vi.fn(),
  };
  mockBind.mockResolvedValue(undefined);
});

function renderGuard(feature: 'changes' | 'preview' | 'office' = 'changes') {
  return render(<WorkspaceEmptyGuard feature={feature} />);
}

describe('WorkspaceEmptyGuard — rendering', () => {
  it('renders the guard with correct title for changes feature', () => {
    renderGuard('changes');
    expect(screen.getByTestId('workspace-empty-guard')).toBeInTheDocument();
    expect(screen.getByText('绑定工作区以查看变更')).toBeInTheDocument();
  });

  it('renders correct title for preview feature', () => {
    renderGuard('preview');
    expect(screen.getByText('绑定工作区以预览文档')).toBeInTheDocument();
  });

  it('renders correct title for office feature', () => {
    renderGuard('office');
    expect(screen.getByText('绑定工作区以管理文档')).toBeInTheDocument();
  });

  it('renders bind button', () => {
    renderGuard();
    expect(screen.getByTestId('workspace-empty-guard-bind')).toBeInTheDocument();
  });
});

describe('WorkspaceEmptyGuard — bind flow', () => {
  it('calls selectDirectory with { intent: "open" } on bind click', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/picked');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    renderGuard();

    fireEvent.click(screen.getByTestId('workspace-empty-guard-bind'));

    await waitFor(() => {
      expect(selectDirectory).toHaveBeenCalledWith({ intent: 'open' });
    });
  });

  it('does not call bind when user cancels the directory picker', async () => {
    const selectDirectory = vi.fn().mockResolvedValue(null);
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    renderGuard();

    fireEvent.click(screen.getByTestId('workspace-empty-guard-bind'));

    await waitFor(() => {
      expect(selectDirectory).toHaveBeenCalled();
    });
    expect(mockBind).not.toHaveBeenCalled();
  });

  it('calls bind with picked path on successful pick', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/ws-a');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    renderGuard();

    fireEvent.click(screen.getByTestId('workspace-empty-guard-bind'));

    await waitFor(() => {
      expect(mockBind).toHaveBeenCalledWith('/tmp/ws-a');
    });
  });

  it('shows error when bind rejects', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/tmp/ws-a');
    (window as unknown as FakeWindow).electronAPI = { selectDirectory };
    mockBind.mockRejectedValue(new Error('bind failed'));
    renderGuard();

    fireEvent.click(screen.getByTestId('workspace-empty-guard-bind'));

    await waitFor(() => {
      expect(screen.getByText('bind failed')).toBeInTheDocument();
    });
  });
});
