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
//
// U2' 检查点面板 (对标增强第五轮批次 A, docs/plans/2026-09-08_coding-agent-parity-round5.md):
// 工作区快照的列表 / 手动创建 / 覆盖恢复。restore 走 confirm 对话框
// (用户主动操作,与 U19 revert 同先例,不经 agent 审批门禁)。
//
// right-panel R5 (2026-09-19): 列表行 +/- 行数徽章 (GET /changes 的
// numstat 字段) + 消费 rightPanelStore.selectedChangePath —— 聊天流内
// 文件修改卡片点击后直达本面板对应文件的 diff 视图。

import {
  Archive,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Columns,
  Files,
  GitBranch,
  History,
  RefreshCw,
  Trash2,
  Undo2,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { useChangesListStore } from '../../../features/changes/changesListStore';
import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { workspaceApi } from '../../../shared/api/workspaceApi';
import type { WorkspaceCheckpoint } from '../../../shared/api/workspaceApi';
import { langFromPath } from '../../../shared/lib/fileLang';
import { confirmDialog } from '../../../shared/ui/ConfirmDialog/confirmService';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

import { ReviewAll } from './ReviewAll';
import { SplitDiff } from './SplitDiff';
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

/** 快照体积展示（B/KB/MB 一位小数） */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ChangesSection({ sessionId }: ChangesSectionProps) {
  // right-panel R3 批次 C: 变更列表/加载/错误上抬 changesListStore（面板
  // header 计数徽标需要 Tab 未激活时的数据）；selection/diff/checkpoint
  // 等交互态保留组件本地。
  const storedChanges = useChangesListStore((s) =>
    sessionId ? s.bySession[sessionId] : undefined,
  );
  const storedError = useChangesListStore((s) =>
    sessionId ? (s.errors[sessionId] ?? null) : null,
  );
  const loading = useChangesListStore((s) =>
    sessionId ? (s.loadingBy[sessionId] ?? false) : false,
  );
  const fetchChanges = useChangesListStore((s) => s.fetch);
  const changes = storedChanges ?? null;
  const error = storedError;
  const notBound = error?.includes('尚未绑定工作区') ?? false;
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffTruncated, setDiffTruncated] = useState(false);
  // U19: 勾选待撤销的 hunk (0-based,与后端 revert-hunks 序号一致)
  const [selectedHunks, setSelectedHunks] = useState<Set<number>>(new Set());
  const [reverting, setReverting] = useState(false);
  // P1-3.8: 分栏 (split) / 统一 (unified) diff 视图切换;默认 unified,保留 per-hunk 撤销
  const [splitView, setSplitView] = useState(false);
  // U2': 检查点快照列表 / 折叠态 / 操作互斥;未绑定工作区时整个检查点区隐藏
  const [checkpoints, setCheckpoints] = useState<WorkspaceCheckpoint[] | null>(null);
  const [checkpointsOpen, setCheckpointsOpen] = useState(false);
  const [checkpointBusy, setCheckpointBusy] = useState(false);
  // right-panel R6: diff / 文件预览 视图切换与预览内容懒加载
  const [viewMode, setViewMode] = useState<'diff' | 'preview'>('diff');
  // right-panel R6 / P2-7: "全部审查" 多文件连续 diff 视图
  const [reviewAll, setReviewAll] = useState(false);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileContentTruncated, setFileContentTruncated] = useState(false);
  const [fileContentLoading, setFileContentLoading] = useState(false);
  const [fileContentError, setFileContentError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!sessionId) return;
    void fetchChanges(sessionId);
  }, [sessionId, fetchChanges]);

  // right-panel R5: 聊天流文件修改卡片（selectChange）直达入口 —— 消费
  // 一次性选中路径,打开对应文件的 diff 视图后立即清除,避免切会话串台。
  const pendingChangePath = useRightPanelStore((s) => s.selectedChangePath);
  const clearSelectedChange = useRightPanelStore((s) => s.clearSelectedChange);
  const openDiff = useCallback(
    (path: string) => {
      if (!sessionId) return;
      setSelectedPath(path);
      setDiff(null);
      setDiffTruncated(false);
      setSelectedHunks(new Set());
      setSplitView(false); // P1-3.8: 切换文件时重置为 unified 视图,避免 per-hunk 撤销 UI 错位
      setViewMode('diff'); // R6: 切换文件回到 diff 视图,预览内容一并失效
      setFileContent(null);
      setFileContentTruncated(false);
      setFileContentError(null);
      if (path.endsWith('/')) return; // 目录条目不拉 diff
      setDiffLoading(true);
      workspaceApi
        .getChangeDiff(sessionId, path)
        .then((d) => {
          setDiff(d.diff);
          setDiffTruncated(d.truncated);
        })
        .catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))
        .finally(() => setDiffLoading(false));
    },
    [sessionId],
  );

  // right-panel R6: 切到"预览"视图时懒加载文件内容（切回 diff 不重拉）
  const showPreview = useCallback(() => {
    setViewMode('preview');
    if (!sessionId || !selectedPath || fileContent !== null || fileContentLoading) return;
    setFileContentLoading(true);
    setFileContentError(null);
    workspaceApi
      .getChangeFile(sessionId, selectedPath)
      .then((f) => {
        setFileContent(f.content);
        setFileContentTruncated(f.truncated);
      })
      .catch((e: unknown) => {
        setFileContentError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setFileContentLoading(false));
  }, [sessionId, selectedPath, fileContent, fileContentLoading]);

  const refreshCheckpoints = useCallback(() => {
    if (!sessionId) return;
    // 检查点是辅助信息:失败静默(列表置空),不与变更错误通道互相干扰
    workspaceApi
      .listCheckpoints(sessionId)
      .then(setCheckpoints)
      .catch(() => setCheckpoints(null));
  }, [sessionId]);

  useEffect(() => {
    setSelectedPath(null);
    setDiff(null);
    setCheckpoints(null);
    setCheckpointsOpen(false);
    setReviewAll(false);
    refresh();
  }, [refresh]);

  // right-panel R5: 消费 pendingChangePath 的 effect 刻意放在重置 effect
  // 之后 —— 面板从关闭态被 selectChange 唤起时组件是首次挂载,若声明在
  // 重置之前,同一 commit 内的重置 effect 会把 openDiff 的选中态清掉。
  useEffect(() => {
    if (!pendingChangePath) return;
    openDiff(pendingChangePath);
    clearSelectedChange();
  }, [pendingChangePath, openDiff, clearSelectedChange]);

  // U19: 撤销单个文件的工作区改动 (未跟踪条目 = 删除)
  const revertFile = useCallback(
    async (path: string, untracked: boolean) => {
      if (!sessionId) return;
      if (
        !(await confirmDialog({
          title: untracked ? `删除未跟踪文件 ${path}？` : `撤销 ${path} 的工作区改动？`,
          message: untracked ? '此操作不可恢复' : undefined,
          danger: untracked,
        }))
      )
        return;
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
  const revertSelectedHunks = useCallback(async () => {
    if (!sessionId || !selectedPath || selectedHunks.size === 0) return;
    if (
      !(await confirmDialog({
        title: `反向应用所选 ${selectedHunks.size} 个 hunk？`,
        message: '将撤销对应的工作区改动。',
      }))
    )
      return;
    setReverting(true);
    workspaceApi
      .revertChangeHunks(
        sessionId,
        selectedPath,
        [...selectedHunks].sort((a, b) => a - b),
      )
      .then((result) => {
        toast.success(`已撤销 ${result.revertedHunks} 个 hunk`);
        setSelectedHunks(new Set());
        refresh();
        openDiff(selectedPath);
      })
      .catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))
      .finally(() => setReverting(false));
  }, [sessionId, selectedPath, selectedHunks, refresh, openDiff]);

  // U2': 手动创建当前状态快照
  const createCheckpoint = useCallback(() => {
    if (!sessionId) return;
    setCheckpointBusy(true);
    workspaceApi
      .createCheckpoint(sessionId)
      .then((cp) => {
        toast.success(`已创建快照（${cp.files} 个文件，${formatBytes(cp.bytes)}）`);
        refreshCheckpoints();
      })
      .catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))
      .finally(() => setCheckpointBusy(false));
  }, [sessionId, refreshCheckpoints]);

  // U2': 覆盖恢复快照(只覆盖快照内文件,不删除快照后新建的文件)
  const restoreCheckpoint = useCallback(
    async (cp: WorkspaceCheckpoint) => {
      if (!sessionId) return;
      if (
        !(await confirmDialog({
          title: `恢复快照 ${cp.checkpointId}？`,
          message:
            '将覆盖工作区中快照包含的文件；快照之后新建的文件会保留。建议先创建一份当前状态的快照。',
        }))
      )
        return;
      setCheckpointBusy(true);
      workspaceApi
        .restoreCheckpoint(sessionId, cp.checkpointId)
        .then((result) => {
          toast.success(`已恢复 ${result.restored} 个文件`);
          refresh();
          refreshCheckpoints();
          if (selectedPath) openDiff(selectedPath);
        })
        .catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))
        .finally(() => setCheckpointBusy(false));
    },
    [sessionId, refresh, refreshCheckpoints, selectedPath, openDiff],
  );

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

  // ---- 全部审查汇总视图 (right-panel R6 / P2-7) ----
  if (reviewAll) {
    return <ReviewAll sessionId={sessionId} onBack={() => setReviewAll(false)} />;
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
          <button
            className={
              'p-1.5 rounded hover:bg-bg-hover transition-colors ' +
              (splitView ? 'text-primary bg-primary/10' : 'text-text-secondary')
            }
            title={splitView ? '切换到统一 (unified) 视图' : '切换到分栏 (side-by-side) 视图'}
            aria-label="切换分栏/统一视图"
            aria-pressed={splitView}
            data-testid="toggle-split-view"
            onClick={() => setSplitView((v) => !v)}
          >
            <Columns className="w-4 h-4" />
          </button>
          {/* right-panel R6: Diff / 预览 分段切换（预览 = 修改后全文，懒加载） */}
          <div
            className="flex items-center rounded border border-border text-xs overflow-hidden shrink-0"
            role="group"
            aria-label="切换 diff/文件预览视图"
          >
            <button
              className={
                'px-2 py-1 transition-colors ' +
                (viewMode === 'diff'
                  ? 'text-primary bg-primary/10'
                  : 'text-text-secondary hover:bg-bg-hover')
              }
              title="查看未提交 diff"
              aria-pressed={viewMode === 'diff'}
              data-testid="view-mode-diff"
              onClick={() => setViewMode('diff')}
            >
              Diff
            </button>
            <button
              className={
                'px-2 py-1 transition-colors ' +
                (viewMode === 'preview'
                  ? 'text-primary bg-primary/10'
                  : 'text-text-secondary hover:bg-bg-hover')
              }
              title="查看修改后文件全文"
              aria-pressed={viewMode === 'preview'}
              data-testid="view-mode-preview"
              onClick={showPreview}
            >
              预览
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {viewMode === 'preview' ? (
            // right-panel R6: 修改后文件全文预览（按扩展名选 Shiki 语言）
            fileContentLoading ? (
              <div className="text-sm text-muted p-2">加载文件…</div>
            ) : fileContentError ? (
              <div className="text-sm text-red-500 p-2">{fileContentError}</div>
            ) : fileContent !== null ? (
              <>
                {fileContentTruncated && (
                  <div className="text-xs text-amber-600 dark:text-amber-400 p-1">
                    文件过长，已截断显示前 512KiB
                  </div>
                )}
                <ShikiCodeBlock language={langFromPath(selectedPath)}>
                  {fileContent}
                </ShikiCodeBlock>
              </>
            ) : null
          ) : diffLoading ? (
            <div className="text-sm text-muted p-2">加载 diff…</div>
          ) : selectedPath.endsWith('/') ? (
            <div className="text-sm text-muted p-2">目录条目不展示 diff</div>
          ) : diff === null ? (
            <div className="text-sm text-muted p-2">无法加载 diff</div>
          ) : diff.trim() === '' ? (
            <div className="text-sm text-muted p-2">未跟踪文件:暂无 diff 内容</div>
          ) : splitView ? (
            <>
              {diffTruncated && (
                <div className="text-xs text-amber-600 dark:text-amber-400 p-1">
                  diff 过长,已截断显示前 64KiB
                </div>
              )}
              <SplitDiff diff={diff} />
            </>
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
        <div className="flex items-center shrink-0">
          {/* right-panel R6 / P2-7: 全部审查汇总视图入口 */}
          {changes && changes.changes.length > 0 && (
            <button
              className="flex items-center gap-1 px-1.5 py-1 rounded hover:bg-bg-hover text-xs text-text-secondary"
              title="连续查看全部文件 diff"
              aria-label="全部审查"
              data-testid="review-all-button"
              onClick={() => setReviewAll(true)}
            >
              <Files className="w-3.5 h-3.5" />
              全部审查
            </button>
          )}
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
            title="刷新"
            aria-label="刷新"
            onClick={refresh}
          >
            <RefreshCw className={'w-4 h-4' + (loading ? ' animate-spin' : '')} />
          </button>
        </div>
      </div>
      {!notBound && (
        <div className="border-b border-border">
          <div className="flex items-center gap-1 px-2 py-1">
            <button
              className="flex items-center gap-1 px-1 py-0.5 rounded text-xs text-text-secondary hover:bg-bg-hover"
              data-testid="checkpoint-toggle"
              aria-expanded={checkpointsOpen}
              onClick={() => {
                const next = !checkpointsOpen;
                setCheckpointsOpen(next);
                if (next && checkpoints === null) refreshCheckpoints();
              }}
            >
              {checkpointsOpen ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
              <Archive className="w-3.5 h-3.5" />
              <span>
                检查点
                {checkpoints !== null && checkpoints.length > 0 ? `（${checkpoints.length}）` : ''}
              </span>
            </button>
            <span className="flex-1" />
            <button
              className="p-1 rounded hover:bg-bg-hover text-text-secondary disabled:opacity-50"
              title="为当前工作区创建快照"
              aria-label="创建快照"
              data-testid="create-checkpoint-button"
              disabled={checkpointBusy}
              onClick={createCheckpoint}
            >
              <Archive className="w-3.5 h-3.5" />
            </button>
          </div>
          {checkpointsOpen &&
            (checkpoints === null ? (
              <div className="px-3 pb-2 text-xs text-muted">加载检查点…</div>
            ) : checkpoints.length === 0 ? (
              <div className="px-3 pb-2 text-xs text-muted">暂无快照</div>
            ) : (
              <div className="divide-y divide-border border-t border-border">
                {checkpoints.map((cp) => (
                  <div
                    key={cp.checkpointId}
                    className="flex items-center gap-2 px-3 py-1.5"
                    data-testid="checkpoint-row"
                  >
                    <span className="text-xs truncate flex-1" title={cp.checkpointId}>
                      {cp.checkpointId}
                    </span>
                    <span className="text-xs text-text-secondary shrink-0">
                      {cp.files ?? '?'} 个文件 · {formatBytes(cp.bytes)}
                    </span>
                    <button
                      className="p-1 rounded hover:bg-bg-hover text-text-secondary shrink-0 disabled:opacity-50"
                      title="恢复此快照（覆盖工作区，不删除快照后新建的文件）"
                      aria-label={`恢复快照 ${cp.checkpointId}`}
                      data-testid={`restore-checkpoint-${cp.checkpointId}`}
                      disabled={checkpointBusy}
                      onClick={() => restoreCheckpoint(cp)}
                    >
                      <History className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            ))}
        </div>
      )}
      <div className="flex-1 overflow-y-auto">
        {error ? (
          <div className="p-3 text-sm text-red-500">{error}</div>
        ) : loading && !changes ? (
          <div className="p-3 text-sm text-muted">加载变更…</div>
        ) : !changes || changes.changes.length === 0 ? (
          // R2 批次 C: 空态引导 —— 说明变更面板的数据来源
          <div className="p-3 text-sm text-muted" data-testid="changes-empty">
            {changes?.clean ? '工作区干净,没有未提交变更' : '暂无变更信息'}
            <div className="mt-1 text-xs text-muted/80">
              agent 改动工作区文件后，这里会列出可审查/可回滚的变更
            </div>
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
                    {/* right-panel R5: +/- 行数徽章（numstat；null=二进制/未知不渲染） */}
                    {entry.insertions !== null && entry.insertions > 0 && (
                      <span
                        className="shrink-0 font-mono text-[11px] text-green-600 dark:text-green-400"
                        data-testid="change-insertions"
                      >
                        +{entry.insertions}
                      </span>
                    )}
                    {entry.deletions !== null && entry.deletions > 0 && (
                      <span
                        className="shrink-0 font-mono text-[11px] text-red-500"
                        data-testid="change-deletions"
                      >
                        −{entry.deletions}
                      </span>
                    )}
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
