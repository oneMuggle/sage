// src/shared/api/worktreeApi.ts
//
// 会话级 worktree 模式（2026-09-18）渲染端 client。
// 走 desktopInvoke 命令面（electron/commands.ts 的 worktree_* 映射），
// wire 为后端 snake_case，这里统一转 camelCase 供组件消费。

import { invoke } from './desktopInvoke';
import { handleApiError } from './utils';

/** 分支条目（picker 列表行） */
export interface BranchEntry {
  name: string;
  kind: 'local' | 'remote';
  isCurrent: boolean;
  head: string;
  date: string;
  subject: string;
  /** 非空 = 分支已在某 worktree 检出（不能再开第二个） */
  worktreePath: string | null;
}

/** 已登记的会话 worktree */
export interface SessionWorktree {
  id: string;
  sessionId: string;
  repoRoot: string;
  worktreePath: string;
  branchName: string | null;
  baseRef: string;
  status: 'active' | 'merged' | 'discarded';
  createdAt: number;
  updatedAt: number;
  isCurrent: boolean;
}

export interface BranchesResponse {
  repoRoot: string;
  currentBranch: string;
  isGit: boolean;
  branches: BranchEntry[];
  worktrees: SessionWorktree[];
}

export type WorktreeMode = 'new' | 'open' | 'checkout';

export interface WorktreeActionResult {
  ok: boolean;
  message: string;
  workspacePath: string | null;
  generation: number | null;
  worktree: SessionWorktree | null;
}

export interface MergeOutcome {
  ok: boolean;
  code: string;
  message: string;
  branch: string;
  base_head: string;
  merge_head: string;
  files_changed: string[];
  conflict_files: string[];
}

interface BranchWire {
  name: string;
  kind: string;
  is_current: boolean;
  head: string;
  date: string;
  subject: string;
  worktree_path: string | null;
}

interface WorktreeWire {
  id: string;
  session_id: string;
  repo_root: string;
  worktree_path: string;
  branch_name: string | null;
  base_ref: string;
  status: string;
  created_at: number;
  updated_at: number;
  is_current: boolean;
}

function mapWorktree(row: WorktreeWire): SessionWorktree {
  return {
    id: row.id,
    sessionId: row.session_id,
    repoRoot: row.repo_root,
    worktreePath: row.worktree_path,
    branchName: row.branch_name,
    baseRef: row.base_ref,
    status: (row.status === 'merged' || row.status === 'discarded'
      ? row.status
      : 'active') as SessionWorktree['status'],
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    isCurrent: row.is_current,
  };
}

function mapBranch(row: BranchWire): BranchEntry {
  return {
    name: row.name,
    kind: row.kind === 'remote' ? 'remote' : 'local',
    isCurrent: row.is_current,
    head: row.head,
    date: row.date,
    subject: row.subject,
    worktreePath: row.worktree_path,
  };
}

export const worktreeApi = {
  /** 分支 picker 数据源：分支清单 + worktree 占用 + 已登记 worktree。 */
  async branches(sessionId: string, includeRemote = true): Promise<BranchesResponse> {
    try {
      const response = await invoke<{
        repo_root: string;
        current_branch: string;
        is_git: boolean;
        branches: BranchWire[];
        worktrees: WorktreeWire[];
      }>('worktree_branches', { sessionId, includeRemote });
      return {
        repoRoot: response.repo_root,
        currentBranch: response.current_branch,
        isGit: response.is_git,
        branches: response.branches.map(mapBranch),
        worktrees: response.worktrees.map(mapWorktree),
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async list(sessionId: string): Promise<SessionWorktree[]> {
    try {
      const response = await invoke<{ worktrees: WorktreeWire[] }>('worktree_list', {
        sessionId,
      });
      return response.worktrees.map(mapWorktree);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async create(
    sessionId: string,
    mode: WorktreeMode,
    branch: string,
    baseRef = 'HEAD',
  ): Promise<WorktreeActionResult> {
    try {
      const response = await invoke<{
        ok: boolean;
        message: string;
        workspace_path: string | null;
        generation: number | null;
        worktree: WorktreeWire | null;
      }>('worktree_create', { sessionId, mode, branch, baseRef });
      return {
        ok: response.ok,
        message: response.message,
        workspacePath: response.workspace_path,
        generation: response.generation,
        worktree: response.worktree ? mapWorktree(response.worktree) : null,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async merge(sessionId: string, worktreeId: string): Promise<MergeOutcome> {
    try {
      const response = await invoke<{ result: MergeOutcome }>('worktree_merge', {
        sessionId,
        worktreeId,
      });
      return response.result;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async remove(
    sessionId: string,
    worktreeId: string,
    deleteBranch = false,
  ): Promise<WorktreeActionResult> {
    try {
      const response = await invoke<{
        ok: boolean;
        message: string;
        workspace_path: string | null;
        generation: number | null;
        worktree: WorktreeWire | null;
      }>('worktree_delete', { sessionId, worktreeId, deleteBranch });
      return {
        ok: response.ok,
        message: response.message,
        workspacePath: response.workspace_path,
        generation: response.generation,
        worktree: response.worktree ? mapWorktree(response.worktree) : null,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
