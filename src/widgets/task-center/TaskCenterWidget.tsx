// src/widgets/task-center/TaskCenterWidget.tsx
//
// P4 first slice (docs/plans/2026-09-13_ui-optimization-p4-task-center.md):
// global task-center floating capsule. Aggregates long-running work so users
// who navigate away still see what is still running:
//  - registry tasks from taskCenterStore (office / wiki / custom run states)
//  - background session chat streams (chatStreamStore slots, single source)
//  - orchestration lanes (laneBoardStore, active / blocked / failed)
// Renders nothing when idle; collapsed shows a count capsule, expanded lists
// entries that jump to their page.
//
// P5 dedupe: the current session stream is already expressed inside Chat
// (ActiveAgentIndicator / cursor / right-panel progress), so the capsule only
// lists streams of OTHER sessions. Per-session sidebar badges stay untouched.
//
// A1 (parity-s4): entries carry a unified TaskCenterStatus, failures render an
// error row, chat streams and lanes cancel in place, and finished registry
// entries stay visible until cleared.

import { AlertCircle, CheckCircle2, Clock, Loader2, PauseCircle, X, XCircle } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { useChatStreamStore } from '../../features/send-message/chatStreamStore';
import { cancelSessionStream } from '../../features/send-message/useChat';
import {
  TERMINAL_TASK_STATUSES,
  useTaskCenterStore,
  type OfficeDeliveryRef,
  type TaskCenterStatus,
} from '../../features/task-center/taskCenterStore';
import type { Lane, LaneStatus } from '../../shared/api/types';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';

type EntrySource = 'registry' | 'chat' | 'lane';

interface Entry {
  id: string;
  source: EntrySource;
  title: string;
  status: TaskCenterStatus;
  startedAt: number | null;
  route: string | null;
  /** P7: backend percent channel (registry tasks only). */
  percent?: number | null;
  error?: string | null;
  cancellable: boolean;
  sessionId?: string;
  laneId?: string;
  /** A4b: office 交付包坐标（awaiting 条目开抽屉用）。 */
  deliveryRef?: OfficeDeliveryRef | null;
  /** P11: 关联文档名（office 条目跳转后高亮文档行）。 */
  docName?: string | null;
  /**
   * A4: 点击直达交付抽屉（而非 route 跳转）。仅交付待验收项置位；
   * blocked lane 等仍走原 route（其 awaiting 语义是等审批/输入，
   * 非交付验收）。
   */
  opensDelivery?: boolean;
}

const STATUS_LABEL_KEYS: Readonly<Record<TaskCenterStatus, TranslationKey>> = {
  queued: 'taskCenter.status.queued',
  running: 'taskCenter.status.running',
  awaiting_approval: 'taskCenter.status.awaiting_approval',
  paused: 'taskCenter.status.paused',
  succeeded: 'taskCenter.status.succeeded',
  failed: 'taskCenter.status.failed',
  cancelled: 'taskCenter.status.cancelled',
};

const LANE_STATUS_MAP: Readonly<Record<LaneStatus, TaskCenterStatus>> = {
  created: 'queued',
  ready: 'queued',
  running: 'running',
  blocked: 'awaiting_approval',
  succeeded: 'succeeded',
  failed: 'failed',
  stopped: 'cancelled',
  cancelled: 'cancelled',
};

/** A1: lanes worth surfacing in the capsule (live work plus failures). */
function isLaneVisible(status: LaneStatus): boolean {
  return (
    status === 'created' ||
    status === 'ready' ||
    status === 'running' ||
    status === 'blocked' ||
    status === 'failed'
  );
}

/**
 * A4: 待验收 lane —— succeeded 且尚未决议（无 accepted_at/rejected_at）。
 * 在胶囊中以 awaiting_approval 呈现，点击直达交付抽屉。
 */
function isLaneAwaitingDecision(lane: Lane): boolean {
  if (lane.status !== 'succeeded') return false;
  const meta = lane.metadata ?? {};
  return typeof meta.accepted_at !== 'number' && typeof meta.rejected_at !== 'number';
}

function isLaneCancellable(status: LaneStatus): boolean {
  return status === 'created' || status === 'ready' || status === 'running' || status === 'blocked';
}

