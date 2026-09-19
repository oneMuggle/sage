// src/widgets/chat/changes/FileChangeCard.tsx
//
// right-panel R5 (2026-09-19): 聊天流内的文件修改卡片（对标 Cursor /
// Copilot Edits 的 inline diff 卡）。write_file / edit_file / apply_patch
// 的工具卡片头下方展示：文件路径 + +/- 行数徽章 + 展开箭头；展开就地
// 懒加载该文件的工作区 diff（复用 GET /changes/diff 与 ShikiCodeBlock 的
// diff 高亮）；右侧面板按钮经 rightPanelStore.selectChange 直达变更 Tab
// 对应文件的 diff 视图（行内快看 / 右面板细审两层体验）。

import { ChevronDown, ChevronRight, PanelRightOpen } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { useChangesListStore } from '../../../features/changes/changesListStore';
import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { workspaceApi } from '../../../shared/api/workspaceApi';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

interface FileChangeCardProps {
  sessionId: string;
  /** 相对工作区根的文件路径（与 git status / diff 接口口径一致） */
  path: string;
}

export function FileChangeCard({ sessionId, path }: FileChangeCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // +/- 行数来自变更列表缓存（P0-1 numstat 字段）；缓存未热时拉一次
  //（fetch 有 inflight 去重，多张卡片同帧挂载只发一个请求）。
  const stats = useChangesListStore((s) =>
    s.bySession[sessionId]?.changes.find((c) => c.path === path),
  );
  const fetchChanges = useChangesListStore((s) => s.fetch);
  useEffect(() => {
    if (!useChangesListStore.getState().bySession[sessionId]) {
      void fetchChanges(sessionId);
    }
  }, [sessionId, fetchChanges]);

  const toggle = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev;
      if (next && diff === null && !loading) {
        setLoading(true);
        setError(null);
        workspaceApi
          .getChangeDiff(sessionId, path)
          .then((d) => {
            setDiff(d.diff);
            setTruncated(d.truncated);
          })
          .catch((e: unknown) => {
            setError(e instanceof Error ? e.message : String(e));
          })
          .finally(() => setLoading(false));
      }
      return next;
    });
  }, [sessionId, path, diff, loading]);

  const openInPanel = useCallback(() => {
    useRightPanelStore.getState().selectChange(path);
  }, [path]);

  return (
    <div className="mx-2 mb-1.5 rounded border border-border bg-surface" data-testid="file-change-card">
      <div className="flex items-center gap-1 px-2 py-1">
        <button
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          onClick={toggle}
          aria-expanded={expanded}
          title={expanded ? '收起 diff' : '展开 diff'}
          data-testid="file-change-toggle"
        >
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 shrink-0 text-text-secondary" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 shrink-0 text-text-secondary" />
          )}
          <span className="truncate font-mono text-[11px] text-text" title={path}>
            {path}
          </span>
          {stats?.insertions != null && stats.insertions > 0 && (
            <span className="shrink-0 font-mono text-[11px] text-green-600 dark:text-green-400">
              +{stats.insertions}
            </span>
          )}
          {stats?.deletions != null && stats.deletions > 0 && (
            <span className="shrink-0 font-mono text-[11px] text-red-500">
              −{stats.deletions}
            </span>
          )}
        </button>
        <button
          className="shrink-0 rounded p-1 text-text-secondary hover:bg-bg-hover"
          onClick={openInPanel}
          title="在右侧面板中查看 diff"
          aria-label={`在右侧面板中查看 ${path} 的 diff`}
          data-testid="file-change-open-panel"
        >
          <PanelRightOpen className="w-3.5 h-3.5" />
        </button>
      </div>
      {expanded && (
        <div className="border-t border-border px-2 py-1.5">
          {loading ? (
            <div className="py-1 text-xs text-muted">加载 diff…</div>
          ) : error ? (
            <div className="py-1 text-xs text-red-500">{error}</div>
          ) : diff !== null && diff.trim() === '' ? (
            <div className="py-1 text-xs text-muted">暂无 diff 内容</div>
          ) : diff !== null ? (
            <>
              {truncated && (
                <div className="pb-1 text-xs text-amber-600 dark:text-amber-400">
                  diff 过长，已截断显示前 64KiB
                </div>
              )}
              <ShikiCodeBlock language="diff">{diff.trimEnd()}</ShikiCodeBlock>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
