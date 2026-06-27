/**
 * IPC command → backend HTTP route mapping for Electron main process.
 *
 * Pure module (no electron imports) so it can be unit-tested with vitest
 * without spinning up the Electron runtime.
 */
export interface CommandRoute {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: (args: Record<string, unknown>) => string;
  isSse?: boolean;
}

export const COMMAND_ROUTES: Record<string, CommandRoute> = {
  // chat
  // I2: create + attach split — POST 立即返回 {streamId} 启动后台 LLM 调用,
  // GET attach 到同一 stream 拉取 NDJSON 事件。LLM 只跑一次。
  //
  // 注意：所有路径以 /api/v1 开头。backend/main.py:215 把 legacy_router 挂在
  // /api/v1 下 —— 去掉前缀会全部 404。commands.test.ts 有 guard 测试
  // 防止漏前缀。
  agent_chat_stream: { method: 'POST', path: () => '/api/v1/chat/stream' },
  attach_chat_stream: {
    method: 'GET',
    path: (a) => `/api/v1/chat/stream/${encodeURIComponent(String(a.streamId))}`,
  },
  interrupt_agent: { method: 'POST', path: () => '/api/v1/interrupt' },

  // sessions
  list_sessions: {
    method: 'GET',
    path: (a) => {
      const limit = (a?.limit as number) ?? 100;
      const offset = (a?.offset as number) ?? 0;
      return `/api/v1/sessions?limit=${limit}&offset=${offset}`;
    },
  },
  create_session: { method: 'POST', path: () => '/api/v1/sessions' },
  get_session: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.id))}`,
  },
  delete_session: {
    method: 'DELETE',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.id))}`,
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

  // memory
  get_memories: {
    method: 'GET',
    path: (a) => {
      const page = (a?.page as number) ?? 1;
      const pageSize = (a?.pageSize as number) ?? 20;
      const memoryType = a?.memoryType as string | null;
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (memoryType) params.set('type', memoryType);
      return `/api/v1/memory/list?${params.toString()}`;
    },
  },
  delete_memory: { method: 'POST', path: () => '/api/v1/memory/delete' },

  // evolution
  trigger_evolution: { method: 'POST', path: () => '/api/v1/evolution/trigger' },

  // settings & preferences
  get_settings: { method: 'GET', path: () => '/api/v1/settings' },
  set_settings: { method: 'PUT', path: () => '/api/v1/settings' },
  get_preference: {
    method: 'GET',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },
  set_preference: {
    method: 'PUT',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },

  // scheduled tasks (Phase 8)
  scheduled_list_tasks: {
    method: 'GET',
    path: () => '/api/v1/scheduled/tasks',
  },
  scheduled_create_task: {
    method: 'POST',
    path: () => '/api/v1/scheduled/tasks',
  },
  scheduled_update_task: {
    method: 'PATCH',
    path: (a) => `/api/v1/scheduled/tasks/${encodeURIComponent(String(a.id))}`,
  },
  scheduled_delete_task: {
    method: 'DELETE',
    path: (a) => `/api/v1/scheduled/tasks/${encodeURIComponent(String(a.id))}`,
  },
  scheduled_run_task: {
    method: 'POST',
    path: (a) => `/api/v1/scheduled/tasks/${encodeURIComponent(String(a.id))}/run`,
  },

  // custom CSS theme storage (themeCssClient)
  // Backend theme_router 挂在 /api/theme（不是 /api/v1）
  theme_list: { method: 'GET', path: () => '/api/theme/list' },
  theme_save: { method: 'POST', path: () => '/api/theme/save' },
  theme_get: {
    method: 'GET',
    path: (a) => `/api/theme/get/${encodeURIComponent(String(a.id))}`,
  },
  theme_delete: { method: 'POST', path: () => '/api/theme/delete' },

  // orchestration (Phase 4: multi-agent coordination)
  orchestration_list_lanes: {
    method: 'GET',
    path: (a) => {
      const params = (a?.params as Record<string, unknown>) ?? {};
      const search = new URLSearchParams();
      if (params.status) search.set('status', String(params.status));
      if (params.team_id) search.set('team_id', String(params.team_id));
      if (params.limit) search.set('limit', String(params.limit));
      const qs = search.toString();
      return `/api/v1/orchestration/lanes${qs ? `?${qs}` : ''}`;
    },
  },
  orchestration_get_lane: {
    method: 'GET',
    path: (a) => `/api/v1/orchestration/lanes/${encodeURIComponent(String(a.lane_id))}`,
  },
  orchestration_list_lane_events: {
    method: 'GET',
    path: (a) => `/api/v1/orchestration/lanes/${encodeURIComponent(String(a.lane_id))}/events`,
  },
  orchestration_cancel_lane: {
    method: 'POST',
    path: (a) => `/api/v1/orchestration/lanes/${encodeURIComponent(String(a.lane_id))}/cancel`,
  },
};

export class UnknownIpcCommandError extends Error {
  constructor(cmd: string) {
    super(
      `Unknown IPC command: ${cmd}. ` +
        `See electron/commands.ts COMMAND_ROUTES for the supported set.`,
    );
    this.name = 'UnknownIpcCommandError';
  }
}
