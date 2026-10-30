// electron/feedback/feedbackIpc.ts
//
// 用户反馈系统的 main 侧 IPC —— 配置读写 + 手动同步 + 附件上传。
//
// 数据类命令（会话/消息 CRUD）走 electron/commandRoutes/feedback.ts（backend HTTP 映射）；
// 这里只处理必须留在 main 进程的操作：
//   - sharedSecret 需要 Electron safeStorage 加密，不能落到 backend SQLite
//   - 附件上传是 raw binary，CommandRoute 只支持 JSON body
//   - 手动触发 syncer 属于 main 进程内部行为
//
// 设计见 docs/technical/109-feedback-relay-deployment.md §11.2。

import { fetchCompat } from '../fetchCompat';
import { logger } from '../logger';
import { FeedbackConfig } from './feedbackConfig';
import { FeedbackSyncer } from './feedbackSyncer';

const LOG_TAG = '[feedback:ipc]';

export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

export interface FeedbackIpcDeps {
  /** 本地 backend 基址。 */
  getBackendUrl: () => string;
  /** 本地 backend 的 SAGE_LOCAL_AUTH_TOKEN。 */
  getAuthToken: () => string | undefined;
  /** 配置实例（主进程单例）。 */
  config: FeedbackConfig;
  /** 手动同步入口；未初始化（未配置 / 应用未就绪）时返回 null。 */
  getSyncer: () => FeedbackSyncer | null;
  /** 配置变更后重启 syncer，让新配置立即生效。 */
  restartSyncer: () => void;
}

export interface FeedbackConfigView {
  managerUrl: string;
  hasSecret: boolean;
  installationUuid: string;
  configured: boolean;
  /** 新建反馈会话时自动附带最近日志（用户可关）。 */
  includeDiagnostics: boolean;
}

export interface FeedbackSyncStats {
  submitted: number;
  received: number;
  errors: number;
}

export interface FeedbackAttachmentView {
  id: string;
  conversation_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

interface AttachmentUploadPayload {
  conversationId: string;
  filename: string;
  mimeType: string;
  /** base64 编码的原始字节（IPC 传二进制不安全）。 */
  dataBase64: string;
}

function configView(config: FeedbackConfig): FeedbackConfigView {
  return {
    managerUrl: config.getManagerUrl(),
    hasSecret: Boolean(config.getSharedSecret()),
    installationUuid: config.getInstallationUuid(),
    configured: config.isConfigured(),
    includeDiagnostics: config.getIncludeDiagnostics(),
  };
}

export function registerFeedbackIpc(register: RegisterIpcHandler, deps: FeedbackIpcDeps): void {
  register('feedback:config:get', () => configView(deps.config));

  register('feedback:config:set', (...args: unknown[]) => {
    const payload = (args[0] ?? {}) as {
      managerUrl?: string;
      sharedSecret?: string;
      includeDiagnostics?: boolean;
    };

    // 只有连接参数变化才需要重启 syncer；诊断开关只影响 renderer 组装消息
    let connectionChanged = false;
    if (typeof payload.managerUrl === 'string') {
      deps.config.setManagerUrl(payload.managerUrl);
      connectionChanged = true;
    }
    // sharedSecret 传 undefined 表示"不改动"；传空串表示"清空"
    if (typeof payload.sharedSecret === 'string') {
      deps.config.setSharedSecret(payload.sharedSecret);
      connectionChanged = true;
    }
    if (typeof payload.includeDiagnostics === 'boolean') {
      deps.config.setIncludeDiagnostics(payload.includeDiagnostics);
    }

    if (connectionChanged) {
      deps.restartSyncer();
    }
    logger.info(`${LOG_TAG} config updated`, {
      managerUrl: deps.config.getManagerUrl(),
      hasSecret: Boolean(deps.config.getSharedSecret()),
      includeDiagnostics: deps.config.getIncludeDiagnostics(),
    });
    return { ok: true, ...configView(deps.config) };
  });

  register('feedback:sync-now', async () => {
    const syncer = deps.getSyncer();
    if (!syncer) {
      return { submitted: 0, received: 0, errors: 0 } satisfies FeedbackSyncStats;
    }
    return (await syncer.syncOnce()) satisfies FeedbackSyncStats;
  });

  register('feedback:attachment:upload', async (...args: unknown[]) => {
    const payload = args[0] as AttachmentUploadPayload;
    if (!payload?.conversationId || !payload?.dataBase64) {
      throw new Error('附件上传参数不完整');
    }

    const bytes = Buffer.from(payload.dataBase64, 'base64');
    if (bytes.length === 0) {
      throw new Error('附件内容为空');
    }

    const base = deps.getBackendUrl().replace(/\/+$/, '');
    const url = `${base}/api/v1/feedback/conversations/${encodeURIComponent(
      payload.conversationId,
    )}/attachments`;

    const token = deps.getAuthToken();
    const res = await fetchCompat(url, {
      method: 'POST',
      headers: {
        'Content-Type': payload.mimeType || 'image/png',
        'X-Filename': payload.filename || 'screenshot.png',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: bytes,
    });

    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`附件上传失败 (HTTP ${res.status}): ${detail.slice(0, 200)}`);
    }

    return (await res.json()) as FeedbackAttachmentView;
  });
}
