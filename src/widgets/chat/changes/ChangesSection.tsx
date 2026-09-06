// src/widgets/chat/changes/ChangesSection.tsx
//
// U1 变更面板 (对标增强第二轮, docs/plans/2026-09-06-parity-round2):
// 会话工作区的 git 变更清单 + 按文件 diff 视图。
// 数据源: GET /sessions/{id}/workspace/changes[/diff] (只读,复用 git_status /
// git_diff 工具的实现口径)。渲染 diff 复用 ShikiCodeBlock 的 diff 语言支持。

import { ArrowLeft, GitBranch, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { workspaceApi } from '../../../shared/api/workspaceApi';
import type { WorkspaceChanges } from '../../../shared/api/workspaceApi';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

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

  const refresh = useCallback(() => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    workspaceApi
      .getChanges(sessionId)
      .then(setChanges)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
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
              <ShikiCodeBlock language="diff">{diff}</ShikiCodeBlock>
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
            {changes.changes.map((entry) => (
              <button
                key={entry.path}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-bg-hover transition-colors"
                onClick={() => openDiff(entry.path)}
              >
                <span
                  className={'text-xs font-medium shrink-0 w-12 ' + statusColor(entry.worktreeStatus)}
                >
                  {statusLabel(entry)}
                </span>
                <span className="text-sm truncate" title={entry.path}>
                  {entry.path}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
