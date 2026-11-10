// electron/schedulerNotifications.ts
//
// 后台任务完成通知轮询器（2026-11-05）。
//
// 后端把"定时任务触发/失败"、"待办提醒"、"后台任务完成"与"闲时目标终态"累积在四个内存队列里；
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
  /** 2026-11-06 Phase 3: webhook 载荷补充字段 */
  kind?: string;
  session_id?: string;
  created_at?: string;
}

export interface PendingNotificationsPayload {
  scheduled_tasks?: PendingNotificationItem[];
  todo_reminders?: PendingNotificationItem[];
  /** 2026-11-06 Phase 1: 后台 Bash 任务完成通知 */
  background_tasks?: PendingNotificationItem[];
  /** 2026-11-09: 闲时目标终态通知（独立队列，不混入 background_tasks） */
  goal_notifications?: PendingNotificationItem[];
}

export interface SchedulerNotificationPollerDeps {
  fetchPending: () => Promise<PendingNotificationsPayload>;
  isEnabled: () => boolean;
  notify: (title: string, body: string) => void;
  /** 2026-11-06 Phase 3: 每条通知额外投递（Webhook / Slack），可选。 */
  deliver?: (item: PendingNotificationItem) => void;
  intervalMs?: number;
  log?: (event: string, details?: Record<string, unknown>) => void;
}

export const SCHEDULER_NOTIFICATION_POLL_MS = 15_000;

/** 合并四路队列并丢弃没有标题的条目。 */
export function collectNotificationItems(
  payload: PendingNotificationsPayload | null | undefined,
): PendingNotificationItem[] {
  const items = [
    ...(payload?.scheduled_tasks ?? []),
    ...(payload?.todo_reminders ?? []),
    ...(payload?.background_tasks ?? []),
    ...(payload?.goal_notifications ?? []),
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
        // fire-and-forget 外发；deliver 内部自行隔离异常
        deps.deliver?.(item);
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
