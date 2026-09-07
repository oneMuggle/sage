// src/widgets/chat/changes/ChangesSection.tsx
//
// U1 变更面板 (对标增强第二轮, docs/plans/2026-09-06-parity-round2):
// 会话工作区的 git 变更清单 + 按文件 diff 视图。
// 数据源: GET /sessions/{id}/workspace/changes[/diff] (复用 git_status /
// git_diff 工具的实现口径)。渲染 diff 复用 ShikiCodeBlock 的 diff 语言支持。
//
// U19 可操作化 (对标增强第四轮批次 B, docs/plans/2026-09-07_coding-agent-parity-round4.md):
// 逐文件撤销 (git checkout --) + 逐 hunk 勾选反向应用 (git apply --reverse)。
// 撤销只作用于工作区改动,不碰暂存区;未跟踪文件走显式删除。

import { ArrowLeft, GitBranch, RefreshCw, Trash2, Undo2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { workspaceApi } from '../../../shared/api/workspaceApi';
import type { WorkspaceChanges } from '../../../shared/api/workspaceApi';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

import { splitDiffHunks } from './diffHunks';

interface ChangesSectionProps {
  sessionId: string | null;
}

/** worktree 状态 → 徽章配色（porcelain v1 首两列） */
function statusColor(status: string): string {
  if (!status || status === '?') return 'text-text-secondary';
  if (status === '!') return 'text-red-500';
  return 'text-green-600 dark:text-green-400';
}

function statusLabel(entry: { indexStatus: string; worktreeStatus: string }): string {
  const idx = entry.indexStatus;
  const wt = entry.worktreeStatus;
  if (idx === 'A') return '新增';
  if (idx === 'D' || wt === 'D') return '删除';
  if (idx === 'R') return '重命名';
  if (wt === '?') return '未跟踪';
  if (wt === 'M') return '已修改';
  return (idx + wt).trim() || '变更';
}

export function ChangesSection({ sessionId }: ChangesSectionProps) {
  const [changes, setChanges] = useState<WorkspaceChanges | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffTruncated, setDiffTruncated] = useState(false);
  // U19: 勾选待撤销的 hunk (0-based,与后端 revert-hunks 序号一致)
  const [selectedHunks, setSelectedHunks] = useState<Set<number>>(new Set());
  const [reverting, setReverting] = useState(false);

  const refresh = useCallback(() => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    workspaceApi
      .getChanges(sessionId)
      .then(setChanges)
      .catch((e: unknown) => {
        // 友好处理 workspace_not_bound 错误
        const errMsg = e instanceof Error ? e.message : String(e);
        if (errMsg.includes('workspace_not_bound') || errMsg.includes('尚未绑定工作区')) {
          setError('当前会话尚未绑定工作区，无法查看变更');
        } else {
          setError(errMsg);
        }
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    setChanges(null);
    setSelectedPath(null);
    setDiff(null);
    setError(null);
    refresh();
  }, [refresh]);

  const openDiff = useCallback(
    (path: string) => {
      if (!sessionId) return;
      setSelectedPath(path);
      setDiff(null);
      setDiffTruncated(false);
      setSelectedHunks(new Set());
      if (path.endsWith('/')) return; // 目录条目不拉 diff
      setDiffLoading(true);
      workspaceApi
        .getChangeDiff(sessionId, path)
        .then((d) => {
          setDiff(d.diff);
          setDiffTruncated(d.truncated);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
        .finally(() => setDiffLoading(false));
    },
    [sessionId],
  );

  // U19: 撤销单个文件的工作区改动 (未跟踪条目 = 删除)
  const revertFile = useCallback(
    (path: string, untracked: boolean) => {
      if (!sessionId) return;
      const confirmed = window.confirm(
        untracked ? `删除未跟踪文件 ${path}？此操作不可恢复` : `撤销 ${path} 的工作区改动？`,
      );
      if (!confirmed) return;
      setReverting(true);
      workspaceApi
        .revertChanges(sessionId, [path], untracked)
        .then((result) => {
          if (result.errors.length > 0) {
            toast.error(result.errors[0].error);
            return;
          }
          toast.success(untracked ? '已删除' : '已撤销该文件的改动');
          refresh();
          if (selectedPath === path) openDiff(path);
        })
        .catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))
        .finally(() => setReverting(false));
    },
    [sessionId, refresh, selectedPath, openDiff],
  );

  // U19: 撤销勾选的 hunk 子集
  const revertSelectedHunks = useCallback(() => {
    if (!sessionId || !selectedPath || selectedHunks.size === 0) return;
    const confirmed = window.confirm(
      `反向应用所选 ${selectedHunks.size} 个 hunk（撤销对应改动）？`,
    );
    if (!confirmed) return;
    setReverting(true);
    workspaceApi
      .revertChangeHunks(sessionId, selectedPath, [...selectedHunks].sort((a, b) => a - b))
      .then((result) => {
        toast.success(`已撤销 ${result.revertedHunks} 个 hunk`);
        setSelectedHunks(new Set());
        refresh();
        openDiff(selectedPath);
      })
      .catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))
      .finally(() => setReverting(false));
  }, [sessionId, selectedPath, selectedHunks, refresh, openDiff]);

  const hunks = useMemo(() => (diff ? splitDiffHunks(diff) : []), [diff]);

  const toggleHunk = useCallback((index: number, checked: boolean) => {
    setSelectedHunks((prev) => {
      const next = new Set(prev);
      if (checked) next.add(index);
      else next.delete(index);
      return next;
    });
  }, []);

  if (!sessionId) {
    return <div className="p-3 text-sm text-muted">请先选择会话</div>;
  }

  // ---- diff 视图 ----
  if (selectedPath) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
            title="返回变更列表"
            aria-label="返回变更列表"
            onClick={() => {
              setSelectedPath(null);
              setDiff(null);
            }}
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium truncate flex-1" title={selectedPath}>
            {selectedPath}
          </span>
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary disabled:opacity-50"
            title="撤销该文件全部工作区改动"
            aria-label="撤销该文件改动"
            disabled={reverting}
            onClick={() => revertFile(selectedPath, false)}
          >
            <Undo2 className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {diffLoading ? (
            <div className="text-sm text-muted p-2">加载 diff…</div>
          ) : selectedPath.endsWith('/') ? (
            <div className="text-sm text-muted p-2">目录条目不展示 diff</div>
          ) : diff === null ? (
            <div className="text-sm text-muted p-2">无法加载 diff</div>
          ) : diff.trim() === '' ? (
            <div className="text-sm text-muted p-2">未跟踪文件:暂无 diff 内容</div>
          ) : (
            <>
              {diffTruncated && (
                <div className="text-xs text-amber-600 dark:text-amber-400 p-1">
                  diff 过长,已截断显示前 64KiB
                </div>
              )}
              {hunks.length > 1 ? (
                <>
                  <div className="flex items-center justify-between px-1 pb-2">
                    <span className="text-xs text-text-secondary">
                      共 {hunks.length} 个 hunk，勾选要撤销的改动块
                    </span>
                    <button
                      className="px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-hover disabled:opacity-50"
                      disabled={selectedHunks.size === 0 || reverting}
                      data-testid="revert-hunks-button"
                      onClick={revertSelectedHunks}
                    >
                      撤销所选 ({selectedHunks.size})
                    </button>
                  </div>
                  <div className="flex flex-col gap-3">
                    {hunks.map((hunk, index) => (
                      <div key={index} className="rounded border border-border">
                        <label className="flex items-center gap-2 px-2 py-1 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={selectedHunks.has(index)}
                            onChange={(e) => toggleHunk(index, e.target.checked)}
                            data-testid={`hunk-checkbox-${index}`}
                          />
                          <span className="text-xs text-text-secondary truncate">
                            {index + 1}. {hunk.summary}
                          </span>
                        </label>
                        <ShikiCodeBlock language="diff">
                          {(hunk.header + hunk.body).trimEnd()}
                        </ShikiCodeBlock>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-center justify-between px-1 pb-2">
                    <span className="text-xs text-text-secondary">
                      {hunks.length === 1 ? '单一 hunk，可用右上角按钮整体撤销' : ''}
                    </span>
                  </div>
                  <ShikiCodeBlock language="diff">{diff}</ShikiCodeBlock>
                </>
              )}
            </>
          )}
        </div>
      </div>
    );
  }

  // ---- 列表视图 ----
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-2 py-1 border-b border-border">
        <div className="flex items-center gap-2 min-w-0 text-xs text-text-secondary">
          <GitBranch className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate" title={changes?.upstream || changes?.branch}>
            {changes?.branch || '—'}
          </span>
          {changes && (changes.ahead > 0 || changes.behind > 0) && (
            <span className="shrink-0">
              ↑{changes.ahead} ↓{changes.behind}
            </span>
          )}
        </div>
        <button
          className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
          title="刷新"
          aria-label="刷新"
          onClick={refresh}
        >
          <RefreshCw className={'w-4 h-4' + (loading ? ' animate-spin' : '')} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {error ? (
          <div className="p-3 text-sm text-red-500">{error}</div>
        ) : loading && !changes ? (
          <div className="p-3 text-sm text-muted">加载变更…</div>
        ) : !changes || changes.changes.length === 0 ? (
          <div className="p-3 text-sm text-muted">
            {changes?.clean ? '工作区干净,没有未提交变更' : '暂无变更信息'}
          </div>
        ) : (
          <div className="divide-y divide-border">
            {changes.changes.map((entry) => {
              const untracked = entry.worktreeStatus === '?';
              return (
                <div
                  key={entry.path}
                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-bg-hover transition-colors"
                >
                  <button
                    className="flex items-center gap-2 text-left flex-1 min-w-0"
                    onClick={() => openDiff(entry.path)}
                  >
                    <span
                      className={
                        'text-xs font-medium shrink-0 w-12 ' + statusColor(entry.worktreeStatus)
                      }
                    >
                      {statusLabel(entry)}
                    </span>
                    <span className="text-sm truncate" title={entry.path}>
                      {entry.path}
                    </span>
                  </button>
                  {untracked ? (
                    <button
                      className="p-1 rounded hover:bg-bg-hover text-text-secondary shrink-0 disabled:opacity-50"
                      title="删除未跟踪文件"
                      aria-label={`删除 ${entry.path}`}
                      disabled={reverting}
                      onClick={() => revertFile(entry.path, true)}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  ) : (
                    <button
                      className="p-1 rounded hover:bg-bg-hover text-text-secondary shrink-0 disabled:opacity-50"
                      title="撤销该文件的工作区改动"
                      aria-label={`撤销 ${entry.path}`}
                      disabled={reverting}
                      onClick={() => revertFile(entry.path, false)}
                    >
                      <Undo2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
