// electron/webhookDelivery.ts
//
// Webhook / Slack 外发（2026-11-06 Phase 3；Phase 4 增加签名与重试）。
//
// 主进程通知轮询器排空后端通知队列后，对每条通知额外投递：
//   - webhookUrl        → POST JSON {type:'sage_notification', kind, title, ...}
//   - slackWebhookUrl   → POST {"text": "title\nbody"}（Slack Incoming Webhook）
//
// Phase 4：
//   - webhookSecret 非空时，通用 Webhook 附带
//     `X-Sage-Signature: sha256=<hex(hmac_sha256(secret, body))>` 供接收方验签。
//   - 每个 URL 最多 3 次尝试（初始 + 2 次重试），退避 1s / 3s；
//     仅网络异常或非 2xx 重试。sleep/时间参数可注入以便单测。
//
// 仍为 fire-and-forget：重试在后台异步任务内完成，不阻塞轮询器。
// 5s 超时由 AbortController 控制（Electron 21 的 Node 16 无 AbortSignal.timeout）。

import { createHmac } from 'node:crypto';

import type { PendingNotificationItem } from './schedulerNotifications';

export interface WebhookPrefs {
  webhookUrl: string;
  slackWebhookUrl: string;
  webhookSecret?: string;
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

/** HMAC-SHA256 签名（hex），格式与常见 webhook 验签约定一致。 */
export function buildWebhookSignature(secret: string, body: string): string {
  return `sha256=${createHmac('sha256', secret).update(body).digest('hex')}`;
}

type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string>; body: string; signal?: AbortSignal },
) => Promise<unknown>;

type SleepFn = (ms: number) => Promise<void>;

export const WEBHOOK_TIMEOUT_MS = 5_000;
export const WEBHOOK_MAX_ATTEMPTS = 3;
export const WEBHOOK_RETRY_DELAYS_MS = [1_000, 3_000];

const defaultSleep: SleepFn = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

interface PostOptions {
  timeoutMs: number;
  maxAttempts: number;
  retryDelays: number[];
  sleep: SleepFn;
  extraHeaders?: Record<string, string>;
  log?: (event: string, details?: Record<string, unknown>) => void;
  label: string;
}

async function postJson(
  fetchImpl: FetchLike,
  url: string,
  payload: unknown,
  options: PostOptions,
): Promise<void> {
  const body = JSON.stringify(payload);
  const { timeoutMs, maxAttempts, retryDelays, sleep, extraHeaders, log, label } = options;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = (await fetchImpl(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(extraHeaders ?? {}) },
        body,
        signal: controller.signal,
      })) as { ok?: boolean; status?: number } | undefined;
      if (response && response.ok === false) {
        throw new Error(`HTTP ${response.status ?? 'error'}`);
      }
      return;
    } catch (err) {
      if (attempt >= maxAttempts) {
        log?.(`${label} failed after ${maxAttempts} attempts`, {
          error: String(err),
        });
        return;
      }
      const delay = retryDelays[Math.min(attempt - 1, retryDelays.length - 1)] ?? 0;
      await sleep(delay);
    } finally {
      clearTimeout(timer);
    }
  }
}

export interface WebhookDeliverOptions {
  fetchImpl?: FetchLike;
  log?: (event: string, details?: Record<string, unknown>) => void;
  timeoutMs?: number;
  maxAttempts?: number;
  retryDelays?: number[];
  sleep?: SleepFn;
}

/**
 * 创建逐条通知的 webhook 投递函数。
 *
 * @param getPrefs 读取当前偏好（每次投递重新读取，设置修改即时生效）
 */
export function createWebhookDeliver(
  getPrefs: () => WebhookPrefs,
  options: WebhookDeliverOptions = {},
): (item: PendingNotificationItem) => void {
  const fetchImpl = options.fetchImpl ?? (fetch as unknown as FetchLike);
  const sleep = options.sleep ?? defaultSleep;
  const timeoutMs = options.timeoutMs ?? WEBHOOK_TIMEOUT_MS;
  const maxAttempts = options.maxAttempts ?? WEBHOOK_MAX_ATTEMPTS;
  const retryDelays = options.retryDelays ?? WEBHOOK_RETRY_DELAYS_MS;
  const log = options.log;

  return (item) => {
    const prefs = getPrefs();
    const genericUrl = (prefs.webhookUrl ?? '').trim();
    const slackUrl = (prefs.slackWebhookUrl ?? '').trim();
    if (!genericUrl && !slackUrl) return;
    const secret = (prefs.webhookSecret ?? '').trim();

    void (async () => {
      if (genericUrl) {
        const body = JSON.stringify(buildWebhookPayload(item));
        const extraHeaders: Record<string, string> = {};
        if (secret) {
          extraHeaders['X-Sage-Signature'] = buildWebhookSignature(secret, body);
        }
        await postJson(fetchImpl, genericUrl, buildWebhookPayload(item), {
          timeoutMs,
          maxAttempts,
          retryDelays,
          sleep,
          extraHeaders,
          log,
          label: 'webhook: generic delivery',
        });
      }
      if (slackUrl) {
        await postJson(fetchImpl, slackUrl, buildSlackPayload(item), {
          timeoutMs,
          maxAttempts,
          retryDelays,
          sleep,
          log,
          label: 'webhook: slack delivery',
        });
      }
    })();
  };
}
