import { useMemo } from 'react';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../shared/ui/Select/Select';
import type { BranchEntry, SessionWorktree } from '../../shared/api/worktreeApi';

export type WorktreeMode = 'none' | 'new' | 'open';

export interface WorktreePickerValue {
  mode: WorktreeMode;
  branch: string | null;
  worktreeId: string | null;
}

export interface WorktreePickerProps {
  mode: WorktreeMode;
  branch: string | null;
  worktreeId: string | null;
  onChange: (value: WorktreePickerValue) => void;
  branches: BranchEntry[];
  worktrees: SessionWorktree[];
}

export function WorktreePicker({
  mode,
  branch,
  worktreeId,
  onChange,
  branches,
  worktrees,
}: WorktreePickerProps) {
  // 过滤掉已被 worktree 检出的分支（不能重复检出）
  const availableBranches = useMemo(() => {
    return branches.filter((b) => !b.worktreePath);
  }, [branches]);

  const activeWorktrees = useMemo(() => {
    return worktrees.filter((wt) => wt.status === 'active');
  }, [worktrees]);

  const handleModeChange = (newMode: string) => {
    onChange({
      mode: newMode as WorktreeMode,
      branch: null,
      worktreeId: null,
    });
  };

  const handleBranchChange = (newBranch: string) => {
    onChange({
      mode: 'new',
      branch: newBranch,
      worktreeId: null,
    });
  };

  const handleWorktreeChange = (newWorktreeId: string) => {
    onChange({
      mode: 'open',
      branch: null,
      worktreeId: newWorktreeId,
    });
  };

  return (
    <div className="flex items-center gap-2">
      <Select value={mode} onValueChange={handleModeChange}>
        <SelectTrigger aria-label="Worktree 选项" className="w-40">
          <SelectValue placeholder="Worktree 选项" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">不创建</SelectItem>
          <SelectItem value="new">新建 worktree</SelectItem>
          <SelectItem value="open">使用已有</SelectItem>
        </SelectContent>
      </Select>

      {mode === 'new' && (
        <Select value={branch ?? ''} onValueChange={handleBranchChange}>
          <SelectTrigger aria-label="选择分支" className="w-48">
            <SelectValue placeholder="选择分支" />
          </SelectTrigger>
          <SelectContent>
            {availableBranches.length > 0 ? (
              availableBranches.map((b) => (
                <SelectItem key={b.name} value={b.name}>
                  {b.name}
                </SelectItem>
              ))
            ) : (
              <div className="px-2 py-1.5 text-sm text-muted">无可用分支</div>
            )}
          </SelectContent>
        </Select>
      )}

      {mode === 'open' && (
        <Select value={worktreeId ?? ''} onValueChange={handleWorktreeChange}>
          <SelectTrigger aria-label="选择 worktree" className="w-48">
            <SelectValue placeholder="选择 worktree" />
          </SelectTrigger>
          <SelectContent>
            {activeWorktrees.length > 0 ? (
              activeWorktrees.map((wt) => (
                <SelectItem key={wt.id} value={wt.id}>
                  {wt.branchName ?? wt.worktreePath.split('/').pop()}
                </SelectItem>
              ))
            ) : (
              <div className="px-2 py-1.5 text-sm text-muted">无可用 worktree</div>
            )}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}
