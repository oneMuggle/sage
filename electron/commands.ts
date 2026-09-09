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
  // orchestration run control
  orchestration_get_run_snapshot: {
    method: 'GET',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/snapshot`,
  },

  // Phase 3: parent agent steering — POST /orch/runs/{run_id}/tasks/{task_id}/steer
  // Appends a context message (constraint/clarification/additional_context/...)
  // that the executor drains at the next boundary. Returns 409 task_state_changed
  // on CAS revision mismatch.
  orchestration_steer_task: {
    method: 'POST',
    path: (a) =>
      `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/tasks/${encodeURIComponent(String(a.task_id ?? a.taskId))}/steer`,
  },

  // Phase 3: run cancellation control — POST /orch/runs/{run_id}/cancel
  // Broadcasts run.cancel_requested; executor-driven abort belongs to Phase 4.
  orchestration_cancel_run_control: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/cancel`,
  },

  // live-events P1: subagent approval mode — POST /orch/runs/{run_id}/approval-mode
  // body {mode: 'ask' | 'auto'}; 404 when the run is not active in-process.
  orchestration_set_approval_mode: {
    method: 'POST',
    path: (a) =>
      `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/approval-mode`,
    body: (a) => ({ mode: a.mode }),
  },

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
  // M4: session engineering — 上下文压缩 + 会话分叉
  session_compact: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/compact`,
  },
  session_fork: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/fork`,
    // 后端 ForkSessionRequest 用 snake_case 字段；省略的参数不下发。
    // beforeMessage (U5'): 开区间截断——复制 atMessageId 之前的消息。
    body: (a) => {
      const body: Record<string, unknown> = {};
      if (a.atMessageId != null) body.at_message_id = a.atMessageId;
      if (a.title != null) body.title = a.title;
      if (a.beforeMessage != null) body.before_message = a.beforeMessage;
      return body;
    },
  },
  // U18: HTML 会话导出 — 后端返回 JSON 信封 {html, filename}，渲染进程
  // 用 Blob 触发下载。body 只下发 theme：ExportSessionRequest extra=forbid，
  // 若走默认 camelToSnake 会把 sessionId 带进 body 触发 422。
  export_session_html: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/export`,
    body: (a) => ({ theme: a.theme ?? 'auto' }),
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

  // U1 变更面板 (对标增强第二轮): 会话工作区 git 变更清单 + 按文件 diff,均只读
  workspace_get_changes: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/changes`,
  },
  workspace_get_changes_diff: {
    method: 'GET',
    path: (a) => {
      const sessionId = encodeURIComponent(String(a.sessionId));
      const path = encodeURIComponent(String(a.path ?? ''));
      const staged = a.staged ? 'true' : 'false';
      return `/api/v1/sessions/${sessionId}/workspace/changes/diff?path=${path}&staged=${staged}`;
    },
  },
  // U19 变更面板可操作化 (对标增强第四轮批次 B): 逐文件/逐 hunk 撤销
  workspace_revert_changes: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/changes/revert`,
    body: (a) => ({ paths: a.paths, delete_untracked: a.deleteUntracked === true }),
  },
  workspace_revert_change_hunks: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/changes/revert-hunks`,
    body: (a) => ({ path: a.path, hunk_indices: a.hunkIndices }),
  },
  // U2' 检查点面板 (对标增强第五轮批次 A): 快照列表 / 手动快照 / 覆盖恢复。
  // restore 语义"只覆盖不删除"由前端 confirm 文案明示;POST body 必须
  // 剥掉路径参数 (后端 extra="forbid",与 workspace_revert_changes 同理)。
  workspace_list_checkpoints: {
    method: 'GET',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/checkpoints`,
  },
  workspace_create_checkpoint: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/checkpoints`,
    body: () => ({}),
  },
  workspace_restore_checkpoint: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/checkpoints/restore`,
    body: (a) => ({ checkpoint_id: a.checkpointId }),
  },

  // U8 (批次 B): 会话级模型覆盖 (G5 收尾,只改模型不改端点)
  session_get_model: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/model`,
  },
  session_set_model: {
    method: 'PUT',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/model`,
    body: (a) => ({ model: a.model }),
  },
  // U4' (对标增强第五轮批次 A): 会话重命名——后端 PATCH 路由早已存在
  // (SessionUpdate extra="forbid"),只透传 title;置顶仍由既有单独语义覆盖。
  session_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}`,
    body: (a) => ({ title: a.title }),
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
      const offset = a?.offset as number | null;
      const sessionId = a?.sessionId as string | null;
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (memoryType) params.set('type', memoryType);
      // 批次三 step 6 (spec §4.3 line 150):
      // 前端 memoryApi.getMemories() 增加 offset / sessionId 透传,
      // 否则后端 4-way /memory/list 收不到 session 隔离和 offset cursor。
      if (offset !== null && offset !== undefined) {
        params.set('offset', String(offset));
      }
      if (sessionId) {
        params.set('session_id', sessionId);
      }
      return `/api/v1/memory/list?${params.toString()}`;
    },
  },
  // 批次三 step 6 (spec §4.3 line 150):
  // 新增 GET /memory/summaries 端点 — 之前前端 memoryApi.getSessionSummaries()
  // 调用 invoke('get_session_summaries', ...) 找不到映射,直接 404。
  // sessionId 必填(spec step 5 严令禁止"全部 session"视图)。
  get_session_summaries: {
    method: 'GET',
    path: (a) => {
      const sessionId = a?.sessionId as string | null | undefined;
      const page = (a?.page as number) ?? 1;
      const pageSize = (a?.pageSize as number) ?? 20;
      const sid = sessionId ? String(sessionId) : '';
      const params = new URLSearchParams({
        session_id: sid,
        page: String(page),
        page_size: String(pageSize),
      });
      return `/api/v1/memory/summaries?${params.toString()}`;
    },
  },
  delete_memory: { method: 'POST', path: () => '/api/v1/memory/delete' },
  // PR-C §5.4: front-end memoryApi.ts 调用 invoke('search_memory'|'save_memory'),
  // 但 commands.ts 没映射 → 前端 404。后端端点已存在 (legacy_routes.py:2479, :2490)。
  search_memory: {
    method: 'POST',
    path: () => '/api/v1/memory/search',
    // Body 字段: query (required), memory_type?, limit? — 缺省 limit=20
    body: (a) => ({
      query: a.query,
      memory_type: a.memoryType,
      limit: (a.limit as number) ?? 20,
    }),
  },
  save_memory: {
    method: 'POST',
    path: () => '/api/v1/memory/save',
    // Body 字段: content (required), memory_type?, importance?, tags?
    body: (a) => ({
      content: a.content,
      memory_type: a.memoryType,
      importance: a.importance,
      tags: a.tags,
    }),
  },

  // settings & preferences
  get_settings: { method: 'GET', path: () => '/api/v1/settings' },
  get_evolution_logs: {
    method: 'GET',
    path: (a) => {
      const limit = a.limit ?? 50;
      const offset = a.offset ?? 0;
      return `/api/v1/evolution/logs?limit=${limit}&offset=${offset}`;
    },
  },
  set_settings: { method: 'PUT', path: () => '/api/v1/settings' },
  get_preference: {
    method: 'GET',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },
  set_preference: {
    method: 'PUT',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },

  // M1 tool security hardening: 工具审批 gate（backend/api/permission_routes.py）。
  // permission_request 流事件到达后,渲染进程弹出 ApprovalDialog;用户点
  // 批准/拒绝 → permissions_answer 应答。pending 端点用于断线重连后补拉。
  permissions_pending: { method: 'GET', path: () => '/api/v1/permissions/pending' },
  permissions_answer: {
    method: 'POST',
    path: (a) => `/api/v1/permissions/${encodeURIComponent(String(a.requestId))}/answer`,
    // 后端 ApprovalAnswerBody 是 extra="forbid" — body 里只允许
    // approved/remember;requestId 是路径参数,必须从 body 剥掉,否则 422。
    // (与 workspace_bind 剥 sessionId 同理)
    body: (a) => ({ approved: a.approved, remember: a.remember }),
  },

  // M2 part B: AskUserQuestion 提问 gate（backend/api/question_routes.py）。
  // ask_user_question 流事件到达后,渲染进程弹出 QuestionDialog;用户选择/
  // 填写 → questions_answer 应答。pending 端点用于断线重连后补拉。
  questions_pending: { method: 'GET', path: () => '/api/v1/questions/pending' },
  questions_answer: {
    method: 'POST',
    path: (a) => `/api/v1/questions/${encodeURIComponent(String(a.requestId))}/answer`,
    // 后端 QuestionAnswerBody 是 extra="forbid" — body 里只允许
    // answers/custom;requestId 是路径参数,必须从 body 剥掉,否则 422。
    // (与 permissions_answer 剥 requestId 同理)
    body: (a) => ({
      answers: Array.isArray(a.answers) ? a.answers : [],
      custom: a.custom ?? null,
    }),
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
  archive_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/archive`,
  },

  // Path B: list user-invocable SKILL.md slash command names.
  // Returns {commands: ["/name1", "/name2", ...]} for skills with
  // user_invocable: true. Used by ChatInput to merge into the slash menu.
  list_slash_commands: { method: 'GET', path: () => '/api/v1/skills/commands' },

  // Background Review: skill drafts approval queue (Task 11)
  // src/pages/Skills.tsx "Pending Drafts" tab calls skillDraftsApi.list/approve/reject
  // which route through these IPC names. Backend endpoints at
  // backend/api/legacy_routes.py:1949-1995.
  list_skill_drafts: {
    method: 'GET',
    path: (a) => {
      const status = a?.status ? `?status=${encodeURIComponent(String(a.status))}` : '';
      return `/api/v1/skill-drafts${status}`;
    },
  },
  approve_skill_draft: {
    method: 'POST',
    path: (a) => `/api/v1/skill-drafts/${encodeURIComponent(String(a.draft_id))}/approve`,
  },
  reject_skill_draft: {
    method: 'POST',
    path: (a) => `/api/v1/skill-drafts/${encodeURIComponent(String(a.draft_id))}/reject`,
  },

  // Background Review: explicit learn trigger (Task 12)
  // src/pages/Chat.tsx onLearn callback invokes learnApi.trigger(sessionId)
  // which routes through this IPC name. Backend endpoint at
  // backend/api/legacy_routes.py:1910 (POST /learn).
  trigger_learn: {
    method: 'POST',
    path: () => '/api/v1/learn',
  },

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
  // M5: planner-driven lane creation. Body {goal, agent?} — args are
  // auto camelToSnake'd by invokeBackend (both keys stay single-segment).
  orchestration_create_lane: {
    method: 'POST',
    path: () => '/api/v1/orchestration/lanes',
  },
  // P2-5: LaneBoard 快照（freshness_summary + view 投影协商）。
  // GET /api/v1/orchestration/board?view=ops_full|ui_minimal
  orchestration_board: {
    method: 'GET',
    path: (a) => {
      const view = a?.view ? `?view=${encodeURIComponent(String(a.view))}` : '';
      return `/api/v1/orchestration/board${view}`;
    },
  },

  // Wave 2 P1-4 (2026-08-14): run 生命周期 —— plan 更新 / run 取消,
  // 对应 backend/api/orch_routes.py 的 /api/v1/orch/runs 端点。
  // Wave 4 (2026-09-06): 历史编排记录功能移除 —— 删除 list_runs / get_run / resume_run。
  orchestration_cancel_run: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/cancel`,
  },
  // B3 (2026-09-09): 单任务跳过 —— POST /orch/runs/{run_id}/tasks/{task_id}/cancel。
  // queued 任务 acquire 后短路 / running 任务软中断，不影响其余子任务。
  orchestration_cancel_run_task: {
    method: 'POST',
    path: (a) =>
      `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/tasks/${encodeURIComponent(String(a.task_id))}/cancel`,
  },
  orchestration_update_plan: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/plan`,
    body: (a) => ({ plan: a.plan }),
  },
  // Fix #3 (2026-09-06): 用户确认编排计划 → 唤醒 producer 开始执行。
  orchestration_confirm_run: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/confirm`,
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
  // M6 生态扩展: 用量/成本面板 (backend/services/usage_tracker.py 内存态)
  // L8 PR-A (2026-09-09): 支持 range=today|total 查询参数, 默认 today。
  // L8 PR-B (2026-09-09): range 扩到 today|7d|30d|total。
  // 未传 range 时省略 query string (后端会按 today 默认处理)。
  usage_summary: {
    method: 'GET',
    path: (a) => {
      const range = a?.range as string | undefined;
      if (!range) return '/api/v1/usage';
      return `/api/v1/usage?range=${encodeURIComponent(range)}`;
    },
  },
  // U14 (批次 C): 会话级持久化用量
  usage_get_session: {
    method: 'GET',
    path: (a) => `/api/v1/usage/session/${encodeURIComponent(String(a.sessionId))}`,
  },
  // L8 PR-B (2026-09-09): 单次请求详情 (usage_events 分页)
  usage_list_requests: {
    method: 'GET',
    path: (a) => {
      const limit = a?.limit ?? 50;
      const offset = a?.offset ?? 0;
      const sid = a?.sessionId;
      let url = `/api/v1/usage/requests?limit=${limit}&offset=${offset}`;
      if (typeof sid === 'string' && sid) url += `&session_id=${encodeURIComponent(sid)}`;
      return url;
    },
  },
  // L8 PR-C (2026-09-09): 趋势图时序 (按桶聚合)
  usage_trend: {
    method: 'GET',
    path: (a) => {
      const range = (a?.range as string) ?? '7d';
      const sid = a?.sessionId;
      let url = `/api/v1/usage/trend?range=${encodeURIComponent(range)}`;
      if (typeof sid === 'string' && sid) url += `&session_id=${encodeURIComponent(sid)}`;
      return url;
    },
  },
  // L8 PR-C (2026-09-09): CSV 导出 (text/plain)
  usage_export_csv: {
    method: 'GET',
    path: (a) => {
      const range = (a?.range as string) ?? 'total';
      const sid = a?.sessionId;
      let url = `/api/v1/usage/export.csv?range=${encodeURIComponent(range)}`;
      if (typeof sid === 'string' && sid) url += `&session_id=${encodeURIComponent(sid)}`;
      return url;
    },
  },
  // 2026-09-04: 本地开发环境助手 — 复用 ChatService.tools 路径,
  // runtime_exec 在后端经 PermissionEnforcer 审批 (与 bash 同等闸口)。
  // 见 docs/plans/2026-09-04_local-development-assistant.md Stage 4。
  runtime_probe: { method: 'POST', path: () => '/api/v1/runtime/probe' },
  runtime_diagnose: { method: 'POST', path: () => '/api/v1/runtime/diagnose' },
  runtime_exec: { method: 'POST', path: () => '/api/v1/runtime/exec' },
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
