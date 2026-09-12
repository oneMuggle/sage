import { AlertCircle, Check, Clock, FileText, GitBranch, Loader2, Paperclip, PauseCircle, Pencil, Pin, PinOff, Download, Search } from 'lucide-react';
import { useEffect, useReducer, useRef, useState } from 'react';

import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import { useScheduledTaskStore } from '../../entities/scheduled/taskStore';
import { useArtifactEventsStore } from '../../features/artifacts/artifactEventsStore';
import {
  selectSessionSlots,
  useChatStreamStore,
} from '../../features/send-message/chatStreamStore';
import { downloadHtmlFile, downloadMarkdownFile, sessionApi } from '../../shared/api/sessionApi';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import type { Session } from '../../shared/lib/store';
import { formatRelativeTime } from '../../shared/lib/utils';
import { TwoStepDelete } from '../sidebar/TwoStepDelete';

interface SessionItemProps {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  /** U4': 重命名回调——API 与 store 更新由上层负责,组件只管 inline 编辑态 */
  onRename?: (sessionId: string, title: string) => Promise<void>;
  /** F12: 消息内容命中条数（侧栏搜索增强;缺省不显示徽标） */
  messageHits?: number;
}

/** 文件变更类工具（S6-lite: 本次运行的变更文件计数徽章）。
 *  与后端工具注册名对齐：file_tool.py write_file / edit_tool.py edit_file /
 *  patch_tool.py apply_patch。 */
const FILE_CHANGE_TOOLS = new Set(['write_file', 'edit_file', 'apply_patch']);

/** S4: completed ✓ 徽章的保鲜期 —— 超过后不再显示（避免整列表常亮绿勾）。 */
const COMPLETED_FRESH_MS = 60_000;

