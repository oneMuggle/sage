// src/features/task-center/TaskCenterCard.tsx
//
// 统一的任务卡片。侧边栏 compact 分区与 /tasks 完整页面共用同一组件。
// 放在 features 层：TaskCenterPanel（features）要复用它，而 features 不得 import widgets。
import { clsx } from 'clsx';
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  ListTodo,
  Loader2,
  MessageSquare,
  Network,
  PauseCircle,
  Play,
  Target,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import type { TaskCenterStatus } from './taskCenterStore';
import type { UnifiedTaskEntry, UnifiedTaskSource } from './unifiedTaskModel';
import type { TaskCenterActions } from './useTaskCenterActions';

const SOURCE_ICON: Record<UnifiedTaskSource, LucideIcon> = {
  registry: FileSpreadsheet,
  chat: MessageSquare,
  lane: Network,
  goal: Target,
  todo: ListTodo,
  scheduled: CalendarClock,
};

const STATUS_ICON: Record<TaskCenterStatus, LucideIcon> = {
  queued: Clock,
  running: Loader2,
  awaiting_approval: AlertCircle,
  paused: PauseCircle,
  succeeded: CheckCircle2,
  failed: XCircle,
  cancelled: XCircle,
};

const STATUS_TONE: Record<TaskCenterStatus, string> = {
  queued: 'text-muted',
  running: 'text-primary',
  awaiting_approval: 'text-warning',
  paused: 'text-muted',
  succeeded: 'text-success',
  failed: 'text-error',
  cancelled: 'text-muted',
};

function formatElapsed(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hour = Math.floor(min / 60);
  return `${hour}h ${min % 60}m`;
}

export interface TaskCenterCardProps {
  entry: UnifiedTaskEntry;
  actions: TaskCenterActions;
  compact?: boolean;
}

export function TaskCenterCard({ entry, actions, compact = false }: TaskCenterCardProps) {
  const { t } = useI18n();
  const SourceIcon = SOURCE_ICON[entry.source];
  const StatusIcon = STATUS_ICON[entry.status];
  const tone = STATUS_TONE[entry.status];
  const sourceLabel = t(`taskCenter.source.${entry.source}` as TranslationKey);
  const statusLabel = t(`taskCenter.status.${entry.status}` as TranslationKey);

  const elapsed =
    entry.startedAt != null && entry.status === 'running'
      ? formatElapsed(Date.now() - entry.startedAt)
      : null;

  // Spec §5.7 动作矩阵：goal 显示 pause/resume 切换；scheduled 显示 runNow。
  const showPauseResume =
    entry.source === 'goal' &&
    entry.cancelRef != null &&
    (entry.status === 'running' || entry.status === 'paused');
  const showRunNow = entry.source === 'scheduled';
  const isGoalRunning = showPauseResume && entry.status === 'running';

  return (
    <div className="group flex items-start gap-2 px-3 py-1.5 rounded-md hover:bg-bg-hover transition-colors">
      <button
        type="button"
        onClick={() => actions.open(entry)}
        aria-label={`${entry.title} · ${statusLabel}`}
        title={t('taskCenter.action.viewDetail')}
        className="flex-1 min-w-0 text-left"
      >
        <div className="flex items-center gap-1.5">
          <SourceIcon className="w-3.5 h-3.5 shrink-0 text-muted" aria-hidden />
          <span className="truncate text-ui-sm text-text">{entry.title}</span>
          <StatusIcon
            className={clsx(
              'w-3.5 h-3.5 shrink-0',
              tone,
              entry.status === 'running' && 'animate-spin',
            )}
            aria-hidden
          />
          <span className={clsx('text-ui-2xs shrink-0', tone)}>{statusLabel}</span>
        </div>

        <div className="mt-0.5 flex items-center gap-2">
          {!compact && <span className="text-ui-2xs text-muted shrink-0">{sourceLabel}</span>}
          {entry.percent != null ? (
            <div
              className="h-1 flex-1 max-w-[120px] rounded-full bg-ui-border overflow-hidden"
              role="progressbar"
              aria-valuenow={entry.percent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="h-full bg-primary transition-[width]"
                style={{ width: `${Math.min(100, Math.max(0, entry.percent))}%` }}
              />
            </div>
          ) : elapsed ? (
            <span className="text-ui-2xs text-muted">{elapsed}</span>
          ) : null}
          {entry.status === 'failed' && entry.error && (
            <span className="text-ui-2xs text-error truncate" title={entry.error}>
              {entry.error}
            </span>
          )}
        </div>
      </button>

      {showPauseResume && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            if (isGoalRunning) void actions.pause(entry);
            else void actions.resume(entry);
          }}
          className="shrink-0 p-1 rounded text-muted hover:text-primary opacity-0 group-hover:opacity-100 focus:opacity-100"
          aria-label={isGoalRunning ? t('taskCenter.action.pause') : t('taskCenter.action.resume')}
          title={isGoalRunning ? t('taskCenter.action.pause') : t('taskCenter.action.resume')}
        >
          {isGoalRunning ? (
            <PauseCircle className="w-3.5 h-3.5" aria-hidden />
          ) : (
            <Play className="w-3.5 h-3.5" aria-hidden />
          )}
        </button>
      )}

      {showRunNow && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            void actions.runNow(entry);
          }}
          className="shrink-0 p-1 rounded text-muted hover:text-primary opacity-0 group-hover:opacity-100 focus:opacity-100"
          aria-label={t('taskCenter.action.runNow')}
          title={t('taskCenter.action.runNow')}
        >
          <Play className="w-3.5 h-3.5" aria-hidden />
        </button>
      )}

      {entry.cancellable && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            void actions.cancel(entry);
          }}
          className="shrink-0 p-1 rounded text-muted hover:text-error opacity-0 group-hover:opacity-100 focus:opacity-100"
          aria-label={t('taskCenter.action.cancel')}
          title={t('taskCenter.action.cancel')}
        >
          <X className="w-3.5 h-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}
