// electron/schedulerNotifications.ts
//
// 后台任务完成通知轮询器（2026-11-05）。
//
// 后端把"定时任务触发/失败"与"待办提醒"累积在两个内存队列里；
// GET /api/v1/scheduled/notifications/pending 原子排空它们。
// 本模块在主进程每 15s 拉一次，转成 OS 通知——不依赖 renderer 是否
// 在运行，因此最小化/关闭到托盘后仍能收到提醒。
//
// 抽成独立模块便于单测：所有外部依赖（fetch/通知/偏好）由调用方注入。

export interface PendingNotificationItem {
  title?: string;
  body?: string;
  status?: string;
  urgency?: string;
}

export interface PendingNotificationsPayload {
  scheduled_tasks?: PendingNotificationItem[];
  todo_reminders?: PendingNotificationItem[];
  /** 2026-11-06 Phase 1: 后台 Bash 任务完成通知 */
  background_tasks?: PendingNotificationItem[];
}

export interface SchedulerNotificationPollerDeps {
  fetchPending: () => Promise<PendingNotificationsPayload>;
  isEnabled: () => boolean;
  notify: (title: string, body: string) => void;
  intervalMs?: number;
  log?: (event: string, details?: Record<string, unknown>) => void;
}

export const SCHEDULER_NOTIFICATION_POLL_MS = 15_000;

/** 合并两路队列并丢弃没有标题的条目。 */
export function collectNotificationItems(
  payload: PendingNotificationsPayload | null | undefined,
): PendingNotificationItem[] {
  const items = [
    ...(payload?.scheduled_tasks ?? []),
    ...(payload?.todo_reminders ?? []),
    ...(payload?.background_tasks ?? []),
  ];
  return items.filter((item) => typeof item.title === 'string' && item.title.length > 0);
}

/**
 * 启动轮询器；返回停止函数。
 *
 * - `isEnabled()` 为 false 时跳过整轮（连请求都不发）。
 * - 上一轮未完成时跳过本轮，避免慢后端下堆积并发请求。
 * - 任何拉取/通知异常都只记日志，不中断轮询。
 */
export function startSchedulerNotificationPoller(
  deps: SchedulerNotificationPollerDeps,
): () => void {
  const intervalMs = deps.intervalMs ?? SCHEDULER_NOTIFICATION_POLL_MS;
  let busy = false;

  const tick = async (): Promise<void> => {
    if (busy || !deps.isEnabled()) return;
    busy = true;
    try {
      const payload = await deps.fetchPending();
      for (const item of collectNotificationItems(payload)) {
        deps.notify(item.title ?? '', item.body ?? '');
      }
    } catch (err) {
      deps.log?.('scheduler-notifications: poll failed', { error: String(err) });
    } finally {
      busy = false;
    }
  };

  const timer = setInterval(() => {
    void tick();
  }, intervalMs);
  // Node 定时器不应阻止进程退出。
  (timer as unknown as { unref?: () => void }).unref?.();

  return () => clearInterval(timer);
}
