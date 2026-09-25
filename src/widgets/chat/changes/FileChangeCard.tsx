// src/widgets/chat/changes/FileChangeCard.tsx
//
// right-panel R5 (2026-09-19): 聊天流内的文件修改卡片（对标 Cursor /
// Copilot Edits 的 inline diff 卡）。write_file / edit_file / apply_patch
// 的工具卡片头下方展示：文件路径 + +/- 行数徽章 + 展开箭头；展开就地
// 懒加载该文件的工作区 diff（复用 GET /changes/diff 与 ShikiCodeBlock 的
// diff 高亮）；右侧面板按钮经 rightPanelStore.selectChange 直达变更 Tab
// 对应文件的 diff 视图（行内快看 / 右面板细审两层体验）。

import {
  Check,
  ChevronDown,
  ChevronRight,
  Columns,
  ExternalLink,
  Eye,
  FileText,
  PanelRightOpen,
  RotateCcw,
  Rows,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { useChangesListStore } from '../../../features/changes/changesListStore';
import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { workspaceApi } from '../../../shared/api/workspaceApi';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

import { SplitDiff } from './SplitDiff';

interface FileChangeCardProps {
  sessionId: string;
  /** 相对工作区根的文件路径（与 git status / diff 接口口径一致） */
  path: string;
}

/** Phase 2 (2026-09-25): 可在预览 Tab 渲染的文档扩展名（与 DocumentPreview 一致） */
const PREVIEWABLE_EXTS = new Set(['docx', 'pdf', 'xlsx', 'xls', 'pptx', 'ppt']);

function isPreviewable(filePath: string): boolean {
  const dot = filePath.lastIndexOf('.');
  if (dot === -1) return false;
  return PREVIEWABLE_EXTS.has(filePath.slice(dot + 1).toLowerCase());
}

export function FileChangeCard({ sessionId, path }: FileChangeCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Phase 4 (2026-09-25): diff 视图模式 — inline（ShikiCodeBlock）或 split（SplitDiff）
  const [diffMode, setDiffMode] = useState<'inline' | 'split'>('inline');
  // Phase 4: 单文件回滚中状态
  const [reverting, setReverting] = useState(false);
  // Phase 4: 用户已接受此变更（本地标记，卡片折叠并降低视觉权重）
  const [accepted, setAccepted] = useState(false);

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

  // Phase 2 (2026-09-25): 在预览 Tab 打开 Office 文档
  const previewInPanel = useCallback(() => {
    useRightPanelStore.getState().selectPreview(path);
  }, [path]);

  // Phase 4 (2026-09-25): 回滚此文件的变更（调用后端 git checkout --）
  const handleRevert = useCallback(async () => {
    setReverting(true);
    try {
      const result = await workspaceApi.revertChanges(sessionId, [path]);
      if (result.errors.length > 0) {
        toast.error(`回滚失败：${result.errors[0].error}`);
      } else {
        toast.success(`已回滚 ${path}`);
        // 刷新 diff（应该变为空）
        setDiff(null);
        setExpanded(false);
      }
      // 刷新变更列表缓存
      void fetchChanges(sessionId);
    } catch (e: unknown) {
      toast.error(`回滚失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setReverting(false);
    }
  }, [sessionId, path, fetchChanges]);

  // Phase 4: 在系统默认编辑器中打开此文件
  const handleOpenInEditor = useCallback(() => {
    const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
    if (api?.file?.openInEditor) {
      void api.file.openInEditor(sessionId, path);
    } else {
      toast.error('桌面端功能不可用');
    }
  }, [sessionId, path]);

  // Phase 4: 切换 diff 视图模式
  const toggleDiffMode = useCallback(() => {
    setDiffMode((prev) => (prev === 'inline' ? 'split' : 'inline'));
  }, []);

  // Phase 4: 标记为已接受（本地折叠）
  const handleAccept = useCallback(() => {
    setAccepted(true);
    setExpanded(false);
  }, []);

  return (
    <div
      className={`mx-2 mb-1.5 rounded border bg-surface ${accepted ? 'border-green-300 dark:border-green-800 opacity-60' : 'border-border'}`}
      data-testid="file-change-card"
    >
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
          {accepted && <Check className="w-3 h-3 shrink-0 text-green-500" />}
          {stats?.insertions != null && stats.insertions > 0 && (
            <span className="shrink-0 font-mono text-[11px] text-green-600 dark:text-green-400">
              +{stats.insertions}
            </span>
          )}
          {stats?.deletions != null && stats.deletions > 0 && (
            <span className="shrink-0 font-mono text-[11px] text-red-500">−{stats.deletions}</span>
          )}
        </button>
        {/* Phase 4: Accept 按钮 */}
        <button
          className="shrink-0 rounded p-1 text-text-secondary hover:bg-bg-hover hover:text-green-500"
          onClick={handleAccept}
          title="接受此变更"
          aria-label={`接受 ${path} 的变更`}
          data-testid="file-change-accept"
        >
          <Check className="w-3.5 h-3.5" />
        </button>
        {/* Phase 4: Revert 按钮 */}
        <button
          className="shrink-0 rounded p-1 text-text-secondary hover:bg-bg-hover hover:text-red-500 disabled:opacity-50"
          onClick={handleRevert}
          disabled={reverting}
          title={reverting ? '回滚中…' : '回滚此变更'}
          aria-label={`回滚 ${path} 的变更`}
          data-testid="file-change-revert"
        >
          <RotateCcw className={`w-3.5 h-3.5 ${reverting ? 'animate-spin' : ''}`} />
        </button>
        {/* Phase 4: Diff 视图切换 */}
        <button
          className="shrink-0 rounded p-1 text-text-secondary hover:bg-bg-hover"
          onClick={toggleDiffMode}
          title={diffMode === 'inline' ? '切换到并排视图' : '切换到内联视图'}
          aria-label={diffMode === 'inline' ? '切换到并排 diff 视图' : '切换到内联 diff 视图'}
          data-testid="file-change-toggle-view"
        >
          {diffMode === 'inline' ? (
            <Columns className="w-3.5 h-3.5" />
          ) : (
            <Rows className="w-3.5 h-3.5" />
          )}
        </button>
        {/* Phase 4: 在编辑器中打开 */}
        <button
          className="shrink-0 rounded p-1 text-text-secondary hover:bg-bg-hover"
          onClick={handleOpenInEditor}
          title="在系统编辑器中打开"
          aria-label={`在编辑器中打开 ${path}`}
          data-testid="file-change-open-editor"
        >
          <ExternalLink className="w-3.5 h-3.5" />
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
        {isPreviewable(path) && (
          <button
            className="shrink-0 rounded p-1 text-text-secondary hover:bg-bg-hover"
            onClick={previewInPanel}
            title="在预览 Tab 中查看文档"
            aria-label={`预览文档 ${path}`}
            data-testid="file-change-preview-doc"
          >
            <Eye className="w-3.5 h-3.5" />
          </button>
        )}
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
              {diffMode === 'inline' ? (
                <ShikiCodeBlock language="diff">{diff.trimEnd()}</ShikiCodeBlock>
              ) : (
                <SplitDiff diff={diff} />
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

/** 一次工具调用涉及的文件数达到该值时,默认折叠为汇总条（对标 Cline） */
const GROUP_COLLAPSE_THRESHOLD = 3;

/**
 * right-panel R6: 一次工具调用的文件修改卡组（P2-8 汇总条）。
 *
 * 文件数少于阈值逐张平铺（Cursor 观感）;达到阈值默认折叠为一条
 * "修改了 N 个文件 +X/−Y" 汇总 chip 防刷屏,点击展开逐文件卡片。
 * 汇总条的 +/- 合计来自 changesListStore 缓存（未命中时拉一次）。
 */
export function FileChangeCards({ sessionId, paths }: { sessionId: string; paths: string[] }) {
  const [expanded, setExpanded] = useState(paths.length < GROUP_COLLAPSE_THRESHOLD);

  const stats = useChangesListStore((s) => s.bySession[sessionId]);
  const fetchChanges = useChangesListStore((s) => s.fetch);
  useEffect(() => {
    if (!useChangesListStore.getState().bySession[sessionId]) {
      void fetchChanges(sessionId);
    }
  }, [sessionId, fetchChanges]);

  const totals = useMemo(() => {
    let insertions = 0;
    let deletions = 0;
    let known = false;
    for (const path of paths) {
      const entry = stats?.changes.find((c) => c.path === path);
      if (entry?.insertions != null) {
        insertions += entry.insertions;
        known = true;
      }
      if (entry?.deletions != null) {
        deletions += entry.deletions;
        known = true;
      }
    }
    return { insertions, deletions, known };
  }, [stats, paths]);

  if (paths.length === 0) return null;

  if (!expanded) {
    return (
      <button
        className="mx-2 mb-1.5 flex items-center gap-1.5 rounded border border-border bg-surface px-2 py-1 text-left hover:bg-bg-hover transition-colors"
        onClick={() => setExpanded(true)}
        title="展开查看逐文件 diff"
        data-testid="file-change-group"
      >
        <ChevronRight className="w-3.5 h-3.5 shrink-0 text-text-secondary" />
        <FileText className="w-3.5 h-3.5 shrink-0 text-primary" />
        <span className="text-[11px] text-text">修改了 {paths.length} 个文件</span>
        {totals.known && (
          <>
            <span className="font-mono text-[11px] text-green-600 dark:text-green-400">
              +{totals.insertions}
            </span>
            {totals.deletions > 0 && (
              <span className="font-mono text-[11px] text-red-500">−{totals.deletions}</span>
            )}
          </>
        )}
        <span className="text-[11px] text-muted">点击展开</span>
      </button>
    );
  }

  return (
    <div className="flex flex-col">
      {paths.map((path) => (
        <FileChangeCard key={path} sessionId={sessionId} path={path} />
      ))}
    </div>
  );
}
