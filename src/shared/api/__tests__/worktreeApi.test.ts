/**
 * r93: worktreeApi 单元测试——wire(snake_case)→camelCase 映射、状态回退与通道约定。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { worktreeApi } from '../worktreeApi';

const WIRE = {
  id: 'wt-1',
  session_id: 's-1',
  repo_root: 'C:/repo',
  worktree_path: 'C:/repo/.wt/wt-1',
  branch_name: 'feat/x',
  base_ref: 'HEAD',
  status: 'active',
  created_at: 100,
  updated_at: 200,
  is_current: true,
};

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('worktreeApi wire 映射', () => {
  it('mapWorktree: snake_case→camelCase，status 合法值原样保留', async () => {
    mockInvoke.mockResolvedValueOnce({ worktrees: [WIRE] });
    const r = await worktreeApi.list('s-1');
    expect(r[0]).toMatchObject({
      id: 'wt-1',
      sessionId: 's-1',
      repoRoot: 'C:/repo',
      worktreePath: 'C:/repo/.wt/wt-1',
      branchName: 'feat/x',
      baseRef: 'HEAD',
      status: 'active',
      isCurrent: true,
    });
  });

  it('mapWorktree: 未知 status 回退 active；branch_name 缺省为 null', async () => {
    mockInvoke.mockResolvedValueOnce({
      worktrees: [{ ...WIRE, status: 'weird', branch_name: null, is_current: false }],
    });
    const r = await worktreeApi.list('s-1');
    expect(r[0].status).toBe('active');
    expect(r[0].branchName).toBeNull();
    expect(r[0].isCurrent).toBe(false);
  });

  it('mapWorktree: merged/discarded 状态直通', async () => {
    mockInvoke.mockResolvedValueOnce({ worktrees: [{ ...WIRE, status: 'merged' }] });
    expect((await worktreeApi.list('s-1'))[0].status).toBe('merged');
    mockInvoke.mockResolvedValueOnce({ worktrees: [{ ...WIRE, status: 'discarded' }] });
    expect((await worktreeApi.list('s-1'))[0].status).toBe('discarded');
  });
});

describe('worktreeApi 通道', () => {
  it('branches() 默认 includeRemote=true 并映射分支/占用清单', async () => {
    mockInvoke.mockResolvedValueOnce({
      repo_root: 'C:/repo',
      current_branch: 'main',
      is_git: true,
      branches: [
        {
          name: 'main', kind: 'local', is_current: true, head: 'abc',
          date: '2026-09-20', subject: 's', worktree_path: null,
        },
        {
          name: 'origin/dev', kind: 'weird', is_current: false, head: 'def',
          date: '', subject: '', worktree_path: 'C:/other',
        },
      ],
      worktrees: [WIRE],
    });
    const r = await worktreeApi.branches('s-1');
    expect(mockInvoke).toHaveBeenCalledWith('worktree_branches', { sessionId: 's-1', includeRemote: true });
    expect(r.repoRoot).toBe('C:/repo');
    expect(r.currentBranch).toBe('main');
    expect(r.isGit).toBe(true);
    expect(r.branches[0].kind).toBe('local');
    expect(r.branches[1].kind).toBe('local'); // 未知 kind 回退 local
    expect(r.worktrees[0].sessionId).toBe('s-1');
  });

  it('branches() 显式 includeRemote=false', async () => {
    mockInvoke.mockResolvedValueOnce({
      repo_root: '', current_branch: '', is_git: false, branches: [], worktrees: [],
    });
    await worktreeApi.branches('s-1', false);
    expect(mockInvoke).toHaveBeenCalledWith('worktree_branches', { sessionId: 's-1', includeRemote: false });
  });

  it('list() invokes worktree_list', async () => {
    mockInvoke.mockResolvedValueOnce({ worktrees: [] });
    await worktreeApi.list('s-1');
    expect(mockInvoke).toHaveBeenCalledWith('worktree_list', { sessionId: 's-1' });
  });

  it('create() 默认 baseRef=HEAD；worktree 为 null 时原样透传', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true, message: 'created', workspace_path: 'C:/wt', generation: 3, worktree: null,
    });
    const r = await worktreeApi.create('s-1', 'new', 'feat/y');
    expect(mockInvoke).toHaveBeenCalledWith('worktree_create', {
      sessionId: 's-1', mode: 'new', branch: 'feat/y', baseRef: 'HEAD',
    });
    expect(r).toEqual({ ok: true, message: 'created', workspacePath: 'C:/wt', generation: 3, worktree: null });
  });

  it('create() 显式 baseRef 且映射 worktree wire', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true, message: '', workspace_path: null, generation: null, worktree: WIRE,
    });
    const r = await worktreeApi.create('s-1', 'checkout', 'feat/z', 'origin/main');
    expect(mockInvoke).toHaveBeenCalledWith('worktree_create', {
      sessionId: 's-1', mode: 'checkout', branch: 'feat/z', baseRef: 'origin/main',
    });
    expect(r.worktree?.sessionId).toBe('s-1');
  });

  it('merge() 解包 result 信封', async () => {
    const outcome = {
      ok: true, code: 'merged', message: '', branch: 'feat/x',
      base_head: 'a', merge_head: 'b', files_changed: ['f1'], conflict_files: [],
    };
    mockInvoke.mockResolvedValueOnce({ result: outcome });
    const r = await worktreeApi.merge('s-1', 'wt-1');
    expect(mockInvoke).toHaveBeenCalledWith('worktree_merge', { sessionId: 's-1', worktreeId: 'wt-1' });
    expect(r).toEqual(outcome);
  });

  it('remove() 默认 deleteBranch=false', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true, message: 'removed', workspace_path: null, generation: null, worktree: null,
    });
    await worktreeApi.remove('s-1', 'wt-1');
    expect(mockInvoke).toHaveBeenCalledWith('worktree_delete', {
      sessionId: 's-1', worktreeId: 'wt-1', deleteBranch: false,
    });
  });

  it('remove() 可携带 deleteBranch=true', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true, message: '', workspace_path: null, generation: null, worktree: null,
    });
    await worktreeApi.remove('s-1', 'wt-1', true);
    expect(mockInvoke).toHaveBeenCalledWith('worktree_delete', {
      sessionId: 's-1', worktreeId: 'wt-1', deleteBranch: true,
    });
  });

  it('invoke 拒绝经 handleApiError 包装', async () => {
    mockInvoke.mockRejectedValueOnce({ error: 'IPC_DOWN', message: 'down' });
    await expect(worktreeApi.list('s-1')).rejects.toMatchObject({ code: 'IPC_DOWN' });
  });
});