function StatusIcon({ status }: { status: TaskCenterStatus }) {
  const cls = 'w-3.5 h-3.5 shrink-0';
  switch (status) {
    case 'running':
      return <Loader2 className={`${cls} text-primary animate-spin`} aria-hidden />;
    case 'queued':
      return <Clock className={`${cls} text-muted`} aria-hidden />;
    case 'awaiting_approval':
      return <AlertCircle className={`${cls} text-warning`} aria-hidden />;
    case 'paused':
      return <PauseCircle className={`${cls} text-muted`} aria-hidden />;
    case 'succeeded':
      return <CheckCircle2 className={`${cls} text-success`} aria-hidden />;
    case 'failed':
      return <XCircle className={`${cls} text-error`} aria-hidden />;
    case 'cancelled':
      return <X className={`${cls} text-muted`} aria-hidden />;
  }
}

export function TaskCenterWidget() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [cancellingIds, setCancellingIds] = useState<ReadonlySet<string>>(new Set());

  const registryTasks = useTaskCenterStore((s) => s.tasks);
  const clearFinished = useTaskCenterStore((s) => s.clearFinished);
  const openDelivery = useTaskCenterStore((s) => s.openDelivery);
  const setHighlight = useTaskCenterStore((s) => s.setHighlight);
  const streamSessions = useChatStreamStore((s) => s.sessions);
  const lanes = useLaneBoardStore((s) => s.lanes);
  const cancelLane = useLaneBoardStore((s) => s.cancel);
  const sessions = useStore((s) => s.sessions);
  const currentSessionId = useStore((s) => s.currentSessionId);

  // First-seen time of chat streams: chatStreamStore has no startedAt, so the
  // capsule records it here to render elapsed time like registry tasks.
  const streamStartsRef = useRef<Map<string, number>>(new Map());

  const activeStreamIds = useMemo(
    () =>
      Object.entries(streamSessions)
        .filter(([, slots]) => slots.streaming != null)
        // P5 dedupe: the current session stream is expressed inside Chat.
        .map(([id]) => id)
        .filter((id) => id !== currentSessionId),
    [streamSessions, currentSessionId],
  );

  // Maintain first-seen times and drop entries whose stream ended.
  useEffect(() => {
    for (const id of activeStreamIds) {
      if (!streamStartsRef.current.has(id)) {
        streamStartsRef.current.set(id, Date.now());
      }
    }
    for (const id of streamStartsRef.current.keys()) {
      if (!activeStreamIds.includes(id)) {
        streamStartsRef.current.delete(id);
      }
    }
  }, [activeStreamIds]);

  const entries = useMemo<Entry[]>(() => {
    const registryEntries: Entry[] = Object.values(registryTasks).map((task) => ({
      id: task.id,
      source: 'registry',
      title: task.phase ? `${task.title} · ${task.phase}` : task.title,
      status: task.status,
      startedAt: task.startedAt,
      route: task.kind === 'office' ? '/office' : task.kind === 'wiki' ? '/knowledge' : null,
      percent: task.percent ?? null,
      error: task.error ?? null,
      cancellable: false,
      deliveryRef: task.deliveryRef ?? null,
      opensDelivery: task.status === 'awaiting_approval' && task.deliveryRef != null,
    }));
    const chatEntries: Entry[] = activeStreamIds.map((id) => ({
      id: `chat:${id}`,
      source: 'chat',
      title: sessions.find((s) => s.id === id)?.title ?? t('taskCenter.chatFallback'),
      status: 'running',
      startedAt: streamStartsRef.current.get(id) ?? null,
      route: `/chat?session=${encodeURIComponent(id)}`,
      cancellable: true,
      sessionId: id,
    }));
    const laneEntries: Entry[] = lanes
      .filter((lane) => isLaneVisible(lane.status) || isLaneAwaitingDecision(lane))
      .map((lane) => ({
        id: `lane:${lane.lane_id}`,
        source: 'lane',
        title: `${t('taskCenter.laneFallback')} ${lane.task_id}${
          lane.agent_id ? ` · ${lane.agent_id}` : ''
        }`,
        status: isLaneAwaitingDecision(lane) ? 'awaiting_approval' : LANE_STATUS_MAP[lane.status],
        // Lane timestamps are backend-epoch based; elapsed display stays off
        // for lanes until a shared relative-time helper lands (A4).
        startedAt: null,
        route: '/orchestration',
        error: lane.error,
        cancellable: isLaneCancellable(lane.status),
        laneId: lane.lane_id,
        opensDelivery: isLaneAwaitingDecision(lane),
      }));
    return [...registryEntries, ...chatEntries, ...laneEntries];
    // streamStartsRef is a ref and stays out of deps: entries read it after
    // the maintenance effect above, so first-seen times are already present.
  }, [registryTasks, activeStreamIds, lanes, sessions, t]);

  const busy = entries.length > 0;
  const finishedCount = entries.filter((e) => TERMINAL_TASK_STATUSES.has(e.status)).length;

  // Ticking clock while tasks are active (decouples elapsed display); no timer
  // when idle.
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  const handleCancel = async (entry: Entry): Promise<void> => {
    if (cancellingIds.has(entry.id)) return;
    setCancellingIds((prev) => new Set(prev).add(entry.id));
    try {
      if (entry.source === 'chat' && entry.sessionId) {
        const ok = await cancelSessionStream(entry.sessionId);
        if (!ok) toast.error(t('taskCenter.cancelFailed'));
      } else if (entry.source === 'lane' && entry.laneId) {
        await cancelLane(entry.laneId);
      }
    } catch {
      toast.error(t('taskCenter.cancelFailed'));
    } finally {
      setCancellingIds((prev) => {
        const next = new Set(prev);
        next.delete(entry.id);
        return next;
      });
    }
  };

  const handleNavigate = (entry: Entry): void => {
    setExpanded(false);
    // A4: 交付待验收条目点击直达交付抽屉（其余仍走 route 跳转）。
    if (entry.opensDelivery) {
      if (entry.source === 'lane' && entry.laneId) {
        openDelivery({ kind: 'lane', laneId: entry.laneId });
        return;
      }
      if (entry.source === 'registry' && entry.deliveryRef) {
        openDelivery({ kind: 'office', entryId: entry.id });
        return;
      }
    }
    // P11: office 任务带关联文档名 → 跳转后定位并高亮对应文档行。
    if (entry.source === 'registry' && entry.route === '/office' && entry.docName) {
      setHighlight(entry.docName);
    }
    if (entry.route) navigate(entry.route);
  };

  if (!busy) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-40 flex flex-col items-end gap-2"
      data-testid="task-center"
    >
      {expanded && (
        <div
          data-testid="task-center-list"
          className="max-h-72 min-w-56 overflow-y-auto rounded-lg border border-border bg-surface shadow-lg p-1.5 flex flex-col gap-1"
        >
          {entries.map((entry) => {
            const terminal = TERMINAL_TASK_STATUSES.has(entry.status);
            const cancelling = cancellingIds.has(entry.id);
            return (
              <div
                key={entry.id}
                className="flex items-center gap-1 max-w-64 rounded text-left hover:bg-bg-hover transition-colors"
              >
                <button
                  type="button"
                  onClick={() => handleNavigate(entry)}
                  title={t(STATUS_LABEL_KEYS[entry.status])}
                  className="flex flex-1 items-center gap-2 px-2 py-1.5 text-xs text-text min-w-0"
                >
                  <StatusIcon status={entry.status} />
                  <span className="truncate flex-1">
                    {entry.title}
                    {entry.status === 'failed' && entry.error ? (
                      <span className="block truncate text-[10px] text-error">{entry.error}</span>
                    ) : null}
                  </span>
                  {entry.percent != null ? (
                    <span className="text-[10px] text-primary tabular-nums shrink-0">
                      {Math.round(entry.percent)}%
                    </span>
                  ) : entry.startedAt != null ? (
                    <span className="text-[10px] text-muted tabular-nums shrink-0">
                      {Math.max(0, Math.floor((now - entry.startedAt) / 1000))}s
                    </span>
                  ) : null}
                </button>
                {entry.cancellable && !terminal ? (
                  <button
                    type="button"
                    aria-label={t('taskCenter.cancel')}
                    data-testid={`task-center-cancel-${entry.id}`}
                    disabled={cancelling}
                    onClick={() => void handleCancel(entry)}
                    className="p-1 rounded text-text-secondary hover:text-error disabled:opacity-50 shrink-0"
                  >
                    {cancelling ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
                    ) : (
                      <X className="w-3.5 h-3.5" aria-hidden />
                    )}
                  </button>
                ) : null}
              </div>
            );
          })}
          {finishedCount > 0 ? (
            <button
              type="button"
              data-testid="task-center-clear"
              onClick={() => clearFinished()}
              className="mt-1 px-2 py-1 rounded text-[11px] text-text-secondary hover:text-text hover:bg-bg-hover transition-colors"
            >
              {t('taskCenter.clearFinished')}
            </button>
          ) : null}
        </div>
      )}
      <button
        type="button"
        data-testid="task-center-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface border border-border shadow-md text-xs text-text hover:bg-bg-hover transition-colors"
      >
        <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" aria-hidden />
        {t('taskCenter.activeCount').replace('{n}', String(entries.length))}
      </button>
    </div>
  );
}
