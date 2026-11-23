// electron/orchNotifications.ts
//
// 待展示通知 → OS 通知 + 点击深链（M4.3a, 2026-11-23）。
//
// 职责边界：**只**负责"把一条待展示通知变成 OS 通知，并把点击回传给
// 渲染进程"。通知从哪来（轮询器 / 队列）不归这里管。
//
// 深链：编排类通知带 run_id（可选 task_id），点击时聚焦窗口并回发
// 'sage:event:orch-notify-click'；渲染进程据此深链到任务中心。
// 其余队列（定时任务 / 待办 / 后台任务 / 目标 / 项目健康）没有深链
// 锚点，点击行为与 M4.3a 之前保持一致（仅展示）。
//
// 窗口句柄由调用方注入（main.ts 传 () => mainWindow）—— 本模块不持有
// 全局窗口，便于单测。

import { Notification } from 'electron';
import type { BrowserWindow } from 'electron';

import type { PendingNotificationItem } from './schedulerNotifications';

/** 点击通知后回发给渲染进程的深链锚点。 */
export interface OrchNotifyClickTarget {
  sessionId: string;
  runId: string;
  taskId: string;
}

/** 主进程回发的 IPC 事件名（渲染进程 listen 用；preload 走通用 sage:event:* 通道）。 */
export const ORCH_NOTIFY_CLICK_EVENT = 'sage:event:orch-notify-click';

/** 通知标题 / 正文的截断上限（与 M4.3a 之前的内联实现一致）。 */
const TITLE_MAX_CHARS = 120;
const BODY_MAX_CHARS = 200;

/** 由通知条目解析点击深链锚点。 */
export function toClickTarget(item: PendingNotificationItem): OrchNotifyClickTarget {
  return {
    sessionId: item.session_id ?? '',
    runId: item.run_id ?? '',
    taskId: item.task_id ?? '',
  };
}

/**
 * 展示一条待展示通知；编排类通知带点击深链。
 *
 * getWindow 由调用方注入 —— 本模块不持有全局窗口引用，便于单测。
 */
export function showPendingNotification(
  item: PendingNotificationItem,
  getWindow: () => BrowserWindow | null,
): void {
  if (!Notification.isSupported()) return;
  const title = (item.title ?? '').slice(0, TITLE_MAX_CHARS);
  const body = (item.body ?? '').slice(0, BODY_MAX_CHARS);
  const notification = new Notification({ title, body, silent: false });

  // 只有带 run_id 的编排通知才有深链；其余队列保持"仅展示"语义。
  if (item.run_id) {
    const target = toClickTarget(item);
    notification.on('click', () => {
      const win = getWindow();
      if (!win || win.isDestroyed()) return;
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
      win.webContents.send(ORCH_NOTIFY_CLICK_EVENT, target);
    });
  }

  notification.show();
}
