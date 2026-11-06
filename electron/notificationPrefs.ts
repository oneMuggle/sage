// electron/notificationPrefs.ts
//
// 通知偏好持久化（2026-11-05）。
//
// 主进程无 SQLite 依赖——沿用 closeToTray / pet-config 的 JSON 文件先例：
// <userData>/sage-notification-prefs.json（dev = <cwd>/data/）。
// main.ts 在发 OS 通知前读取本模块维护的内存态；设置页通过 IPC 读写。
//
// 两个开关：
//   enabled          —— 全局通知总开关（会话完成/失败、审批等待）
//   backgroundTasks  —— 后台任务通知（定时任务触发、待办提醒、子代理完成）

import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export interface NotificationPrefs {
  enabled: boolean;
  backgroundTasks: boolean;
  /** 2026-11-06 Phase 3: 通用 Webhook（JSON POST），空 = 关闭。 */
  webhookUrl: string;
  /** 2026-11-06 Phase 3: Slack Incoming Webhook，空 = 关闭。 */
  slackWebhookUrl: string;
}

export const DEFAULT_NOTIFICATION_PREFS: NotificationPrefs = {
  enabled: true,
  backgroundTasks: true,
  webhookUrl: '',
  slackWebhookUrl: '',
};

export function getNotificationPrefsPath(
  isPackaged: boolean,
  userDataPath: string,
  cwd: string,
): string {
  if (isPackaged) return join(userDataPath, 'sage-notification-prefs.json');
  return join(cwd, 'data', 'sage-notification-prefs.json');
}

export function readNotificationPrefs(path: string): NotificationPrefs {
  try {
    const raw = readFileSync(path, 'utf-8');
    const parsed = JSON.parse(raw) as Partial<NotificationPrefs>;
    // 缺字段按默认开启处理：升级用户不会被静默静音。
    return {
      enabled: parsed.enabled !== false,
      backgroundTasks: parsed.backgroundTasks !== false,
      webhookUrl: typeof parsed.webhookUrl === 'string' ? parsed.webhookUrl : '',
      slackWebhookUrl:
        typeof parsed.slackWebhookUrl === 'string' ? parsed.slackWebhookUrl : '',
    };
  } catch {
    // 文件不存在/JSON 损坏 → 默认开（保持既有"默认提醒"预期）
    return { ...DEFAULT_NOTIFICATION_PREFS };
  }
}

export function writeNotificationPrefs(path: string, prefs: NotificationPrefs): void {
  writeFileSync(path, JSON.stringify(prefs), 'utf-8');
}
