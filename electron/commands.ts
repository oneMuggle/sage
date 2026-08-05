/**
 * IPC command → backend HTTP route mapping for Electron main process.
 *
 * Pure module (no electron imports) so it can be unit-tested with vitest
 * without spinning up the Electron runtime.
 */
export interface CommandRoute {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: (args: Record<string, unknown>) => string;
  body?: (args: Record<string, unknown>) => Record<string, unknown>;
  isSse?: boolean;
  /**
   * Skip the camelCase→snake_case body translation. For payloads whose
   * keys are user-defined data rather than JS identifiers — e.g. MCP
   * server `env` maps, where `PATH` would be mangled into `_p_a_t_h`.
   * Callers must send snake_case top-level keys themselves.
   */
  rawBody?: boolean;
}

const DEFAULT_WORKSPACE_SEARCH_LIMIT = 20;
const MIN_WORKSPACE_SEARCH_LIMIT = 1;
const MAX_WORKSPACE_SEARCH_LIMIT = 50;

function normalizeWorkspaceSearchLimit(value: unknown): number {
  const limit =
    typeof value === 'number' && Number.isFinite(value)
      ? Math.trunc(value)
      : DEFAULT_WORKSPACE_SEARCH_LIMIT;
  return Math.min(MAX_WORKSPACE_SEARCH_LIMIT, Math.max(MIN_WORKSPACE_SEARCH_LIMIT, limit));
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

  // session workspace binding
  workspace_bind: {
    method: 'PUT',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace`,
    body: (a) => ({ workspacePath: a.workspacePath }),
  },
  workspace_get: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace`,
  },
  workspace_revoke: {
    method: 'DELETE',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace`,
  },
  workspace_search_files: {
    method: 'GET',
    path: (a) => {
      const sessionId = encodeURIComponent(String(a.sessionId));
      const query = encodeURIComponent(String(a.query));
      const limit = normalizeWorkspaceSearchLimit(a.limit);
      return `/api/v1/sessions/${sessionId}/workspace/files?q=${query}&limit=${limit}`;
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

  // Gap D — memory CRUD + preferences + traceability IPC wiring (T1).
  // 6 of the 9 endpoints already exist on the backend; the 3 with
  // path placeholders (find_by_turn, get_summary) and the /profile endpoint
  // are added in later tasks — calling them now returns 404, which is
  // expected for T1 (renderer callers added in T2/T5/T6).
  // Paths with {turn_id}/{session_id} are template strings — invoke.ts
  // substitutes them from args via extractPathParams(). Routes with
  // query-string args (memory_search, memory_list) build the URL via
  // path: (a) => … matching the existing get_memories convention.
  memory_search: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      if (a?.query !== undefined && a.query !== null) {
        params.set('query', String(a.query));
      }
      const limit = (a?.limit as number) ?? 20;
      params.set('limit', String(limit));
      if (a?.type) params.set('type', String(a.type));
      const qs = params.toString();
      return `/api/v1/memory/search${qs ? `?${qs}` : ''}`;
    },
  },
  memory_save: { method: 'POST', path: () => '/api/v1/memory/save' },
  memory_list: {
    method: 'GET',
    path: (a) => {
      const page = (a?.page as number) ?? 1;
      const pageSize = (a?.page_size as number) ?? 20;
      const memoryType = a?.type as string | null;
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (memoryType) params.set('type', memoryType);
      return `/api/v1/memory/list?${params.toString()}`;
    },
  },
  memory_delete: { method: 'POST', path: () => '/api/v1/memory/delete' },
  memory_get_auto: { method: 'GET', path: () => '/api/v1/preferences/auto_memory' },
  memory_set_auto: { method: 'PUT', path: () => '/api/v1/preferences/auto_memory' },
  memory_get_retrieval: {
    method: 'GET',
    path: () => '/api/v1/preferences/memory_retrieval',
  },
  memory_set_retrieval: {
    method: 'PUT',
    path: () => '/api/v1/preferences/memory_retrieval',
  },
  memory_find_by_turn: {
    method: 'GET',
    path: () => '/api/v1/memory/by-turn/{turn_id}',
  },
  memory_get_profile: { method: 'GET', path: () => '/api/v1/memory/profile' },
  memory_get_summary: {
    method: 'GET',
    path: () => '/api/v1/memory/summary/{session_id}',
  },

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
  // Backend theme_router 挂在 /api/v1/theme (与其他 IPC 路由一致)
  theme_list: { method: 'GET', path: () => '/api/v1/theme/list' },
  theme_save: { method: 'POST', path: () => '/api/v1/theme/save' },
  theme_get: {
    method: 'GET',
    path: (a) => `/api/v1/theme/get/${encodeURIComponent(String(a.id))}`,
  },
  theme_delete: { method: 'POST', path: () => '/api/v1/theme/delete' },

  // skills (PR-7)
  // src/pages/Skills.tsx calls skillsApi.list() / .toggle() / .execute()
  // which route through these IPC names. Backend exposes matching endpoints
  // at backend/api/legacy_routes.py:487-559. Without these entries the
  // /skills page throws UnknownIpcCommandError.
  list_skills: { method: 'GET', path: () => '/api/v1/skills' },
  toggle_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/toggle`,
  },
  execute_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/execute`,
  },
  delete_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/delete`,
  },

  // Path B: list user-invocable SKILL.md slash command names.
  // Returns {commands: ["/name1", "/name2", ...]} for skills with
  // user_invocable: true. Used by ChatInput to merge into the slash menu.
  list_slash_commands: { method: 'GET', path: () => '/api/v1/skills/commands' },

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

  // Office document features (Phase 1.3, plan §4.1.3 step 14).
  // 5 routes for Phase 1.2 backend (3 read + list + delete).
  // Generate endpoints (ppt_generate, word_generate, excel_generate)
  // deferred to Phase 1.4 follow-up PR.
  office_ppt_read: { method: 'POST', path: () => '/api/v1/office/ppt/read' },
  office_word_read: { method: 'POST', path: () => '/api/v1/office/word/read' },
  office_excel_read: { method: 'POST', path: () => '/api/v1/office/excel/read' },
  office_list_documents: {
    method: 'GET',
    path: (a) =>
      `/api/v1/office/documents?workspace_path=${encodeURIComponent(String(a.workspacePath))}`,
  },
  office_delete_document: {
    method: 'DELETE',
    path: (a) => `/api/v1/office/documents/${encodeURIComponent(String(a.docId))}`,
  },
  // Phase 1.4 (2026-07-16): Office generate endpoints (plan §4.1.4 step 19).
  office_ppt_generate: { method: 'POST', path: () => '/api/v1/office/ppt/generate' },
  office_word_generate: { method: 'POST', path: () => '/api/v1/office/word/generate' },
  office_excel_generate: { method: 'POST', path: () => '/api/v1/office/excel/generate' },

  // M3: MCP multi-server management (backend/api/mcp_routes.py).
  // mcp_server_add: args are the full server config, forwarded as body.
  // mcp_server_update: name goes in the path; body carries only the
  // merge-patch fields (enabled / timeout_seconds) — extra=forbid on the
  // backend model means name must NOT leak into the body.
  mcp_status: { method: 'GET', path: () => '/api/v1/mcp/status' },
  mcp_servers: { method: 'GET', path: () => '/api/v1/mcp/servers' },
  // rawBody: env keys are user-defined (API_TOKEN, PATH, …) and must not
  // pass through camelToSnakeKeys; mcpClient sends snake_case keys.
  mcp_server_add: { method: 'POST', path: () => '/api/v1/mcp/servers', rawBody: true },
  mcp_server_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/mcp/servers/${encodeURIComponent(String(a.name))}`,
    body: (a) => {
      const body: Record<string, unknown> = {};
      if (a.enabled !== undefined) body.enabled = a.enabled;
      if (a.timeout_seconds !== undefined) body.timeout_seconds = a.timeout_seconds;
      return body;
    },
  },
  mcp_server_delete: {
    method: 'DELETE',
    path: (a) => `/api/v1/mcp/servers/${encodeURIComponent(String(a.name))}`,
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

/**
 * Module-level Map: streamId → AbortController.
 *
 * Tracks in-flight streaming IPC commands (e.g. `wiki_chat_stream`) so the
 * renderer can abort the backend HTTP request via `sage:unlisten` when it
 * unsubscribes. The controller is created when the stream starts and
 * removed in the `finally` block of the relay loop on normal completion,
 * error, or abort. Read by main.ts on `sage:unlisten`.
 */
export const streamControllers = new Map<string, AbortController>();