export function SessionItem({
  session,
  isActive,
  onSelect,
  onDelete,
  onRename,
  messageHits,
}: SessionItemProps) {
  const { t } = useI18n();
  const [exporting, setExporting] = useState(false);
  // U4': inline 重命名态(标题位置换成输入框,Enter 提交 / Esc 取消)
  const [renaming, setRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');
  const renameInputRef = useRef<HTMLInputElement>(null);

  // S2/S4: 该会话的实时流槽位 —— 运行中指示、mini 进度、变更计数都从这里
  // 派生（跨页面保留；会话无流时返回共享空槽位，引用稳定不触发重渲染）。
  const slots = useChatStreamStore((s) => selectSessionSlots(s, session.id));
  // S7: 本次运行产物计数徽章
  const artifactCount = useArtifactEventsStore((s) => s.counts[session.id] ?? 0);
  // S4: 注意力点按会话聚合（旧实现是全局计数挂在"对话"导航上）
  const hasPendingApproval = usePermissionState((s) => s.currentRequest?.session_id === session.id);
  const hasPendingQuestion = useQuestionState((s) => s.currentQuestion?.session_id === session.id);
  // S9: 有启用的定时任务指向该会话 → ⏰ 标记
  const hasCron = useScheduledTaskStore((s) =>
    s.tasks.some((task) => task.session_id === session.id && task.enabled),
  );

  const isLive = slots.streaming != null;
  const dbStatus = session.run_status ?? 'idle';
  // 保鲜的 completed ✓：刚完成 60s 内显示，之后回归 idle 观感
  const completedFresh = !isLive && dbStatus === 'completed' && hasFreshRunAt(session.last_run_at);
  const showCompletedTick = useExpireAfter(completedFresh, session.last_run_at, COMPLETED_FRESH_MS);
  const failed = !isLive && dbStatus === 'failed';
  const suspended = !isLive && dbStatus === 'suspended';
  const hasAttention = hasPendingApproval || hasPendingQuestion;

  // S5: mini 进度 —— 编排 5 元组优先，todo 完成度兜底
  const progress = slots.taskBoard?.progress;
  const todoDone = slots.todos.filter((td) => td.status === 'completed').length;
  const todoTotal = slots.todos.length;

  // S6-lite: 本次运行的文件变更计数（只统计已有结果的调用 = 已执行完成）
  const changeCount = slots.streamingToolCalls.filter(
    (tc) => FILE_CHANGE_TOOLS.has(tc.name) && tc.result != null,
  ).length;

  // U18: 导出完整会话为自包含 HTML(离线可开,含工具调用/diff/思考过程)
  const handleExport = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (exporting) {
      return;
    }
    setExporting(true);
    try {
      const result = await sessionApi.exportHtml(session.id);
      downloadHtmlFile(result.html, result.filename);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      alert(t('session.export_failed').replace('{message}', message));
    } finally {
      setExporting(false);
    }
  };
  // R18-C: 导出 Markdown(轻量、可版本管理)
  const [exportingMd, setExportingMd] = useState(false);
  const handleExportMarkdown = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (exportingMd) return;
    setExportingMd(true);
    try {
      const result = await sessionApi.exportMarkdown(session.id);
      downloadMarkdownFile(result.html, result.filename);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      alert(t('session.export_failed').replace('{message}', message));
    } finally {
      setExportingMd(false);
    }
  };

  // R18-B: 置顶/取消置顶 —— API 落库 + store 原地更新（避免整表 reload）
  const updateSession = useStore((st) => st.updateSession);
  const [pinning, setPinning] = useState(false);
  const handleTogglePin = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (pinning) return;
    setPinning(true);
    try {
      await sessionApi.setPinned(session.id, !session.is_pinned);
      updateSession(session.id, { is_pinned: !session.is_pinned });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      alert(message);
    } finally {
      setPinning(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect();
    }
  };

  // U4': 进入 inline 编辑;拖拽激活距离 8px 不影响双击/按钮点击
  const startRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setRenameDraft(session.title);
    setRenaming(true);
    // 等输入框挂载后聚焦并全选,便于直接覆盖输入
    requestAnimationFrame(() => {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    });
  };
  const submitRename = () => {
    const next = renameDraft.trim();
    setRenaming(false);
    if (!next || next === session.title) return;
    void onRename?.(session.id, next);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid="session-item"
      data-session-id={session.id}
      data-run-status={isLive ? 'running' : dbStatus}
      aria-label={`选择会话 ${session.title}`}
      aria-pressed={isActive}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      className={`
        group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
        transition-colors focus:outline-none focus:ring-2 focus:ring-primary
        ${isActive ? 'bg-primary/10 text-primary' : 'hover:bg-bg-hover'}
      `}
    >
      {/* 会话标题 */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium flex items-center gap-1 min-w-0">
          {/* M4: fork 徽标 — session.fork_root 存在时显示，tooltip 带源会话 id */}
          {session.fork_root && (
            <span
              data-testid="fork-badge"
              aria-label={t('session.fork_badge')}
              title={`${t('session.fork_badge')} · fork_root: ${session.fork_root}`}
              className="inline-flex flex-shrink-0"
            >
              <GitBranch className="w-3 h-3 text-muted" />
            </span>
          )}
          {/* U4': inline 重命名态——输入框替换标题文本,Enter 提交 / Esc 取消 */}
          {renaming ? (
            <input
              ref={renameInputRef}
              data-testid="rename-session-input"
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === 'Enter') {
                  e.preventDefault();
                  submitRename();
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setRenaming(false);
                }
              }}
              onBlur={submitRename}
              maxLength={200}
              aria-label={t('session.rename')}
              className="flex-1 min-w-0 text-sm font-medium bg-bg-hover border border-primary rounded px-1 py-0 focus:outline-none"
            />
          ) : (
            <span className="truncate">{session.title}</span>
          )}
          {/* U4': 双击标题进入 inline 重命名 */}
          {onRename && !renaming && (
            <span
              className="hidden group-hover:inline-flex flex-shrink-0 text-muted hover:text-primary"
              title={t('session.rename')}
              aria-label={t('session.rename')}
              data-testid="rename-session"
              onClick={startRename}
              onDoubleClick={startRename}
            >
              <Pencil className="w-3 h-3" />
            </span>
          )}
          {/* S4: 会话状态徽章 —— 优先级 注意力 > 运行中 > 失败 > 挂起 > 刚完成 */}
          {hasAttention && (
            <span
              data-testid="session-attention"
              aria-label={t('session.attention')}
              title={t('session.attention')}
              className="inline-flex flex-shrink-0 w-2 h-2 rounded-full bg-warning animate-pulse"
            />
          )}
          {isLive && (
            <span
              data-testid="session-running"
              aria-label={t('session.status_running')}
              title={t('session.status_running')}
              className="inline-flex flex-shrink-0 text-primary"
            >
              <Loader2 className="w-3 h-3 animate-spin" />
            </span>
          )}
          {!isLive && failed && (
            <span
              data-testid="session-failed"
              aria-label={t('session.status_failed')}
              title={
                session.last_error
                  ? `${t('session.status_failed')}: ${session.last_error}`
                  : t('session.status_failed')
              }
              className="inline-flex flex-shrink-0 text-error"
            >
              <AlertCircle className="w-3 h-3" />
            </span>
          )}
          {!isLive && suspended && (
            <span
              data-testid="session-suspended"
              aria-label={t('session.status_suspended')}
              title={t('session.status_suspended')}
              className="inline-flex flex-shrink-0 text-muted"
            >
              <PauseCircle className="w-3 h-3" />
            </span>
          )}
          {!isLive && showCompletedTick && (
            <span
              data-testid="session-completed"
              aria-label={t('session.status_completed')}
              title={t('session.status_completed')}
              className="inline-flex flex-shrink-0 text-success"
            >
              <Check className="w-3 h-3" />
            </span>
          )}
          {!isLive && hasCron && (
            <span
              data-testid="session-cron"
              aria-label={t('session.cron_badge')}
              title={t('session.cron_badge')}
              className="inline-flex flex-shrink-0 text-muted"
            >
              <Clock className="w-3 h-3" />
            </span>
          )}
          {/* S7: 产物计数（本次运行） */}
          {artifactCount > 0 && (
            <span
              data-testid="session-artifacts-badge"
              title={t('session.artifacts_badge').replace('{count}', String(artifactCount))}
              className="inline-flex flex-shrink-0 items-center gap-0.5 text-[10px] text-muted"
            >
              <Paperclip className="w-3 h-3" />
              {artifactCount}
            </span>
          )}
          {/* S6-lite: 文件变更计数（本次运行） */}
          {changeCount > 0 && (
            <span
              data-testid="session-changes-badge"
              title={t('session.changes_badge').replace('{count}', String(changeCount))}
              className="inline-flex flex-shrink-0 text-[10px] font-medium text-primary"
            >
              +{changeCount}
            </span>
          )}
          {/* F12: 消息内容命中（侧栏搜索增强） */}
          {messageHits != null && messageHits > 0 && (
            <span
              data-testid="session-message-hits"
              title={t('session.message_hits').replace('{count}', String(messageHits))}
              className="inline-flex flex-shrink-0 items-center gap-0.5 text-[10px] font-medium text-primary"
            >
              <Search className="w-3 h-3" />
              {messageHits}
            </span>
          )}
        </p>
        <p className="text-xs text-muted truncate">
          {/* P0-4 (UI 优化方案 2026-09-13): 元信息行 — 消息预览 + 相对时间 + 消息数 */}
          {session.last_message_preview ? (
            <span className="truncate">{session.last_message_preview}</span>
          ) : (
            <span>{formatRelativeTime(session.last_message_at ?? session.updated_at)}</span>
          )}
          <span className="mx-1 text-muted/50">·</span>
          <span className="flex-shrink-0">
            {formatRelativeTime(session.last_message_at ?? session.updated_at)}
          </span>
          {session.message_count > 0 && (
            <>
              <span className="mx-1 text-muted/50">·</span>
              <span className="flex-shrink-0">{session.message_count} 条</span>
            </>
          )}
        </p>
        {/* S5: mini 进度条 —— 编排 5 元组 / todo 完成度（仅运行中显示） */}
        {isLive && (progress != null || todoTotal > 0) && (
          <div className="mt-1 flex items-center gap-1.5" data-testid="session-progress">
            <div className="flex-1 h-0.5 rounded bg-bg-hover overflow-hidden min-w-6">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${progressPercent(progress, todoDone, todoTotal)}%` }}
              />
            </div>
            <span className="text-[10px] text-muted flex-shrink-0">
              {progress != null ? `${progress.done}/${progress.total}` : `${todoDone}/${todoTotal}`}
            </span>
          </div>
        )}
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {session.is_pinned && <Pin className="w-4 h-4 text-primary" />}
        {/* U18: 导出完整会话为自包含 HTML */}
        <button
          data-testid="export-session"
          onClick={handleExport}
          disabled={exporting}
          className="p-1 rounded hover:bg-primary/10 text-muted hover:text-primary disabled:opacity-50"
          title={exporting ? t('session.export_html_exporting') : t('session.export_html')}
          aria-label={t('session.export_html')}
        >
          <Download className="w-4 h-4" />
        </button>
        {/* R18-C: Markdown 导出 —— 轻量文本,便于归档与版本管理 */}
        <button
          data-testid="export-session-md"
          onClick={handleExportMarkdown}
          disabled={exportingMd}
          className="p-1 rounded hover:bg-primary/10 text-muted hover:text-primary disabled:opacity-50"
          title={t('session.export_md')}
          aria-label={t('session.export_md')}
        >
          <FileText className="w-4 h-4" />
        </button>
        {/* R18-B: 置顶切换 —— 置顶会话在侧栏置顶组中始终排在最前 */}
        <button
          data-testid="toggle-pin"
          onClick={handleTogglePin}
          disabled={pinning}
          className={`p-1 rounded disabled:opacity-50 ${
            session.is_pinned
              ? 'text-primary hover:bg-primary/10'
              : 'text-muted hover:bg-bg-hover hover:text-primary'
          }`}
          title={session.is_pinned ? t('session.unpin') : t('session.pin')}
          aria-label={session.is_pinned ? t('session.unpin') : t('session.pin')}
        >
          {session.is_pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
        </button>
        {/* U12: 两步式确认删除 — 不弹 modal，armed 后二次点击生效 */}
        <TwoStepDelete
          data-testid="delete-session"
          onConfirm={onDelete}
          label={t('common.delete')}
          armedLabel={t('common.delete_confirm')}
          className="p-1"
        />
      </div>
    </div>
  );
}

function hasFreshRunAt(lastRunAt?: number | null): boolean {
  if (lastRunAt == null) return false;
  return Date.now() - lastRunAt < COMPLETED_FRESH_MS;
}

/** completed ✓ 保鲜到期后强制一次重渲染让徽章消失（不引入全局 ticker）。 */
function useExpireAfter(visible: boolean, lastRunAt: number | undefined | null, ttlMs: number) {
  const [, tick] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    if (!visible || lastRunAt == null) return;
    const remaining = lastRunAt + ttlMs - Date.now();
    if (remaining <= 0) {
      tick();
      return;
    }
    const timer = setTimeout(tick, remaining);
    return () => clearTimeout(timer);
  }, [visible, lastRunAt, ttlMs]);
  return visible;
}

function progressPercent(
  progress: { total: number; done: number } | undefined,
  todoDone: number,
  todoTotal: number,
): number {
  const done = progress != null ? progress.done : todoDone;
  const total = progress != null ? progress.total : todoTotal;
  if (total <= 0) return 0;
  return Math.min(100, Math.round((done / total) * 100));
}
