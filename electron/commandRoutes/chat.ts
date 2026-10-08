/**
 * Chat, agents, messages & attachment RAG IPC commands.
 */
import type { CommandRoute } from '../commands';

export const chatRoutes: Record<string, CommandRoute> = {
  // chat
  // I2: create + attach split — POST 立即返回 {streamId} 启动后台 LLM 调用,
  // GET attach 到同一 stream 拉取 NDJSON 事件。LLM 只跑一次。
  //
  // 注意：所有路径以 /api/v1 开头。backend/main.py:215 把 legacy_router 挂在
  // /api/v1 下 —— 去掉前缀会全部 404。commands.test.ts 有 guard 测试
  // 防止漏前缀。
  agent_chat_stream: { method: 'POST', path: () => '/api/v1/chat/stream' },
  list_agents: { method: 'GET', path: () => '/api/v1/agents' },
  get_agent: {
    method: 'GET',
    path: (a) => `/api/v1/agents/${encodeURIComponent(String(a.id))}`,
  },
  update_agent: {
    method: 'PATCH',
    path: (a) => `/api/v1/agents/${encodeURIComponent(String(a.id))}`,
    // 后端 update body 是 extra="forbid" — id 是路径参数，必须从 body 剥掉，
    // 否则 422（与 permissions_answer 剥 requestId 同理）。显式 body 后
    // invoke 仍会递归 camelToSnakeKeys（electron/invoke.ts L68-69），
    // update 内部 systemPrompt → system_prompt 自动转换。
    body: (a) => (a.update as Record<string, unknown>) ?? {},
  },
  toggle_agent: {
    method: 'PATCH',
    path: (a) => `/api/v1/agents/${encodeURIComponent(String(a.id))}/toggle`,
    body: (a) => ({ enabled: a.enabled }),
  },
  create_agent: { method: 'POST', path: () => '/api/v1/agents' },
  attach_chat_stream: {
    method: 'GET',
    path: (a) => `/api/v1/chat/stream/${encodeURIComponent(String(a.streamId))}`,
  },
  interrupt_agent: { method: 'POST', path: () => '/api/v1/interrupt' },
  // RT5 (round7): 单 agent steering —— 运行中注入用户补充消息（body 经
  // relay camelToSnakeKeys 转成 { stream_id, content }）。
  chat_steer: { method: 'POST', path: () => '/api/v1/chat/steer' },

  // R25-D4: 查询会话活跃 chat 流（renderer 重载后 reattach）。null = 无活跃流。
  chat_stream_active: {
    method: 'GET',
    path: (a) => `/api/v1/chat/stream/active?session_id=${encodeURIComponent(String(a.sessionId))}`,
  },
  // F12 (对标增强第五轮批次 B): 跨会话消息全文搜索（侧栏搜索框数据源）
  search_messages: {
    method: 'GET',
    path: (a) => {
      const q = encodeURIComponent(String(a.query));
      const limit = typeof a.limit === 'number' ? a.limit : 20;
      const sessionId =
        a.sessionId != null ? `&session_id=${encodeURIComponent(String(a.sessionId))}` : '';
      return `/api/v1/search/messages?q=${q}&limit=${limit}${sessionId}`;
    },
  },

  // messages
  get_messages: {
    method: 'GET',
    path: (a) => {
      const id = encodeURIComponent(String(a.sessionId));
      const limit = (a?.limit as number) ?? 100;
      const offset = (a?.offset as number) ?? 0;
      return `/api/v1/sessions/${id}/messages?limit=${limit}&offset=${offset}`;
    },
  },
  delete_message: {
    method: 'POST',
    path: (a) => `/api/v1/messages/${encodeURIComponent(String(a.id))}/delete`,
  },

  // r59: 附件向量索引三端点透传（backend/api/chat_attachment_routes.py r58）。
  // embed 配置 / query_vector 由调用方构造，body 原样透传（键已 snake）。
  attachment_rag_index: {
    method: 'POST',
    path: (a) => `/api/v1/chat/attachments/${encodeURIComponent(String(a.mediaId))}/index`,
    body: (a) => {
      const body: Record<string, unknown> = { embed: a.embed };
      if (a.target_chunk_size !== undefined) body.target_chunk_size = a.target_chunk_size;
      return body;
    },
  },
  attachment_rag_search: {
    method: 'POST',
    path: () => '/api/v1/chat/attachments/search',
    rawBody: true,
  },
  attachment_rag_delete_index: {
    method: 'DELETE',
    path: (a) => `/api/v1/chat/attachments/${encodeURIComponent(String(a.mediaId))}/index`,
  },
};
