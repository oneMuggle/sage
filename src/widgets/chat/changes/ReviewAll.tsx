// src/widgets/chat/changes/ReviewAll.tsx
//
// right-panel R6 (2026-09-19): "全部审查" 汇总视图（P2-7，对标 Copilot
// Edits Review all / Cline See changes）。拉取全仓库 unified diff
// （GET /changes/diff 不带 path，复用既有接口），按文件切分后连续滚动
// 展示：顶部文件 chip 锚点导航 + 每文件一节（路径 + +/- 合计 + 折叠），
// 节内复用 ShikiCodeBlock 的 diff 高亮（>30 行自带折叠兜底）。
//
// 只读视图，撤销仍回列表视图逐文件/逐 hunk 操作。

import { ArrowLeft, ChevronDown, ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useChangesListStore } from '../../../features/changes/changesListStore';
import { workspaceApi } from '../../../shared/api/workspaceApi';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

import { splitReviewSections } from './reviewSections';

interface ReviewAllProps {
  sessionId: string;
  onBack: () => void;
}

export function ReviewAll({ sessionId, onBack }: ReviewAllProps) {
  const [fullDiff, setFullDiff] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const sectionRefs = useRef<Array<HTMLElement | null>>([]);

  // +/- 合计来自变更列表缓存（与列表视图共用数据源）
  const stats = useChangesListStore((s) => s.bySession[sessionId]);
  const fetchChanges = useChangesListStore((s) => s.fetch);

  useEffect(() => {
    if (!useChangesListStore.getState().bySession[sessionId]) {
      void fetchChanges(sessionId);
    }
  }, [sessionId, fetchChanges]);

  useEffect(() => {
    setFullDiff(null);
    setError(null);
    setCollapsed(new Set());
    workspaceApi
      .getChangeDiff(sessionId, '')
      .then((d) => {
        setFullDiff(d.diff);
        setTruncated(d.truncated);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [sessionId]);

  const sections = useMemo(() => (fullDiff !== null ? splitReviewSections(fullDiff) : []), [
    fullDiff,
  ]);

  const toggle = useCallback((path: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const statsFor = useCallback(
    (path: string) => stats?.changes.find((c) => c.path === path) ?? null,
    [stats],
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
        <button
          className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
          title="返回变更列表"
          aria-label="返回变更列表"
          data-testid="review-all-back"
          onClick={onBack}
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="text-sm font-medium flex-1">
          全部审查{sections.length > 0 ? `（${sections.length} 个文件）` : ''}
        </span>
      </div>
      {truncated && (
        <div className="text-xs text-amber-600 dark:text-amber-400 px-2 py-1 border-b border-border">
          diff 过长，已截断显示前 64KiB——末尾文件可能不完整
        </div>
      )}
      {/* 文件锚点导航 */}
      {sections.length > 1 && (
        <div className="flex flex-wrap gap-1 px-2 py-1.5 border-b border-border">
          {sections.map((section, i) => (
            <button
              key={section.path}
              className="px-1.5 py-0.5 rounded border border-border bg-surface hover:bg-bg-hover text-[11px] text-text-secondary max-w-56 truncate"
              title={`跳到 ${section.path}`}
              data-testid={`review-all-jump-${section.path}`}
              onClick={() =>
                sectionRefs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }
            >
              {section.path}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-2">
        {error ? (
          <div className="text-sm text-red-500 p-2">{error}</div>
        ) : fullDiff === null ? (
          <div className="text-sm text-muted p-2">加载全部 diff…</div>
        ) : sections.length === 0 ? (
          <div className="text-sm text-muted p-2">没有可展示的文本 diff</div>
        ) : (
          <div className="flex flex-col gap-3">
            {sections.map((section, i) => {
              const isCollapsed = collapsed.has(section.path);
              const fileStats = statsFor(section.path);
              return (
                <div
                  key={section.path}
                  ref={(el) => {
                    sectionRefs.current[i] = el;
                  }}
                  className="rounded border border-border scroll-mt-1"
                  data-testid="review-all-section"
                >
                  <button
                    className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left hover:bg-bg-hover transition-colors"
                    onClick={() => toggle(section.path)}
                    aria-expanded={!isCollapsed}
                    title={isCollapsed ? '展开该文件 diff' : '收起该文件 diff'}
                    data-testid={`review-all-toggle-${section.path}`}
                  >
                    {isCollapsed ? (
                      <ChevronRight className="w-3.5 h-3.5 shrink-0 text-text-secondary" />
                    ) : (
                      <ChevronDown className="w-3.5 h-3.5 shrink-0 text-text-secondary" />
                    )}
                    <span className="truncate font-mono text-xs text-text flex-1" title={section.path}>
                      {section.path}
                    </span>
                    {fileStats?.insertions != null && fileStats.insertions > 0 && (
                      <span className="shrink-0 font-mono text-[11px] text-green-600 dark:text-green-400">
                        +{fileStats.insertions}
                      </span>
                    )}
                    {fileStats?.deletions != null && fileStats.deletions > 0 && (
                      <span className="shrink-0 font-mono text-[11px] text-red-500">
                        −{fileStats.deletions}
                      </span>
                    )}
                  </button>
                  {!isCollapsed && (
                    <div className="border-t border-border p-1">
                      {section.binary ? (
                        <div className="p-2 text-xs text-muted">二进制文件，无文本 diff</div>
                      ) : (
                        <ShikiCodeBlock language="diff">{section.diffText.trimEnd()}</ShikiCodeBlock>
                      )}
                    </div>
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
