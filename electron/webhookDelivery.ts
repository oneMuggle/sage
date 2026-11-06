// electron/webhookDelivery.ts
//
// Webhook / Slack 外发（2026-11-06 Phase 3）。
//
// 主进程通知轮询器排空后端通知队列后，对每条通知额外投递：
//   - webhookUrl        → POST JSON {type:'sage_notification', kind, title, ...}
//   - slackWebhookUrl   → POST {"text": "title\nbody"}（Slack Incoming Webhook）
//
// fire-and-forget：外发失败只记日志，不阻塞轮询器、不重试（下一条通知不等待）。
// 5s 超时由 AbortController 控制（Electron 21 的 Node 16 无 AbortSignal.timeout）。

import type { PendingNotificationItem } from './schedulerNotifications';

export interface WebhookPrefs {
  webhookUrl: string;
  slackWebhookUrl: string;
}

/** 通用 Webhook 载荷（合成/脱敏字段）。 */
export function buildWebhookPayload(item: PendingNotificationItem): Record<string, unknown> {
  return {
    type: 'sage_notification',
    kind: item.kind ?? '',
    title: item.title ?? '',
    body: item.body ?? '',
    status: item.status ?? '',
    session_id: item.session_id ?? '',
    created_at: item.created_at ?? '',
  };
}

/** Slack Incoming Webhook 载荷。 */
export function buildSlackPayload(item: PendingNotificationItem): { text: string } {
  return {
    text: `${item.title ?? ''}\n${item.body ?? ''}`.trim(),
  };
}

type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string>; body: string; signal?: AbortSignal },
) => Promise<unknown>;

export const WEBHOOK_TIMEOUT_MS = 5_000;

async function postJson(
  fetchImpl: FetchLike,
  url: string,
  payload: unknown,
  timeoutMs: number,
): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await fetchImpl(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 创建逐条通知的 webhook 投递函数。
 *
 * @param getPrefs 读取当前偏好（每次投递重新读取，设置修改即时生效）
 * @param fetchImpl 注入以便单测
 */
export function createWebhookDeliver(
  getPrefs: () => WebhookPrefs,
  fetchImpl: FetchLike = fetch as unknown as FetchLike,
  log?: (event: string, details?: Record<string, unknown>) => void,
  timeoutMs: number = WEBHOOK_TIMEOUT_MS,
): (item: PendingNotificationItem) => void {
  return (item) => {
    const prefs = getPrefs();
    const genericUrl = (prefs.webhookUrl ?? '').trim();
    const slackUrl = (prefs.slackWebhookUrl ?? '').trim();
    if (!genericUrl && !slackUrl) return;

    void (async () => {
      if (genericUrl) {
        try {
          await postJson(fetchImpl, genericUrl, buildWebhookPayload(item), timeoutMs);
        } catch (err) {
          log?.('webhook: generic delivery failed', { error: String(err) });
        }
      }
      if (slackUrl) {
        try {
          await postJson(fetchImpl, slackUrl, buildSlackPayload(item), timeoutMs);
        } catch (err) {
          log?.('webhook: slack delivery failed', { error: String(err) });
        }
      }
    })();
  };
}
