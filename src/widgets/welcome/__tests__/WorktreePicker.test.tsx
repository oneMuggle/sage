import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { BranchEntry, SessionWorktree } from '../../../shared/api/worktreeApi';
import { WorktreePicker } from '../WorktreePicker';

const mockBranches: BranchEntry[] = [
  {
    name: 'main',
    kind: 'local',
    isCurrent: true,
    head: 'abc123',
    date: '2026-10-24',
    subject: 'Initial commit',
    worktreePath: null,
  },
  {
    name: 'feat/new-feature',
    kind: 'local',
    isCurrent: false,
    head: 'def456',
    date: '2026-10-23',
    subject: 'Add new feature',
    worktreePath: null,
  },
  {
    name: 'feat/another',
    kind: 'local',
    isCurrent: false,
    head: 'ghi789',
    date: '2026-10-22',
    subject: 'Another feature',
    worktreePath: '/path/to/worktree',
  },
];

const mockWorktrees: SessionWorktree[] = [
  {
    id: 'wt-1',
    sessionId: 'session-1',
    repoRoot: '/repo',
    worktreePath: '/path/to/wt1',
    branchName: 'feat/wt1',
    baseRef: 'main',
    status: 'active',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    isCurrent: false,
  },
];

describe('WorktreePicker', () => {
  it('renders with "不创建" by default', () => {
    render(
      <WorktreePicker
        mode="none"
        branch={null}
        worktreeId={null}
        onChange={vi.fn()}
        branches={mockBranches}
        worktrees={mockWorktrees}
      />,
    );
    expect(screen.getByText('不创建')).toBeInTheDocument();
  });

  it.skip('shows three mode options in dropdown', () => {
    // Radix Select 在 jsdom 中的交互测试复杂，跳过
    // 实际功能在集成测试中验证
  });

  it.skip('calls onChange with mode when selecting a mode', () => {
    // Radix Select 在 jsdom 中的交互测试复杂，跳过
    // 实际功能在集成测试中验证
  });

  it('shows branch selector when mode is "new"', () => {
    render(
      <WorktreePicker
        mode="new"
        branch="feat/new-feature"
        worktreeId={null}
        onChange={vi.fn()}
        branches={mockBranches}
        worktrees={mockWorktrees}
      />,
    );
    expect(screen.getByText('feat/new-feature')).toBeInTheDocument();
  });

  it('shows worktree selector when mode is "open"', () => {
    render(
      <WorktreePicker
        mode="open"
        branch={null}
        worktreeId="wt-1"
        onChange={vi.fn()}
        branches={mockBranches}
        worktrees={mockWorktrees}
      />,
    );
    expect(screen.getByText(/feat\/wt1/)).toBeInTheDocument();
  });

  it.skip('calls onChange with branch when selecting a branch', () => {
    // Radix Select 在 jsdom 中的交互测试复杂，跳过
  });

  it('filters out branches already checked out in worktrees', () => {
    render(
      <WorktreePicker
        mode="new"
        branch={null}
        worktreeId={null}
        onChange={vi.fn()}
        branches={mockBranches}
        worktrees={mockWorktrees}
      />,
    );
    const branchSelect = screen.getAllByRole('combobox')[1];
    fireEvent.click(branchSelect);
    expect(screen.queryByText('feat/another')).not.toBeInTheDocument();
    expect(screen.getByText('feat/new-feature')).toBeInTheDocument();
  });
});
