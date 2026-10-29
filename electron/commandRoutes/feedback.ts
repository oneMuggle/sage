// electron/commandRoutes/feedback.ts
//
// 用户反馈系统的 backend HTTP 路由映射。Renderer 通过 src/shared/api/feedbackApi.ts
// 调用这些 IPC 命令，invoke.ts 把 camelCase 翻译成 snake_case 后发到 backend。
//
// 配置类命令（managerUrl / sharedSecret）不走 backend，直接在 main.ts 注册 IPC handler
// （因为 sharedSecret 需要 Electron safeStorage 加密，存在 electron-store JSON 中）。
//
// 设计见 docs/plans/2026-10-29_direct-feedback-channel.md §4。

import type { CommandRoute } from '../commands';

export const feedbackRoutes: Record<string, CommandRoute> = {
  // 会话列表（默认按 last_activity_at DESC 排序，limit=50）
  feedback_conversations: {
    method: 'GET',
    path: (a) => {
      const limit = a.limit ?? 50;
      return `/api/v1/feedback/conversations?limit=${encodeURIComponent(String(limit))}`;
    },
  },

  // 会话详情（含 messages 数组）
  feedback_conversation_get: {
    method: 'GET',
    path: (a) => `/api/v1/feedback/conversations/${encodeURIComponent(String(a.id))}`,
  },

  // 创建会话（首条消息随 body 一起发；backend 内部 add_message + touch_conversation）
  feedback_conversation_create: {
    method: 'POST',
    path: () => '/api/v1/feedback/conversations',
    body: (a) => {
      const body: Record<string, unknown> = {
        title: a.title,
        body: a.body,
      };
      if (a.id !== undefined) body.id = a.id; // 幂等创建（syncer 用）
      if (a.media_ids !== undefined) body.media_ids = a.media_ids;
      return body;
    },
  },

  // 追加消息（user 补充 / admin 回复）
  feedback_message_append: {
    method: 'POST',
    path: (a) =>
      `/api/v1/feedback/conversations/${encodeURIComponent(String(a.conversationId ?? a.id))}/messages`,
    body: (a) => {
      const body: Record<string, unknown> = {
        role: a.role ?? 'user',
        body: a.body,
      };
      if (a.id !== undefined) body.id = a.id; // 显式 id → add_message 幂等去重
      if (a.media_ids !== undefined) body.media_ids = a.media_ids;
      return body;
    },
  },

  // 状态更新（open / resolved / closed）
  feedback_conversation_status_update: {
    method: 'PATCH',
    path: (a) =>
      `/api/v1/feedback/conversations/${encodeURIComponent(String(a.id))}/status`,
    body: (a) => ({ status: a.status }),
  },

  // 日志尾部（诊断信息，附在反馈里方便管理员看）
  feedback_log_tail: {
    method: 'GET',
    path: (a) => {
      const maxLines = a.maxLines ?? 200;
      return `/api/v1/feedback/log-tail?max_lines=${encodeURIComponent(String(maxLines))}`;
    },
  },
};
