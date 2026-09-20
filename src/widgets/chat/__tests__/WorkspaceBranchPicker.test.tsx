// src/widgets/chat/__tests__/WorkspaceBranchPicker.test.tsx
// worktree 模式 (2026-09-18)：分支选择器组件测试 —— worktreeApi 与
// workspace context 全 mock。
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkspaceBranchPicker } from '../WorkspaceBranchPicker';

const mockBranches = vi.fn();
const mockCreate = vi.fn();
const mockMerge = vi.fn();
const mockRemove = vi.fn();
const mockList = vi.fn();
const mockRefresh = vi.fn();

vi.mock('../../../shared/api/worktreeApi', () => ({
  worktreeApi: {
    branches: (...a: unknown[]) => mockBranches(...a),
    create: (...a: unknown[]) => mockCreate(...a),
    merge: (...a: unknown[]) => mockMerge(...a),
    remove: (...a: unknown[]) => mockRemove(...a),
    list: (...a: unknown[]) => mockList(...a),
  },
}));

vi.mock('../../../shared/api/workspaceApi', () => ({
  workspaceApi: { bind: vi.fn().mockResolvedValue({}) },
}));

vi.mock('../../../shared/lib/workspaceContext', () => ({
  useOptionalWorkspaceContext: () => ({
    sessionId: 's1',
    binding: {
      sessionId: 's1',
      workspacePath: '/home/me/repo',
      generation: 1,
      activatedAt: 0,
      revokedAt: null,
    },
    status: 'ready',
    error: null,
    bind: vi.fn(),
    revoke: vi.fn(),
    refresh: mockRefresh,
  }),
}));

const branchesPayload = {
  repoRoot: '/home/me/repo',
  currentBranch: 'main',
  isGit: true,
  branches: [
    {
      name: 'main',
      kind: 'local' as const,
      isCurrent: true,
      head: 'abc1234',
      date: '2026-09-18 10:00:00 +0800',
      subject: 'init',
      worktreePath: '/home/me/repo',
    },
    {
      name: 'feat/x',
      kind: 'local' as const,
      isCurrent: false,
      head: 'def5678',
      date: '2026-09-17 09:00:00 +0800',
      subject: 'work',
      worktreePath: null,
    },
  ],
  worktrees: [],
};

describe('WorkspaceBranchPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockBranches.mockResolvedValue(branchesPayload);
    mockCreate.mockResolvedValue({
      ok: true,
      message: 'ok',
      workspacePath: '/wt',
      generation: 2,
      worktree: null,
    });
  });

  it('renders chip with directory and branch after loading', async () => {
    render(<WorkspaceBranchPicker sessionId="s1" />);
    const trigger = screen.getByTestId('workspace-branch-picker');
    await waitFor(() => {
      expect(trigger.textContent).toContain('repo');
      expect(trigger.textContent).toContain('main');
    });
  });

  it('opens popover and lists branches; clicking a free branch opens a worktree', async () => {
    render(<WorkspaceBranchPicker sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('workspace-branch-picker').textContent).toContain('main');
    });
    fireEvent.click(screen.getByTestId('workspace-branch-picker'));
    await waitFor(() => expect(screen.getByText('feat/x')).toBeInTheDocument());
    fireEvent.click(screen.getByText('feat/x'));
    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith('s1', 'open', 'feat/x', 'HEAD');
    });
  });

  it('Enter in the filter input creates a new branch worktree from current branch', async () => {
    render(<WorkspaceBranchPicker sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('workspace-branch-picker').textContent).toContain('main');
    });
    fireEvent.click(screen.getByTestId('workspace-branch-picker'));
    const input = await waitFor(() => screen.getByPlaceholderText(/新分支名/));
    fireEvent.change(input, { target: { value: 'feat/new' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith('s1', 'new', 'feat/new', 'main');
    });
  });

  it('renders nothing without a session', () => {
    const { container } = render(<WorkspaceBranchPicker sessionId={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
