// electron/feedback/feedbackSyncer.ts
//
// 周期性把本地 SQLite 里尚未转发的用户消息推到管理员转发脚本，
// 并把管理员通过 Jira/GitLab/SMTP 回的回复拉回本地 SQLite。
//
// 数据流：
//   local backend  ──(GET /feedback/conversations/{id}/pending)──▶  syncer  ──▶  remote manager
//   remote manager ──(GET /feedback/conversations/{id}/messages?since=)──▶  syncer  ──▶  local backend
//
// 失败重试退避：[5min, 15min, 1h, 4h, 24h]。配置缺失（managerUrl / sharedSecret 任一为空）
// 时 syncer 不启动，等用户填好设置后手动 start() 或下次 app 启动时启动。
//
// 设计见 docs/plans/2026-10-29_direct-feedback-channel.md §4 Endpoint A/B/C。

import { fetchCompat } from '../fetchCompat';
import { logger } from '../logger';
import { FeedbackConfig, getFeedbackConfig } from './feedbackConfig';

const LOG_TAG = '[feedback:syncer]';

/** 失败重试退避序列（ms）。最后一次即 24h，之后停在该档不再递增。 */
const BACKOFF_SCHEDULE_MS = [
  5 * 60 * 1000, // 5 min
  15 * 60 * 1000, // 15 min
  60 * 60 * 1000, // 1 h
  4 * 60 * 60 * 1000, // 4 h
  24 * 60 * 60 * 1000, // 24 h
];

const INITIAL_BACKOFF_INDEX = 0;

/** 单次 HTTP 请求的超时（ms）。内网环境通常秒级往返，30s 给足余量。 */
const REQUEST_TIMEOUT_MS = 30_000;

/** 单轮 sync 拉取的本地会话数上限（避免启动时把 SQLite 锁住太久）。 */
const CONVERSATIONS_PER_TICK_LIMIT = 50;

/** 管理员新回复落库后的通知载荷。一次 tick 内同一会话只回调一次。 */
export interface ReplyNotification {
  conversationId: string;
  /** 会话标题，通知标题用。 */
  title: string;
  /** 本轮新写入的回复条数。 */
  count: number;
  /** 最后一条回复正文，通知正文用。 */
  lastBody: string;
}

export interface SyncerDeps {
  /** 本地 backend 基址，如 "http://127.0.0.1:8765"。 */
  getBackendUrl: () => string;
  /** 本地 backend 的 SAGE_LOCAL_AUTH_TOKEN。 */
  getAuthToken: () => string | undefined;
  /** 配置实例（可注入以便测试，默认用单例）。 */
  config?: FeedbackConfig;
  /** 注入的 setTimeout 包装（测试用，prod 用 node 原生）。 */
  scheduleTimeout?: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  /** 注入的 fetch（测试用，prod 用 fetchCompat）。 */
  fetchImpl?: typeof fetchCompat;
  /** 管理员回复写进本地库后回调；main 侧据此弹托盘/OS 通知。默认 no-op。 */
  onRepliesReceived?: (info: ReplyNotification) => void;
}

interface LocalConversationDto {
  id: string;
  title: string;
  status: 'open' | 'resolved' | 'closed';
  app_version: string;
  os_info: string;
  last_activity_at: number;
  created_at: number;
  updated_at: number;
}

interface LocalMessageDto {
  id: string;
  conversation_id: string;
  role: 'user' | 'admin';
  body: string;
  media_ids: string[];
  created_at: number;
  synced_at: number | null;
}

interface RemoteMessage {
  id: string;
  role: 'user' | 'admin';
  body: string;
  created_at: number;
}

export class FeedbackSyncer {
  private readonly deps: Required<Omit<SyncerDeps, 'config'>>;
  private readonly config: FeedbackConfig;
  private backoffIndex = INITIAL_BACKOFF_INDEX;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private inFlight = false;

  constructor(deps: SyncerDeps) {
    this.deps = {
      getBackendUrl: deps.getBackendUrl,
      getAuthToken: deps.getAuthToken,
      scheduleTimeout: deps.scheduleTimeout ?? ((fn, ms) => setTimeout(fn, ms)),
      fetchImpl: deps.fetchImpl ?? fetchCompat,
      onRepliesReceived: deps.onRepliesReceived ?? (() => {}),
    };
    this.config = deps.config ?? getFeedbackConfig();
  }

  /** 启动周期循环。配置缺失时仅 warn 一次，不抛错，等设置页填好后外部再调 start()。 */
  start(): void {
    if (this.running) return;
    this.running = true;
    if (!this.config.isConfigured()) {
      logger.info(`${LOG_TAG} not configured (managerUrl/sharedSecret empty); idle until set`);
      return;
    }
    this.scheduleTick(0); // 立即跑首轮
  }

