// src/widgets/chat/WorkspaceBranchPicker.tsx
//
// 会话级 worktree / 分支选择器（worktree 模式 P1，2026-09-18）。
// 聊天页头部 chip：显示「目录名 · 分支」，点击弹出 Radix Popover：
//   1. 主工作区（回到绑定前的原目录）
//   2. 已登记的会话 worktree（切换 / 合并 / 移除）
//   3. 本地 & 远端分支清单（已被占用的禁选）——点本地分支 = open 模式
//   4. 输入新分支名 + Enter = new 模式（当前分支为基新建 worktree）
//
// 数据面复用 SessionWorkspaceProvider 的 refresh()：动作成功后绑定即
// generation 自增，工具面自动落到新目录。

import * as Popover from '@radix-ui/react-popover';
import {
  Check,
  GitBranch,
  GitMerge,
  FolderGit2,
  Loader2,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';

import { workspaceApi } from '../../shared/api/workspaceApi';
import {
  worktreeApi,
  type BranchesResponse,
  type SessionWorktree,
  type WorktreeMode,
} from '../../shared/api/worktreeApi';
import { useOptionalWorkspaceContext } from '../../shared/lib/workspaceContext';

interface WorkspaceBranchPickerProps {
  sessionId: string | null;
}

function baseName(p: string): string {
  const parts = p.replace(/[/\\]+$/, '').split(/[/\\]/);
  return parts[parts.length - 1] || p;
}

export function WorkspaceBranchPicker({ sessionId }: WorkspaceBranchPickerProps) {
  const ctx = useOptionalWorkspaceContext();
  const workspacePath = ctx?.binding?.workspacePath;
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<BranchesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('');

  const reload = useCallback(async (): Promise<BranchesResponse | null> => {
    if (!sessionId) return null;
    try {
      const next = await worktreeApi.branches(sessionId);
      setData(next);
      return next;
    } catch {
      return null; // 非 git / 未绑定：chip 退化为纯目录名
    }
  }, [sessionId]);

  useEffect(() => {
    setData(null);
    // chip 需要展示分支名：挂载即静默拉一次（失败退化为纯目录名）
    void reload();
  }, [sessionId, workspacePath, reload]);

  const handleOpenChange = (next: boolean): void => {
    setOpen(next);
    if (next) {
      setFilter('');
      setLoading(true);
      void reload().finally(() => setLoading(false));
    }
  };

  const runAction = useCallback(
    async (mode: WorktreeMode, branch: string, baseRef = 'HEAD'): Promise<boolean> => {
      if (!sessionId || busy) return false;
      setBusy(true);
      try {
        const r = await worktreeApi.create(sessionId, mode, branch, baseRef);
        if (!r.ok) {
          toast.error(r.message);
          return false;
        }
        toast.success(r.message);
        await ctx?.refresh();
        await reload();
        setOpen(false);
        return true;
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : '操作失败');
        return false;
      } finally {
        setBusy(false);
      }
    },
    [sessionId, busy, ctx, reload],
  );

  const mergeWorktree = useCallback(
    async (wt: SessionWorktree): Promise<void> => {
      if (!sessionId || busy || !wt.branchName) return;
      setBusy(true);
      try {
        const result = await worktreeApi.merge(sessionId, wt.id);
        if (result.ok) {
          toast.success(result.message);
        } else {
          toast.error(result.message);
        }
        await reload();
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : '合并失败');
      } finally {
        setBusy(false);
      }
    },
    [sessionId, busy, reload],
  );

  const removeWorktree = useCallback(
    async (wt: SessionWorktree): Promise<void> => {
      if (!sessionId || busy) return;
      setBusy(true);
      try {
        const r = await worktreeApi.remove(sessionId, wt.id, false);
        toast[r.ok ? 'success' : 'error'](r.message);
        await ctx?.refresh();
        await reload();
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : '移除失败');
      } finally {
        setBusy(false);
      }
    },
    [sessionId, busy, ctx, reload],
  );

  const q = filter.trim().toLowerCase();
  const localBranches = useMemo(
    () =>
      (data?.branches ?? []).filter(
        (b) => b.kind === 'local' && (!q || b.name.toLowerCase().includes(q)),
      ),
    [data, q],
  );
  const remoteBranches = useMemo(
    () =>
      (data?.branches ?? []).filter(
        (b) => b.kind === 'remote' && (!q || b.name.toLowerCase().includes(q)),
      ),
    [data, q],
  );
  const registered = useMemo(
    () => (data?.worktrees ?? []).filter((w) => w.status !== 'discarded'),
    [data],
  );

  if (!sessionId || !workspacePath) return null;

  const isGit = data?.isGit ?? true;
  const branchLabel = data?.currentBranch ?? "";
  const inWorktree = registered.find((w) => w.worktreePath === workspacePath);

  return (
    <Popover.Root open={open} onOpenChange={handleOpenChange}>
      <Popover.Trigger asChild>
        <button
          type="button"
          data-testid="workspace-branch-picker"
          disabled={busy}
          className="flex items-center gap-1.5 max-w-64 text-xs text-text-secondary bg-surface border border-border rounded-radius-sm px-2 py-1 hover:bg-bg-hover disabled:opacity-50 truncate"
          title={`工作区 ${workspacePath}${data?.currentBranch ? ` · ${data.currentBranch}` : ''}`}
        >
          {isGit ? (
            <GitBranch className="w-3.5 h-3.5 shrink-0" />
          ) : (
            <FolderGit2 className="w-3.5 h-3.5 shrink-0 opacity-50" />
          )}
          <span className="truncate">
            {baseName(workspacePath)}
            {branchLabel ? ` · ${branchLabel}` : ''}
          </span>
          {inWorktree && (
            <span className="text-[10px] text-primary shrink-0">worktree</span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-96 max-h-[70vh] overflow-y-auto rounded-radius-md border border-border bg-surface shadow-xl"
        >
          <div className="p-2 border-b border-border">
            <input
              autoFocus
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && filter.trim() && isGit) {
                  e.preventDefault();
                  void runAction('new', filter.trim(), data?.currentBranch || 'HEAD');
                }
              }}
              placeholder={
                isGit
                  ? '输入新分支名回车创建 worktree，或过滤下方列表…'
                  : '当前目录不是 git 仓库'
              }
              className="w-full text-xs bg-bg-input border border-border rounded-radius-sm px-2 py-1.5 outline-none focus:border-primary"
            />
          </div>

          {loading && (
            <div className="flex items-center gap-2 p-3 text-xs text-text-secondary">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> 加载分支…
            </div>
          )}

          {!loading && isGit && (
            <>
              {data && (
                <Row
                  icon={<FolderGit2 className="w-3.5 h-3.5" />}
                  title={baseName(data.repoRoot)}
                  subtitle={`主工作区 · ${data.currentBranch || '无提交'}`}
                  active={workspacePath === data.repoRoot}
                  onClick={() => {
                    if (workspacePath !== data.repoRoot) {
                      void (async () => {
                        setBusy(true);
                        try {
                          await workspaceApi.bind(sessionId, data.repoRoot);
                          await ctx?.refresh();
                          await reload();
                          setOpen(false);
                          toast.success('已回到主工作区');
                        } catch (e: unknown) {
                          toast.error(e instanceof Error ? e.message : '切换失败');
                        } finally {
                          setBusy(false);
                        }
                      })();
                    } else {
                      setOpen(false);
                    }
                  }}
                />
              )}
              {registered.length > 0 && (
                <Section>Worktree</Section>
              )}
              {registered.map((wt) => (
                <Row
                  key={wt.id}
                  icon={<GitBranch className="w-3.5 h-3.5" />}
                  title={wt.branchName || baseName(wt.worktreePath)}
                  subtitle={baseName(wt.worktreePath)}
                  badge={wt.status === 'merged' ? '已合并' : undefined}
                  active={wt.isCurrent}
                  actions={
                    <>
                      {wt.branchName && (
                        <button
                          type="button"
                          title="合并回主工作区"
                          disabled={busy}
                          onClick={(e) => {
                            e.stopPropagation();
                            void mergeWorktree(wt);
                          }}
                          className="p-1 rounded hover:bg-bg-hover text-text-secondary"
                        >
                          <GitMerge className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        title="移除 worktree"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          void removeWorktree(wt);
                        }}
                        className="p-1 rounded hover:bg-bg-hover text-text-secondary"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </>
                  }
                  onClick={() => {
                    if (!wt.isCurrent && wt.branchName) {
                      void runAction('open', wt.branchName);
                    } else {
                      setOpen(false);
                    }
                  }}
                />
              ))}
              <Section>本地分支</Section>
              {localBranches.map((b) => {
                const occupiedElsewhere =
                  !!b.worktreePath && b.worktreePath !== workspacePath;
                const atCurrent =
                  b.worktreePath === workspacePath ||
                  (b.isCurrent && workspacePath === data?.repoRoot);
                return (
                  <Row
                    key={b.name}
                    icon={<GitBranch className="w-3.5 h-3.5" />}
                    title={b.name}
                    subtitle={`${b.subject} · ${b.date.slice(0, 10)}`}
                    active={atCurrent}
                    disabled={busy || occupiedElsewhere || b.isCurrent}
                    titleHint={
                      occupiedElsewhere ? `已在 ${b.worktreePath} 检出` : b.name
                    }
                    onClick={() => void runAction('open', b.name)}
                  />
                );
              })}
              {remoteBranches.length > 0 && <Section>远端分支</Section>}
              {remoteBranches.slice(0, 30).map((b) => (
                <Row
                  key={b.name}
                  icon={<GitBranch className="w-3.5 h-3.5 opacity-60" />}
                  title={b.name}
                  subtitle={`${b.subject} · ${b.date.slice(0, 10)}`}
                  disabled
                  titleHint="远端分支请先拉取；本地分支点击即以 worktree 检出"
                />
              ))}
            </>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function Section({ children }: { children: ReactNode }) {
  return (
    <div className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide text-text-tertiary">
      {children}
    </div>
  );
}

interface RowProps {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  badge?: string;
  active?: boolean;
  disabled?: boolean;
  titleHint?: string;
  actions?: ReactNode;
  onClick?: () => void;
}

function Row({
  icon,
  title,
  subtitle,
  badge,
  active,
  disabled,
  titleHint,
  actions,
  onClick,
}: RowProps) {
  return (
    <div
      role={onClick ? 'button' : undefined}
      title={titleHint ?? title}
      tabIndex={onClick && !disabled ? 0 : -1}
      onClick={disabled ? undefined : onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !disabled) onClick?.();
      }}
      className={`group flex items-center gap-2 px-3 py-1.5 text-xs max-w-full ${
        disabled
          ? 'opacity-45 cursor-default'
          : onClick
            ? 'cursor-pointer hover:bg-bg-hover'
            : ''
      } ${active ? 'bg-bg-hover' : ''}`}
    >
      <span className="shrink-0 text-text-secondary">{icon}</span>
      <span className="flex-1 min-w-0">
        <span className="block truncate text-text">{title}</span>
        {subtitle && (
          <span className="block truncate text-[10px] text-text-tertiary">{subtitle}</span>
        )}
      </span>
      {badge && (
        <span className="shrink-0 text-[10px] text-amber-600 dark:text-amber-400">{badge}</span>
      )}
      {actions}
      {active && <Check className="w-3.5 h-3.5 shrink-0 text-primary" />}
    </div>
  );
}