  /** 停止周期循环（app quit / 用户关闭反馈时调用）。 */
  stop(): void {
    this.running = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /** 触发一次完整 sync（提交 + 拉取）。暴露给测试和"立即同步"按钮。 */
  async syncOnce(): Promise<{ submitted: number; received: number; errors: number }> {
    if (this.inFlight) {
      return { submitted: 0, received: 0, errors: 0 };
    }
    this.inFlight = true;
    try {
      return await this.runTick();
    } finally {
      this.inFlight = false;
    }
  }

  /** 当前退避档位（测试可观察）。 */
  getBackoffIndex(): number {
    return this.backoffIndex;
  }

  // ==================== Internals ====================

  private scheduleTick(delayMs: number): void {
    if (!this.running) return;
    this.timer = this.deps.scheduleTimeout(() => {
      this.timer = null;
      void this.tick();
    }, delayMs);
  }

  private async tick(): Promise<void> {
    if (!this.running) return;
    if (!this.config.isConfigured()) {
      // 配置被清空 → 停止循环，等设置页重新启用
      logger.info(`${LOG_TAG} config cleared mid-run; stopping loop`);
      this.running = false;
      return;
    }
    let ok = true;
    try {
      const stats = await this.runTick();
      ok = stats.errors === 0;
    } catch (err) {
      logger.warn(`${LOG_TAG} tick failed`, { err: String(err) });
      ok = false;
    }
    if (ok) this.backoffIndex = INITIAL_BACKOFF_INDEX; // 成功重置退避
    if (this.running) {
      // 按当前档位排下一轮，再升档：首次失败等 5min（而非直接跳到 15min）。
      this.scheduleTick(this.currentBackoffMs());
      if (!ok) this.bumpBackoff();
    }
  }

  private async runTick(): Promise<{ submitted: number; received: number; errors: number }> {
    const stats = { submitted: 0, received: 0, errors: 0 };

    const conversations = await this.localGet<LocalConversationDto[]>(
      `/api/v1/feedback/conversations?limit=${CONVERSATIONS_PER_TICK_LIMIT}`,
    );
    if (!conversations) {
      stats.errors += 1;
      return stats;
    }

    // 仅对 open 状态会话尝试提交 + 拉取回复
    for (const conv of conversations) {
      if (conv.status !== 'open') continue;

      const submitResult = await this.submitConversation(conv);
      if (submitResult < 0) {
        stats.errors += 1;
        continue; // 提交失败 → 不拉回复（远端可能还没收到新消息）
      }
      stats.submitted += submitResult;

      const received = await this.pollReplies(conv);
      if (received < 0) {
        stats.errors += 1;
      } else {
        stats.received += received;
      }
    }

    return stats;
  }

  /** 提交一个会话的 pending 消息到远端；返回提交条数；失败返回 -1。 */
  private async submitConversation(conv: LocalConversationDto): Promise<number> {
    const pending = await this.localGet<LocalMessageDto[]>(
      `/api/v1/feedback/conversations/${encodeURIComponent(conv.id)}/pending`,
    );
    if (!pending) return -1;
    if (pending.length === 0) return 0;

    for (const msg of pending) {
      const ok = await this.remotePost(
        `/api/v1/feedback/conversations/${encodeURIComponent(conv.id)}/messages`,
        {
          id: msg.id,
          role: msg.role,
          body: msg.body,
          media_ids: msg.media_ids,
          created_at: msg.created_at,
          // 会话元数据：转发脚本首次见到该会话时用它建工单；已存在时忽略。
          title: conv.title,
          app_version: conv.app_version,
          os_info: conv.os_info,
          conversation_created_at: conv.created_at,
        },
      );
      if (!ok) return -1;

      // 远端接收成功 → 标记本地已同步
      const markOk = await this.localPost(
        `/api/v1/feedback/messages/${encodeURIComponent(msg.id)}/synced`,
        {},
      );
      if (!markOk) {
        // 不太可能：本地 DB 写失败。记录并继续下一条，下次 tick 重试。
        logger.warn(`${LOG_TAG} mark_synced failed after remote accepted`, {
          messageId: msg.id,
        });
      }
    }
    return pending.length;
  }

  /** 从远端拉取管理员回复并写入本地；返回新写入条数；失败返回 -1。 */
  private async pollReplies(conv: LocalConversationDto): Promise<number> {
    const conversationId = conv.id;
    // 拿本地会话详情以计算"最新 admin 消息时间戳"作为 since 参数
    const detail = await this.localGet<{
      conversation: LocalConversationDto;
      messages: LocalMessageDto[];
    }>(`/api/v1/feedback/conversations/${encodeURIComponent(conversationId)}`);
    if (!detail) return -1;

    const adminMessages = detail.messages.filter((m) => m.role === 'admin');
    const since = adminMessages.length ? Math.max(...adminMessages.map((m) => m.created_at)) : 0;

    const remoteMessages = await this.remoteGet<RemoteMessage[]>(
      `/api/v1/feedback/conversations/${encodeURIComponent(conversationId)}/messages?since=${since}`,
    );
    if (!remoteMessages) return -1;

    const newReplies = remoteMessages.filter((m) => m.role === 'admin' && m.created_at > since);
    for (const reply of newReplies) {
      // 显式 id 写入本地 → FeedbackRepo.add_message 已做幂等去重
      const ok = await this.localPost(
        `/api/v1/feedback/conversations/${encodeURIComponent(conversationId)}/messages`,
        {
          id: reply.id,
          role: 'admin',
          body: reply.body,
          media_ids: [],
        },
      );
      if (!ok) {
        logger.warn(`${LOG_TAG} failed to persist admin reply locally`, {
          conversationId,
          messageId: reply.id,
        });
        return -1;
      }
    }
    if (newReplies.length > 0) {
      const last = newReplies[newReplies.length - 1];
      this.deps.onRepliesReceived({
        conversationId,
        title: conv.title,
        count: newReplies.length,
        lastBody: last.body,
      });
    }
    return newReplies.length;
  }

  private bumpBackoff(): void {
    if (this.backoffIndex < BACKOFF_SCHEDULE_MS.length - 1) {
      this.backoffIndex += 1;
    }
  }

  private currentBackoffMs(): number {
    return BACKOFF_SCHEDULE_MS[this.backoffIndex];
  }

  // ==================== HTTP helpers ====================

  private authHeaders(): Record<string, string> {
    const token = this.deps.getAuthToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  private remoteHeaders(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.config.getSharedSecret()}`,
      'X-Client-Id': this.config.getInstallationUuid(),
      'Content-Type': 'application/json',
    };
  }

  private remoteUrl(path: string): string {
    const base = this.config.getManagerUrl().replace(/\/+$/, '');
    return `${base}${path.startsWith('/') ? path : `/${path}`}`;
  }

  private localUrl(path: string): string {
    const base = this.deps.getBackendUrl().replace(/\/+$/, '');
    return `${base}${path.startsWith('/') ? path : `/${path}`}`;
  }

  private async localGet<T>(path: string): Promise<T | null> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await this.deps.fetchImpl(this.localUrl(path), {
        method: 'GET',
        headers: this.authHeaders(),
        signal: controller.signal as never,
      });
      if (!res.ok) {
        logger.warn(`${LOG_TAG} local GET failed`, { path, status: res.status });
        return null;
      }
      return (await res.json()) as T;
    } catch (err) {
      logger.warn(`${LOG_TAG} local GET error`, { path, err: String(err) });
      return null;
    } finally {
      clearTimeout(timeout);
    }
  }

  private async localPost(path: string, body: unknown): Promise<boolean> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await this.deps.fetchImpl(this.localUrl(path), {
        method: 'POST',
        headers: { ...this.authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal as never,
      });
      if (!res.ok) {
        logger.warn(`${LOG_TAG} local POST failed`, { path, status: res.status });
        return false;
      }
      return true;
    } catch (err) {
      logger.warn(`${LOG_TAG} local POST error`, { path, err: String(err) });
      return false;
    } finally {
      clearTimeout(timeout);
    }
  }

  private async remoteGet<T>(path: string): Promise<T | null> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await this.deps.fetchImpl(this.remoteUrl(path), {
        method: 'GET',
        headers: this.remoteHeaders(),
        signal: controller.signal as never,
      });
      if (res.status === 401) {
        logger.warn(`${LOG_TAG} remote GET 401 — shared secret mismatch`);
        return null;
      }
      if (!res.ok) {
        logger.warn(`${LOG_TAG} remote GET failed`, { path, status: res.status });
        return null;
      }
      return (await res.json()) as T;
    } catch (err) {
      logger.warn(`${LOG_TAG} remote GET error`, { path, err: String(err) });
      return null;
    } finally {
      clearTimeout(timeout);
    }
  }

  private async remotePost(path: string, body: unknown): Promise<boolean> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await this.deps.fetchImpl(this.remoteUrl(path), {
        method: 'POST',
        headers: this.remoteHeaders(),
        body: JSON.stringify(body),
        signal: controller.signal as never,
      });
      if (res.status === 401) {
        logger.warn(`${LOG_TAG} remote POST 401 — shared secret mismatch`);
        return false;
      }
      if (!res.ok) {
        logger.warn(`${LOG_TAG} remote POST failed`, { path, status: res.status });
        return false;
      }
      return true;
    } catch (err) {
      logger.warn(`${LOG_TAG} remote POST error`, { path, err: String(err) });
      return false;
    } finally {
      clearTimeout(timeout);
    }
  }
}

/** 全局单例（main.ts 初始化后供 commandRoutes 暴露 "立即同步" 触发器）。 */
let _global: FeedbackSyncer | null = null;

export function initGlobalFeedbackSyncer(deps: SyncerDeps): FeedbackSyncer {
  if (_global) return _global;
  _global = new FeedbackSyncer(deps);
  return _global;
}

export function getGlobalSyncer(): FeedbackSyncer | null {
  return _global;
}
